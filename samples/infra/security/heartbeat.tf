# 守りの口座の見張りの正本（functions/guard-expected.json）と、この構成コードの資源の名を、計画のたびに突き合わせる（第 16 回）。
#   event-watch の関数は 15 分ごとに、正本と今のアラーム・メトリクスフィルタ・記録の購読・話題を数え、欠けが 0 のときだけ
#   AWS の外の受け手（heartbeat-receiver.json）へ便りを送る。正本と資源がずれると、足したアラームが数えられないか、消したアラームで
#   便りが止まり続ける。ずれは計画の段で落とす（check）。
#   変えられる人: この file と正本は持ち主の欄（/infra/）の内側で、セキュリティの承認が要る。関数のコードは watch-apply だけが置く。
#   止まったら鳴る: 便りが止まれば受け手が 20 分で鳴る（AWS の外）。

locals {
  guard_expected = jsondecode(file("${path.module}/functions/guard-expected.json"))
  guard_alarm_names = toset(concat(
    [for a in aws_cloudwatch_metric_alarm.watch : a.alarm_name],
    [for a in aws_cloudwatch_metric_alarm.event_watch_ng : a.alarm_name],
    [for a in aws_cloudwatch_metric_alarm.watch_function_errors : a.alarm_name],
    [for a in aws_cloudwatch_metric_alarm.account_silent : a.alarm_name],
    [for a in aws_cloudwatch_metric_alarm.heartbeat : a.alarm_name],
    [
      aws_cloudwatch_metric_alarm.github_audit_silent.alarm_name,
      aws_cloudwatch_metric_alarm.github_watch_not_ok.alarm_name,
      aws_cloudwatch_metric_alarm.github_watch_ng.alarm_name,
      aws_cloudwatch_metric_alarm.static_watch_ng.alarm_name,
      aws_cloudwatch_metric_alarm.static_watch_missed.alarm_name,
      aws_cloudwatch_metric_alarm.static_sweep_missed.alarm_name,
      aws_cloudwatch_metric_alarm.oncall_queries.alarm_name,
      aws_cloudwatch_metric_alarm.oncall_query_results.alarm_name,
    ],
  ))
  guard_filter_names = toset(concat(
    [for f in aws_cloudwatch_log_metric_filter.watch : f.name],
    [for f in aws_cloudwatch_log_metric_filter.event_watch : f.name],
  ))
}

check "guard_expected_matches_resources" {
  assert {
    condition     = toset(local.guard_expected.alarms) == local.guard_alarm_names
    error_message = "functions/guard-expected.json の alarms が、security/ のアラームの名と食い違う。便りの数え方を直してから適用する。"
  }
  assert {
    condition     = alltrue([for f in local.guard_expected.metric_filters : contains(local.guard_filter_names, f)])
    error_message = "functions/guard-expected.json の metric_filters に、security/ に無い名がある。"
  }
}
