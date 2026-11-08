# 出来事ごとの見張り（守りの口座の関数 event-watch。functions/event_watch.py）。状態が変わったときだけ鳴るアラームに頼らない。
#   起点 1: 組織の CloudTrail の購読。人と信頼の根の入り（当番、緊急の管理、守りの適用、土台、守りの口座の適用、管理の口座の root と
#     コンソール）を 1 件ごとにセキュリティの宛先へ送る。当番の入りは、作業の口座の障害の記録（アラームが ALARM になった出来事）と
#     突き合わせ、前後 2 時間に記録が無ければ ng で鳴らす。宛先は当番（SRE）の外なので、当番が自分の通知を片付けても残る。
#     DB の管理者を使う作業（利用者づくり db-bootstrap の起動）も 1 件ごとに送る（第 14 回）。移行と利用者づくりのイメージの押し込み
#     （ECR の PutImage）は、来歴を確かめて送る。第 15 回: 長く使える鍵（IAM の利用者）の利用はどの口座でも ng で送り、管理の口座の
#     読むだけでない出来事（StackSet、芯の通知の書き換えを含む）と AssumeRoot も 1 件ごとに送る。来歴が main の db-image-push.yml の作る job の物でないか、利用者づくりのイメージの
#     roles.sql の指紋が今の main の roles.sql と違えば ng（指紋の正本は repo の file だけ。DB の上で取り直した指紋を正にしない）。
#     第 16 回: 管理の口座の借り入れ（AssumeRole*）は readOnly の値によらず送る。OrganizationAccountAccessRole の借り入れはどの口座でも送る。
#     利用者づくりの起動（RunTask）は、起動した像のダイジェストを記録から引き、来歴と中身を今の main に照らす（1 つ前の像へ戻す手）。
#     15 分ごとの便り（security/heartbeat.tf）も、この関数が見張りの欠けを数えてから送る。
#   起点 2: GitHub の監査ログの流し出し（GitHub Enterprise の audit log streaming。OIDC で下の役割を借りて、このバケットへ書く）。
#     main の保護と規則と環境の変更、自前の走る機械の登録、公開の状態、実行の消去、team の顔ぶれ、main への直の push を、出来事ごとに鳴らす。
#     毎時の照らし（github-watch）の間に外して戻す手も、その場で鳴る。流し出しの型と出来事の名前の確かめは未確定 24。
#   変えられる人: 関数のコードと設定、役割と方針、呼び出しの許可、出来事の宛先は、信頼の根の経路の watch-apply だけ（watchers/）。
#     守りの口座へ適用する CI は、ここにある鍵・印の表・アラーム・購読の外側だけを持ち、見張りの役割でコードを動かせない（SCP）。
#     どちらの変更も watch-change と watch-path-change が鳴らし、関数の変更は管理の口座の芯（watch-code）も 1 件ずつ鳴らす。
#   止まったら鳴る: 関数が落ちたら event-watch-errors。流し出しの file が 24 時間届かなければ github-audit-silent。

# ---- 起点 1: 組織の記録の人と信頼の根の入り（ロググループの 2 本目の購読。1 本目は static-watch）

resource "aws_cloudwatch_log_subscription_filter" "event_watch" {
  name            = "${local.name}-entries"
  log_group_name  = aws_cloudwatch_log_group.org_trail.name
  filter_pattern  = "{ (($.eventName = \"AssumeRoleWithSAML\") && ($.requestParameters.roleArn = \"*AWSReservedSSO_orders-*\")) || (($.eventName = \"AssumeRole*\") && (($.requestParameters.roleArn = \"*-apply-guarded\") || ($.requestParameters.roleArn = \"*:role/platform-foundation\") || ($.requestParameters.roleArn = \"*:role/${local.name}-apply\") || ($.requestParameters.roleArn = \"*:role/${local.name}-core-watch-apply\") || ($.requestParameters.roleArn = \"*:role/OrganizationAccountAccessRole\"))) || ($.userIdentity.type = \"IAMUser\") || (($.recipientAccountId = \"${var.management_account_id}\") && ($.userIdentity.type != \"AWSService\") && (($.readOnly IS FALSE) || ($.userIdentity.type = \"Root\") || ($.eventName = \"ConsoleLogin\") || ($.eventName = \"AssumeRo*\"))) || (($.eventName = \"RunTask\") && ($.requestParameters.taskDefinition = \"*-db-bootstrap*\")) || (($.eventName = \"PutImage\") && (($.requestParameters.repositoryName = \"*/db-bootstrap\") || ($.requestParameters.repositoryName = \"*/db-migrate\"))) }"
  destination_arn = local.watch_function_arns["event-watch"]
}

# 障害の記録。作業の口座のアラームが ALARM になった出来事を、作業の口座の規則（guardrails.tf の alarm-forward）が便りのバスへ送り、ここに残す。
# 当番は SCP でアラームの状態を変えられない（SetAlarmState は守りの適用だけ）ので、入る理由を自分で作れない。
resource "aws_cloudwatch_log_group" "incidents" {
  name              = "/aws/events/${local.name}-incidents"
  retention_in_days = var.trail_retention_days
  kms_key_id        = aws_kms_key.watch.arn
}

resource "aws_cloudwatch_event_rule" "incidents" {
  name           = "${local.name}-incidents"
  event_bus_name = aws_cloudwatch_event_bus.heartbeat.name
  # 送り元は AWS のサービスの出来事（source が aws. で始まる名前は PutEvents で作れない）なので、作業の口座の主体は記録を偽れない。
  event_pattern = jsonencode({
    source        = ["aws.cloudwatch"]
    account       = values(var.workload_accounts)
    "detail-type" = ["CloudWatch Alarm State Change"]
  })
}

# ---- 起点 2: GitHub の監査ログの流し出し

resource "aws_s3_bucket" "github_audit" {
  bucket = "${local.name}-github-audit-${var.security_account_id}"
}

resource "aws_s3_bucket_public_access_block" "github_audit" {
  bucket                  = aws_s3_bucket.github_audit.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "github_audit" {
  bucket = aws_s3_bucket.github_audit.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "github_audit" {
  bucket = aws_s3_bucket.github_audit.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.watch.arn
    }
  }
}

# GitHub の監査ログの流し出しが借りる役割。OIDC の発行元と sub は GitHub の手引きの型（enterprise の名前）。確かめは未確定 24。
resource "aws_iam_openid_connect_provider" "github_audit" {
  url            = "https://oidc-configuration.audit-log.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"]
}

resource "aws_iam_role" "github_audit_stream" {
  name                 = "${local.name}-github-audit-stream"
  permissions_boundary = local.guard_boundary_arn
  max_session_duration = 3600
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Federated = aws_iam_openid_connect_provider.github_audit.arn }
      Action    = "sts:AssumeRoleWithWebIdentity"
      Condition = {
        StringEquals = {
          "oidc-configuration.audit-log.githubusercontent.com:aud" = "sts.amazonaws.com"
          "oidc-configuration.audit-log.githubusercontent.com:sub" = "https://github.com/${var.github_enterprise}"
        }
      }
    }]
  })
}

resource "aws_iam_role_policy" "github_audit_stream" {
  name = "write-audit-stream"
  role = aws_iam_role.github_audit_stream.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "WriteStream"
        Effect   = "Allow"
        Action   = "s3:PutObject"
        Resource = "${aws_s3_bucket.github_audit.arn}/*"
      },
      {
        Sid       = "EncryptStream"
        Effect    = "Allow"
        Action    = "kms:GenerateDataKey"
        Resource  = aws_kms_key.watch.arn
        Condition = { StringEquals = { "kms:ViaService" = "s3.${var.region}.amazonaws.com" } }
      },
    ]
  })
}

resource "aws_s3_bucket_notification" "github_audit" {
  bucket = aws_s3_bucket.github_audit.id

  lambda_function {
    lambda_function_arn = local.watch_function_arns["event-watch"]
    events              = ["s3:ObjectCreated:*"]
  }
}

# ---- 鳴らす

locals {
  event_watch_filters = {
    "entry-ng"          = "{ ($.kind = \"entry\") && ($.status = \"ng\") }"
    "github-audit-ng"   = "{ ($.kind = \"github-audit\") && ($.status = \"ng\") }"
    "github-audit-file" = "{ $.kind = \"github-audit-file\" }"
  }
}

resource "aws_cloudwatch_log_metric_filter" "event_watch" {
  for_each       = local.event_watch_filters
  name           = "${local.name}-${each.key}"
  log_group_name = aws_cloudwatch_log_group.watch_functions["event-watch"].name
  pattern        = each.value

  metric_transformation {
    name      = each.key
    namespace = "${local.name}/watch"
    value     = "1"
  }
}

# 障害の記録の無い当番の入りと、GitHub の守りの変更。出来事ごとの通知は関数が送り、このアラームは数の記録として残す。
resource "aws_cloudwatch_metric_alarm" "event_watch_ng" {
  for_each            = toset(["entry-ng", "github-audit-ng"])
  alarm_name          = "${local.name}-${each.key}"
  alarm_description   = "The event watch found ${each.key}"
  namespace           = "${local.name}/watch"
  metric_name         = each.key
  statistic           = "Sum"
  period              = 60
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.watch.arn, aws_sns_topic.security.arn]

  depends_on = [aws_cloudwatch_log_metric_filter.event_watch]
}

# 流し出しが止まった（GitHub の側で流し出しを外した、役割の信頼を壊した、関数が呼ばれない）。
resource "aws_cloudwatch_metric_alarm" "github_audit_silent" {
  alarm_name          = "${local.name}-github-audit-silent"
  alarm_description   = "No GitHub audit log stream file arrived for 24 hours"
  namespace           = "${local.name}/watch"
  metric_name         = "github-audit-file"
  statistic           = "Sum"
  period              = 86400
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "LessThanThreshold"
  treat_missing_data  = "breaching"
  alarm_actions       = [aws_sns_topic.watch.arn, aws_sns_topic.security.arn]

  depends_on = [aws_cloudwatch_log_metric_filter.event_watch]
}
