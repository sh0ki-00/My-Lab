# データの層。注文のデータベース（PostgreSQL）。外から届かず、API の役割だけが IAM の認証で入る。
# 管理者の合言葉は RDS が Secrets Manager に作って回転する（コードにも変数にも書かない）。

resource "aws_db_subnet_group" "orders" {
  name       = "${local.name}-orders"
  subnet_ids = aws_subnet.data[*].id
}

resource "aws_db_parameter_group" "orders" {
  name   = "${local.name}-orders-pg16"
  family = "postgres16"

  parameter {
    name  = "rds.force_ssl"
    value = "1"
  }

  # 毎時の DB の突き合わせ（db/roles.sql の guard.check_all）を、DB の中の予定の仕組み（pg_cron）で回す。
  # 管理者の名で動くので、移行の利用者と API は止めも変えもできない。RDS での読み込みの確かめは未確定 20。
  parameter {
    name         = "shared_preload_libraries"
    value        = "pg_cron"
    apply_method = "pending-reboot"
  }

  parameter {
    name         = "cron.database_name"
    value        = "orders"
    apply_method = "pending-reboot"
  }

  # SQL の本文と束ねた値を、どの道からもログに出さない（注文者の名前や住所がログに混ざらないように）。
  #   log_statement: 実行した文を出さない。
  #   log_min_duration_statement: 遅い文の本文を出さない（-1 で止める）。遅い文は Performance Insights の型で見る。
  #   log_parameter_max_length（_on_error）: 束ねた値を 0 字にする（PostgreSQL 16 の既定 -1 は全部出す）。
  #   log_min_error_statement: 誤りのときに文を添えない。log_error_verbosity: DETAIL（一意制約の値など）を出さない。
  #   log_min_messages: 誤りの本文（入力の値を引用する型がある）を出さない。
  parameter {
    name  = "log_statement"
    value = "none"
  }

  parameter {
    name  = "log_min_duration_statement"
    value = "-1"
  }

  parameter {
    name  = "log_parameter_max_length"
    value = "0"
  }

  parameter {
    name  = "log_parameter_max_length_on_error"
    value = "0"
  }

  parameter {
    name  = "log_min_error_statement"
    value = "panic"
  }

  parameter {
    name  = "log_error_verbosity"
    value = "terse"
  }

  # 誤り（ERROR）の本文そのものに入力の値が入る型がある（例: 型の誤りは、受けた値を引用して返す）。terse で消えるのは DETAIL だけなので、
  # ERROR の行をサーバーのログに書かない。残すのは FATAL と PANIC（接続と起動の誤り）だけ。誤りの数は API の指標と Performance Insights で見る。
  parameter {
    name  = "log_min_messages"
    value = "fatal"
  }
}

# RDS がログを書き出す先のロググループ。先に作り、鍵と保持の日数をこの構成で決める（RDS に任せると鍵が無く、消えない）。
resource "aws_cloudwatch_log_group" "rds" {
  name              = "/aws/rds/instance/${local.name}-orders/postgresql"
  retention_in_days = var.log_retention_days
  kms_key_id        = aws_kms_key.logs.arn
}

resource "aws_db_instance" "orders" {
  identifier     = "${local.name}-orders"
  engine         = "postgres"
  engine_version = "16"
  instance_class = var.db_instance_class
  db_name        = "orders"
  username       = "orders_admin"

  manage_master_user_password   = true
  master_user_secret_kms_key_id = aws_kms_key.data.arn

  allocated_storage     = var.db_allocated_storage
  max_allocated_storage = 100
  storage_type          = "gp3"
  storage_encrypted     = true
  kms_key_id            = aws_kms_key.data.arn

  multi_az               = var.db_multi_az
  db_subnet_group_name   = aws_db_subnet_group.orders.name
  vpc_security_group_ids = [aws_security_group.db.id]
  publicly_accessible    = false
  parameter_group_name   = aws_db_parameter_group.orders.name

  iam_database_authentication_enabled = true

  backup_retention_period   = var.backup_retention_days
  backup_window             = "18:00-18:30"
  maintenance_window        = "sun:19:00-sun:19:30"
  copy_tags_to_snapshot     = true
  deletion_protection       = true
  skip_final_snapshot       = false
  final_snapshot_identifier = "${local.name}-orders-final"

  auto_minor_version_upgrade            = true
  performance_insights_enabled          = true
  performance_insights_kms_key_id       = aws_kms_key.data.arn
  performance_insights_retention_period = 7
  enabled_cloudwatch_logs_exports       = ["postgresql"]

  depends_on = [aws_cloudwatch_log_group.rds]
}

# 管理者の合言葉の資源の方針。読めるのは、RDS 自身（回転）と、最初の 1 回の利用者づくりの作業だけ。
# 口座の管理者も読めない。この方針を外せるのは CI の守りの適用の役割（承認 2 人）だけで、外す操作も読む操作も通知される。
resource "aws_secretsmanager_secret_policy" "db_admin" {
  secret_arn = aws_db_instance.orders.master_user_secret[0].secret_arn
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "OnlyRdsAndBootstrapRead"
        Effect    = "Deny"
        Principal = { AWS = "*" }
        Action    = ["secretsmanager:GetSecretValue", "secretsmanager:PutSecretValue", "secretsmanager:UpdateSecret"]
        Resource  = "*"
        Condition = {
          ArnNotLike = {
            "aws:PrincipalArn" = [
              local.bootstrap_role,
              "arn:${local.partition}:iam::${local.account_id}:role/aws-service-role/rds.amazonaws.com/AWSServiceRoleForRDS",
            ]
          }
          StringNotEquals = { "aws:PrincipalServiceName" = "rds.amazonaws.com" }
        }
      },
      {
        Sid       = "PolicyOnlyFromGuardedApply"
        Effect    = "Deny"
        Principal = { AWS = "*" }
        Action    = ["secretsmanager:PutResourcePolicy", "secretsmanager:DeleteResourcePolicy"]
        Resource  = "*"
        Condition = { ArnNotEquals = { "aws:PrincipalArn" = local.guard_role_arn } }
      },
    ]
  })
}
