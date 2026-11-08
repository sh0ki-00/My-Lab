# 見張りの関数と、それに届く物（守りの口座。信頼の根の経路だけが適用する）。
#   置く物: 見張りの関数 3 つ（github-watch、static-watch、event-watch）のコードと設定、その役割と方針、呼び出しの許可、
#     出来事の宛先（全部の規則の targets）、github-watch の前回の印。どれも、見張りの役割の名でデータを読める所か、鳴る先を決める所である。
#   適用する役割: orders-guard-core-watch-apply（org/guard-core.tf の StackSet が置く）。借りられるのは、環境 org-guarded
#     （セキュリティの承認、信頼の根の経路）を通った main の watch-apply.yml だけ。借りたら管理の口座の芯が AWS の外へ鳴らす。
#   守りの口座へ適用する CI（orders-guard-apply）は、ここに届かない。守りの口座の SCP（orders-guard-core）が、関数の作成と
#     コードと設定と呼び出しの許可の変更、見張りの役割の受け渡しと書き換え、出来事の宛先の変更を、この役割のほかに拒む。
#     前の作りでは、その CI が見張りの役割で動く自前のコードを置き、見張りの例外（DataReadsOnlyForWatch）を通って組織の記録と秘密を読めた。
#     関数の呼び出しの許可を外の口座へ開く道（Lambda は RCP の対象の外）も、同じ SCP で閉じる。関数の URL は誰にも作らせない。
#   読む物は security/ の資源で、名前で引く（data）。適用の順は security/ → watchers/ → security/（購読と通知を付ける 2 回目）。
#   止まったら鳴る: 関数の Errors と ok の途絶のアラームは security/ にある。コードと設定の変更は、芯の watch-code が 1 件ずつ鳴らす。
# 値は ../security.tfvars（架空）。

locals {
  watch_functions = {
    "github-watch" = { handler = "github_watch.handler", timeout = 120 }
    "static-watch" = { handler = "static_watch.handler", timeout = 300 }
    "event-watch"  = { handler = "event_watch.handler", timeout = 60 }
  }
  heartbeat_bus = "${local.name}-heartbeat"
  rule_arns     = { for r in ["github-watch-hourly", "static-sweep"] : r => "arn:${local.partition}:events:${var.region}:${var.security_account_id}:rule/${local.name}-${r}" }
}

data "aws_kms_alias" "watch" {
  name = "alias/${local.name}-watch"
}

data "aws_sns_topic" "watch" {
  name = "${local.name}-watch"
}

data "aws_sns_topic" "security" {
  name = "${local.name}-security"
}

data "aws_cloudwatch_log_group" "org_trail" {
  name = "/${local.name}/org-trail"
}

data "aws_cloudwatch_log_group" "incidents" {
  name = "/aws/events/${local.name}-incidents"
}

data "aws_cloudwatch_log_group" "watch_functions" {
  for_each = local.watch_functions
  name     = "/aws/lambda/${local.name}-${each.key}"
}

data "aws_cloudwatch_log_group" "heartbeat" {
  for_each = var.workload_accounts
  name     = "/aws/events/${local.name}-heartbeat-${each.key}"
}

data "aws_dynamodb_table" "static_checked" {
  name = "${local.name}-static-checked"
}

data "aws_s3_bucket" "github_audit" {
  bucket = "${local.name}-github-audit-${var.security_account_id}"
}

data "aws_secretsmanager_secret" "github_app_key" {
  name = "${local.name}/github-app-key"
}

# ---- 見張りの本体（もとは security/github-watch.tf にあった物）

data "archive_file" "watch" {
  type        = "zip"
  source_dir  = "${path.module}/../functions"
  output_path = "${path.module}/.build/watch.zip"
}

# 前回の main の先頭の印。書くのは github-watch の関数だけ。消されたら、次の回が「印が無い」で ng を出す。
resource "aws_ssm_parameter" "github_watch_state" {
  name  = "/${local.name}/github-watch/state"
  type  = "String"
  value = "{}"

  lifecycle {
    ignore_changes = [value]
  }
}

resource "aws_iam_role" "watch_functions" {
  for_each             = local.watch_functions
  name                 = "${local.name}-${each.key}"
  permissions_boundary = local.guard_boundary_arn
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
      Condition = { StringEquals = { "aws:SourceAccount" = var.security_account_id } }
    }]
  })
}

resource "aws_iam_role_policy" "github_watch" {
  name = "github-watch"
  role = aws_iam_role.watch_functions["github-watch"].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "AppKeyAndState"
        Effect   = "Allow"
        Action   = ["secretsmanager:GetSecretValue", "ssm:GetParameter", "ssm:PutParameter"]
        Resource = [data.aws_secretsmanager_secret.github_app_key.arn, aws_ssm_parameter.github_watch_state.arn]
      },
      {
        Sid       = "DecryptAppKey"
        Effect    = "Allow"
        Action    = "kms:Decrypt"
        Resource  = data.aws_kms_alias.watch.target_key_arn
        Condition = { StringEquals = { "kms:ViaService" = "secretsmanager.${var.region}.amazonaws.com" } }
      },
      {
        # 組織の CloudTrail から、CI の役割の借り入れを読む。読むのは記録の 1 か所だけ。
        Sid      = "ReadOrgTrail"
        Effect   = "Allow"
        Action   = "logs:FilterLogEvents"
        Resource = "${data.aws_cloudwatch_log_group.org_trail.arn}:*"
      },
      {
        # 管理の口座の IAM の数（利用者、root の鍵、root の MFA）を毎時読む（第 15 回）。借りられる役割は 1 つだけ。
        Sid      = "MgmtSummary"
        Effect   = "Allow"
        Action   = "sts:AssumeRole"
        Resource = "arn:${local.partition}:iam::${var.management_account_id}:role/orders-guard-core-mgmt-summary"
      },
      {
        Sid      = "OwnLog"
        Effect   = "Allow"
        Action   = ["logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = "${data.aws_cloudwatch_log_group.watch_functions["github-watch"].arn}:*"
      },
    ]
  })
}

# 層の中身の指紋を決めた値と照らす。層（PyJWT と sigstore）を悪い版に替えると、いつも合うと返す見張りになる。
# 層の版を替えるのは守りの口座への適用だけで、指紋の変更は計画の差分に出るので、承認する人が版の差分を読む（手順は未確定 7）。
data "aws_lambda_layer_version" "watch" {
  layer_name = regex("^(.*):[0-9]+$", var.watch_python_layer_arn)[0]
  version    = tonumber(regex(":([0-9]+)$", var.watch_python_layer_arn)[0])
}

check "watch_layer_pinned" {
  assert {
    condition     = data.aws_lambda_layer_version.watch.code_sha256 == var.watch_python_layer_sha256
    error_message = "見張りの関数の層の指紋が決めた値と違う。層の版の差分を読み、決めた値を守りの経路で変える。"
  }
}

resource "aws_lambda_function" "watch" {
  for_each         = local.watch_functions
  function_name    = "${local.name}-${each.key}"
  role             = aws_iam_role.watch_functions[each.key].arn
  runtime          = "python3.12"
  architectures    = ["arm64"]
  handler          = each.value.handler
  filename         = data.archive_file.watch.output_path
  source_code_hash = data.archive_file.watch.output_base64sha256
  timeout          = each.value.timeout
  memory_size      = 256
  layers           = [var.watch_python_layer_arn]

  environment {
    variables = {
      APP_KEY_SECRET      = data.aws_secretsmanager_secret.github_app_key.arn
      APP_ID              = tostring(var.github_app_id)
      APP_INSTALLATION_ID = tostring(var.github_app_installation_id)
      STATE_PARAMETER     = aws_ssm_parameter.github_watch_state.name
      ORG_TRAIL_LOG_GROUP = data.aws_cloudwatch_log_group.org_trail.name
      REPOSITORY          = var.github_repository
      REPOSITORY_ID       = var.github_repository_id
      REPOSITORY_OWNER_ID = var.github_repository_owner_id
      SIGNER_WORKFLOW     = ".github/workflows/static-build.yml"
      WORKLOAD_REGION     = var.region
      STATIC_BUCKETS      = jsonencode({ for e, a in var.workload_accounts : "orders-admin-${e}-static-${a}" => "arn:${local.partition}:iam::${a}:role/orders-admin-${e}-ci-push-static" })
      CHECKED_TABLE       = data.aws_dynamodb_table.static_checked.name
      # 非公開のリポジトリの来歴は GitHub の Sigstore が署名する。信頼の根の file は層に入れる（未確定 7 と 29）。
      SIGSTORE_TRUSTED_ROOT = "/opt/sigstore/github-trusted-root.json"
      SECURITY_TOPIC        = data.aws_sns_topic.security.arn
      WATCH_TOPIC           = data.aws_sns_topic.watch.arn
      INCIDENT_LOG_GROUP    = data.aws_cloudwatch_log_group.incidents.name
      # 第 15 回: 像を読む作業の口座の一覧、信頼の根の書き込みを見分ける管理の口座、毎時に IAM の数を読む役割。
      WORKLOAD_ACCOUNTS     = join(",", values(var.workload_accounts))
      MANAGEMENT_ACCOUNT_ID = var.management_account_id
      MGMT_SUMMARY_ROLE     = "arn:${local.partition}:iam::${var.management_account_id}:role/orders-guard-core-mgmt-summary"
      # 第 16 回: 15 分ごとの便りが数えるアラームの名の頭。
      NAME_PREFIX = "${local.name}-"
    }
  }
}

resource "aws_cloudwatch_event_target" "github_watch" {
  rule = "${local.name}-github-watch-hourly"
  arn  = aws_lambda_function.watch["github-watch"].arn
}

resource "aws_lambda_permission" "github_watch" {
  statement_id  = "HourlyGitHubWatch"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.watch["github-watch"].function_name
  principal     = "events.amazonaws.com"
  source_arn    = local.rule_arns["github-watch-hourly"]
}

# ---- 見張りの本体（もとは security/static-watch.tf にあった物）

resource "aws_iam_role_policy" "static_watch" {
  name = "static-watch"
  role = aws_iam_role.watch_functions["static-watch"].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "ReadStaticVersions"
        Effect = "Allow"
        Action = ["s3:ListBucket", "s3:ListBucketVersions", "s3:GetObjectVersion", "s3:GetObject"]
        Resource = flatten([for e, a in var.workload_accounts : [
          "arn:${local.partition}:s3:::orders-admin-${e}-static-${a}", "arn:${local.partition}:s3:::orders-admin-${e}-static-${a}/*",
        ]])
      },
      {
        Sid       = "DecryptStaticThroughS3"
        Effect    = "Allow"
        Action    = "kms:Decrypt"
        Resource  = [for a in values(var.workload_accounts) : "arn:${local.partition}:kms:${var.region}:${a}:key/*"]
        Condition = { StringEquals = { "kms:ViaService" = "s3.${var.region}.amazonaws.com" } }
      },
      {
        # 照らした版の印。書くのはこの関数だけ。印を消されても、照らし直すだけで、照らしは抜けない（閉じる側）。
        Sid      = "CheckedMarks"
        Effect   = "Allow"
        Action   = ["dynamodb:GetItem", "dynamodb:PutItem"]
        Resource = data.aws_dynamodb_table.static_checked.arn
      },
      {
        Sid       = "DecryptMarks"
        Effect    = "Allow"
        Action    = ["kms:Decrypt", "kms:GenerateDataKey"]
        Resource  = data.aws_kms_alias.watch.target_key_arn
        Condition = { StringEquals = { "kms:ViaService" = "dynamodb.${var.region}.amazonaws.com" } }
      },
      {
        Sid      = "AppKey"
        Effect   = "Allow"
        Action   = "secretsmanager:GetSecretValue"
        Resource = data.aws_secretsmanager_secret.github_app_key.arn
      },
      {
        Sid       = "DecryptAppKey"
        Effect    = "Allow"
        Action    = "kms:Decrypt"
        Resource  = data.aws_kms_alias.watch.target_key_arn
        Condition = { StringEquals = { "kms:ViaService" = "secretsmanager.${var.region}.amazonaws.com" } }
      },
      {
        Sid      = "OwnLog"
        Effect   = "Allow"
        Action   = ["logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = "${data.aws_cloudwatch_log_group.watch_functions["static-watch"].arn}:*"
      },
    ]
  })
}

resource "aws_lambda_permission" "static_watch" {
  statement_id  = "OrgTrailSubscription"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.watch["static-watch"].function_name
  principal     = "logs.${var.region}.amazonaws.com"
  source_arn    = "${data.aws_cloudwatch_log_group.org_trail.arn}:*"
}

resource "aws_cloudwatch_event_target" "static_sweep" {
  rule  = "${local.name}-static-sweep"
  arn   = aws_lambda_function.watch["static-watch"].arn
  input = jsonencode({ mode = "sweep" })
}

resource "aws_lambda_permission" "static_sweep" {
  statement_id  = "DailySweep"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.watch["static-watch"].function_name
  principal     = "events.amazonaws.com"
  source_arn    = local.rule_arns["static-sweep"]
}

# ---- 見張りの本体（もとは security/event-watch.tf にあった物）

resource "aws_iam_role_policy" "event_watch" {
  name = "event-watch"
  role = aws_iam_role.watch_functions["event-watch"].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "PublishBothTopics"
        Effect   = "Allow"
        Action   = "sns:Publish"
        Resource = [data.aws_sns_topic.security.arn, data.aws_sns_topic.watch.arn]
      },
      {
        Sid      = "ReadIncidents"
        Effect   = "Allow"
        Action   = "logs:FilterLogEvents"
        Resource = "${data.aws_cloudwatch_log_group.incidents.arn}:*"
      },
      {
        Sid      = "ReadAuditStream"
        Effect   = "Allow"
        Action   = "s3:GetObject"
        Resource = "${data.aws_s3_bucket.github_audit.arn}/*"
      },
      {
        # 移行と利用者づくりのイメージの来歴と、main の roles.sql を GitHub から読む（第 14 回。functions/event_watch.py の db_image_checks）。
        Sid      = "ReadGitHubAppKey"
        Effect   = "Allow"
        Action   = "secretsmanager:GetSecretValue"
        Resource = data.aws_secretsmanager_secret.github_app_key.arn
      },
      {
        Sid      = "UseWatchKey"
        Effect   = "Allow"
        Action   = ["kms:Decrypt", "kms:GenerateDataKey"]
        Resource = data.aws_kms_alias.watch.target_key_arn
      },
      {
        # DB の 2 つの像の層を読む（第 15 回）。作業の口座の像のリポジトリの方針も、この役割だけに読むことを許す（app.tf）。
        Sid      = "ReadDbImages"
        Effect   = "Allow"
        Action   = ["ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer"]
        Resource = flatten([for e, a in var.workload_accounts : [for r in ["db-bootstrap", "db-migrate"] : "arn:${local.partition}:ecr:${var.region}:${a}:repository/orders-admin-${e}/${r}"]])
      },
      {
        Sid      = "OwnLog"
        Effect   = "Allow"
        Action   = ["logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = "${data.aws_cloudwatch_log_group.watch_functions["event-watch"].arn}:*"
      },
      {
        # 15 分ごとの便りの前に、見張りの形を数える（第 16 回。読むだけの呼び出し。中身は読まない）。
        Sid    = "CountWatchShape"
        Effect = "Allow"
        Action = ["cloudwatch:DescribeAlarms", "logs:DescribeMetricFilters", "logs:DescribeSubscriptionFilters", "sns:ListSubscriptionsByTopic"]
        Resource = [
          "arn:${local.partition}:cloudwatch:${var.region}:${var.security_account_id}:alarm:${local.name}-*",
          "arn:${local.partition}:logs:${var.region}:${var.security_account_id}:log-group:*",
          data.aws_sns_topic.security.arn, data.aws_sns_topic.watch.arn,
        ]
      },
      {
        Sid      = "ListTopics"
        Effect   = "Allow"
        Action   = "sns:ListTopics"
        Resource = "*" # iac-scan:allow IAC-003 sns:ListTopics は対象を絞れない（AWS の仕様）。返るのは話題の名だけ
      },
    ]
  })
}

resource "aws_lambda_permission" "event_watch_trail" {
  statement_id  = "OrgTrailEntries"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.watch["event-watch"].function_name
  principal     = "logs.${var.region}.amazonaws.com"
  source_arn    = "${data.aws_cloudwatch_log_group.org_trail.arn}:*"
}

resource "aws_cloudwatch_event_target" "incidents" {
  rule           = "${local.name}-incidents"
  event_bus_name = local.heartbeat_bus
  arn            = data.aws_cloudwatch_log_group.incidents.arn
}

resource "aws_lambda_permission" "event_watch_audit" {
  statement_id   = "GitHubAuditStream"
  action         = "lambda:InvokeFunction"
  function_name  = aws_lambda_function.watch["event-watch"].function_name
  principal      = "s3.amazonaws.com"
  source_arn     = data.aws_s3_bucket.github_audit.arn
  source_account = var.security_account_id
}

# ---- 見張りの本体（もとは security/watch.tf にあった物）

# 15 分ごとの便り（第 16 回）。決まった便りを話題へ直に出す形をやめ、event-watch の関数が見張りの欠けを数えて、欠けが 0 のときだけ出す。
resource "aws_cloudwatch_event_target" "notify_heartbeat" {
  rule  = "${local.name}-notify-heartbeat"
  arn   = aws_lambda_function.watch["event-watch"].arn
  input = jsonencode({ kind = "guard-heartbeat" })
}

resource "aws_lambda_permission" "event_watch_heartbeat" {
  statement_id   = "GuardHeartbeat"
  action         = "lambda:InvokeFunction"
  function_name  = aws_lambda_function.watch["event-watch"].function_name
  principal      = "events.amazonaws.com"
  source_arn     = "arn:${local.partition}:events:${var.region}:${var.security_account_id}:rule/${local.name}-notify-heartbeat"
  source_account = var.security_account_id
}

moved {
  from = aws_cloudwatch_event_target.notify_heartbeat["watch"]
  to   = aws_cloudwatch_event_target.notify_heartbeat
}

resource "aws_cloudwatch_event_target" "heartbeat" {
  for_each       = var.workload_accounts
  rule           = "${local.name}-heartbeat-${each.key}"
  event_bus_name = local.heartbeat_bus
  arn            = data.aws_cloudwatch_log_group.heartbeat[each.key].arn
}

# 便りと障害の記録のロググループへ、EventBridge が書くための資源の方針（もとは security/watch.tf にあった物）。
# ロググループの資源の方針を置けるのは watch-apply だけ（org/guard-core.tf の WatchLogPolicies）。守りの口座へ適用する CI は置けない。
# 外の口座の主体に読み出しを許す方針を書いても、組織の RCP（org/scp.tf の OrgPrincipalsOnly の logs:*）が拒む。
resource "aws_cloudwatch_log_resource_policy" "heartbeat" {
  policy_name = "${local.name}-heartbeat"
  policy_document = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = ["events.amazonaws.com", "delivery.logs.amazonaws.com"] }
      Action    = ["logs:CreateLogStream", "logs:PutLogEvents"]
      Resource  = concat([for g in data.aws_cloudwatch_log_group.heartbeat : "${g.arn}:*"], ["${data.aws_cloudwatch_log_group.incidents.arn}:*"])
    }]
  })
}
