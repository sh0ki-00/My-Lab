# 複製の棚卸し（copy-inventory）。1 時間に 1 回、口座の中の複製を数えて台帳に書き、決めた日数を過ぎた手の複製と、
# 決めた時間を過ぎた訓練の写しを消す。守りそのもの（アラーム、購読、起動の規則）も数える。
# 棚卸しは守りの仕組みなので、関数と設定と起動の規則を変えられるのは守りの適用の役割だけ（org/scp.tf、plan-gate の一覧の外）。
# 止まったか誤ったら鳴る: 呼ばれない（Invocations）、落ちた（Errors）、最後まで動かなかった（summary の行が届かない）の 3 本。
#   点検は 1 つずつ動き、1 つが落ちても残りを続ける。落ちた点検は知らせに載せ、知らせと便り（ng）を出してから例外で終わる。
#   アラームは状態が変わったときだけ鳴るので、落ち続けても黙らないよう、知らせは毎時 SNS へ出す。ALARM のままのアラームも毎時並べ直す。
#   役割の方針の操作は、権限の境界（foundation/ の boundary）の内側にあること。外の操作は iac-scan の「境界の外」が落とす。
#   見る地域: 東京と us-east-1（SCP が許す 2 つ）。見るもの: 手とクラスタのスナップショット、データベースとクラスタ、
#     自動バックアップ（別の地域へ複製されたものを含む）、保管庫、バケット、CloudFront の配信。
#   台帳: Lambda の出力のロググループ（1 行 1 複製の JSON。監査ログと同じ日数残す）。移行の写しの消す日もここに載る。
#   消す: 名前が「<構成の名前>-」で始まる手の複製のうち、var.manual_copy_max_days 日を過ぎたもの（最後の複製を含む）。
#   知らせる: 札（managed_by など）は見ない。札は付け替えられるので、名前と日数と地域で決める。
#     名前の分からない手とクラスタの複製、名前が -restore- で 1 日を超えたデータベース、知っている 1 つの外のデータベースとクラスタ、
#     住みかの地域の外の自動バックアップ、外から届くデータベース、知らないバケット、WAF の無い配信と、内部のロードバランサーへつなぐ 2 本目の配信、
#     アドレスの範囲で受ける通信の規則（この構成の受け口は、どれもセキュリティグループの名指し）。
#     VAULT_NAME の外の保管庫（既定の保管庫を含む）にある復旧点。
#   守りの欠け: 購読の数が EXPECTED_SUBS と違う、購読に絞り込み（FilterPolicy）が付いた、アラームの動作が止まった、起動の規則が止まった、
#     点検が落ちた。画面のバケットの中身の照らしは、守りの口座が書き込みのたびに行う（security/static-watch.tf）。
#   外への便り: 守りの欠けが 0 のときだけ、守りの口座のバス（var.guard_heartbeat_bus_arn）へ status=ok を送る。
#     ok が 2 時間届かなければ、守りの口座が鳴らす（作業の口座の SNS を通らない 2 本目の確かめ）。
# 手の複製を新しく作れるのは AWS Backup だけ（org/ の SCP）。保管庫の複製は寿命つきで、ここでは数えるだけ。

data "archive_file" "copy_inventory" {
  type        = "zip"
  source_file = "${path.module}/functions/copy_inventory.py"
  output_path = "${path.module}/.build/copy_inventory.zip"
}

resource "aws_cloudwatch_log_group" "copy_ledger" {
  name              = "/aws/lambda/${local.name}-copy-inventory"
  retention_in_days = var.audit_retention_days
  kms_key_id        = aws_kms_key.logs.arn
}

resource "aws_lambda_function" "copy_inventory" {
  function_name    = "${local.name}-copy-inventory"
  role             = aws_iam_role.copy_inventory.arn
  runtime          = "python3.12"
  architectures    = ["arm64"]
  handler          = "copy_inventory.handler"
  filename         = data.archive_file.copy_inventory.output_path
  source_code_hash = data.archive_file.copy_inventory.output_base64sha256
  timeout          = 120
  memory_size      = 256

  tracing_config {
    mode = "Active"
  }

  environment {
    variables = {
      NAME_PREFIX      = "${local.name}-"
      MAX_DAYS         = tostring(var.manual_copy_max_days)
      VAULT_NAME       = aws_backup_vault.orders.name
      ALERT_TOPIC      = aws_sns_topic.alerts.arn
      ALERT_TOPIC_USE1 = aws_sns_topic.alerts_use1.arn
      DELETE_EXPIRE    = "true"
      REGIONS          = join(",", [var.region, "us-east-1"])
      HOME_REGION      = var.region
      KNOWN_DBS        = aws_db_instance.orders.identifier
      RESTORE_MARK     = "${local.name}-restore-"
      RESTORE_HOURS    = tostring(var.drill_copy_max_hours)
      KNOWN_BUCKETS    = join(",", [aws_s3_bucket.static.id, aws_s3_bucket.audit.id, var.state_bucket_name])
      WEB_ACL_ARN      = aws_wafv2_web_acl.admin.arn
      EDGE_ID          = aws_cloudfront_distribution.admin.id
      RULE_NAME        = "${local.name}-copy-inventory-hourly"
      MIN_ALARMS       = tostring(length(local.trail_filters) + length(local.protected_log_groups))
      EXPECTED_SUBS    = "2"
      VPC_ID           = aws_vpc.main.id
      HEARTBEAT_BUS    = var.guard_heartbeat_bus_arn
    }
  }

  depends_on = [aws_cloudwatch_log_group.copy_ledger]
}

resource "aws_cloudwatch_event_rule" "copy_inventory" {
  name                = "${local.name}-copy-inventory-hourly"
  description         = "Count copies and guards, expire manual copies and drill copies, write the ledger"
  schedule_expression = "rate(1 hour)"
}

resource "aws_cloudwatch_event_target" "copy_inventory" {
  rule = aws_cloudwatch_event_rule.copy_inventory.name
  arn  = aws_lambda_function.copy_inventory.arn
}

resource "aws_lambda_permission" "copy_inventory" {
  statement_id  = "DailyInventory"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.copy_inventory.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.copy_inventory.arn
}

# 止まったか誤ったら鳴る 3 本。どれも宛先は SRE の当番。
#   not-run: 2 時間呼ばれていない（起動の規則を止められた、消された）。
#   errors: 1 回でも落ちた（設定の値が幅の外、権限が足りない、コードの誤り）。
#   incomplete: 最後まで動いた印（summary の行）が 2 時間届かない（中身を空にされた、途中で黙って止まった）。
resource "aws_cloudwatch_metric_alarm" "copy_inventory_not_run" {
  alarm_name          = "${local.name}-copy-inventory-not-run"
  alarm_description   = "The copy inventory was not invoked for 2 hours"
  namespace           = "AWS/Lambda"
  metric_name         = "Invocations"
  dimensions          = { FunctionName = aws_lambda_function.copy_inventory.function_name }
  statistic           = "Sum"
  period              = 3600
  evaluation_periods  = 2
  threshold           = 1
  comparison_operator = "LessThanThreshold"
  treat_missing_data  = "breaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
}

resource "aws_cloudwatch_metric_alarm" "copy_inventory_errors" {
  alarm_name          = "${local.name}-copy-inventory-errors"
  alarm_description   = "The copy inventory failed"
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  dimensions          = { FunctionName = aws_lambda_function.copy_inventory.function_name }
  statistic           = "Sum"
  period              = 3600
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
}

resource "aws_cloudwatch_log_metric_filter" "copy_inventory_done" {
  name           = "${local.name}-copy-inventory-done"
  log_group_name = aws_cloudwatch_log_group.copy_ledger.name
  pattern        = "{ $.kind = \"summary\" }"

  metric_transformation {
    name      = "copy-inventory-done"
    namespace = local.guard_namespace
    value     = "1"
  }
}

resource "aws_cloudwatch_metric_alarm" "copy_inventory_incomplete" {
  alarm_name          = "${local.name}-copy-inventory-incomplete"
  alarm_description   = "The copy inventory did not finish for 2 hours"
  namespace           = local.guard_namespace
  metric_name         = "copy-inventory-done"
  statistic           = "Sum"
  period              = 3600
  evaluation_periods  = 2
  threshold           = 1
  comparison_operator = "LessThanThreshold"
  treat_missing_data  = "breaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]

  depends_on = [aws_cloudwatch_log_metric_filter.copy_inventory_done]
}
