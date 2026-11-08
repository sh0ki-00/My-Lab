# 画面の照らし（守りの口座の関数）。画面のバケットへの書き込みのたびに、書かれた版を作りの来歴と照らして鳴らす（functions/static_watch.py）。
#   照らしを CI の外に置く。CI が書く指紋の一覧は置かない（前の作りの _manifest/ と指紋の job と、毎時の照らしは消した）。
#   時刻の窓は使わない。キーの版のうち、まだ照らしていない全部の版を照らし、照らした版の印を守りの口座の表（static_checked）に置く。
#   どの版も、書かれた時刻の main の最新の作り（成功した push の実行のうち、やり直しでない実行の run_number の最大）の来歴であることを確かめる。
#   今の版かどうかで照らし方を変えないので、古い作りを書いて照らしの前に戻しても、書いた版が鳴る。
#   毎日 1 回の見回り（static_sweep）が、今の版の全部の file を今の index.html と同じ作りか照らす（外した部品の古い file の残りを鳴らす）。
#   起点: 組織の CloudTrail（watch.tf の org）が、作業の口座の画面のバケットへの書き込みをデータイベントで取る。作業の口座からは止められない。
#     守りの口座のロググループの購読が、その記録だけを関数へ渡す。待ち時間は無く、書いて戻す手も、書いた時点で照らす。
#   正: 版の SHA-256 で GitHub の来歴を引き、Sigstore の署名と、署名した workflow（main の static-build.yml）を関数が自分で確かめる。
#     配る job の資格や部品では、static-build.yml の署名を作れない（workflow の file が違う）。
#   読む権限: 作業の口座の画面のバケットの版（edge.tf の GuardStaticWatchReads）と、配信の鍵の S3 を通す復号（kms.tf）だけ。
#   変えられる人: 関数のコードと設定、役割と方針、呼び出しの許可、出来事の宛先は、信頼の根の経路の watch-apply だけ（watchers/）。
#     守りの口座へ適用する CI は、ここにある鍵・印の表・アラーム・購読の外側だけを持ち、見張りの役割でコードを動かせない（SCP）。
#     どちらの変更も watch-change と watch-path-change が鳴らし、関数の変更は管理の口座の芯（watch-code）も 1 件ずつ鳴らす。
#   止まったら鳴る: 関数が落ちたら static-watch-errors。書き込みの数より照らした数が少なければ static-watch-missed。
#     見回りが 1 日動かなければ static-sweep-missed。

# 照らした版の印（バケット/キー#版）。消す操作はこの関数の役割に無い。
resource "aws_dynamodb_table" "static_checked" {
  name                        = "${local.name}-static-checked"
  billing_mode                = "PAY_PER_REQUEST"
  hash_key                    = "mark"
  deletion_protection_enabled = true

  attribute {
    name = "mark"
    type = "S"
  }

  server_side_encryption {
    enabled     = true
    kms_key_arn = aws_kms_key.watch.arn
  }

  point_in_time_recovery {
    enabled = true
  }
}

locals {
  # 作業の口座の画面のバケットへの書き込み（データイベント）。拒まれた試みも含む。
  static_write_pattern = "{ ($.eventSource = \"s3.amazonaws.com\") && ($.requestParameters.bucketName = \"orders-admin-*-static-*\") && ($.readOnly IS FALSE) }"
}

resource "aws_cloudwatch_log_subscription_filter" "static_watch" {
  name            = "${local.name}-static-watch"
  log_group_name  = aws_cloudwatch_log_group.org_trail.name
  filter_pattern  = local.static_write_pattern
  destination_arn = local.watch_function_arns["static-watch"]
}

resource "aws_cloudwatch_log_metric_filter" "static_writes" {
  name           = "${local.name}-static-writes"
  log_group_name = aws_cloudwatch_log_group.org_trail.name
  pattern        = local.static_write_pattern

  metric_transformation {
    name      = "static-writes"
    namespace = "${local.name}/watch"
    value     = "1"
  }
}

resource "aws_cloudwatch_log_metric_filter" "static_checks" {
  # 照らした数（static-checks）は書き込みごとの照らしだけを数える。見回りの行（event = sweep）を数えると、見回りの時刻の照らし漏れが隠れる。
  for_each       = { "static-checks" = "{ ($.kind = \"static-check\") && ($.event != \"sweep\") }", "static-watch-ng" = "{ ($.kind = \"static-check\") && ($.status = \"ng\") }" }
  name           = "${local.name}-${each.key}"
  log_group_name = aws_cloudwatch_log_group.watch_functions["static-watch"].name
  pattern        = each.value

  metric_transformation {
    name      = each.key
    namespace = "${local.name}/watch"
    value     = "1"
  }
}

# 来歴と合わない版、配る役割の外の書き込み、照らす版の無い書き込み。宛先は守りの口座の 2 つ（メールと呼び出しの窓口）。
resource "aws_cloudwatch_metric_alarm" "static_watch_ng" {
  alarm_name          = "${local.name}-static-watch-ng"
  alarm_description   = "A write to the screen bucket did not match the build provenance"
  namespace           = "${local.name}/watch"
  metric_name         = "static-watch-ng"
  statistic           = "Sum"
  period              = 60
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.watch.arn]

  depends_on = [aws_cloudwatch_log_metric_filter.static_checks]
}

# 書き込みはあったのに、照らした数が足りない（購読が外れた、関数が呼ばれない）。1 時間の数で比べる。
resource "aws_cloudwatch_metric_alarm" "static_watch_missed" {
  alarm_name          = "${local.name}-static-watch-missed"
  alarm_description   = "Writes to the screen bucket were not all checked within the hour"
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.watch.arn]

  metric_query {
    id          = "missed"
    expression  = "FILL(writes, 0) - FILL(checks, 0)"
    label       = "Writes not checked"
    return_data = true
  }

  metric_query {
    id = "writes"
    metric {
      namespace   = "${local.name}/watch"
      metric_name = "static-writes"
      period      = 3600
      stat        = "Sum"
    }
  }

  metric_query {
    id = "checks"
    metric {
      namespace   = "${local.name}/watch"
      metric_name = "static-checks"
      period      = 3600
      stat        = "Sum"
    }
  }

  depends_on = [aws_cloudwatch_log_metric_filter.static_writes, aws_cloudwatch_log_metric_filter.static_checks]
}

# 毎日の見回り。今の版の全部の file が、今の index.html と同じ作りの来歴を持つかを照らす（functions/static_watch.py の sweep）。
# 配る手順は今の作りに無い file を消すが、消し漏れと古い作りの残りは、書き込みが無くてもここで鳴る（static-watch-ng）。
resource "aws_cloudwatch_event_rule" "static_sweep" {
  name                = "${local.name}-static-sweep"
  schedule_expression = "cron(0 22 * * ? *)"
}

resource "aws_cloudwatch_log_metric_filter" "static_sweeps" {
  name           = "${local.name}-static-sweeps"
  log_group_name = aws_cloudwatch_log_group.watch_functions["static-watch"].name
  pattern        = "{ ($.kind = \"static-check\") && ($.event = \"sweep\") }"

  metric_transformation {
    name      = "static-sweeps"
    namespace = "${local.name}/watch"
    value     = "1"
  }
}

# 見回りが 1 日動かない（規則を止めた、関数が落ちた）。
resource "aws_cloudwatch_metric_alarm" "static_sweep_missed" {
  alarm_name          = "${local.name}-static-sweep-missed"
  alarm_description   = "The daily sweep of the screen bucket did not run"
  namespace           = "${local.name}/watch"
  metric_name         = "static-sweeps"
  statistic           = "Sum"
  period              = 86400
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "LessThanThreshold"
  treat_missing_data  = "breaching"
  alarm_actions       = [aws_sns_topic.watch.arn]

  depends_on = [aws_cloudwatch_log_metric_filter.static_sweeps]
}
