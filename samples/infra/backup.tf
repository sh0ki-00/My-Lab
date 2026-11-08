# 復元を確かめるバックアップ。2 段で持つ。
#   1. RDS の自動バックアップ（時点復元）。backup_retention_days 日。
#   2. ロックした保管庫への日次の複製。ロックの後は、管理者の権限でも保持の日数より前に消せない。
# 復元は毎月、各環境の口座の中で、その環境の複製から測る（検証環境は合成のデータ、本番は本番の口座の中だけ）。
# 手順は skills/infra/scripts/restore-drill.sh と同じで、復元は foundation/iam.tf の restore の役割だけが行う。
# 保管庫から外へ写す・消す・寿命を変える操作は、方針で誰にも許さない（別の口座への複製は未確定 4）。

resource "aws_backup_vault" "orders" {
  name        = "${local.name}-orders"
  kms_key_arn = aws_kms_key.data.arn
}

resource "aws_backup_vault_policy" "orders" {
  backup_vault_name = aws_backup_vault.orders.name
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "NoCopyOutNoEarlyDelete"
        Effect    = "Deny"
        Principal = { AWS = "*" }
        Action    = ["backup:CopyFromBackupVault", "backup:DeleteRecoveryPoint", "backup:UpdateRecoveryPointLifecycle"]
        Resource  = "*"
      },
      {
        # 別の口座からの写しを受け取らない（第 14 回）。本番の守りの適用で写しの規則を足し、検証環境のこの保管庫へ本番の復旧点を
        # 写す道を、受け取る側でも止める。写しの開始と方針の書き換えは、守りの口座の backup-copy が 1 件ずつ鳴らす。
        Sid       = "NoCopyInFromOtherAccounts"
        Effect    = "Deny"
        Principal = { AWS = "*" }
        Action    = "backup:CopyIntoBackupVault"
        Resource  = "*"
        Condition = { StringNotEquals = { "aws:PrincipalAccount" = var.account_id } }
      },
      {
        Sid       = "RestoreOnlyByRestoreRole"
        Effect    = "Deny"
        Principal = { AWS = "*" }
        Action    = "backup:StartRestoreJob"
        Resource  = "*"
        Condition = { ArnNotEquals = { "aws:PrincipalArn" = local.restore_role } }
      },
    ]
  })
}

resource "aws_backup_vault_lock_configuration" "orders" {
  backup_vault_name   = aws_backup_vault.orders.name
  min_retention_days  = 7
  max_retention_days  = 35
  changeable_for_days = 3
}

resource "aws_backup_plan" "orders" {
  name = "${local.name}-orders"

  rule {
    rule_name         = "daily"
    target_vault_name = aws_backup_vault.orders.name
    schedule          = "cron(0 18 * * ? *)"
    start_window      = 60
    completion_window = 180

    lifecycle {
      delete_after = var.snapshot_retention_days
    }

    recovery_point_tags = { purpose = "daily" }
  }
}

resource "aws_backup_selection" "orders" {
  name         = "${local.name}-orders"
  plan_id      = aws_backup_plan.orders.id
  iam_role_arn = local.backup_role
  resources    = [aws_db_instance.orders.arn]
}
