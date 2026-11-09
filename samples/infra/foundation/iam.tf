# 口座ごとの土台の役割。どれも GitHub の OIDC か AWS のサービスが借り、長期のアクセスキーは作らない。
#   計画（plan）: 読むだけ（ReadOnlyAccess）で、データの中身と WAF の見本の要求を読む操作は拒む。
#     信頼は main にある再利用の workflow（infra-plan-run.yml@refs/heads/main）だけ。PR の中で workflow を書き換えても借りられない。
#     PR から借りられるのは検証環境（合成のデータ）の口座だけ。本番の口座の計画は、main に入った後にだけ出す。
#     部品の指紋（.terraform.lock.hcl）は main の版を使い、init -lockfile=readonly で回す。PR で足した部品は読み込まれない。
#   適用（apply）: 承認 1 人の環境（var.env）を通った main の infra-apply.yml。plan-gate の「承認 1 人の一覧」と同じ操作だけ。
#   守りの適用（apply-guarded）: 承認 2 人（うち 1 人はセキュリティ）の環境（var.env-guarded）を通った main の infra-apply.yml。
#     権限・信頼・資源の方針・配信・WAF・監査の設定と、データベースの設定（大きさを含む）を変えられるのは、この役割だけ。
#     作る役割には必ず権限の境界を付ける。
#   復元、バックアップ、利用者づくりの起動の役割: 口座の上限（SCP）が名前で例外にする役割なので、ここで作る。
#     SCP が、これらの役割と境界の方針を platform-foundation のほかに誰にも変えさせない。
# データを持つ資源（データベース、バケット、保管庫、鍵、秘密、ロググループ）を消す操作は、どの役割にも持たせない。

resource "aws_iam_openid_connect_provider" "github" {
  url            = "https://token.actions.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"]
}

locals {
  acct = var.account_id
  p    = local.partition
  r    = var.region

  boundary_arn = "arn:${local.p}:iam::${local.acct}:policy/${local.name}-boundary"
  data_key_by_alias = {
    "ForAnyValue:StringEquals" = { "kms:ResourceAliases" = "alias/${local.name}-data" }
  }

  # 計画と適用のどちらにも付ける拒否。ReadOnlyAccess に入っている「データの中身を読む」操作を外す。
  # 管理の記録（CloudTrail の出来事の履歴）も中身に数える。当番が Logs Insights に入れた問い合わせの文が、要求の欄に残るからである。
  # 状態のバケットだけは計画に要るので外す。読んだ記録は CloudTrail のデータイベントに残る（audit.tf）。
  deny_data_reads = {
    Sid    = "NoDataContentReads"
    Effect = "Deny"
    Action = [
      "s3:GetObject", "s3:GetObjectVersion", "logs:GetLogEvents", "logs:FilterLogEvents", "logs:StartQuery", "logs:GetLogRecord",
      "logs:Unmask", "secretsmanager:GetSecretValue", "rds:DownloadDBLogFilePortion", "rds:DownloadCompleteDBLogFile",
      "pi:*", "ecr:GetDownloadUrlForLayer", "ecr:BatchGetImage", "wafv2:GetSampledRequests", "logs:GetQueryResults", "logs:DescribeQueries",
      "logs:StartLiveTail", "logs:GetLogObject", "logs:ListAnomalies", "logs:CreateLogAnomalyDetector",
      "cloudtrail:LookupEvents", "cloudtrail:StartQuery", "cloudtrail:GetQueryResults", "athena:GetQueryResults",
      "ssm:GetParameter", "ssm:GetParameters", "ssm:GetParametersByPath", "secretsmanager:BatchGetSecretValue",
    ]
    NotResource = ["arn:${local.p}:s3:::${var.state_bucket_name}/*"]
  }

  # 適用（承認 1 人）が持つ操作。plan-gate の「承認 1 人の一覧」と同じ範囲だけにする（AWS の側でも一覧の外は通らない）。
  #   API の作業の定義の登録とサービスの更新、API の数の自動の増減、ロードバランサーの待ち先の設定。
  #   データベースの変更（rds:ModifyDBInstance）は持たない。大きさのつもりの 1 回の操作で、合言葉・公開・網・パラメータグループ・
  #   削除の保護・保持の日数まで変わる。この操作に効く条件キーは rds:ManageMasterUserPassword だけで、IAM では大きさだけに絞れない
  #   （aws-facts の 47〜52）。守りの適用（承認 2 人）だけが持つ。
  #   作る操作、ネットワーク、作業の起動、移行の役割の受け渡し、パラメータグループ、秘密と鍵、Lambda も持たない（守りの適用だけ）。
  apply_statements = [
    local.deny_data_reads,
    {
      # データベース（rds:*）は対象にも操作にも入れない。RDS を通してデータの鍵を使う許し（旧 DataKeyThroughRds）も、大きさの変更と
      # 一緒に守りの適用へ移した（DataAndAlarms の kms:CreateGrant などが受ける）。
      Sid    = "ReleaseAndTargetGroup"
      Effect = "Allow"
      Action = [
        "ecs:UpdateService", "ecs:TagResource",
        "elasticloadbalancing:ModifyTargetGroup", "elasticloadbalancing:ModifyTargetGroupAttributes", "elasticloadbalancing:AddTags",
      ]
      Resource = [
        "arn:${local.p}:ecs:${local.r}:${local.acct}:service/${local.name}/orders-api",
        "arn:${local.p}:ecs:${local.r}:${local.acct}:task-definition/${local.name}-orders-api:*",
        "arn:${local.p}:elasticloadbalancing:${local.r}:${local.acct}:targetgroup/${local.name}-api/*",
      ]
    },
    {
      # 役割を渡す相手のサービスを ECS に決める。渡せるのは API の 2 つの役割だけ（移行と利用者づくりは守りの適用だけ）。
      Sid      = "PassApiRolesToEcsOnly"
      Effect   = "Allow"
      Action   = "iam:PassRole"
      Resource = ["arn:${local.p}:iam::${local.acct}:role/${local.name}-api-execution", "arn:${local.p}:iam::${local.acct}:role/${local.name}-api-task"]
      Condition = {
        StringEquals = { "iam:PassedToService" = "ecs-tasks.amazonaws.com" }
      }
    },
    {
      Sid    = "RegisterWithoutResourceArn"
      Effect = "Allow"
      Action = [
        "ecs:RegisterTaskDefinition", "ecs:DeregisterTaskDefinition", "application-autoscaling:RegisterScalableTarget",
        "application-autoscaling:PutScalingPolicy",
      ]
      Resource = "*" # iac-scan:allow IAC-003 登録の操作で、AWS の仕様が資源の名指しを受けない。渡せる役割は上で API の 2 つに絞る
    },
  ]

  # 守りの適用（承認 2 人）だけが足して持つ操作。権限、信頼、資源の方針、配信と WAF、監査と検出の設定。
  guarded_statements = [
    {
      # 作る・変える操作（ネットワーク、ロードバランサー、ECS、リポジトリ、Lambda、DNS の守り）。承認 1 人の一覧の外は、全部ここ。
      Sid    = "NetworkAndCompute"
      Effect = "Allow"
      Action = [
        "ec2:CreateVpc", "ec2:ModifyVpcAttribute", "ec2:CreateSubnet", "ec2:DeleteSubnet", "ec2:CreateRouteTable", "ec2:DeleteRouteTable",
        "ec2:AssociateRouteTable", "ec2:DisassociateRouteTable", "ec2:CreateSecurityGroup", "ec2:DeleteSecurityGroup",
        "ec2:AuthorizeSecurityGroupIngress", "ec2:AuthorizeSecurityGroupEgress", "ec2:RevokeSecurityGroupIngress",
        "ec2:RevokeSecurityGroupEgress", "ec2:ModifySecurityGroupRules", "ec2:CreateFlowLogs", "ec2:CreateTags", "ec2:DeleteTags",
        "elasticloadbalancing:CreateLoadBalancer", "elasticloadbalancing:ModifyLoadBalancerAttributes", "elasticloadbalancing:SetSecurityGroups",
        "elasticloadbalancing:CreateTargetGroup", "elasticloadbalancing:CreateListener", "elasticloadbalancing:ModifyListener",
        "elasticloadbalancing:CreateRule", "elasticloadbalancing:ModifyRule",
        "ecs:CreateCluster", "ecs:UpdateCluster", "ecs:UpdateClusterSettings", "ecs:CreateService",
        "ecr:CreateRepository", "ecr:PutImageScanningConfiguration", "ecr:PutLifecyclePolicy", "ecr:TagResource",
        "lambda:CreateFunction", "lambda:UpdateFunctionCode", "lambda:UpdateFunctionConfiguration", "lambda:TagResource",
        "route53resolver:CreateFirewallRule", "route53resolver:AssociateResolverQueryLogConfig", "route53resolver:TagResource",
      ]
      Resource = [
        "arn:${local.p}:ec2:${local.r}:${local.acct}:*",
        "arn:${local.p}:elasticloadbalancing:${local.r}:${local.acct}:*",
        "arn:${local.p}:ecs:${local.r}:${local.acct}:*",
        "arn:${local.p}:ecr:${local.r}:${local.acct}:repository/${local.name}/*",
        "arn:${local.p}:lambda:${local.r}:${local.acct}:function:${local.name}-*",
        "arn:${local.p}:route53resolver:${local.r}:${local.acct}:*",
      ]
    },
    {
      # Lambda を VPC の中に置かせない（API のグループからデータベースへ届く関数を作らせない）。
      Sid      = "NoLambdaInVpc"
      Effect   = "Deny"
      Action   = ["lambda:CreateFunction", "lambda:UpdateFunctionConfiguration"]
      Resource = "arn:${local.p}:lambda:${local.r}:${local.acct}:function:*"
      Condition = {
        Null = { "lambda:VpcIds" = "false" }
      }
    },
    {
      # データベースの変更（rds:ModifyDBInstance）はここだけ。大きさの変更も、合言葉・公開・網・削除の保護・保持の日数と同じ 1 回の
      # 操作で、IAM の条件キーでは分けられない（効く条件キーは rds:ManageMasterUserPassword だけ。aws-facts の 47〜52）。
      # 大きさを変えるときに RDS がデータの鍵を使う分は、この文の kms:CreateGrant などが受ける。
      Sid    = "DataAndAlarms"
      Effect = "Allow"
      Action = [
        "rds:CreateDBInstance", "rds:ModifyDBInstance", "rds:AddTagsToResource", "rds:CreateDBSubnetGroup", "rds:ModifyDBSubnetGroup",
        "kms:CreateAlias", "kms:UpdateAlias", "kms:EnableKeyRotation", "kms:TagResource", "kms:UpdateKeyDescription",
        "kms:CreateGrant", "kms:DescribeKey", "kms:GenerateDataKey", "kms:Decrypt",
        "secretsmanager:CreateSecret", "secretsmanager:UpdateSecret", "secretsmanager:TagResource",
        "logs:CreateLogGroup", "logs:AssociateKmsKey", "logs:TagResource",
        "cloudwatch:TagResource", "sns:CreateTopic", "sns:TagResource", "events:TagResource",
        "s3:CreateBucket", "s3:PutBucketOwnershipControls", "s3:PutBucketVersioning", "s3:PutEncryptionConfiguration",
        "s3:PutBucketObjectLockConfiguration", "s3:PutBucketTagging", "s3:PutLifecycleConfiguration",
        "cloudtrail:StartLogging", "cloudtrail:AddTags",
        "backup:CreateBackupVault", "backup:CreateBackupPlan", "backup:UpdateBackupPlan", "backup:CreateBackupSelection",
        "backup:TagResource", "backup:StartBackupJob", "access-analyzer:CreateAnalyzer", "access-analyzer:TagResource",
        "cloudfront:TagResource",
      ]
      Resource = [
        "arn:${local.p}:rds:${local.r}:${local.acct}:*",
        "arn:${local.p}:kms:${local.r}:${local.acct}:*",
        "arn:${local.p}:kms:us-east-1:${local.acct}:*",
        "arn:${local.p}:secretsmanager:${local.r}:${local.acct}:secret:${local.name}/*",
        "arn:${local.p}:logs:${local.r}:${local.acct}:*",
        "arn:${local.p}:logs:us-east-1:${local.acct}:*",
        "arn:${local.p}:cloudwatch:${local.r}:${local.acct}:alarm:${local.name}-*",
        "arn:${local.p}:cloudwatch:us-east-1:${local.acct}:alarm:${local.name}-*",
        "arn:${local.p}:sns:${local.r}:${local.acct}:${local.name}-*",
        "arn:${local.p}:sns:us-east-1:${local.acct}:${local.name}-*",
        "arn:${local.p}:events:${local.r}:${local.acct}:rule/${local.name}-*",
        "arn:${local.p}:events:us-east-1:${local.acct}:rule/${local.name}-*",
        "arn:${local.p}:s3:::${local.name}-*",
        "arn:${local.p}:cloudtrail:${local.r}:${local.acct}:trail/${local.name}-*",
        "arn:${local.p}:backup:${local.r}:${local.acct}:*",
        "arn:${local.p}:access-analyzer:${local.r}:${local.acct}:analyzer/${local.name}-*",
        "arn:${local.p}:access-analyzer:us-east-1:${local.acct}:analyzer/${local.name}-*",
        "arn:${local.p}:cloudfront::${local.acct}:*",
      ]
    },
    {
      # 移行（表の持ち主）と利用者づくりの役割を ECS に渡す。棚卸しの役割を Lambda に渡す。サービスの役割を渡す。
      Sid      = "PassDbJobRolesToEcsOnly"
      Effect   = "Allow"
      Action   = "iam:PassRole"
      Resource = ["arn:${local.p}:iam::${local.acct}:role/${local.name}-db-migrate", "arn:${local.p}:iam::${local.acct}:role/${local.name}-db-migrate-execution", aws_iam_role.db_bootstrap_execution.arn]
      Condition = {
        StringEquals = { "iam:PassedToService" = "ecs-tasks.amazonaws.com" }
      }
    },
    {
      Sid      = "PassInventoryRoleToLambdaOnly"
      Effect   = "Allow"
      Action   = "iam:PassRole"
      Resource = "arn:${local.p}:iam::${local.acct}:role/${local.name}-copy-inventory"
      Condition = {
        StringEquals = { "iam:PassedToService" = "lambda.amazonaws.com" }
      }
    },
    {
      Sid      = "PassServiceRoles"
      Effect   = "Allow"
      Action   = "iam:PassRole"
      Resource = ["arn:${local.p}:iam::${local.acct}:role/${local.name}-flow-logs", "arn:${local.p}:iam::${local.acct}:role/${local.name}-cloudtrail", aws_iam_role.backup.arn]
      Condition = {
        StringEquals = { "iam:PassedToService" = ["vpc-flow-logs.amazonaws.com", "cloudtrail.amazonaws.com", "backup.amazonaws.com"] }
      }
    },
    {
      # 起動するのは移行と利用者づくりの 2 つの family だけ。版は CI が状態から読んだ 1 つを名指しし、上書きは使わない。
      Sid      = "RunDbJobs"
      Effect   = "Allow"
      Action   = "ecs:RunTask"
      Resource = ["arn:${local.p}:ecs:${local.r}:${local.acct}:task-definition/${local.name}-db-migrate:*", "arn:${local.p}:ecs:${local.r}:${local.acct}:task-definition/${local.name}-db-bootstrap:*"]
    },
    {
      # 作る役割には境界を必ず付ける。管理の方針（AdministratorAccess など）を付ける操作は持たない。
      Sid      = "OwnRolesWithBoundary"
      Effect   = "Allow"
      Action   = ["iam:CreateRole", "iam:PutRolePolicy", "iam:DeleteRolePolicy"]
      Resource = "arn:${local.p}:iam::${local.acct}:role/${local.name}-*"
      Condition = {
        StringEquals = { "iam:PermissionsBoundary" = local.boundary_arn }
      }
    },
    {
      Sid      = "OwnRolesTrustAndTags"
      Effect   = "Allow"
      Action   = ["iam:UpdateAssumeRolePolicy", "iam:TagRole"]
      Resource = "arn:${local.p}:iam::${local.acct}:role/${local.name}-*"
    },
    {
      Sid    = "PoliciesEdgeAndGuards"
      Effect = "Allow"
      Action = [
        "kms:PutKeyPolicy", "secretsmanager:PutResourcePolicy", "secretsmanager:RotateSecret",
        "rds:CreateDBParameterGroup", "rds:ModifyDBParameterGroup", "logs:PutMetricFilter", "cloudwatch:PutMetricAlarm", "events:PutRule",
        "s3:PutBucketPolicy", "s3:PutBucketPublicAccessBlock", "sns:SetTopicAttributes", "sns:Subscribe", "events:PutTargets",
        "cloudtrail:CreateTrail", "cloudtrail:UpdateTrail", "cloudtrail:PutEventSelectors",
        "backup:PutBackupVaultAccessPolicy", "backup:PutBackupVaultLockConfiguration", "logs:PutDataProtectionPolicy", "logs:PutRetentionPolicy",
        "lambda:AddPermission", "ec2:CreateVpcEndpoint", "ec2:ModifyVpcEndpoint",
        "route53resolver:UpdateFirewallDomains", "route53resolver:UpdateFirewallRule", "route53resolver:AssociateFirewallRuleGroup",
        "route53resolver:UpdateFirewallConfig",
        "cloudfront:CreateDistribution", "cloudfront:UpdateDistribution", "cloudfront:UpdateOriginAccessControl", "cloudfront:UpdateVpcOrigin",
        "cloudfront:UpdateResponseHeadersPolicy",
        "wafv2:CreateWebACL", "wafv2:UpdateWebACL", "wafv2:CreateIPSet", "wafv2:UpdateIPSet", "wafv2:PutLoggingConfiguration",
        "wafv2:TagResource",
      ]
      Resource = [
        "arn:${local.p}:kms:${local.r}:${local.acct}:key/*",
        "arn:${local.p}:kms:us-east-1:${local.acct}:key/*",
        "arn:${local.p}:secretsmanager:${local.r}:${local.acct}:secret:*",
        "arn:${local.p}:rds:${local.r}:${local.acct}:pg:${local.name}-*",
        "arn:${local.p}:cloudwatch:${local.r}:${local.acct}:alarm:${local.name}-*",
        "arn:${local.p}:cloudwatch:us-east-1:${local.acct}:alarm:${local.name}-*",
        "arn:${local.p}:s3:::${local.name}-*",
        "arn:${local.p}:sns:${local.r}:${local.acct}:${local.name}-*",
        "arn:${local.p}:sns:us-east-1:${local.acct}:${local.name}-*",
        "arn:${local.p}:events:${local.r}:${local.acct}:rule/${local.name}-*",
        "arn:${local.p}:events:us-east-1:${local.acct}:rule/${local.name}-*",
        "arn:${local.p}:cloudtrail:${local.r}:${local.acct}:trail/${local.name}-*",
        "arn:${local.p}:backup:${local.r}:${local.acct}:backup-vault:${local.name}-*",
        "arn:${local.p}:logs:${local.r}:${local.acct}:*",
        "arn:${local.p}:logs:us-east-1:${local.acct}:*",
        "arn:${local.p}:lambda:${local.r}:${local.acct}:function:${local.name}-*",
        "arn:${local.p}:ec2:${local.r}:${local.acct}:*",
        "arn:${local.p}:route53resolver:${local.r}:${local.acct}:*",
        "arn:${local.p}:cloudfront::${local.acct}:*",
        "arn:${local.p}:wafv2:us-east-1:${local.acct}:global/*",
      ]
    },
    {
      Sid    = "GuardedCreateWithoutResourceArn"
      Effect = "Allow"
      Action = [
        "kms:CreateKey", "logs:PutResourcePolicy", "logs:CreateLogDelivery", "ecr:PutRegistryScanningConfiguration", "inspector2:Enable",
        "cloudfront:CreateOriginAccessControl", "cloudfront:CreateVpcOrigin", "cloudfront:CreateResponseHeadersPolicy",
        "route53resolver:CreateFirewallDomainList", "route53resolver:CreateFirewallRuleGroup", "route53resolver:CreateResolverQueryLogConfig",
      ]
      Resource = "*" # iac-scan:allow IAC-003 作る操作で、AWS の仕様が資源の名指しを受けない（作る前に ARN が無い）
    },
  ]
}

# ---- 計画の役割

resource "aws_iam_role" "plan" {
  name                 = "${local.name}-plan"
  max_session_duration = 3600
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Federated = aws_iam_openid_connect_provider.github.arn }
      Action    = "sts:AssumeRoleWithWebIdentity"
      Condition = {
        StringEquals = { "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com" }
        StringLike = {
          # PR の側の workflow は、main の再利用の workflow を呼ぶだけ。job_workflow_ref は呼ばれた側（main）を指す。
          # PR から借りられるのは検証環境の口座だけ（var.plan_from_pull_requests）。本番の計画は、main に入った後にだけ出す。
          "token.actions.githubusercontent.com:sub" = "repo:${var.github_repository}:${var.plan_from_pull_requests ? "pull_request" : "ref:refs/heads/main"}:job_workflow_ref:${var.github_repository}/.github/workflows/infra-plan-run.yml@refs/heads/main${local.gh_ids}"
        }
      }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "plan_read" {
  role       = aws_iam_role.plan.name
  policy_arn = "arn:${local.p}:iam::aws:policy/ReadOnlyAccess"
}

resource "aws_iam_role_policy" "plan_guard" {
  name = "no-data-reads"
  role = aws_iam_role.plan.id
  policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [local.deny_data_reads]
  })
}

# ---- 適用の役割（承認 1 人）

resource "aws_iam_role" "apply" {
  name                 = "${local.name}-apply"
  max_session_duration = 3600
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Federated = aws_iam_openid_connect_provider.github.arn }
      Action    = "sts:AssumeRoleWithWebIdentity"
      Condition = {
        StringEquals = {
          "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"
          "token.actions.githubusercontent.com:sub" = "${local.gh_sub}/infra-apply.yml@refs/heads/main${local.gh_ids}"
        }
      }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "apply_read" {
  role       = aws_iam_role.apply.name
  policy_arn = "arn:${local.p}:iam::aws:policy/ReadOnlyAccess"
}

resource "aws_iam_role_policy" "apply_write" {
  name = "write-this-stack"
  role = aws_iam_role.apply.id
  policy = jsonencode({
    Version   = "2012-10-17"
    Statement = local.apply_statements
  })
}

# ---- 守りの適用の役割（承認 2 人。環境 <env>-guarded を通ったときだけ借りられる）

resource "aws_iam_role" "apply_guarded" {
  name                 = "${local.name}-apply-guarded"
  max_session_duration = 3600
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Federated = aws_iam_openid_connect_provider.github.arn }
      Action    = "sts:AssumeRoleWithWebIdentity"
      Condition = {
        StringEquals = {
          "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"
          "token.actions.githubusercontent.com:sub" = "${local.gh_guarded_sub}/infra-apply.yml@refs/heads/main${local.gh_ids}"
        }
      }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "apply_guarded_read" {
  role       = aws_iam_role.apply_guarded.name
  policy_arn = "arn:${local.p}:iam::aws:policy/ReadOnlyAccess"
}

resource "aws_iam_role_policy" "apply_guarded_write" {
  name = "write-this-stack-and-guards"
  role = aws_iam_role.apply_guarded.id
  policy = jsonencode({
    Version   = "2012-10-17"
    Statement = concat(local.apply_statements, local.guarded_statements)
  })
}

# ---- 権限の境界。守りの適用が作る役割は、どれもこの上限の中でしか動けない（SCP が境界なしの作成を拒む）。
# 上限の中身は、構成の役割が使う操作の和。IAM、Lambda と ECS の起動、方針の書き換え、配信、監査の停止は入れない。

resource "aws_iam_policy" "boundary" {
  name        = "${local.name}-boundary"
  description = "Ceiling for every role the workload stack creates"
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "WorkloadCeiling"
        Effect = "Allow"
        Action = [
          "ecr:GetAuthorizationToken", "ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer", "ecr:BatchCheckLayerAvailability",
          "ecr:InitiateLayerUpload", "ecr:UploadLayerPart", "ecr:CompleteLayerUpload", "ecr:PutImage",
          "logs:CreateLogStream", "logs:PutLogEvents", "logs:DescribeLogStreams",
          "secretsmanager:GetSecretValue", "kms:Decrypt", "kms:GenerateDataKey", "rds-db:connect",
          "rds:DescribeDBSnapshots", "rds:DescribeDBClusterSnapshots", "rds:DescribeDBInstances", "rds:DescribeDBClusters",
          "rds:DescribeDBInstanceAutomatedBackups", "rds:ListTagsForResource", "rds:DeleteDBSnapshot",
          "backup:ListRecoveryPointsByBackupVault", "sns:Publish", "xray:PutTraceSegments", "xray:PutTelemetryRecords",
          "cloudfront:ListDistributions", "s3:ListAllMyBuckets", "cloudwatch:DescribeAlarms", "sns:ListSubscriptionsByTopic",
          "sns:GetSubscriptionAttributes", "logs:DescribeMetricFilters", "events:DescribeRule", "ec2:DescribeSecurityGroupRules",
          "backup:ListBackupVaults",
        ]
        Resource = "*" # iac-scan:allow IAC-003 境界は上限で、対象の名指しは各役割の方針がする（境界の Resource は全体を指す決まり）
      },
      {
        # 守りの口座へ送る便り（棚卸しの ok と ng）。宛先は守りの口座の便りのバスだけ。
        Sid      = "GuardHeartbeatOnly"
        Effect   = "Allow"
        Action   = "events:PutEvents"
        Resource = "arn:${local.p}:events:*:*:event-bus/*-heartbeat"
      },
      {
        # 画面の file を書けるのは、画面のバケットだけ（配る役割）。照らしは守りの口座の役割が、バケットの方針の許しで読む。
        # ほかのバケットの読み書きは境界の外。
        Sid      = "StaticFilesOnly"
        Effect   = "Allow"
        Action   = ["s3:PutObject", "s3:DeleteObject", "s3:ListBucket", "s3:GetObject"]
        Resource = ["arn:${local.p}:s3:::${local.name}-static-*", "arn:${local.p}:s3:::${local.name}-static-*/*"]
      },
      {
        # データベースを消せるのは、訓練の写し（名前が -restore-）だけ。本番のデータベースは境界の外。
        Sid      = "DeleteDrillCopiesOnly"
        Effect   = "Allow"
        Action   = "rds:DeleteDBInstance"
        Resource = "arn:${local.p}:rds:${local.r}:${local.acct}:db:${local.name}-restore-*"
      },
      {
        Sid      = "NeverTheAdminSecret"
        Effect   = "Deny"
        Action   = "secretsmanager:GetSecretValue"
        Resource = "arn:${local.p}:secretsmanager:${local.r}:${local.acct}:secret:rds!*"
      },
    ]
  })
}

# ---- 復元の役割（この環境の承認を通った、main の restore-drill.yml からだけ借りられる）
# 復元先は、この構成のデータの層のサブネットの組と、名前が「-restore-」の資源に限る。付けられる札は purpose と drill_id だけで、
# managed_by などを付けて棚卸しの目を逃れることはできない（棚卸しは札ではなく名前と日数で見る）。

resource "aws_iam_role" "restore" {
  name                 = "${local.name}-restore"
  max_session_duration = 7200
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Federated = aws_iam_openid_connect_provider.github.arn }
      Action    = "sts:AssumeRoleWithWebIdentity"
      Condition = {
        StringEquals = {
          "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"
          "token.actions.githubusercontent.com:sub" = "${local.gh_sub}/restore-drill.yml@refs/heads/main${local.gh_ids}"
        }
      }
    }]
  })
}

resource "aws_iam_role_policy" "restore" {
  name = "restore-into-data-subnets"
  role = aws_iam_role.restore.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "RestoreIntoOwnSubnetsOnly"
        Effect = "Allow"
        Action = ["rds:RestoreDBInstanceFromDBSnapshot", "rds:RestoreDBInstanceToPointInTime"]
        Resource = [
          "arn:${local.p}:rds:${local.r}:${local.acct}:db:${local.name}-restore-*",
          "arn:${local.p}:rds:${local.r}:${local.acct}:db:${local.name}-orders",
          "arn:${local.p}:rds:${local.r}:${local.acct}:snapshot:awsbackup:*",
          "arn:${local.p}:rds:${local.r}:${local.acct}:subgrp:${local.name}-orders",
          "arn:${local.p}:rds:${local.r}:${local.acct}:pg:${local.name}-orders-pg16",
          "arn:${local.p}:rds:${local.r}:${local.acct}:og:default:postgres-16",
        ]
      },
      {
        Sid      = "TagDrillCopiesWithPurposeOnly"
        Effect   = "Allow"
        Action   = "rds:AddTagsToResource"
        Resource = "arn:${local.p}:rds:${local.r}:${local.acct}:db:${local.name}-restore-*"
        Condition = {
          "ForAllValues:StringEquals" = { "aws:TagKeys" = ["purpose", "drill_id"] }
        }
      },
      {
        Sid    = "WatchRestore"
        Effect = "Allow"
        Action = ["rds:DescribeDBInstances", "rds:DescribeDBSnapshots"]
        Resource = [
          "arn:${local.p}:rds:${local.r}:${local.acct}:db:*",
          "arn:${local.p}:rds:${local.r}:${local.acct}:snapshot:*",
        ]
      },
      {
        Sid      = "RemoveDrillCopies"
        Effect   = "Allow"
        Action   = "rds:DeleteDBInstance"
        Resource = "arn:${local.p}:rds:${local.r}:${local.acct}:db:${local.name}-restore-*"
      },
      {
        Sid      = "UseDataKeyThroughRds"
        Effect   = "Allow"
        Action   = ["kms:CreateGrant", "kms:Decrypt", "kms:DescribeKey", "kms:GenerateDataKeyWithoutPlaintext"]
        Resource = "arn:${local.p}:kms:${local.r}:${local.acct}:key/*"
        Condition = merge(local.data_key_by_alias, {
          StringEquals = { "kms:ViaService" = "rds.${local.r}.amazonaws.com" }
          Bool         = { "kms:GrantIsForAWSResource" = "true" }
        })
      },
    ]
  })
}

# ---- AWS Backup の役割（AWS が管理する、バックアップと復元だけの方針）

resource "aws_iam_role" "backup" {
  name = "${local.name}-backup"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "backup.amazonaws.com" }
      Action    = "sts:AssumeRole"
      Condition = { StringEquals = { "aws:SourceAccount" = local.acct } }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "backup" {
  role       = aws_iam_role.backup.name
  policy_arn = "arn:${local.p}:iam::aws:policy/service-role/AWSBackupServiceRolePolicyForBackup"
}

resource "aws_iam_role_policy_attachment" "restore" {
  role       = aws_iam_role.backup.name
  policy_arn = "arn:${local.p}:iam::aws:policy/service-role/AWSBackupServiceRolePolicyForRestores"
}

# ---- 利用者づくりの起動の役割。管理者の合言葉を読める唯一の役割（合言葉の方針が名指しする）。
# 信頼は ECS の作業だけで、渡せるのは守りの適用だけ（PassedToService は ecs-tasks）。引けるイメージは利用者づくり専用の 1 つ。

resource "aws_iam_role" "db_bootstrap_execution" {
  name = "${local.name}-db-bootstrap-execution"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
      Action    = "sts:AssumeRole"
      Condition = { StringEquals = { "aws:SourceAccount" = local.acct } }
    }]
  })
}

resource "aws_iam_role_policy" "db_bootstrap_execution" {
  name = "pull-log-admin-secret"
  role = aws_iam_role.db_bootstrap_execution.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "EcrToken"
        Effect   = "Allow"
        Action   = "ecr:GetAuthorizationToken"
        Resource = "*" # iac-scan:allow IAC-003 ecr:GetAuthorizationToken は対象を絞れない（AWS の仕様）
      },
      {
        Sid      = "EcrPullBootstrapImageOnly"
        Effect   = "Allow"
        Action   = ["ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer", "ecr:BatchCheckLayerAvailability"]
        Resource = "arn:${local.p}:ecr:${local.r}:${local.acct}:repository/${local.name}/db-bootstrap"
      },
      {
        Sid      = "Logs"
        Effect   = "Allow"
        Action   = ["logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = "arn:${local.p}:logs:${local.r}:${local.acct}:log-group:/${local.name}/db-jobs/bootstrap:*"
      },
      {
        Sid      = "AdminSecret"
        Effect   = "Allow"
        Action   = "secretsmanager:GetSecretValue"
        Resource = "arn:${local.p}:secretsmanager:${local.r}:${local.acct}:secret:rds!db-*"
      },
      {
        Sid       = "DecryptWithDataKey"
        Effect    = "Allow"
        Action    = "kms:Decrypt"
        Resource  = "arn:${local.p}:kms:${local.r}:${local.acct}:key/*"
        Condition = local.data_key_by_alias
      },
    ]
  })
}

# ---- 口座の公開のブロック（バケットごとの設定に加えて、口座の全バケットに掛ける）。変えられるのは土台だけ（SCP）。

resource "aws_s3_account_public_access_block" "account" {
  account_id              = local.acct
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# ---- 状態のバケットの古い版は 90 日で消す（設定の写しが古い版として溜まり続けないように）。

resource "aws_s3_bucket_lifecycle_configuration" "state" {
  bucket = var.state_bucket_name

  rule {
    id     = "expire-old-state-versions"
    status = "Enabled"
    filter {}
    noncurrent_version_expiration {
      noncurrent_days = 90
    }
  }
}
