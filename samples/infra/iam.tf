# 最小権限の IAM。役割ごとに、許す操作と対象の資源を名指しする。長期のアクセスキー（IAM ユーザー）は作らない。
# CI は GitHub の OIDC（短命の資格）で役割を借りる。OIDC の窓口、計画と適用と守りの適用の役割、権限の境界は foundation/ にある。
# SCP が名前で例外にする役割（復元、バックアップ、利用者づくりの起動）も foundation/ にあり、ここからは名前で指すだけ。
# ここで作る役割には、どれも権限の境界（foundation/ の <name>-boundary）を付ける。付けないと SCP が作成を拒む。
# GitHub の資格の sub は org/ で「repo・context・job_workflow_ref」の形に変えてある。どの役割も、
# 「この環境の承認を通った、main のこの workflow」からだけ借りられる。

locals {
  gh_workflow_sub = "repo:${var.github_repository}:environment:${var.env}:job_workflow_ref:${var.github_repository}/.github/workflows"
  # OIDC の sub の後ろに、変わらない番号（リポジトリと持ち主）を足す（org/github.tf の include_claim_keys の順）。
  # 名前の付け替えや、消した後の同じ名前の作り直しでは、番号が合わず借りられない。
  gh_ids          = ":repository_id:${var.github_repository_id}:repository_owner_id:${var.github_repository_owner_id}"
  role_arn_prefix = "arn:${local.partition}:iam::${local.account_id}:role/${local.name}"
  guard_role_arn  = "${local.role_arn_prefix}-apply-guarded"
  restore_role    = "${local.role_arn_prefix}-restore"
  backup_role     = "${local.role_arn_prefix}-backup"
  bootstrap_role  = "${local.role_arn_prefix}-db-bootstrap-execution"
  boundary_arn    = "arn:${local.partition}:iam::${local.account_id}:policy/${local.name}-boundary"
  oncall_role_arn = "arn:${local.partition}:iam::${local.account_id}:role/aws-reserved/sso.amazonaws.com/*${var.oncall_role_name_prefix}*"

  ecs_assume = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
      Action    = "sts:AssumeRole"
      Condition = { StringEquals = { "aws:SourceAccount" = local.account_id } }
    }]
  })
}

# ---- 注文 API の起動の役割（イメージを引き、ログを書き、秘密を 1 つだけ読む）

resource "aws_iam_role" "api_execution" {
  name                 = "${local.name}-api-execution"
  permissions_boundary = local.boundary_arn
  assume_role_policy   = local.ecs_assume
}

resource "aws_iam_role_policy" "api_execution" {
  name = "pull-log-secrets"
  role = aws_iam_role.api_execution.id
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
        Sid      = "EcrPull"
        Effect   = "Allow"
        Action   = ["ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer", "ecr:BatchCheckLayerAvailability"]
        Resource = aws_ecr_repository.api.arn
      },
      {
        Sid      = "Logs"
        Effect   = "Allow"
        Action   = ["logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = "${aws_cloudwatch_log_group.api.arn}:*"
      },
      {
        Sid      = "Secrets"
        Effect   = "Allow"
        Action   = "secretsmanager:GetSecretValue"
        Resource = aws_secretsmanager_secret.session_signing_key.arn
      },
      {
        Sid      = "DecryptSecrets"
        Effect   = "Allow"
        Action   = "kms:Decrypt"
        Resource = aws_kms_key.data.arn
      },
    ]
  })
}

# ---- 注文 API の実行中の役割（データベースへ orders_api の利用者で入るだけ）

resource "aws_iam_role" "api_task" {
  name                 = "${local.name}-api-task"
  permissions_boundary = local.boundary_arn
  assume_role_policy   = local.ecs_assume
}

resource "aws_iam_role_policy" "api_task" {
  name = "db-connect"
  role = aws_iam_role.api_task.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid      = "DbConnect"
      Effect   = "Allow"
      Action   = "rds-db:connect"
      Resource = "arn:${local.partition}:rds-db:${var.region}:${local.account_id}:dbuser:${aws_db_instance.orders.resource_id}/orders_api"
    }]
  })
}

# ---- VPC フローログと CloudTrail が、決めたロググループにだけ書く役割

resource "aws_iam_role" "flow" {
  name                 = "${local.name}-flow-logs"
  permissions_boundary = local.boundary_arn
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "vpc-flow-logs.amazonaws.com" }
      Action    = "sts:AssumeRole"
      Condition = { StringEquals = { "aws:SourceAccount" = local.account_id } }
    }]
  })
}

resource "aws_iam_role_policy" "flow" {
  name = "write-flow-logs"
  role = aws_iam_role.flow.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["logs:CreateLogStream", "logs:PutLogEvents", "logs:DescribeLogStreams"]
      Resource = "${aws_cloudwatch_log_group.flow.arn}:*"
    }]
  })
}

resource "aws_iam_role" "trail" {
  name                 = "${local.name}-cloudtrail"
  permissions_boundary = local.boundary_arn
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "cloudtrail.amazonaws.com" }
      Action    = "sts:AssumeRole"
      Condition = { StringEquals = { "aws:SourceAccount" = local.account_id } }
    }]
  })
}

resource "aws_iam_role_policy" "trail" {
  name = "write-trail-logs"
  role = aws_iam_role.trail.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["logs:CreateLogStream", "logs:PutLogEvents"]
      Resource = "${aws_cloudwatch_log_group.trail.arn}:*"
    }]
  })
}

# ---- CI がイメージを押し込む役割。API と、データベースの作業（移行と利用者づくり）で役割を分ける。
#   API: この環境の承認を通った、main の image-push.yml からだけ借りられる。押し込めるのは API のリポジトリ 1 つ。
#   データベースの作業: 承認 2 人の環境（<環境>-guarded）を通った、main の db-image-push.yml からだけ借りられる。
#   API の部品（npm）が乗っ取られても、API のビルドの資格では移行と利用者づくりのイメージに届かない。
#   どちらの workflow も、押し込んだダイジェストに来歴（どの commit を、どの workflow が作ったか）の署名を付ける。
#   適用の前に CI がその署名を確かめ、確かめたダイジェストだけを plan-gate の --attested に渡す（一覧の外は守りの経路）。

data "aws_iam_openid_connect_provider" "github" {
  url = "https://token.actions.githubusercontent.com"
}

locals {
  push_roles = {
    api = {
      sub   = "${local.gh_workflow_sub}/image-push.yml@refs/heads/main${local.gh_ids}"
      repos = [aws_ecr_repository.api.arn]
    }
    db-jobs = {
      sub   = "repo:${var.github_repository}:environment:${var.env}-guarded:job_workflow_ref:${var.github_repository}/.github/workflows/db-image-push.yml@refs/heads/main${local.gh_ids}"
      repos = [aws_ecr_repository.db_bootstrap.arn, aws_ecr_repository.db_migrate.arn]
    }
  }
}

resource "aws_iam_role" "ci_push" {
  for_each             = local.push_roles
  name                 = "${local.name}-ci-push-${each.key}"
  permissions_boundary = local.boundary_arn
  max_session_duration = 3600
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Federated = data.aws_iam_openid_connect_provider.github.arn }
      Action    = "sts:AssumeRoleWithWebIdentity"
      Condition = {
        StringEquals = {
          "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"
          "token.actions.githubusercontent.com:sub" = each.value.sub
        }
      }
    }]
  })
}

resource "aws_iam_role_policy" "ci_push" {
  for_each = local.push_roles
  name     = "push-image"
  role     = aws_iam_role.ci_push[each.key].id
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
        Sid    = "EcrPush"
        Effect = "Allow"
        Action = [
          "ecr:BatchCheckLayerAvailability",
          "ecr:InitiateLayerUpload",
          "ecr:UploadLayerPart",
          "ecr:CompleteLayerUpload",
          "ecr:PutImage",
        ]
        Resource = each.value.repos
      },
    ]
  })
}

# ---- 移行の起動の役割（移行専用のイメージを引き、移行のロググループにだけ書く。秘密は読まない）

resource "aws_iam_role" "db_migrate_execution" {
  name                 = "${local.name}-db-migrate-execution"
  permissions_boundary = local.boundary_arn
  assume_role_policy   = local.ecs_assume
}

resource "aws_iam_role_policy" "db_migrate_execution" {
  name = "pull-log-migrate"
  role = aws_iam_role.db_migrate_execution.id
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
        Sid      = "EcrPullMigrateImageOnly"
        Effect   = "Allow"
        Action   = ["ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer", "ecr:BatchCheckLayerAvailability"]
        Resource = aws_ecr_repository.db_migrate.arn
      },
      {
        Sid      = "Logs"
        Effect   = "Allow"
        Action   = ["logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = "${aws_cloudwatch_log_group.db_migrate.arn}:*"
      },
      {
        Sid      = "DecryptImageLayers"
        Effect   = "Allow"
        Action   = "kms:Decrypt"
        Resource = aws_kms_key.data.arn
      },
    ]
  })
}

# ---- 移行の役割（ECS の 1 回だけの作業。守りの適用の役割だけが起動し、この役割を渡せるのも守りの適用だけ）
# 利用者づくりの起動の役割は foundation/ にあり、守りの適用の役割だけが起動する。db/roles.sql が orders_api と
# orders_migrate の権限を作り、最後に「表と操作の一覧と、行の単位の制限どおりか」を確かめる。

resource "aws_iam_role" "db_migrate" {
  name                 = "${local.name}-db-migrate"
  permissions_boundary = local.boundary_arn
  assume_role_policy   = local.ecs_assume
}

resource "aws_iam_role_policy" "db_migrate" {
  name = "db-connect-migrate"
  role = aws_iam_role.db_migrate.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid      = "DbConnect"
      Effect   = "Allow"
      Action   = "rds-db:connect"
      Resource = "arn:${local.partition}:rds-db:${var.region}:${local.account_id}:dbuser:${aws_db_instance.orders.resource_id}/orders_migrate"
    }]
  })
}

# ---- 複製の棚卸しの役割（copy-inventory。手で取った複製を数え、決めた日数を過ぎたものを消し、台帳に書く）

resource "aws_iam_role" "copy_inventory" {
  name                 = "${local.name}-copy-inventory"
  permissions_boundary = local.boundary_arn
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
      Condition = { StringEquals = { "aws:SourceAccount" = local.account_id } }
    }]
  })
}

resource "aws_iam_role_policy" "copy_inventory" {
  name = "count-and-expire-copies"
  role = aws_iam_role.copy_inventory.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "ListCopies"
        Effect = "Allow"
        Action = [
          "rds:DescribeDBSnapshots", "rds:DescribeDBClusterSnapshots", "rds:DescribeDBInstances", "rds:DescribeDBClusters",
          "rds:DescribeDBInstanceAutomatedBackups", "rds:ListTagsForResource", "backup:ListRecoveryPointsByBackupVault",
        ]
        Resource = [
          "arn:${local.partition}:rds:*:${local.account_id}:snapshot:*",
          "arn:${local.partition}:rds:*:${local.account_id}:cluster-snapshot:*",
          "arn:${local.partition}:rds:*:${local.account_id}:db:*",
          "arn:${local.partition}:rds:*:${local.account_id}:cluster:*",
          "arn:${local.partition}:rds:*:${local.account_id}:auto-backup:*",
          "arn:${local.partition}:backup:*:${local.account_id}:backup-vault:*",
        ]
      },
      {
        # 2 本目の配信と、知らないバケット（書き出しの置き場など）と、知らない保管庫（既定の保管庫を含む）を見つける。
        # どれも一覧の操作で、対象を名指しできない。
        Sid      = "ListEdgeAndBuckets"
        Effect   = "Allow"
        Action   = ["cloudfront:ListDistributions", "s3:ListAllMyBuckets", "backup:ListBackupVaults"]
        Resource = "*" # iac-scan:allow IAC-003 一覧の操作は対象を絞れない（AWS の仕様）。読むのは設定だけで、中身は読まない
      },
      {
        Sid      = "ExpireManualCopies"
        Effect   = "Allow"
        Action   = "rds:DeleteDBSnapshot"
        Resource = "arn:${local.partition}:rds:${var.region}:${local.account_id}:snapshot:${local.name}-*"
      },
      {
        # 訓練の写し（名前が -restore-）が決めた時間を超えたら消す。最後の複製は取らない（写しの写しを残さない）。
        Sid      = "ExpireDrillCopies"
        Effect   = "Allow"
        Action   = "rds:DeleteDBInstance"
        Resource = "arn:${local.partition}:rds:${var.region}:${local.account_id}:db:${local.name}-restore-*"
      },
      {
        # 守りそのものを数える。アラームが有効で宛先があるか、購読が確認済みか、メトリクスフィルタと毎日の起動の規則が残っているか。
        Sid    = "CountGuards"
        Effect = "Allow"
        Action = [
          "cloudwatch:DescribeAlarms", "sns:ListSubscriptionsByTopic", "sns:GetSubscriptionAttributes", "logs:DescribeMetricFilters",
          "events:DescribeRule",
        ]
        Resource = [
          "arn:${local.partition}:cloudwatch:*:${local.account_id}:alarm:${local.name}-*",
          aws_sns_topic.alerts.arn,
          aws_sns_topic.alerts_use1.arn,
          "${aws_sns_topic.alerts.arn}:*",
          "${aws_sns_topic.alerts_use1.arn}:*",
          "arn:${local.partition}:logs:${var.region}:${local.account_id}:log-group:*",
          aws_cloudwatch_event_rule.copy_inventory.arn,
        ]
      },
      {
        # 受ける通信の規則を数える。一覧の操作で、対象を名指しできない。
        Sid      = "ListIngressRules"
        Effect   = "Allow"
        Action   = "ec2:DescribeSecurityGroupRules"
        Resource = "*" # iac-scan:allow IAC-003 一覧の操作は対象を絞れない（AWS の仕様）。読むのは規則の設定だけ
      },
      {
        # 守りの欠けが 0 のときだけ、守りの口座へ ok の便りを送る。宛先のバスは 1 つ（組織の中。SCP の WritesStayInOrg の内側）。
        Sid      = "GuardHeartbeat"
        Effect   = "Allow"
        Action   = "events:PutEvents"
        Resource = var.guard_heartbeat_bus_arn
      },
      {
        Sid      = "Ledger"
        Effect   = "Allow"
        Action   = ["logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = "${aws_cloudwatch_log_group.copy_ledger.arn}:*"
      },
      {
        Sid      = "Notify"
        Effect   = "Allow"
        Action   = "sns:Publish"
        Resource = aws_sns_topic.alerts.arn
      },
      {
        Sid      = "Tracing"
        Effect   = "Allow"
        Action   = ["xray:PutTraceSegments", "xray:PutTelemetryRecords"]
        Resource = "*" # iac-scan:allow IAC-003 X-Ray の書き込みは対象を絞れない（AWS の仕様）
      },
      {
        Sid      = "EncryptNotice"
        Effect   = "Allow"
        Action   = ["kms:GenerateDataKey", "kms:Decrypt"]
        Resource = aws_kms_key.logs.arn
      },
    ]
  })
}

# ---- 画面の file を配る役割（画面のバケットへ書く。借りるのは static-deploy.yml の配る job だけ）
# 信頼の sub は「環境 <env> と、main の static-deploy.yml」。作る job（static-build.yml）は別の file で環境も持たないので、借りられない。
# 書けるのは画面のバケットだけで、境界（foundation/ の StaticFilesOnly）も画面のバケットの外を許さない。
# この役割の書き込みも信じない。書くたびに、守りの口座の画面の照らし（security/static-watch.tf）が、書かれた版の指紋を
# 作りの来歴（static-build.yml の署名）と照らし、合わなければ鳴らす。資格を盗んで書いて戻しても、書いた時点で鳴る。

resource "aws_iam_role" "ci_push_static" {
  name                 = "${local.name}-ci-push-static"
  permissions_boundary = local.boundary_arn
  max_session_duration = 3600
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Federated = data.aws_iam_openid_connect_provider.github.arn }
      Action    = "sts:AssumeRoleWithWebIdentity"
      Condition = {
        StringEquals = {
          "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"
          "token.actions.githubusercontent.com:sub" = "${local.gh_workflow_sub}/static-deploy.yml@refs/heads/main${local.gh_ids}"
        }
      }
    }]
  })
}

resource "aws_iam_role_policy" "ci_push_static" {
  name = "push-static-files"
  role = aws_iam_role.ci_push_static.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "ListStatic"
        Effect   = "Allow"
        Action   = "s3:ListBucket"
        Resource = aws_s3_bucket.static.arn
      },
      {
        Sid      = "WriteStatic"
        Effect   = "Allow"
        Action   = ["s3:PutObject", "s3:DeleteObject"]
        Resource = "${aws_s3_bucket.static.arn}/*"
      },
      {
        Sid      = "EncryptStatic"
        Effect   = "Allow"
        Action   = "kms:GenerateDataKey"
        Resource = aws_kms_key.static.arn
      },
    ]
  })
}
