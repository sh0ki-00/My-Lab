# 作業の口座の外から鳴らす見張り。宛先・記録・判定の全部が守りの口座にあり、作業の口座の管理者は止めも変えもできない。

# ---- 鍵（記録、ロググループ、通知）

# 鍵の方針の Resource "*" は「この鍵そのもの」を指す（鍵の方針の決まり）。消す予約と無効化は誰にも許さない。
resource "aws_kms_key" "watch" {
  description             = "Organization trail, watch log groups and the watch topic"
  enable_key_rotation     = true
  deletion_window_in_days = 30
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "AccountAdmin"
        Effect    = "Allow"
        Principal = { AWS = "arn:${local.partition}:iam::${var.security_account_id}:root" }
        Action    = "kms:*"
        Resource  = "*"
      },
      {
        Sid       = "DenyKeyDestruction"
        Effect    = "Deny"
        Principal = { AWS = "*" }
        Action    = ["kms:ScheduleKeyDeletion", "kms:DisableKey", "kms:DeleteImportedKeyMaterial"]
        Resource  = "*"
      },
      {
        Sid       = "TrailEncrypt"
        Effect    = "Allow"
        Principal = { Service = "cloudtrail.amazonaws.com" }
        Action    = ["kms:GenerateDataKey*", "kms:DescribeKey"]
        Resource  = "*"
        Condition = { StringLike = { "kms:EncryptionContext:aws:cloudtrail:arn" = "arn:${local.partition}:cloudtrail:*:${var.security_account_id}:trail/*" } }
      },
      {
        Sid       = "LogsAlarmsEvents"
        Effect    = "Allow"
        Principal = { Service = ["logs.${var.region}.amazonaws.com", "cloudwatch.amazonaws.com", "events.amazonaws.com"] }
        Action    = ["kms:Encrypt", "kms:Decrypt", "kms:ReEncrypt*", "kms:GenerateDataKey*", "kms:DescribeKey"]
        Resource  = "*"
      },
    ]
  })
}

# 見張りの構成（watchers/）が名前で引くための別名。
resource "aws_kms_alias" "watch" {
  name          = "alias/${local.name}-watch"
  target_key_id = aws_kms_key.watch.key_id
}

# ---- 組織の記録（消せない置き場と、判定のためのロググループ）

resource "aws_s3_bucket" "org_trail" {
  bucket              = "${local.name}-org-trail-${var.security_account_id}"
  object_lock_enabled = true
}

resource "aws_s3_bucket_public_access_block" "org_trail" {
  bucket                  = aws_s3_bucket.org_trail.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "org_trail" {
  bucket = aws_s3_bucket.org_trail.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "org_trail" {
  bucket = aws_s3_bucket.org_trail.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.watch.arn
    }
  }
}

resource "aws_s3_bucket_object_lock_configuration" "org_trail" {
  bucket = aws_s3_bucket.org_trail.id
  rule {
    default_retention {
      mode = "COMPLIANCE"
      days = var.trail_retention_days
    }
  }
}

resource "aws_s3_bucket_policy" "org_trail" {
  bucket = aws_s3_bucket.org_trail.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "TrailAcl"
        Effect    = "Allow"
        Principal = { Service = "cloudtrail.amazonaws.com" }
        Action    = "s3:GetBucketAcl"
        Resource  = aws_s3_bucket.org_trail.arn
        Condition = { StringEquals = { "aws:SourceArn" = "arn:${local.partition}:cloudtrail:${var.region}:${var.security_account_id}:trail/${local.name}-org" } }
      },
      {
        Sid       = "TrailWrite"
        Effect    = "Allow"
        Principal = { Service = "cloudtrail.amazonaws.com" }
        Action    = "s3:PutObject"
        Resource  = "${aws_s3_bucket.org_trail.arn}/AWSLogs/*"
        Condition = { StringEquals = { "aws:SourceArn" = "arn:${local.partition}:cloudtrail:${var.region}:${var.security_account_id}:trail/${local.name}-org" } }
      },
    ]
  })
}

resource "aws_cloudwatch_log_group" "org_trail" {
  name              = "/${local.name}/org-trail"
  retention_in_days = var.trail_retention_days
  kms_key_id        = aws_kms_key.watch.arn
}

# 記録のロググループの伏せ字（データ保護の方針）は security/watchers/trail-masking.tf へ移した（第 13 回）。
# 方針の監査の所見には送り先（バケット、Firehose、ロググループ）を書ける。この適用の 1 回で外の口座の送り先を付けられないよう、
# 置けるのは watch-apply（信頼の根の経路）だけにした（org/guard-core.tf の MaskingOnlyByWatchApply）。ここでは消さずに状態から外す。
removed {
  from = aws_cloudwatch_log_data_protection_policy.org_trail
  lifecycle {
    destroy = false
  }
}

resource "aws_iam_role" "org_trail_logs" {
  name                 = "${local.name}-org-trail-logs"
  permissions_boundary = local.guard_boundary_arn
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "cloudtrail.amazonaws.com" }
      Action    = "sts:AssumeRole"
      Condition = { StringEquals = { "aws:SourceAccount" = var.security_account_id } }
    }]
  })
}

resource "aws_iam_role_policy" "org_trail_logs" {
  name = "write-org-trail-log-group"
  role = aws_iam_role.org_trail_logs.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["logs:CreateLogStream", "logs:PutLogEvents"]
      Resource = "${aws_cloudwatch_log_group.org_trail.arn}:*"
    }]
  })
}

# 組織の全口座・全地域の管理の操作（読むだけの操作を含む）と、画面のバケットへの書き込み。作業の口座からは止められない（組織の記録は持ち主の口座だけが変える）。
# 記録の置き場・選び方と、記録のロググループの購読（event_watch と static_watch の 2 本）は、守りの口座の誰も変えられない
# （org/guard-core.tf の GuardFeedFixed）。変えるときは信頼の根の経路で、管理の口座の土台の CI がその SCP を一時に外して適用する。
resource "aws_cloudtrail" "org" {
  name                          = "${local.name}-org"
  s3_bucket_name                = aws_s3_bucket.org_trail.id
  kms_key_id                    = aws_kms_key.watch.arn
  is_organization_trail         = true
  is_multi_region_trail         = true
  include_global_service_events = true
  enable_log_file_validation    = true
  enable_logging                = true
  cloud_watch_logs_group_arn    = "${aws_cloudwatch_log_group.org_trail.arn}:*"
  cloud_watch_logs_role_arn     = aws_iam_role.org_trail_logs.arn

  # 管理の操作は全部。データの操作は、作業の口座の画面のバケットへの書き込みだけ（画面の照らしの起点。static-watch.tf）。
  advanced_event_selector {
    name = "management"
    field_selector {
      field  = "eventCategory"
      equals = ["Management"]
    }
  }

  advanced_event_selector {
    name = "static-writes"
    field_selector {
      field  = "eventCategory"
      equals = ["Data"]
    }
    field_selector {
      field  = "resources.type"
      equals = ["AWS::S3::Object"]
    }
    field_selector {
      field  = "readOnly"
      equals = ["false"]
    }
    field_selector {
      field       = "resources.ARN"
      starts_with = [for e, a in var.workload_accounts : "arn:${local.partition}:s3:::orders-admin-${e}-static-${a}/"]
    }
  }

  # 作業の口座の窓口（VPC エンドポイント）の方針で拒まれた要求。乗っ取った部品が、許した窓口の名前で自分の口座の資源を名指しし、
  # 拒否の記録に行を載せる試みを、こちらで出来事として拾う（network-endpoint-denied）。対象は、作業の口座に置いた窓口のうち
  # aws-facts の 39 で対象と確かめたサービスだけ（S3 と Secrets Manager）。KMS の窓口は置いていない（network.tf）。
  # CloudWatch Logs は対象の外なので書かない（書いても鳴らない）。ECR は対象かを確かめていないので書かない（未確定 20）。
  # 拒まれた要求が相手の口座に残るかも未確定 20。S3 の拒否は相手にも残らない（aws-facts の 38）。
  advanced_event_selector {
    name = "vpce-denied"
    field_selector {
      field  = "eventCategory"
      equals = ["NetworkActivity"]
    }
    field_selector {
      field  = "eventSource"
      equals = ["s3.amazonaws.com", "secretsmanager.amazonaws.com"]
    }
    field_selector {
      field  = "errorCode"
      equals = ["VpceAccessDenied"]
    }
  }

  depends_on = [aws_s3_bucket_policy.org_trail]
}

# ---- 宛先（メールと、メールでない 2 本目）

resource "aws_sns_topic" "watch" {
  name              = "${local.name}-watch"
  kms_master_key_id = aws_kms_key.watch.arn
}

resource "aws_sns_topic_policy" "watch" {
  for_each = { watch = aws_sns_topic.watch.arn, security = aws_sns_topic.security.arn }
  arn      = each.value
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "AlarmsAndScheduleInThisAccount"
      Effect    = "Allow"
      Principal = { Service = ["cloudwatch.amazonaws.com", "events.amazonaws.com"] }
      Action    = "sns:Publish"
      Resource  = each.value
      Condition = { StringEquals = { "aws:SourceAccount" = var.security_account_id } }
    }]
  })
}

# セキュリティの宛先。当番（SRE）の外に置く。当番の利用と信頼の根の入りは、見張られる本人の宛先だけには送らない。
resource "aws_sns_topic" "security" {
  name              = "${local.name}-security"
  kms_master_key_id = aws_kms_key.watch.arn
}

resource "aws_sns_topic_subscription" "security" {
  for_each  = { email = var.security_email, pager = var.security_pager_url }
  topic_arn = aws_sns_topic.security.arn
  protocol  = each.key == "email" ? "email" : "https"
  endpoint  = each.value
}

check "security_subscriptions_confirmed" {
  assert {
    condition     = alltrue([for s in aws_sns_topic_subscription.security : !s.pending_confirmation])
    error_message = "セキュリティの宛先の購読が未確認。確認するまで、当番の入りの通知は当番の外に届かない。"
  }
}

moved {
  from = aws_sns_topic_policy.watch
  to   = aws_sns_topic_policy.watch["watch"]
}

# 宛先と見張りが生きているかは、AWS の外で見る（便りの途絶。第 16 回）。15 分ごとに event-watch の関数が、見張りの正本
# （functions/guard-expected.json）と今のアラーム・メトリクスフィルタ・記録の購読・話題を数え、欠けが 0 のときだけ 2 つの話題へ便りを出す。
# 受け手（AWS の外。heartbeat-receiver.json）は 20 分届かなければ鳴らす。話題やアラームを消す、宛先を空にする、購読を外す、のどれでも
# 便りが止まる。管理の口座（信頼の根）が守りの口座の SCP を外して見張りを消す手も、ここで鳴る（信頼の根の答えの本体）。
resource "aws_cloudwatch_event_rule" "notify_heartbeat" {
  name                = "${local.name}-notify-heartbeat"
  schedule_expression = "rate(15 minutes)"
}

resource "aws_sns_topic_subscription" "watch" {
  for_each  = { email = var.alert_email, pager = var.pager_url }
  topic_arn = aws_sns_topic.watch.arn
  protocol  = each.key == "email" ? "email" : "https"
  endpoint  = each.value
}

check "watch_subscriptions_confirmed" {
  assert {
    condition     = alltrue([for s in aws_sns_topic_subscription.watch : !s.pending_confirmation])
    error_message = "守りの口座の通知の購読（メールか呼び出しの窓口）が未確認。確認するまで、外からの見張りは誰にも届かない。"
  }
}

# ---- 判定（組織の記録から拾う操作）

locals {
  # 作業の口座の記録だけを見る条件。
  in_workload = join(" || ", [for a in values(var.workload_accounts) : "($.recipientAccountId = \"${a}\")"])
  # どの判定も 1 本 1,024 字の内側に収まるよう、型ごとに分ける。
  watch_filters = {
    # 緊急の管理を借りた、または借りた資格で何かをした。作業の口座の root を使った。どの道を選んでも、使った時点で鳴る。
    "breakglass-used" = "{ ($.userIdentity.sessionContext.sessionIssuer.userName = \"AWSReservedSSO_orders-breakglass-*\") || (($.eventName = \"AssumeRoleWithSAML\") && ($.requestParameters.roleArn = \"*AWSReservedSSO_orders-breakglass-*\")) || ((${local.in_workload}) && ($.userIdentity.type = \"Root\")) }"
    # 通知の経路を変えた（購読と絞り込み、話題、アラームと規則）。作業の口座の SNS を通らずに知らせる。
    "notify-path-change" = "{ (${local.in_workload}) && (($.eventName = \"Unsubscribe\") || ($.eventName = \"SetSubscriptionAttributes\") || ($.eventName = \"Subscribe\") || ($.eventName = \"DeleteTopic\") || ($.eventName = \"SetTopicAttributes\") || ($.eventName = \"PutDataProtectionPolicy\") || ($.eventName = \"DeleteAlarms\") || ($.eventName = \"DisableAlarmActions\") || ($.eventName = \"SetAlarmState\") || ($.eventName = \"PutMetricAlarm\") || ($.eventName = \"DisableRule\") || ($.eventName = \"DeleteRule\") || ($.eventName = \"RemoveTargets\")) }"
    # ログの経路を変えた（変換、口座単位の方針、配送、購読、メトリクスフィルタ、記録）。棚卸しの関数を変えた。
    "log-path-change" = "{ (${local.in_workload}) && (($.eventName = \"PutTransformer\") || ($.eventName = \"DeleteTransformer\") || ($.eventName = \"PutAccountPolicy\") || ($.eventName = \"DeleteAccountPolicy\") || ($.eventName = \"CreateDelivery\") || ($.eventName = \"PutDelivery*\") || ($.eventName = \"PutSubscriptionFilter\") || ($.eventName = \"PutMetricFilter\") || ($.eventName = \"DeleteMetricFilter\") || ($.eventName = \"StopLogging\") || ($.eventName = \"PutEventSelectors\") || ($.eventName = \"UpdateFunction*\") || ($.eventName = \"DeleteFunction*\")) }"
    # 名指しの主体の一覧の外の役割を借りた（管理の口座から借りる OrganizationAccountAccessRole など）。SCP はその役割に何もさせないが、
    # 借りた事実そのものを鳴らす。root の利用は breakglass-used が鳴らす。
    "outside-principal" = "{ (${local.in_workload}) && ($.eventSource = \"sts.amazonaws.com\") && ($.eventName = \"AssumeRole*\") && ($.requestParameters.roleArn != \"*:role/orders-admin-*\") && ($.requestParameters.roleArn != \"*/AWSReservedSSO_orders-*\") && ($.requestParameters.roleArn != \"*:role/aws-service-role/*\") && ($.requestParameters.roleArn != \"*:role/platform-foundation\") }"
    # 守りの適用と土台の役割を借りた。どの使い方でも、その場で鳴らす。-guarded の承認者はセキュリティだけなので、
    # セキュリティは自分の承認と突き合わせる。GitHub の側で承認者や main の保護を外されても、AWS の側のこの見張りは外れない。
    "guarded-apply-used" = "{ (${local.in_workload}) && ($.eventName = \"AssumeRole*\") && (($.requestParameters.roleArn = \"*-apply-guarded\") || ($.requestParameters.roleArn = \"*:role/platform-foundation\")) }"
    # 信頼の根を使った。組織の管理の口座の root、コンソールへの入り、役割の借り入れ（人の許可セットでも、土台の CI の orders-org-apply でも）。
    # 管理の口座は SCP を外せるので、拒否ではなく、使った時点で AWS の外の 2 つの宛先へ鳴らす。AWS のサービスが借りる物は外す。
    # 第 15 回: 管理の口座では、読むだけでない出来事を全部数える（芯の話題・購読・規則・アラームの書き換え、StackSet、IAM の利用者と鍵の作成）。
    # IAM の利用者の鍵で直に呼ぶ形（type が IAMUser）と、root の一時の資格を借りる AssumeRoot も数える。借り入れを使わない道を残さない。
    "trust-root-used" = "{ ($.recipientAccountId = \"${var.management_account_id}\") && ($.userIdentity.type != \"AWSService\") && (($.readOnly IS FALSE) || ($.userIdentity.type = \"Root\") || ($.userIdentity.type = \"IAMUser\") || ($.eventName = \"ConsoleLogin\") || ($.eventName = \"AssumeRole*\") || ($.eventName = \"AssumeRoot\")) }"
    # 長く使える鍵の利用と作成（第 15 回）。組織のどの口座でも、IAM の利用者の資格で動いた出来事と、利用者・鍵・合言葉の作成を鳴らす。
    # 人の入口は IAM Identity Center、CI は OIDC なので、平常は 0 件である。管理の口座の利用者の数は github-watch も毎時数える。
    "long-term-key-used" = "{ ($.userIdentity.type = \"IAMUser\") || (($.eventSource = \"iam.amazonaws.com\") && (($.eventName = \"CreateUser\") || ($.eventName = \"CreateAccessKey\") || ($.eventName = \"CreateLoginProfile\") || ($.eventName = \"UpdateAccessKey\"))) }"
    # StackSet の操作（第 15 回）。StackSet が SCP を受けるかは未確定 20 の (3)。受けないと見て、SCP の外の道として作成・更新・消去と
    # 口座への置き直しを、どの口座のどの主体でも鳴らす。芯（guard_core）と土台（platform_foundation）は StackSet が置く。
    "stackset-change" = "{ ($.eventSource = \"cloudformation.amazonaws.com\") && ($.readOnly IS FALSE) && (($.eventName = \"*StackSet*\") || ($.eventName = \"*StackInstances\")) }"
    # 組織の形と上限を変えた（口座の移動と外し、委任、SCP の付け外しと書き換え、SCP の型を止める）。どの主体でも鳴らす。
    "org-guard-change" = "{ ($.eventSource = \"organizations.amazonaws.com\") && (($.eventName = \"UpdatePolicy\") || ($.eventName = \"AttachPolicy\") || ($.eventName = \"DetachPolicy\") || ($.eventName = \"DeletePolicy\") || ($.eventName = \"DisablePolicyType\") || ($.eventName = \"MoveAccount\") || ($.eventName = \"RemoveAccountFromOrganization\") || ($.eventName = \"LeaveOrganization\") || ($.eventName = \"RegisterDelegatedAdministrator\") || ($.eventName = \"DeregisterDelegatedAdministrator\") || ($.eventName = \"CreateOrganizationalUnit\") || ($.eventName = \"DeleteOrganizationalUnit\")) }"
    # 人の入口を変えた（許可セットの方針と割り当て、グループへの人の足し込み）。当番のグループに人を足す手も、ここで鳴る。
    "human-access-change" = "{ (($.eventSource = \"sso.amazonaws.com\") && (($.eventName = \"PutInlinePolicyToPermissionSet\") || ($.eventName = \"DeleteInlinePolicyFromPermissionSet\") || ($.eventName = \"AttachManagedPolicyToPermissionSet\") || ($.eventName = \"AttachCustomerManagedPolicyReferenceToPermissionSet\") || ($.eventName = \"PutPermissionsBoundaryToPermissionSet\") || ($.eventName = \"CreateAccountAssignment\") || ($.eventName = \"UpdatePermissionSet\") || ($.eventName = \"CreatePermissionSet\"))) || (($.eventSource = \"identitystore.amazonaws.com\") && (($.eventName = \"CreateGroupMembership\") || ($.eventName = \"CreateUser\") || ($.eventName = \"UpdateUser\"))) }"
    # 当番を借りた、または借りた資格で何かをした。常設のグループで承認の仕組みが無いので、使うたびに鳴らし、SRE が障害の記録と突き合わせる。
    "oncall-used" = "{ ($.userIdentity.sessionContext.sessionIssuer.userName = \"AWSReservedSSO_orders-oncall-*\") || (($.eventName = \"AssumeRoleWithSAML\") && ($.requestParameters.roleArn = \"*AWSReservedSSO_orders-oncall-*\")) }"
    # 見張りそのものを変えた（守りの口座の関数・秘密・印・購読・記録の選び方・規則・アラーム）。見張りの関数が自分の印を書く操作は外す。
    "watch-change" = "{ ($.recipientAccountId = \"${var.security_account_id}\") && ($.userIdentity.type != \"AWSService\") && ($.userIdentity.sessionContext.sessionIssuer.userName != \"${local.name}-github-watch\") && (($.eventName = \"UpdateFunction*\") || ($.eventName = \"DeleteFunction*\") || ($.eventName = \"PutSecretValue\") || ($.eventName = \"UpdateSecret\") || ($.eventName = \"DeleteSecret\") || ($.eventName = \"PutParameter\") || ($.eventName = \"DeleteParameter\") || ($.eventName = \"PutSubscriptionFilter\") || ($.eventName = \"DeleteSubscriptionFilter\") || ($.eventName = \"PutEventSelectors\") || ($.eventName = \"StopLogging\") || ($.eventName = \"DisableRule\") || ($.eventName = \"RemoveTargets\") || ($.eventName = \"DeleteAlarms\") || ($.eventName = \"DisableAlarmActions\") || ($.eventName = \"DeleteMetricFilter\") || ($.eventName = \"Unsubscribe\")) }"
    # 見張りの通知の経路を変えた（メトリクスフィルタとアラームの書き換え、購読の絞り込み、話題の方針と削除、記録とロググループ、
    # 層と表と鍵の方針）。守りの口座へ適用する CI の 1 回で、型を外れた形に書き換えて黙らせる道を拾う。型の字数の上限で watch-change と分けた。
    "watch-path-change" = "{ ($.recipientAccountId = \"${var.security_account_id}\") && ($.userIdentity.type != \"AWSService\") && (($.eventName = \"PutMetricFilter\") || ($.eventName = \"PutMetricAlarm\") || ($.eventName = \"SetSubscriptionAttributes\") || ($.eventName = \"SetTopicAttributes\") || ($.eventName = \"DeleteTopic\") || ($.eventName = \"Subscribe\") || ($.eventName = \"PutDataProtectionPolicy\") || ($.eventName = \"PutTransformer\") || ($.eventName = \"PutAccountPolicy\") || ($.eventName = \"PutRetentionPolicy\") || ($.eventName = \"DeleteLogGroup\") || ($.eventName = \"UpdateTrail\") || ($.eventName = \"DeleteTrail\") || ($.eventName = \"PutRule\") || ($.eventName = \"PutTargets\") || ($.eventName = \"PublishLayerVersion\") || ($.eventName = \"UpdateTable\") || ($.eventName = \"DeleteTable\") || ($.eventName = \"PutKeyPolicy\") || ($.eventName = \"PutBucket*\")) }"
    # 守りの口座へ適用する CI の借り入れと書き込みは、この口座の外（管理の口座の芯。org/guard-core.tf）が 1 件ずつ鳴らす。
    # この口座の中に同じ型の見張りを置くと、その CI が 1 回で黙らせられるので置かない（前の guard-ci-used は消した）。
    # 人（当番と緊急の管理）の拒まれた書き込み。作業の口座の human-write は通った書き込みだけを障害の記録にするので、
    # わざと拒まれる書き込みで障害の記録を作る手は、ここでセキュリティへ鳴る。
    "human-write-denied" = "{ (${local.in_workload}) && ($.readOnly IS FALSE) && ($.errorCode = \"*\") && ($.userIdentity.sessionContext.sessionIssuer.userName = \"AWSReservedSSO_orders-*\") }"
    # 作業の口座の窓口の方針で拒まれた要求（ネットワークの出来事）。部品が許した窓口の名前で外の資源を名指しした試み。
    "network-endpoint-denied" = "{ (${local.in_workload}) && ($.eventCategory = \"NetworkActivity\") && ($.errorCode = \"VpceAccessDenied\") }"
    # 保管庫の複製の写し（第 14 回）。本番と検証環境の 2 つの守りの適用を重ねて、本番の復旧点を組織の中の別の口座の保管庫へ写す道。
    # 保管庫の方針の書き換え、写しの開始、写しの規則を持つ計画の書き換えを、作業の口座の外から 1 件ずつ数える。
    "backup-copy" = "{ (${local.in_workload}) && (($.eventName = \"StartCopyJob\") || ($.eventName = \"PutBackupVaultAccessPolicy\") || ($.eventName = \"DeleteBackupVaultAccessPolicy\") || ($.eventName = \"CreateBackupPlan\") || ($.eventName = \"UpdateBackupPlan\")) }"
  }
}

resource "aws_cloudwatch_log_metric_filter" "watch" {
  for_each       = local.watch_filters
  name           = "${local.name}-${each.key}"
  log_group_name = aws_cloudwatch_log_group.org_trail.name
  pattern        = each.value

  metric_transformation {
    name      = each.key
    namespace = "${local.name}/watch"
    value     = "1"
  }
}

# 宛先は SRE の当番とセキュリティの 2 つ。当番の利用を見張られる本人の宛先だけに送らない。
# アラームは状態が変わったときだけ鳴るので、人と信頼の根の入りは event-watch.tf が出来事ごとにも送る。
resource "aws_cloudwatch_metric_alarm" "watch" {
  for_each            = local.watch_filters
  alarm_name          = "${local.name}-${each.key}"
  alarm_description   = "Organization trail recorded ${each.key}"
  namespace           = "${local.name}/watch"
  metric_name         = each.key
  statistic           = "Sum"
  period              = 60
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.watch.arn, aws_sns_topic.security.arn]

  depends_on = [aws_cloudwatch_log_metric_filter.watch]
}

# 当番が読んだ量の目安。当番の読み方は Logs Insights の問い合わせだけにした（org/sso.tf。FilterLogEvents と GetLogEvents は許さない）。
# 1 回の問い合わせが返すのは 10,000 行までなので、1 時間の問い合わせの数で読める量の上限が決まる。目安を超えたらセキュリティへ鳴らす。
# 残る量: 目安の内側で 1 時間に var.oncall_queries_hourly_max × 10,000 行まで読める（既定の 20 回で 20 万行）。返した行の数は記録に残らない。
resource "aws_cloudwatch_log_metric_filter" "oncall_queries" {
  name           = "${local.name}-oncall-queries"
  log_group_name = aws_cloudwatch_log_group.org_trail.name
  pattern        = "{ ($.eventName = \"StartQuery\") && ($.userIdentity.sessionContext.sessionIssuer.userName = \"AWSReservedSSO_orders-oncall-*\") }"

  metric_transformation {
    name      = "oncall-queries"
    namespace = "${local.name}/watch"
    value     = "1"
  }
}

resource "aws_cloudwatch_metric_alarm" "oncall_queries" {
  alarm_name          = "${local.name}-oncall-queries-hourly"
  alarm_description   = "On-call ran more Logs Insights queries in one hour than expected"
  namespace           = "${local.name}/watch"
  metric_name         = "oncall-queries"
  statistic           = "Sum"
  period              = 3600
  evaluation_periods  = 1
  threshold           = var.oncall_queries_hourly_max
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.security.arn]

  depends_on = [aws_cloudwatch_log_metric_filter.oncall_queries]
}

# 当番が問い合わせの結果を取った数（第 14 回）。GetQueryResults は queryId だけで結果を返す（aws-facts の 23）。同僚の queryId を
# 拾う入口（DescribeQueries、LookupEvents、作業の口座の管理の記録）は SCP で閉じたが、結果の読み直しの数も、始めた数と別に数える。
# 1 回の問い合わせは結果が揃うまで数回取るので、目安は始めた数の目安より大きい（var.oncall_query_results_hourly_max）。
resource "aws_cloudwatch_log_metric_filter" "oncall_query_results" {
  name           = "${local.name}-oncall-query-results"
  log_group_name = aws_cloudwatch_log_group.org_trail.name
  pattern        = "{ ($.eventName = \"GetQueryResults\") && ($.userIdentity.sessionContext.sessionIssuer.userName = \"AWSReservedSSO_orders-oncall-*\") }"

  metric_transformation {
    name      = "oncall-query-results"
    namespace = "${local.name}/watch"
    value     = "1"
  }
}

resource "aws_cloudwatch_metric_alarm" "oncall_query_results" {
  alarm_name          = "${local.name}-oncall-query-results-hourly"
  alarm_description   = "On-call fetched Logs Insights results more often in one hour than expected (re-reading results by queryId)"
  namespace           = "${local.name}/watch"
  metric_name         = "oncall-query-results"
  statistic           = "Sum"
  period              = 3600
  evaluation_periods  = 1
  threshold           = var.oncall_query_results_hourly_max
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.security.arn]

  depends_on = [aws_cloudwatch_log_metric_filter.oncall_query_results]
}

# 作業の口座ごとの記録の途絶。15 分 1 件も届かなければ鳴る。
resource "aws_cloudwatch_log_metric_filter" "account_heartbeat" {
  for_each       = var.workload_accounts
  name           = "${local.name}-trail-${each.key}"
  log_group_name = aws_cloudwatch_log_group.org_trail.name
  pattern        = "{ $.recipientAccountId = \"${each.value}\" }"

  metric_transformation {
    name      = "trail-events-${each.key}"
    namespace = "${local.name}/watch"
    value     = "1"
  }
}

resource "aws_cloudwatch_metric_alarm" "account_silent" {
  for_each            = var.workload_accounts
  alarm_name          = "${local.name}-trail-silent-${each.key}"
  alarm_description   = "No organization trail events from ${each.key} for 15 minutes"
  namespace           = "${local.name}/watch"
  metric_name         = "trail-events-${each.key}"
  statistic           = "Sum"
  period              = 900
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "LessThanThreshold"
  treat_missing_data  = "breaching"
  alarm_actions       = [aws_sns_topic.watch.arn]

  depends_on = [aws_cloudwatch_log_metric_filter.account_heartbeat]
}

# ---- 棚卸しの便り（作業の口座の SNS を通らない 2 本目の確かめ）
# 作業の口座の棚卸しは、毎時の最後に、守りの欠けが 0 のときだけ status=ok の便りをこのバスへ送る（functions/copy_inventory.py）。
# ok の便りが 2 時間届かなければ鳴る。棚卸しを止めた、落とした、購読を消した、絞り込みを付けた、のどれでも鳴る。

resource "aws_cloudwatch_event_bus" "heartbeat" {
  name = "${local.name}-heartbeat"
}

resource "aws_cloudwatch_event_bus_policy" "heartbeat" {
  event_bus_name = aws_cloudwatch_event_bus.heartbeat.name
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      # 棚卸しの便りと、障害の記録（作業の口座のアラームが ALARM になった出来事。guardrails.tf の alarm-forward が送る）。
      Sid    = "InventoryAndAlarmForwardRolesOnly"
      Effect = "Allow"
      Principal = { AWS = flatten([for e, a in var.workload_accounts : [
        "arn:${local.partition}:iam::${a}:role/orders-admin-${e}-copy-inventory", "arn:${local.partition}:iam::${a}:role/orders-admin-${e}-alarm-forward",
      ]]) }
      Action   = "events:PutEvents"
      Resource = aws_cloudwatch_event_bus.heartbeat.arn
    }]
  })
}

resource "aws_cloudwatch_log_group" "heartbeat" {
  for_each          = var.workload_accounts
  name              = "/aws/events/${local.name}-heartbeat-${each.key}"
  retention_in_days = 30
  kms_key_id        = aws_kms_key.watch.arn
}

# ロググループの資源の方針は、守りの口座へ適用する CI（orders-guard-apply）からは置かない（第 14 回）。資源の方針で外の口座の主体に
# 読み出しを許す道を、信頼の根の経路の watch-apply だけに寄せた（security/watchers/functions.tf の heartbeat）。状態からは外すだけで消さない。
removed {
  from = aws_cloudwatch_log_resource_policy.heartbeat
  lifecycle {
    destroy = false
  }
}

resource "aws_cloudwatch_event_rule" "heartbeat" {
  for_each       = var.workload_accounts
  name           = "${local.name}-heartbeat-${each.key}"
  event_bus_name = aws_cloudwatch_event_bus.heartbeat.name
  event_pattern = jsonencode({
    source        = ["orders-admin.copy-inventory"]
    account       = [each.value]
    "detail-type" = ["guard-heartbeat"]
    detail        = { status = ["ok"] }
  })
}

resource "aws_cloudwatch_log_metric_filter" "heartbeat" {
  for_each       = var.workload_accounts
  name           = "${local.name}-heartbeat-${each.key}"
  log_group_name = aws_cloudwatch_log_group.heartbeat[each.key].name
  pattern        = ""

  metric_transformation {
    name      = "inventory-ok-${each.key}"
    namespace = "${local.name}/watch"
    value     = "1"
  }
}

resource "aws_cloudwatch_metric_alarm" "heartbeat" {
  for_each            = var.workload_accounts
  alarm_name          = "${local.name}-inventory-not-ok-${each.key}"
  alarm_description   = "The copy inventory of ${each.key} did not report status ok for 2 hours"
  namespace           = "${local.name}/watch"
  metric_name         = "inventory-ok-${each.key}"
  statistic           = "Sum"
  period              = 3600
  evaluation_periods  = 2
  threshold           = 1
  comparison_operator = "LessThanThreshold"
  treat_missing_data  = "breaching"
  alarm_actions       = [aws_sns_topic.watch.arn]

  depends_on = [aws_cloudwatch_log_metric_filter.heartbeat]
}
