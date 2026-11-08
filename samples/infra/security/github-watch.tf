# GitHub の見張り（守りの口座の関数）。配備のリポジトリの管理者と GitHub の組織の持ち主（信頼の根）が守りを外したか、
# 守りの外の経路で変更を入れたかを、1 時間に 1 回確かめて鳴らす（functions/github_watch.py）。
#   置き場: コード、決めた値（functions/github-expected.json）、GitHub App の鍵、前回の main の先頭の印は、どれも守りの口座にある。
#     GitHub の中には何も置かないので、組織の持ち主でも、見張りのコードと決めた値は書き換えられない。
#   確かめる物: 設定（環境の承認者、main の保護、持ち主の欄、Actions の部品、OIDC の sub、公開の状態、自前の走る機械 0 台）、
#     前回の先頭からの main の続き（force push で戻していないか）と間の commit の全部、配備の承認、
#     組織の CloudTrail の CI の役割の借り入れと GitHub の実行の突き合わせ（実行と配備の記録を消しても、AWS の側の記録は残る）。
#   変えられる人: 関数のコードと設定、役割と方針、呼び出しの許可、出来事の宛先は、信頼の根の経路の watch-apply だけ（watchers/）。
#     守りの口座へ適用する CI は、ここにある鍵・印の表・アラーム・購読の外側だけを持ち、見張りの役割でコードを動かせない（SCP）。
#     どちらの変更も watch-change と watch-path-change が鳴らし、関数の変更は管理の口座の芯（watch-code）も 1 件ずつ鳴らす。
#   止まったら鳴る: ok が 2 時間届かなければ github-watch-not-ok。App を外された、鍵が無い、API に届かない、のどれも ng になる。

# GitHub App の鍵。値は Terraform にも状態にも置かず、セキュリティが入れる。読めるのは github-watch と static-watch の役割だけ。
resource "aws_secretsmanager_secret" "github_app_key" {
  name       = "${local.name}/github-app-key"
  kms_key_id = aws_kms_key.watch.arn
}

resource "aws_secretsmanager_secret_policy" "github_app_key" {
  secret_arn = aws_secretsmanager_secret.github_app_key.arn
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "OnlyTheWatchFunctions"
      Effect    = "Deny"
      Principal = "*"
      Action    = "secretsmanager:GetSecretValue"
      Resource  = "*"
      Condition = { ArnNotEquals = { "aws:PrincipalArn" = [for k in ["github-watch", "static-watch"] : "arn:${local.partition}:iam::${var.security_account_id}:role/${local.name}-${k}"] } }
    }]
  })
}

locals {
  # 見張りの関数と役割と宛先は watchers/（信頼の根の経路の役割 orders-guard-core-watch-apply だけが適用する）にある。
  # この構成は名前で指すだけで、関数のコード・設定・役割・呼び出しの許可・出来事の宛先を変えられない（SCP の orders-guard-core）。
  watch_function_arns = { for k in keys(local.watch_functions) : k => "arn:${local.partition}:lambda:${var.region}:${var.security_account_id}:function:${local.name}-${k}" }
  # 見張りの関数は 3 つ。同じ束（functions/）を使う。GitHub App の鍵を読めるのは github-watch と static-watch の役割の方針だけ
  # （秘密の方針は 3 つの役割の外を拒み、event-watch の役割の方針は鍵を読む操作を持たない）。
  watch_functions = {
    "github-watch" = { handler = "github_watch.handler", timeout = 120 }
    "static-watch" = { handler = "static_watch.handler", timeout = 300 }
    "event-watch"  = { handler = "event_watch.handler", timeout = 60 }
  }
}

resource "aws_cloudwatch_log_group" "watch_functions" {
  for_each          = local.watch_functions
  name              = "/aws/lambda/${local.name}-${each.key}"
  retention_in_days = var.trail_retention_days
  kms_key_id        = aws_kms_key.watch.arn
}

resource "aws_cloudwatch_event_rule" "github_watch" {
  name                = "${local.name}-github-watch-hourly"
  schedule_expression = "rate(1 hour)"
}

locals {
  github_watch_filters = {
    "github-watch-ok" = "{ ($.kind = \"github-watch\") && ($.status = \"ok\") }"
    "github-watch-ng" = "{ ($.kind = \"github-watch\") && ($.status = \"ng\") }"
  }
}

resource "aws_cloudwatch_log_metric_filter" "github_watch" {
  for_each       = local.github_watch_filters
  name           = "${local.name}-${each.key}"
  log_group_name = aws_cloudwatch_log_group.watch_functions["github-watch"].name
  pattern        = each.value

  metric_transformation {
    name      = each.key
    namespace = "${local.name}/watch"
    value     = "1"
  }
}

# ok が 2 時間届かない。関数を止めた、消した、GitHub App を外した、落ちた、のどれでも鳴る。
resource "aws_cloudwatch_metric_alarm" "github_watch_not_ok" {
  alarm_name          = "${local.name}-github-watch-not-ok"
  alarm_description   = "The GitHub watch did not report status ok for 2 hours"
  namespace           = "${local.name}/watch"
  metric_name         = "github-watch-ok"
  statistic           = "Sum"
  period              = 3600
  evaluation_periods  = 2
  datapoints_to_alarm = 2
  threshold           = 1
  comparison_operator = "LessThanThreshold"
  treat_missing_data  = "breaching"
  alarm_actions       = [aws_sns_topic.watch.arn]

  depends_on = [aws_cloudwatch_log_metric_filter.github_watch]
}

# ng が出た（設定が外れた、main が続いていない、承認の無い配備、PR を通らない commit、承認者の重なり、記録の消えた実行、自前の機械）。
resource "aws_cloudwatch_metric_alarm" "github_watch_ng" {
  alarm_name          = "${local.name}-github-watch-ng"
  alarm_description   = "The GitHub watch found a change outside the guarded path"
  namespace           = "${local.name}/watch"
  metric_name         = "github-watch-ng"
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.watch.arn]

  depends_on = [aws_cloudwatch_log_metric_filter.github_watch]
}

# 3 つの見張りの関数が落ちた（GitHub に届かない、来歴を確かめられない、権限が足りない）。落ちたら黙らず鳴る。
resource "aws_cloudwatch_metric_alarm" "watch_function_errors" {
  for_each            = local.watch_functions
  alarm_name          = "${local.name}-${each.key}-errors"
  alarm_description   = "The ${each.key} function failed"
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  dimensions          = { FunctionName = "${local.name}-${each.key}" }
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.watch.arn]
}
