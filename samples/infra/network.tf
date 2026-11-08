# ネットワークの 3 層。
#   公開の層: CloudFront と WAF（VPC の外）。VPC の中に公開のサブネットもインターネットゲートウェイも置かない。
#   アプリの層: 内部のロードバランサーと注文 API。外へ出る道は VPC エンドポイントだけ。
#   データの層: データベース。経路表に外への道が無い。

resource "aws_vpc" "main" {
  cidr_block           = var.vpc_cidr
  enable_dns_support   = true
  enable_dns_hostnames = true
  tags                 = { Name = local.name }
}

# 既定のセキュリティグループは規則を空にし、誰にも使わせない。
resource "aws_default_security_group" "main" {
  vpc_id = aws_vpc.main.id
}

resource "aws_subnet" "app" {
  count             = length(var.azs)
  vpc_id            = aws_vpc.main.id
  availability_zone = var.azs[count.index]
  cidr_block        = cidrsubnet(var.vpc_cidr, 8, 10 + count.index)
  tags              = { Name = "${local.name}-app-${count.index}", layer = "app" }
}

resource "aws_subnet" "data" {
  count             = length(var.azs)
  vpc_id            = aws_vpc.main.id
  availability_zone = var.azs[count.index]
  cidr_block        = cidrsubnet(var.vpc_cidr, 8, 20 + count.index)
  tags              = { Name = "${local.name}-data-${count.index}", layer = "data" }
}

resource "aws_route_table" "app" {
  vpc_id = aws_vpc.main.id
  tags   = { Name = "${local.name}-app" }
}

resource "aws_route_table" "data" {
  vpc_id = aws_vpc.main.id
  tags   = { Name = "${local.name}-data" }
}

resource "aws_route_table_association" "app" {
  count          = length(var.azs)
  subnet_id      = aws_subnet.app[count.index].id
  route_table_id = aws_route_table.app.id
}

resource "aws_route_table_association" "data" {
  count          = length(var.azs)
  subnet_id      = aws_subnet.data[count.index].id
  route_table_id = aws_route_table.data.id
}

# ---- VPC エンドポイント（AWS の窓口へ、インターネットを通らずに出る道）

resource "aws_vpc_endpoint" "s3" {
  vpc_id            = aws_vpc.main.id
  service_name      = "com.amazonaws.${var.region}.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = [aws_route_table.app.id]

  # 外へ持ち出す道にしないよう、ECR のイメージの層を読むことだけを許す。
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "EcrLayersOnly"
      Effect    = "Allow"
      Principal = { AWS = "arn:${local.partition}:iam::${local.account_id}:root" }
      Action    = "s3:GetObject"
      Resource  = "arn:${local.partition}:s3:::prod-${var.region}-starport-layer-bucket/*"
    }]
  })
}

# 窓口は 4 種（ECR の 2 つ、ログ、秘密）。API は KMS と STS を直接呼ばないので、その窓口は置かない。
# 窓口ごとの方針で、「この口座の主体が、この構成の資源に」使うときだけ通す。
# 乗っ取った部品が、自分の口座のロググループ・リポジトリ・秘密へ書いて持ち出す道を閉じる。
locals {
  own_principal = { StringEquals = { "aws:PrincipalAccount" = local.account_id } }
  ecr_policy = [
    {
      Sid       = "Token"
      Effect    = "Allow"
      Principal = "*"
      Action    = "ecr:GetAuthorizationToken"
      Resource  = "*"
      Condition = local.own_principal
    },
    {
      Sid       = "PullOwnRepositoryOnly"
      Effect    = "Allow"
      Principal = "*"
      Action    = ["ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer", "ecr:BatchCheckLayerAvailability"]
      Resource  = [aws_ecr_repository.api.arn, aws_ecr_repository.db_bootstrap.arn, aws_ecr_repository.db_migrate.arn]
      Condition = local.own_principal
    },
  ]
  endpoint_policies = {
    "ecr.api" = local.ecr_policy
    "ecr.dkr" = local.ecr_policy
    "logs" = [{
      Sid       = "WriteOwnLogGroupsOnly"
      Effect    = "Allow"
      Principal = "*"
      Action    = ["logs:CreateLogStream", "logs:PutLogEvents"]
      Resource  = ["${aws_cloudwatch_log_group.api.arn}:*", "${aws_cloudwatch_log_group.db_bootstrap.arn}:*", "${aws_cloudwatch_log_group.db_migrate.arn}:*"]
      Condition = local.own_principal
    }]
    "secretsmanager" = [{
      Sid       = "ReadOwnSecretsOnly"
      Effect    = "Allow"
      Principal = "*"
      Action    = "secretsmanager:GetSecretValue"
      Resource = [
        aws_secretsmanager_secret.session_signing_key.arn,
        aws_db_instance.orders.master_user_secret[0].secret_arn,
      ]
      Condition = local.own_principal
    }]
  }
}

resource "aws_vpc_endpoint" "interface" {
  for_each            = local.endpoint_policies
  vpc_id              = aws_vpc.main.id
  service_name        = "com.amazonaws.${var.region}.${each.key}"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = aws_subnet.app[*].id
  security_group_ids  = [aws_security_group.endpoints.id]
  private_dns_enabled = true
  policy              = jsonencode({ Version = "2012-10-17", Statement = each.value })
}

# ---- DNS の持ち出しを止める（Route 53 Resolver DNS Firewall）。
# VPC の中から引ける名前は、使う窓口の名前だけにする（許す物の一覧）。4 つの窓口、ECR のイメージの層のバケット、この地域の DB の名前。
#   DB の名前の型（*.<地域>.rds.amazonaws.com）は、どの口座の DB の名前でも引ける。外への経路も、その宛先を許すグループも無いので、
#   引けても届かない（流出の道にはならない）。
# amazonaws.com を丸ごと許すと、S3 の汎用の名前で自分のバケットへ要求を送れる。窓口の方針で拒まれた要求が相手の側の記録に残るかは
# 確かめが要る（未確定 20）ので、名前の側でも閉じる。ほかの名前は全部 NXDOMAIN で返し、問い合わせの中身は query-log に残す。
# 窓口と DB の名前は別名（CNAME）の先を持つことがあるので、許した名前の別名の先は信じる（TRUST_REDIRECTION_DOMAIN）。

resource "aws_route53_resolver_firewall_domain_list" "aws" {
  name = "${local.name}-aws-endpoints"
  domains = [
    "api.ecr.${var.region}.amazonaws.com", "${local.account_id}.dkr.ecr.${var.region}.amazonaws.com",
    "logs.${var.region}.amazonaws.com", "secretsmanager.${var.region}.amazonaws.com",
    "prod-${var.region}-starport-layer-bucket.s3.${var.region}.amazonaws.com", "*.${var.region}.rds.amazonaws.com",
  ]
}

resource "aws_route53_resolver_firewall_domain_list" "everything" {
  name    = "${local.name}-everything-else"
  domains = ["*"]
}

resource "aws_route53_resolver_firewall_rule_group" "main" {
  name = "${local.name}-dns"
}

resource "aws_route53_resolver_firewall_rule" "allow_aws" {
  name                               = "allow-aws-endpoints"
  action                             = "ALLOW"
  firewall_domain_redirection_action = "TRUST_REDIRECTION_DOMAIN"
  firewall_domain_list_id            = aws_route53_resolver_firewall_domain_list.aws.id
  firewall_rule_group_id             = aws_route53_resolver_firewall_rule_group.main.id
  priority                           = 100
}

resource "aws_route53_resolver_firewall_rule" "block_rest" {
  name                    = "block-everything-else"
  action                  = "BLOCK"
  block_response          = "NXDOMAIN"
  firewall_domain_list_id = aws_route53_resolver_firewall_domain_list.everything.id
  firewall_rule_group_id  = aws_route53_resolver_firewall_rule_group.main.id
  priority                = 200
}

resource "aws_route53_resolver_firewall_rule_group_association" "main" {
  name                   = "${local.name}-dns"
  firewall_rule_group_id = aws_route53_resolver_firewall_rule_group.main.id
  vpc_id                 = aws_vpc.main.id
  priority               = 101
  mutation_protection    = "ENABLED"
}

resource "aws_route53_resolver_firewall_config" "main" {
  resource_id        = aws_vpc.main.id
  firewall_fail_open = "DISABLED"
}

resource "aws_cloudwatch_log_group" "dns" {
  name              = "/${local.name}/dns-queries"
  retention_in_days = var.log_retention_days
  kms_key_id        = aws_kms_key.logs.arn
}

resource "aws_route53_resolver_query_log_config" "main" {
  name            = "${local.name}-dns"
  destination_arn = aws_cloudwatch_log_group.dns.arn
}

resource "aws_route53_resolver_query_log_config_association" "main" {
  resolver_query_log_config_id = aws_route53_resolver_query_log_config.main.id
  resource_id                  = aws_vpc.main.id
}

# ---- セキュリティグループ。受ける相手はグループで名指しし、アドレスの範囲で開けない。

# CloudFront の VPC オリジンの通信は、VPC の中の ENI から来る。その ENI には、AWS が VPC オリジンを作るときに
# この VPC に置くグループ CloudFront-VPCOrigins-Service-SG が付く。受け口はこのグループを名指しする。
data "aws_security_group" "cloudfront_vpc_origins" {
  vpc_id = aws_vpc.main.id
  filter {
    name   = "group-name"
    values = ["CloudFront-VPCOrigins-Service-SG"]
  }
  depends_on = [aws_cloudfront_vpc_origin.api]
}

resource "aws_security_group" "alb" {
  name        = "${local.name}-alb"
  description = "Internal ALB. Accepts HTTPS from CloudFront VPC origin only"
  vpc_id      = aws_vpc.main.id
}

resource "aws_security_group" "api" {
  name        = "${local.name}-api"
  description = "Orders API tasks. Accepts traffic from the internal ALB only"
  vpc_id      = aws_vpc.main.id
}

resource "aws_security_group" "db" {
  name        = "${local.name}-db"
  description = "Orders database. Accepts PostgreSQL from the API tasks only"
  vpc_id      = aws_vpc.main.id
}

resource "aws_security_group" "endpoints" {
  name        = "${local.name}-endpoints"
  description = "VPC interface endpoints. Accepts HTTPS from the API tasks only"
  vpc_id      = aws_vpc.main.id
}

resource "aws_vpc_security_group_ingress_rule" "alb_from_cloudfront" {
  security_group_id            = aws_security_group.alb.id
  description                  = "HTTPS from CloudFront VPC origin ENIs"
  ip_protocol                  = "tcp"
  from_port                    = 443
  to_port                      = 443
  referenced_security_group_id = data.aws_security_group.cloudfront_vpc_origins.id
}

resource "aws_vpc_security_group_egress_rule" "alb_to_api" {
  security_group_id            = aws_security_group.alb.id
  description                  = "To API tasks"
  ip_protocol                  = "tcp"
  from_port                    = 8080
  to_port                      = 8080
  referenced_security_group_id = aws_security_group.api.id
}

resource "aws_vpc_security_group_ingress_rule" "api_from_alb" {
  security_group_id            = aws_security_group.api.id
  description                  = "From internal ALB"
  ip_protocol                  = "tcp"
  from_port                    = 8080
  to_port                      = 8080
  referenced_security_group_id = aws_security_group.alb.id
}

resource "aws_vpc_security_group_egress_rule" "api_to_db" {
  security_group_id            = aws_security_group.api.id
  description                  = "To orders database"
  ip_protocol                  = "tcp"
  from_port                    = 5432
  to_port                      = 5432
  referenced_security_group_id = aws_security_group.db.id
}

resource "aws_vpc_security_group_egress_rule" "api_to_endpoints" {
  security_group_id            = aws_security_group.api.id
  description                  = "To VPC interface endpoints"
  ip_protocol                  = "tcp"
  from_port                    = 443
  to_port                      = 443
  referenced_security_group_id = aws_security_group.endpoints.id
}

resource "aws_vpc_security_group_egress_rule" "api_to_s3" {
  security_group_id = aws_security_group.api.id
  description       = "To S3 gateway endpoint (ECR image layers)"
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
  prefix_list_id    = aws_vpc_endpoint.s3.prefix_list_id
}

resource "aws_vpc_security_group_ingress_rule" "db_from_api" {
  security_group_id            = aws_security_group.db.id
  description                  = "PostgreSQL from API tasks"
  ip_protocol                  = "tcp"
  from_port                    = 5432
  to_port                      = 5432
  referenced_security_group_id = aws_security_group.api.id
}

resource "aws_vpc_security_group_ingress_rule" "endpoints_from_api" {
  security_group_id            = aws_security_group.endpoints.id
  description                  = "HTTPS from API tasks"
  ip_protocol                  = "tcp"
  from_port                    = 443
  to_port                      = 443
  referenced_security_group_id = aws_security_group.api.id
}

# ---- 通信の記録（VPC フローログ）

resource "aws_cloudwatch_log_group" "flow" {
  name              = "/${local.name}/vpc-flow"
  retention_in_days = var.log_retention_days
  kms_key_id        = aws_kms_key.logs.arn
}

resource "aws_flow_log" "main" {
  vpc_id               = aws_vpc.main.id
  traffic_type         = "ALL"
  log_destination_type = "cloud-watch-logs"
  log_destination      = aws_cloudwatch_log_group.flow.arn
  iam_role_arn         = aws_iam_role.flow.arn
}
