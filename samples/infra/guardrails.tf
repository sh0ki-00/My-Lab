# 守りが働いたか、破られかけたかを知らせる仕組み。設計書の「確かめ方」を、ここで構成コードにする。
#   1. 通知の宛先（SNS）。東京と us-east-1 に 1 つずつ。どちらも自前の鍵で暗号化し、SRE の当番のメールと、メールでない 2 本目
#      （呼び出しの仕組みの HTTPS の窓口）へ送る。メールの解除のリンクを開かれても、2 本目と守りの口座の見張り（security/）が残る。
#   2. IAM Access Analyzer（東京と us-east-1）。スナップショット・鍵・秘密・バケット・役割が外の口座へ開いたら、所見を通知する。
#   3. CloudTrail のメトリクスフィルタとアラーム。複製と共有、書き出しと方針、配信と WAF、鍵と秘密、監査の停止、人の書き込み、
#      知らない主体の書き込み、作業の起動と上書き、移行と利用者づくりの版の登録、データベースの設定、守りの仕組みの変更、
#      ログと WAF の伏せ字とリポジトリの方針の変更、記録の途絶。
#   4. WAF の量の上限に当たった数、ログの個人情報と合言葉の形の検出、イメージの新しい穴。
#   5. 通知の購読が確認済みか（計画の検査。未確認なら plan-gate が止める）。
# 口座の上限（SCP）は org/ にあり、ここの通知は「SCP で止めた操作を試みた」ことも拾う。

# ---- 1. 通知の宛先

resource "aws_sns_topic" "alerts" {
  name              = "${local.name}-guard-alerts"
  kms_master_key_id = aws_kms_key.logs.arn
}

resource "aws_sns_topic_policy" "alerts" {
  arn = aws_sns_topic.alerts.arn
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "AlarmsAndEventsInThisAccount"
      Effect    = "Allow"
      Principal = { Service = ["cloudwatch.amazonaws.com", "events.amazonaws.com"] }
      Action    = "sns:Publish"
      Resource  = aws_sns_topic.alerts.arn
      Condition = { StringEquals = { "aws:SourceAccount" = local.account_id } }
    }]
  })
}

resource "aws_sns_topic_subscription" "alerts_sre" {
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email
}

resource "aws_sns_topic_subscription" "alerts_pager" {
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "https"
  endpoint  = var.alert_pager_url
}

resource "aws_sns_topic" "alerts_use1" {
  provider          = aws.us_east_1
  name              = "${local.name}-guard-alerts"
  kms_master_key_id = aws_kms_key.logs_use1.arn
}

resource "aws_sns_topic_policy" "alerts_use1" {
  provider = aws.us_east_1
  arn      = aws_sns_topic.alerts_use1.arn
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "AlarmsAndEventsInThisAccount"
      Effect    = "Allow"
      Principal = { Service = ["cloudwatch.amazonaws.com", "events.amazonaws.com"] }
      Action    = "sns:Publish"
      Resource  = aws_sns_topic.alerts_use1.arn
      Condition = { StringEquals = { "aws:SourceAccount" = local.account_id } }
    }]
  })
}

resource "aws_sns_topic_subscription" "alerts_use1_sre" {
  provider  = aws.us_east_1
  topic_arn = aws_sns_topic.alerts_use1.arn
  protocol  = "email"
  endpoint  = var.alert_email
}

resource "aws_sns_topic_subscription" "alerts_use1_pager" {
  provider  = aws.us_east_1
  topic_arn = aws_sns_topic.alerts_use1.arn
  protocol  = "https"
  endpoint  = var.alert_pager_url
}

# 宛先が購読を確認していないと、どのアラームも誰にも届かない。計画のたびに確かめ、未確認なら plan-gate が止める。
# 計画の合間に購読を消されたか絞り込みを付けられたら、毎時の棚卸しが数と絞り込みで見つけ、守りの口座へ ok を送るのを止める（外で鳴る）。
check "alert_subscriptions_confirmed" {
  assert {
    condition     = alltrue([for s in [aws_sns_topic_subscription.alerts_sre, aws_sns_topic_subscription.alerts_pager, aws_sns_topic_subscription.alerts_use1_sre, aws_sns_topic_subscription.alerts_use1_pager] : !s.pending_confirmation])
    error_message = "守りの通知の購読が未確認。SRE の当番が確認のメールを開くまで、通知は誰にも届かない。"
  }
}

# ---- 2. 外の口座へ開いた資源の検出

resource "aws_accessanalyzer_analyzer" "account" {
  analyzer_name = "${local.name}-external-access"
  type          = "ACCOUNT"
}

resource "aws_cloudwatch_event_rule" "access_analyzer" {
  name        = "${local.name}-external-access-finding"
  description = "IAM Access Analyzer found a resource shared outside this account"
  event_pattern = jsonencode({
    source        = ["aws.access-analyzer"]
    "detail-type" = ["Access Analyzer Finding"]
    detail        = { status = ["ACTIVE"], analyzerArn = [aws_accessanalyzer_analyzer.account.arn] }
  })
}

resource "aws_cloudwatch_event_target" "access_analyzer" {
  rule = aws_cloudwatch_event_rule.access_analyzer.name
  arn  = aws_sns_topic.alerts.arn
}

# us-east-1 の鍵、WAF のロググループ、通知も調べる（Access Analyzer は地域ごとに置く）。
resource "aws_accessanalyzer_analyzer" "account_use1" {
  provider      = aws.us_east_1
  analyzer_name = "${local.name}-external-access"
  type          = "ACCOUNT"
}

resource "aws_cloudwatch_event_rule" "access_analyzer_use1" {
  provider    = aws.us_east_1
  name        = "${local.name}-external-access-finding"
  description = "IAM Access Analyzer found a resource shared outside this account (us-east-1)"
  event_pattern = jsonencode({
    source        = ["aws.access-analyzer"]
    "detail-type" = ["Access Analyzer Finding"]
    detail        = { status = ["ACTIVE"], analyzerArn = [aws_accessanalyzer_analyzer.account_use1.arn] }
  })
}

resource "aws_cloudwatch_event_target" "access_analyzer_use1" {
  provider = aws.us_east_1
  rule     = aws_cloudwatch_event_rule.access_analyzer_use1.name
  arn      = aws_sns_topic.alerts_use1.arn
}

resource "aws_cloudwatch_event_rule" "image_findings" {
  name        = "${local.name}-image-high-findings"
  description = "Amazon Inspector found a HIGH or CRITICAL vulnerability in a deployed image"
  event_pattern = jsonencode({
    source        = ["aws.inspector2"]
    "detail-type" = ["Inspector2 Finding"]
    detail        = { severity = ["HIGH", "CRITICAL"], status = ["ACTIVE"] }
  })
}

resource "aws_cloudwatch_event_target" "image_findings" {
  rule = aws_cloudwatch_event_rule.image_findings.name
  arn  = aws_sns_topic.alerts.arn
}

# ---- 3. CloudTrail の記録から拾う操作（全地域の記録が、東京のロググループに集まる）

locals {
  guard_namespace = "${local.name}/guard"
  trail_filters = {
    # 複製を作る・写す・共有する・戻す・書き出す・別の地域へ複製する。SCP で止めた試みも、記録には残るので拾える。
    "copy-share-restore" = "{ ($.eventName = \"ModifyDBSnapshotAttribute\") || ($.eventName = \"ModifyDBClusterSnapshotAttribute\") || ($.eventName = \"ModifySnapshotAttribute\") || ($.eventName = \"CopyDBSnapshot\") || ($.eventName = \"CopyDBClusterSnapshot\") || ($.eventName = \"CreateDBSnapshot\") || ($.eventName = \"Restore*\") || ($.eventName = \"StartRestoreJob\") || ($.eventName = \"StartCopyJob\") || ($.eventName = \"StartExportTask\") || ($.eventName = \"StartDBInstanceAutomatedBackupsReplication\") || ($.eventName = \"PutBackupVaultAccessPolicy\") }"
    # バケットの方針・公開のブロック・複製、ログの書き出しと転送（購読、口座単位の方針、配送）、新しい鍵、関数を呼べる相手と公開の URL、資源の共有。
    "export-and-policy" = "{ ($.eventName = \"PutBucketPolicy\") || ($.eventName = \"DeleteBucketPolicy\") || ($.eventName = \"PutBucketPublicAccessBlock\") || ($.eventName = \"DeleteBucketPublicAccessBlock\") || ($.eventName = \"PutAccountPublicAccessBlock\") || ($.eventName = \"PutBucketReplication\") || ($.eventName = \"PutBucketAcl\") || ($.eventName = \"CreateExportTask\") || ($.eventName = \"PutSubscriptionFilter\") || ($.eventName = \"PutDestination*\") || ($.eventName = \"PutAccountPolicy\") || ($.eventName = \"DeleteAccountPolicy\") || ($.eventName = \"CreateDelivery\") || ($.eventName = \"PutDelivery*\") || ($.eventName = \"CreateKey\") || ($.eventName = \"AddPermission*\") || ($.eventName = \"CreateFunctionUrlConfig*\") || ($.eventName = \"CreateResourceShare\") }"
    # 配信と WAF を作る・変える（WAF の無い 2 本目の配信、量の上限の書き換え）。
    "edge-change" = "{ ($.eventName = \"CreateDistribution*\") || ($.eventName = \"CopyDistribution\") || ($.eventName = \"UpdateDistribution\") || ($.eventName = \"CreateVpcOrigin\") || ($.eventName = \"UpdateVpcOrigin\") || ($.eventName = \"UpdateResponseHeadersPolicy\") || ($.eventName = \"UpdateWebACL\") || ($.eventName = \"DeleteWebACL\") || ($.eventName = \"UpdateIPSet\") || ($.eventName = \"AssociateWebACL\") || ($.eventName = \"DisassociateWebACL\") || ($.eventName = \"DeleteLoggingConfiguration\") }"
    # 鍵を消す・止める・方針を変える。秘密の方針を変える。
    "key-and-secret-policy" = "{ ($.eventName = \"ScheduleKeyDeletion\") || ($.eventName = \"DisableKey\") || ($.eventName = \"PutKeyPolicy\") || ($.eventName = \"PutResourcePolicy\") || ($.eventName = \"DeleteResourcePolicy\") }"
    # 管理者の合言葉を読んだ（平常は 0 回。最初の利用者づくりのときだけ 1 回）。RDS が預ける秘密の名前は rds!db- で始まるので、
    # ARN で呼んでも名前で呼んでも、訓練の写しの合言葉でも拾う。
    "db-admin-secret-read" = "{ ($.eventName = \"GetSecretValue\") && ($.requestParameters.secretId = \"*rds!db-*\") }"
    # 監査と守りを止める・消す。
    "audit-tamper" = "{ ($.eventName = \"StopLogging\") || ($.eventName = \"DeleteTrail\") || ($.eventName = \"UpdateTrail\") || ($.eventName = \"PutEventSelectors\") || ($.eventName = \"DeleteLogGroup\") || ($.eventName = \"DeleteMetricFilter\") || ($.eventName = \"DeleteAlarms\") || ($.eventName = \"DisableAlarmActions\") || ($.eventName = \"DeleteAnalyzer\") || ($.eventName = \"DisassociateFirewallRuleGroup\") || ($.eventName = \"DeleteDataProtectionPolicy\") }"
    # 人（IAM Identity Center の役割）が書き込んだ（通った物だけ）。口座の root が何かをした。拒まれた人の書き込みは障害の記録にせず、
    # 守りの口座の human-write-denied がセキュリティへ送る（当番がわざと拒まれる書き込みをして、障害の記録を作る手を外す）。
    "human-write" = "{ (($.readOnly IS FALSE) && ($.errorCode NOT EXISTS) && ($.userIdentity.sessionContext.sessionIssuer.userName = \"AWSReservedSSO_*\")) || ($.userIdentity.type = \"Root\") }"
    # 知っている役割の外の主体が書き込んだ（CI の役割を悪用して作った役割、役割を乗り継いだ書き込み、境界の中の新しい役割）。
    # 型は 1,024 字の内側に収める（メトリクスフィルタの型の上限。未確定 20）。押し込みの役割 3 つは名前の頭でまとめる。
    "unknown-writer" = "{ ($.readOnly IS FALSE) && ($.userIdentity.type = \"AssumedRole\") && ($.userIdentity.sessionContext.sessionIssuer.userName != \"${local.name}-plan\") && ($.userIdentity.sessionContext.sessionIssuer.userName != \"${local.name}-apply\") && ($.userIdentity.sessionContext.sessionIssuer.userName != \"${local.name}-apply-guarded\") && ($.userIdentity.sessionContext.sessionIssuer.userName != \"${local.name}-restore\") && ($.userIdentity.sessionContext.sessionIssuer.userName != \"${local.name}-copy-inventory\") && ($.userIdentity.sessionContext.sessionIssuer.userName != \"${local.name}-ci-*\") && ($.userIdentity.sessionContext.sessionIssuer.userName != \"${local.name}-backup\") && ($.userIdentity.sessionContext.sessionIssuer.userName != \"AWSServiceRole*\") && ($.userIdentity.sessionContext.sessionIssuer.userName != \"AWSReservedSSO_*\") }"
    # ECS の作業の起動。守りの適用の役割のほかが起動した（SCP で止めた試みも残る）か、上書き（命令・環境変数・役割・2 つ目のコンテナ）を使った。
    "task-run" = "{ (($.eventName = \"RunTask\") || ($.eventName = \"StartTask\")) && (($.userIdentity.sessionContext.sessionIssuer.userName != \"${local.name}-apply-guarded\") || ($.requestParameters.overrides.taskRoleArn = \"*\") || ($.requestParameters.overrides.executionRoleArn = \"*\") || ($.requestParameters.overrides.containerOverrides[0].command[0] = \"*\") || ($.requestParameters.overrides.containerOverrides[0].environment[0].name = \"*\") || ($.requestParameters.overrides.containerOverrides[0].environmentFiles[0].value = \"*\") || ($.requestParameters.overrides.containerOverrides[1].name = \"*\")) }"
    # 守りの適用の役割のほかが、移行と利用者づくりに届く版を登録した。API のほかの family か、どの family でも
    # 移行と利用者づくりの役割（名前に -db- を含む）を作業の役割か起動の役割に書いた版（API の family に表の持ち主の役割を付ける道）。
    "task-def-db-family" = "{ ($.eventName = \"RegisterTaskDefinition\") && ($.userIdentity.sessionContext.sessionIssuer.userName != \"${local.name}-apply-guarded\") && (($.requestParameters.family != \"${local.name}-orders-api\") || ($.requestParameters.taskRoleArn = \"*-db-*\") || ($.requestParameters.executionRoleArn = \"*-db-*\")) }"
    # 役割と方針を書き換えた。守りの適用の役割でも、土台でも鳴らす（承認の記録と突き合わせる）。unknown-writer は守りの適用を外すので、
    # 承認 2 人の経路の IAM の書き込みは、ここで拾う。
    "iam-write" = "{ ($.eventSource = \"iam.amazonaws.com\") && ($.readOnly IS FALSE) }"
    # データベースのログと合言葉と保持を変える手。パラメータグループの中身と付け替え、保持を決めた日数（var.backup_retention_days）未満に、
    # 削除の保護を外す、消す、合言葉の上書きと管理の解除、公開、網の付け替え、名前の変更（-restore- に変えて棚卸しの目を外す手）、ログの書き出しを止める。
    "db-settings-change" = "{ ($.eventName = \"ModifyDBParameterGroup\") || ($.eventName = \"DeleteDBInstance\") || ($.eventName = \"ResetDBParameterGroup\") || ((($.eventName = \"ModifyDBInstance\") || ($.eventName = \"CreateDBInstance\")) && (($.requestParameters.dBParameterGroupName = \"*\") || ($.requestParameters.backupRetentionPeriod < ${var.backup_retention_days}) || ($.requestParameters.deletionProtection IS FALSE) || ($.requestParameters.masterUserPassword = \"*\") || ($.requestParameters.manageMasterUserPassword IS FALSE) || ($.requestParameters.publiclyAccessible IS TRUE) || ($.requestParameters.vpcSecurityGroupIds[0] = \"*\") || ($.requestParameters.newDBInstanceIdentifier = \"*\") || ($.requestParameters.cloudwatchLogsExportConfiguration.disableLogTypes[0] = \"*\"))) }"
    # 入口を開けた。受ける通信の規則、窓口とその方針、ロードバランサーの受け口、API Gateway の VPC リンク、経路、
    # ネットワークのインターフェース（サービスにリンクされた役割が作る物は外す）、Verified Access の端点。
    "network-entrance" = "{ ($.eventName = \"AuthorizeSecurityGroup*\") || ($.eventName = \"ModifySecurityGroupRules\") || ($.eventName = \"CreateVpcEndpoint*\") || ($.eventName = \"ModifyVpcEndpoint*\") || ($.eventName = \"CreateVpcLink\") || ($.eventName = \"CreateLoadBalancer\") || ($.eventName = \"CreateListener\") || ($.eventName = \"ModifyListener\") || ($.eventName = \"CreateRoute\") || ($.eventName = \"ReplaceRoute\") || ($.eventName = \"CreateTransitGatewayVpcAttachment\") || ((($.eventName = \"CreateNetworkInterface*\") || ($.eventName = \"AttachNetworkInterface\")) && ($.userIdentity.sessionContext.sessionIssuer.userName != \"AWSServiceRole*\")) || ($.eventName = \"CreateVerifiedAccess*\") || ($.eventName = \"ModifyVerifiedAccess*\") }"
    # データの中身を読む操作を、当番のほかが試みた（SCP で拒まれた試みも残る）。ログの中身と問い合わせの結果、異常の検知、性能の記録、DB のログのファイル、WAF の見本、
    # 管理の記録の履歴（LookupEvents）。
    "data-read-outside-oncall" = "{ (($.eventName = \"GetQueryResults\") || ($.eventName = \"StartQuery\") || ($.eventName = \"DescribeQueries\") || ($.eventName = \"FilterLogEvents\") || ($.eventName = \"GetLogEvents\") || ($.eventName = \"Unmask\") || ($.eventName = \"ListAnomalies\") || ($.eventName = \"CreateLogAnomalyDetector\") || ($.eventName = \"DescribeDimensionKeys\") || ($.eventName = \"GetDimensionKeyDetails\") || ($.eventName = \"GetResourceMetrics\") || ($.eventName = \"Download*LogFile*\") || ($.eventName = \"GetSampledRequests\") || ($.eventName = \"LookupEvents\")) && ($.userIdentity.sessionContext.sessionIssuer.userName != \"AWSReservedSSO_orders-oncall-*\") }"
    # サービスに API の family の外の版を付けた（移行や利用者づくりの版を、サービスとして動かす道）。
    "service-family" = "{ (($.eventName = \"UpdateService\") || ($.eventName = \"CreateService\") || ($.eventName = \"CreateTaskSet\")) && ($.requestParameters.taskDefinition = \"*\") && ($.requestParameters.taskDefinition != \"*${local.name}-orders-api:*\") }"
    # 守りの仕組みを変えた。棚卸しの関数、起動の規則、アラームとメトリクスフィルタ、通知の宛先と購読の絞り込み、ロググループの変換。
    # 守りの適用の役割でも鳴らす（承認との突き合わせ）。同じ型の変更は、守りの口座の notify-path-change と log-path-change も外で拾う。
    "guard-change" = "{ ($.eventName = \"UpdateFunction*\") || ($.eventName = \"CreateFunction*\") || ($.eventName = \"DeleteFunction*\") || ($.eventName = \"PutFunctionConcurrency*\") || ($.eventName = \"PutRule\") || ($.eventName = \"PutTargets\") || ($.eventName = \"RemoveTargets\") || ($.eventName = \"DisableRule\") || ($.eventName = \"PutMetricAlarm\") || ($.eventName = \"PutMetricFilter\") || ($.eventName = \"Subscribe\") || ($.eventName = \"Unsubscribe\") || ($.eventName = \"SetTopicAttributes\") || ($.eventName = \"SetSubscriptionAttributes\") || ($.eventName = \"DeleteTopic\") || ($.eventName = \"PutTransformer\") || ($.eventName = \"DeleteTransformer\") || ($.eventName = \"SetAlarmState\") || ($.eventName = \"PutCompositeAlarm\") }"
    # ログと WAF の伏せ字の規則、イメージのリポジトリの方針・複製・寿命を変えた。
    "log-and-image-policy" = "{ ($.eventName = \"PutDataProtectionPolicy\") || ($.eventName = \"PutLoggingConfiguration\") || ($.eventName = \"SetRepositoryPolicy\") || ($.eventName = \"PutRegistryPolicy\") || ($.eventName = \"PutReplicationConfiguration\") || ($.eventName = \"CreatePullThroughCacheRule\") || ($.eventName = \"PutLifecyclePolicy\") || ($.eventName = \"DeleteLifecyclePolicy\") || ($.eventName = \"PutImageTagMutability\") }"
  }
}

resource "aws_cloudwatch_log_metric_filter" "trail" {
  for_each       = local.trail_filters
  name           = "${local.name}-${each.key}"
  log_group_name = aws_cloudwatch_log_group.trail.name
  pattern        = each.value

  metric_transformation {
    name      = each.key
    namespace = local.guard_namespace
    value     = "1"
  }
}

resource "aws_cloudwatch_metric_alarm" "trail" {
  for_each            = local.trail_filters
  alarm_name          = "${local.name}-${each.key}"
  alarm_description   = "CloudTrail recorded ${each.key} in ${local.name}"
  namespace           = local.guard_namespace
  metric_name         = each.key
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]

  depends_on = [aws_cloudwatch_log_metric_filter.trail]
}

# 記録の途絶。CloudTrail が 15 分 1 件も届かなければ、止められたか壊れたとみなして知らせる。
resource "aws_cloudwatch_log_metric_filter" "trail_heartbeat" {
  name           = "${local.name}-trail-heartbeat"
  log_group_name = aws_cloudwatch_log_group.trail.name
  pattern        = ""

  metric_transformation {
    name      = "trail-events"
    namespace = local.guard_namespace
    value     = "1"
  }
}

resource "aws_cloudwatch_metric_alarm" "trail_silent" {
  alarm_name          = "${local.name}-trail-silent"
  alarm_description   = "No CloudTrail events for 15 minutes"
  namespace           = local.guard_namespace
  metric_name         = "trail-events"
  statistic           = "Sum"
  period              = 900
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "LessThanThreshold"
  treat_missing_data  = "breaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]

  depends_on = [aws_cloudwatch_log_metric_filter.trail_heartbeat]
}

# ---- 4. WAF の量の上限、ログの個人情報、イメージの穴

# WAF が止めた数。形の悪い要求と、鍵ごとの量の 3 段（API 全体、詳細、一覧）のどれかに当たったら知らせる。
resource "aws_cloudwatch_metric_alarm" "waf_rate" {
  for_each = {
    "rate-per-ip"         = "BlockedRequests"
    "api-request-shape"   = "BlockedRequests"
    "rate-per-key"        = "BlockedRequests"
    "rate-per-key-detail" = "BlockedRequests"
    "rate-per-key-list"   = "BlockedRequests"
  }
  provider            = aws.us_east_1
  alarm_name          = "${local.name}-waf-${each.key}"
  alarm_description   = "WAF ${each.value} by ${each.key}"
  namespace           = "AWS/WAFV2"
  metric_name         = each.value
  dimensions          = { WebACL = aws_wafv2_web_acl.admin.name, Rule = each.key }
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts_use1.arn]
}

# 一覧と詳細の 1 日の総量。5 分の窓の上限より少しずつ抜く手（一覧を 5 分 39 回、詳細を 5 分 99 回で、1 日続けるなど）は、窓の上限では止まらない。
# 全部の鍵の 1 日の回数をパスごとに数え、目安（var.api_list_daily_total と var.api_detail_daily_total）を超えたら知らせる。
# 鍵ごと・利用者ごとの束ねはバックエンド（未確定 16）。目安と平常の差（一覧は約 1,200 回、詳細は約 1,000 回。どちらも架空の幅から）は残る。
resource "aws_cloudwatch_metric_alarm" "waf_path_daily" {
  for_each            = { list = var.api_list_daily_total, detail = var.api_detail_daily_total }
  provider            = aws.us_east_1
  alarm_name          = "${local.name}-waf-${each.key}-daily-total"
  alarm_description   = "Order ${each.key} calls in one day exceeded the expected total"
  namespace           = "AWS/WAFV2"
  metric_name         = "CountedRequests"
  dimensions          = { WebACL = aws_wafv2_web_acl.admin.name, Rule = "${each.key}-volume" }
  statistic           = "Sum"
  period              = 86400
  evaluation_periods  = 1
  threshold           = each.value
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts_use1.arn]
}

moved {
  from = aws_cloudwatch_metric_alarm.waf_list_daily
  to   = aws_cloudwatch_metric_alarm.waf_path_daily["list"]
}

# 出口の総量。乗っ取った API が、届いた鍵で読んだ他の店の行を、自分の鍵の応答にまとめて返す道は、WAF の鍵ごとの回数では数えられない。
# 外へ出る道は配信の応答だけなので、配信が送った 1 時間のバイト数を API の外で数え、目安（var.edge_bytes_hourly_max）を超えたら知らせる。
# 数えるのは CloudFront で、API のコードからは変えられない。鍵ごとの量と、1 つのタスクが読んだ行の数は、横断事項と未確定 27。
resource "aws_cloudwatch_metric_alarm" "edge_bytes_out" {
  provider            = aws.us_east_1
  alarm_name          = "${local.name}-edge-bytes-out-hourly"
  alarm_description   = "Bytes sent by the distribution in one hour exceeded the expected maximum"
  namespace           = "AWS/CloudFront"
  metric_name         = "BytesDownloaded"
  dimensions          = { DistributionId = aws_cloudfront_distribution.admin.id, Region = "Global" }
  statistic           = "Sum"
  period              = 3600
  evaluation_periods  = 1
  threshold           = var.edge_bytes_hourly_max
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts_use1.arn]
}

# ログの個人情報と合言葉の検出と伏せ字（CloudWatch Logs のデータ保護）。電話番号・郵便番号・メールの形、
# 接続文字列と password= の形、秘密鍵と AWS の鍵の形が書かれたら、読む人には伏せ字で見せ、検出の数を指標に出す。
# 氏名と住所は形で拾えないので、出どころで止める（WAF の伏せ、SQL の本文と誤りの本文を出さない、API はログの項目を一覧で決める）。
# 混ざったときの害は、読める人で絞る。ログの中身を読めるのは当番だけ（org/scp.tf の LogReadsOnlyForOncall）。伏せ字を外す操作は誰にも許さない（NoUnmask）。
# 当番が入ったことは、守りの口座の oncall-used が毎回鳴らす（security/watch.tf）。
# 伏せる規則を変えられるのは守りの適用だけで、変えたら log-and-image-policy が、外したら audit-tamper が鳴る。
# VPC のフローログは通信の頭（アドレスと口の番号）だけで中身を持たないので、検出は掛けない。
# 漏れの道は見張りの値で確かめる。検証環境の合成のデータは氏名と住所に ZZCANARY-<6 桁> を入れ、どのログに現れても知らせる。
locals {
  log_identifiers = concat(
    [for d in ["EmailAddress", "AwsSecretKey", "OpenSshPrivateKey", "PgpPrivateKey", "PkcsPrivateKey", "PuttyPrivateKey"] : "arn:${local.partition}:dataprotection::aws:data-identifier/${d}"],
    ["JpPhoneNumber", "JpPostalCode", "PgConnectionString", "PasswordAssignment", "CanaryValue"],
  )
  log_data_protection = jsonencode({
    Name    = "${local.name}-personal-data"
    Version = "2021-06-01"
    Configuration = {
      CustomDataIdentifier = [
        { Name = "JpPhoneNumber", Regex = "0\\d{1,4}-\\d{1,4}-\\d{4}" },
        { Name = "JpPostalCode", Regex = "\\d{3}-\\d{4}" },
        { Name = "PgConnectionString", Regex = "postgres(ql)?://[^\\s:/]+:[^\\s@]+@" },
        { Name = "PasswordAssignment", Regex = "(?i)(password|passwd|pgpassword)\\s*[=:]\\s*[^\\s,;]+" },
        { Name = "CanaryValue", Regex = "ZZCANARY-\\d{6}" },
      ]
    }
    Statement = [
      {
        Sid            = "audit"
        DataIdentifier = local.log_identifiers
        Operation      = { Audit = { FindingsDestination = {} } }
      },
      {
        Sid            = "mask"
        DataIdentifier = local.log_identifiers
        Operation      = { Deidentify = { MaskConfig = {} } }
      },
    ]
  })
  protected_log_groups = {
    api            = aws_cloudwatch_log_group.api.name
    rds            = aws_cloudwatch_log_group.rds.name
    db_bootstrap   = aws_cloudwatch_log_group.db_bootstrap.name
    db_migrate     = aws_cloudwatch_log_group.db_migrate.name
    dns            = aws_cloudwatch_log_group.dns.name
    cloudtrail     = aws_cloudwatch_log_group.trail.name
    copy_inventory = aws_cloudwatch_log_group.copy_ledger.name
  }
}

resource "aws_cloudwatch_log_data_protection_policy" "main" {
  for_each        = local.protected_log_groups
  log_group_name  = each.value
  policy_document = local.log_data_protection
}

resource "aws_cloudwatch_metric_alarm" "log_personal_data" {
  for_each            = local.protected_log_groups
  alarm_name          = "${local.name}-personal-data-in-${each.key}-logs"
  alarm_description   = "Personal data pattern found in ${each.value}"
  namespace           = "AWS/Logs"
  metric_name         = "LogEventsWithFindings"
  dimensions          = { LogGroupName = each.value }
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
}

resource "aws_cloudwatch_log_data_protection_policy" "waf" {
  provider        = aws.us_east_1
  log_group_name  = aws_cloudwatch_log_group.waf.name
  policy_document = local.log_data_protection
}

resource "aws_cloudwatch_metric_alarm" "waf_log_personal_data" {
  provider            = aws.us_east_1
  alarm_name          = "${local.name}-personal-data-in-waf-logs"
  alarm_description   = "Personal data pattern found in ${aws_cloudwatch_log_group.waf.name}"
  namespace           = "AWS/Logs"
  metric_name         = "LogEventsWithFindings"
  dimensions          = { LogGroupName = aws_cloudwatch_log_group.waf.name }
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts_use1.arn]
}

# ---- 障害の記録を守りの口座へ送る（当番の入りの突き合わせ。security/event-watch.tf）
# 障害の記録にするアラーム（local.incident_alarms）が ALARM になった出来事を、守りの口座の便りのバスへ送る。許す物の一覧で書く。
# 人が自分で起こせる型（human-write、data-read-outside-oncall など守りの型）は入れない。守りの口座の event-watch は、当番の入りの前後 2 時間に
# この記録が無ければセキュリティへ鳴らし、ok の便りにも照らした記録の名を載せる。当番はアラームの状態を変えられない（SetAlarmState は守りの適用だけ）。
# us-east-1 のアラーム（WAF と配信の量）はこの規則に入らないので、その障害のときの当番の入りは ng で鳴る（誤って鳴る側。未確定 28）。
# 規則と役割を変えられるのは守りの適用だけで、変えたら guard-change が鳴る。止めた場合は、当番の入りが全部 ng になる（閉じる側）。
locals {
  # 当番を呼ぶ障害のアラーム。サービスの故障と、守りの仕組みの止まりだけ。
  incident_alarms = ["api-5xx", "trail-silent", "copy-inventory-not-run", "copy-inventory-errors", "copy-inventory-incomplete"]
}

resource "aws_iam_role" "alarm_forward" {
  name                 = "${local.name}-alarm-forward"
  permissions_boundary = local.boundary_arn
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "events.amazonaws.com" }
      Action    = "sts:AssumeRole"
      Condition = { StringEquals = { "aws:SourceAccount" = local.account_id } }
    }]
  })
}

resource "aws_iam_role_policy" "alarm_forward" {
  name = "forward-to-guard-bus"
  role = aws_iam_role.alarm_forward.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = "events:PutEvents"
      Resource = var.guard_heartbeat_bus_arn
    }]
  })
}

resource "aws_cloudwatch_event_rule" "alarm_forward" {
  name = "${local.name}-alarm-forward"
  event_pattern = jsonencode({
    source        = ["aws.cloudwatch"]
    "detail-type" = ["CloudWatch Alarm State Change"]
    detail = {
      alarmName = concat([for a in local.incident_alarms : "${local.name}-${a}"], [{ prefix = "${local.name}-personal-data-in-" }])
      state     = { value = ["ALARM"] }
    }
  })
}

resource "aws_cloudwatch_event_target" "alarm_forward" {
  rule     = aws_cloudwatch_event_rule.alarm_forward.name
  arn      = var.guard_heartbeat_bus_arn
  role_arn = aws_iam_role.alarm_forward.arn
}

# ---- データベースの作業が落ちた（移行の後の突き合わせの不一致を含む。db/migrate-run.sh が誤りで終わる）
resource "aws_cloudwatch_event_rule" "db_job_failed" {
  name = "${local.name}-db-job-failed"
  event_pattern = jsonencode({
    source        = ["aws.ecs"]
    "detail-type" = ["ECS Task State Change"]
    detail = {
      lastStatus        = ["STOPPED"]
      taskDefinitionArn = [{ prefix = "arn:${local.partition}:ecs:${var.region}:${local.account_id}:task-definition/${local.name}-db-" }]
      containers        = { exitCode = [{ "anything-but" = 0 }] }
    }
  })
}

resource "aws_cloudwatch_event_target" "db_job_failed" {
  rule = aws_cloudwatch_event_rule.db_job_failed.name
  arn  = aws_sns_topic.alerts.arn
}

# ---- 毎時の DB の突き合わせ（db/roles.sql の guard.check_all を pg_cron が回す）が違いを見つけると、API の利用者の入りを閉じる。
# API が DB へ入れなくなると、ロードバランサーの 5xx が増えるので、ここで鳴らす（閉じる側に倒れる）。
resource "aws_cloudwatch_metric_alarm" "api_5xx" {
  alarm_name          = "${local.name}-api-5xx"
  alarm_description   = "The API returned 5xx; the hourly database guard check may have closed the API login"
  namespace           = "AWS/ApplicationELB"
  metric_name         = "HTTPCode_Target_5XX_Count"
  dimensions          = { LoadBalancer = aws_lb.api.arn_suffix }
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 10
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
}

# ---- 出口の 1 日の総量。1 時間の目安の下で、時間を分けて少しずつ運ぶ道を、1 日の和で数える。
resource "aws_cloudwatch_metric_alarm" "edge_bytes_out_daily" {
  provider            = aws.us_east_1
  alarm_name          = "${local.name}-edge-bytes-out-daily"
  alarm_description   = "Bytes sent by the distribution in one day exceeded the expected maximum"
  namespace           = "AWS/CloudFront"
  metric_name         = "BytesDownloaded"
  dimensions          = { DistributionId = aws_cloudfront_distribution.admin.id, Region = "Global" }
  statistic           = "Sum"
  period              = 86400
  evaluation_periods  = 1
  threshold           = var.edge_bytes_daily_max
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts_use1.arn]
}
