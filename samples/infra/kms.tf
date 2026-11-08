# 鍵は用途ごとに 4 本。データ（データベース、バックアップ、秘密）、ログ（監査ログ、アプリのログ、通知）、
# us-east-1 のログ（WAF のログと、そこの通知）、配信（画面のファイル）。
# どれも年 1 回の自動の回転を入れる。鍵の方針の Resource "*" は「この鍵そのもの」を指す（鍵の方針の決まり）。
# どの鍵も、消す予約と無効化を誰にも許さない。方針を書き換えられるのは CI の守りの適用の役割だけ（承認 2 人。口座の管理者も不可）。
# 消すときは、まず守りの適用の役割が方針からこの拒否を外す。外の口座を方針に足しても、組織の資源の上限（RCP）が外の主体を拒む。その差分は PR の計画に出て、変更は通知される（guardrails.tf）。

locals {
  key_guard = [
    {
      Sid       = "DenyKeyDestruction"
      Effect    = "Deny"
      Principal = { AWS = "*" }
      Action    = ["kms:ScheduleKeyDeletion", "kms:DisableKey", "kms:DeleteImportedKeyMaterial"]
      Resource  = "*"
    },
    {
      Sid       = "PolicyChangesOnlyFromGuardedApply"
      Effect    = "Deny"
      Principal = { AWS = "*" }
      Action    = "kms:PutKeyPolicy"
      Resource  = "*"
      Condition = { ArnNotEquals = { "aws:PrincipalArn" = local.guard_role_arn } }
    },
  ]

  # 暗号化した通知（SNS）に、CloudWatch のアラームと EventBridge が書けるようにする。
  key_notify = {
    Sid       = "AlarmsAndEventsPublish"
    Effect    = "Allow"
    Principal = { Service = ["cloudwatch.amazonaws.com", "events.amazonaws.com"] }
    Action    = ["kms:GenerateDataKey*", "kms:Decrypt"]
    Resource  = "*"
    Condition = { StringEquals = { "aws:SourceAccount" = local.account_id } }
  }
}

resource "aws_kms_key" "data" {
  description             = "${local.name} のデータの鍵"
  enable_key_rotation     = true
  deletion_window_in_days = 30
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = concat([
      {
        Sid       = "AccountAdmin"
        Effect    = "Allow"
        Principal = { AWS = "arn:${local.partition}:iam::${local.account_id}:root" }
        Action    = "kms:*"
        Resource  = "*"
      },
    ], local.key_guard)
  })
}

resource "aws_kms_alias" "data" {
  name          = "alias/${local.name}-data"
  target_key_id = aws_kms_key.data.key_id
}

resource "aws_kms_key" "logs" {
  description             = "${local.name} のログの鍵"
  enable_key_rotation     = true
  deletion_window_in_days = 30
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = concat([
      {
        Sid       = "AccountAdmin"
        Effect    = "Allow"
        Principal = { AWS = "arn:${local.partition}:iam::${local.account_id}:root" }
        Action    = "kms:*"
        Resource  = "*"
      },
      {
        Sid       = "CloudTrailEncrypt"
        Effect    = "Allow"
        Principal = { Service = "cloudtrail.amazonaws.com" }
        Action    = ["kms:GenerateDataKey*", "kms:DescribeKey"]
        Resource  = "*"
        Condition = {
          StringLike = {
            "kms:EncryptionContext:aws:cloudtrail:arn" = "arn:${local.partition}:cloudtrail:*:${local.account_id}:trail/*"
          }
        }
      },
      {
        Sid       = "CloudWatchLogs"
        Effect    = "Allow"
        Principal = { Service = "logs.${var.region}.amazonaws.com" }
        Action    = ["kms:Encrypt", "kms:Decrypt", "kms:ReEncrypt*", "kms:GenerateDataKey*", "kms:DescribeKey"]
        Resource  = "*"
        Condition = {
          ArnLike = {
            "kms:EncryptionContext:aws:logs:arn" = "arn:${local.partition}:logs:${var.region}:${local.account_id}:log-group:*"
          }
        }
      },
      local.key_notify,
    ], local.key_guard)
  })
}

resource "aws_kms_alias" "logs" {
  name          = "alias/${local.name}-logs"
  target_key_id = aws_kms_key.logs.key_id
}

resource "aws_kms_key" "static" {
  description             = "${local.name} の画面のファイルの鍵"
  enable_key_rotation     = true
  deletion_window_in_days = 30
}

# 配信の鍵は CloudFront の配信 1 つと、守りの口座の画面の照らし（S3 を通すときだけ）に読ませる。配信の ARN が要るので方針を分けて置く。
resource "aws_kms_key_policy" "static" {
  key_id = aws_kms_key.static.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = concat([
      {
        Sid       = "AccountAdmin"
        Effect    = "Allow"
        Principal = { AWS = "arn:${local.partition}:iam::${local.account_id}:root" }
        Action    = "kms:*"
        Resource  = "*"
      },
      {
        Sid       = "CloudFrontDecrypt"
        Effect    = "Allow"
        Principal = { Service = "cloudfront.amazonaws.com" }
        Action    = "kms:Decrypt"
        Resource  = "*"
        Condition = {
          StringEquals = { "AWS:SourceArn" = aws_cloudfront_distribution.admin.arn }
        }
      },
      {
        # 守りの口座の画面の照らしが、書かれた版を S3 を通して読む。直の復号はさせない（kms:ViaService）。
        Sid       = "GuardStaticWatchDecrypt"
        Effect    = "Allow"
        Principal = { AWS = var.guard_static_watch_role_arn }
        Action    = "kms:Decrypt"
        Resource  = "*"
        Condition = {
          StringEquals = { "kms:ViaService" = "s3.${var.region}.amazonaws.com" }
        }
      },
    ], local.key_guard)
  })
}

# us-east-1 のログの鍵。WAF のログ（CloudFront に付ける WAF は us-east-1 にしか置けない）と、そこの通知を守る。
resource "aws_kms_key" "logs_use1" {
  provider                = aws.us_east_1
  description             = "${local.name} の us-east-1 のログの鍵"
  enable_key_rotation     = true
  deletion_window_in_days = 30
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = concat([
      {
        Sid       = "AccountAdmin"
        Effect    = "Allow"
        Principal = { AWS = "arn:${local.partition}:iam::${local.account_id}:root" }
        Action    = "kms:*"
        Resource  = "*"
      },
      {
        Sid       = "CloudWatchLogs"
        Effect    = "Allow"
        Principal = { Service = "logs.us-east-1.amazonaws.com" }
        Action    = ["kms:Encrypt", "kms:Decrypt", "kms:ReEncrypt*", "kms:GenerateDataKey*", "kms:DescribeKey"]
        Resource  = "*"
        Condition = {
          ArnLike = {
            "kms:EncryptionContext:aws:logs:arn" = "arn:${local.partition}:logs:us-east-1:${local.account_id}:log-group:*"
          }
        }
      },
      local.key_notify,
    ], local.key_guard)
  })
}

resource "aws_kms_alias" "logs_use1" {
  provider      = aws.us_east_1
  name          = "alias/${local.name}-logs"
  target_key_id = aws_kms_key.logs_use1.key_id
}
