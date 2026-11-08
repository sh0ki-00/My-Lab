# 組織の記録のロググループの伏せ字（データ保護の方針）。守りの口座。適用するのは orders-guard-core-watch-apply だけ（第 13 回）。
#   記録の要求の欄には、当番が流した問い合わせの文などが入りうる。作業の口座のロググループと同じ形の検出と伏せ字を掛ける。
#   監査の所見の送り先は空にする（外へ書かない）。送り先を書ける操作（PutDataProtectionPolicy）は、守りの口座の SCP
#   （org/guard-core.tf の MaskingOnlyByWatchApply）が、この役割のほかに拒む。守りの口座へ適用する CI は、ここに届かない。
#   変えたら: 守りの口座の watch-path-change（PutDataProtectionPolicy）と、芯の ci-writes の外の watch-apply の書き込みの見張り。
#   security/watch.tf の前の資源は、removed で状態から外したので、ここで取り込む（消してから作り直す差分を出さない）。

locals {
  trail_identifiers = concat(
    [for d in ["EmailAddress", "AwsSecretKey"] : "arn:${local.partition}:dataprotection::aws:data-identifier/${d}"],
    ["JpPhoneNumber", "JpPostalCode", "PasswordAssignment", "CanaryValue"],
  )
}

import {
  to = aws_cloudwatch_log_data_protection_policy.org_trail
  id = "/orders-guard/org-trail"
}

resource "aws_cloudwatch_log_data_protection_policy" "org_trail" {
  log_group_name = data.aws_cloudwatch_log_group.org_trail.name
  policy_document = jsonencode({
    Name    = "${local.name}-org-trail-personal-data"
    Version = "2021-06-01"
    Configuration = {
      CustomDataIdentifier = [
        { Name = "JpPhoneNumber", Regex = "0\\d{1,4}-\\d{1,4}-\\d{4}" },
        { Name = "JpPostalCode", Regex = "\\d{3}-\\d{4}" },
        { Name = "PasswordAssignment", Regex = "(?i)(password|passwd|pgpassword)\\s*[=:]\\s*[^\\s,;]+" },
        { Name = "CanaryValue", Regex = "ZZCANARY-\\d{6}" },
      ]
    }
    Statement = [
      {
        Sid            = "audit"
        DataIdentifier = local.trail_identifiers
        Operation      = { Audit = { FindingsDestination = {} } }
      },
      {
        Sid            = "mask"
        DataIdentifier = local.trail_identifiers
        Operation      = { Deidentify = { MaskConfig = {} } }
      },
    ]
  })
}
