# 環境の差はここにある変数だけで出す。値は env/stg.tfvars と env/prod.tfvars。

variable "env" {
  description = "環境の名前。stg か prod"
  type        = string
  validation {
    condition     = contains(["stg", "prod"], var.env)
    error_message = "env は stg か prod にする。"
  }
}

variable "region" {
  description = "主に置く地域"
  type        = string
  default     = "ap-northeast-1"
}

variable "vpc_cidr" {
  description = "VPC のアドレスの範囲"
  type        = string
}

variable "azs" {
  description = "使うアベイラビリティゾーン（2 つ）"
  type        = list(string)
  default     = ["ap-northeast-1a", "ap-northeast-1c"]
}

variable "office_cidrs" {
  description = "管理画面を開いてよい事務所の出口のアドレス（架空）"
  type        = list(string)
}

variable "admin_domain" {
  description = "管理画面の名前（例: admin.example.jp）"
  type        = string
}

variable "edge_certificate_arn" {
  description = "CloudFront の証明書（us-east-1 の ACM）"
  type        = string
}

variable "api_certificate_arn" {
  description = "内部のロードバランサーの証明書（ACM）"
  type        = string
}

variable "api_image_digest" {
  description = "注文 API のイメージのダイジェスト（sha256:...）。タグではなくダイジェストで固定する"
  type        = string
}

variable "db_bootstrap_image_digest" {
  description = "利用者づくり専用のイメージのダイジェスト（sha256:...）。中身は利用者の道具と db/roles.sql だけ"
  type        = string
  validation {
    condition     = can(regex("^sha256:[0-9a-f]{64}$", var.db_bootstrap_image_digest))
    error_message = "db_bootstrap_image_digest は sha256: で始まる 64 桁にする。"
  }
}

variable "db_migrate_image_digest" {
  description = "移行専用のイメージのダイジェスト（API の部品の入らないイメージ。db-image-push.yml が作る）"
  type        = string
  validation {
    condition     = can(regex("^sha256:[0-9a-f]{64}$", var.db_migrate_image_digest))
    error_message = "db_migrate_image_digest は sha256:<64 桁> の形にする。"
  }
}

variable "db_table_owner" {
  description = "注文の表の今の持ち主（旧 API の側。正本 db-access.json の owner。段 0 で名前を調べる。架空）。移行はこの役割で流す"
  type        = string
  default     = "orders_owner"
  validation {
    condition     = can(regex("^[a-z_][a-z0-9_]{0,62}$", var.db_table_owner)) && !contains(["orders_admin", "orders_api", "rds_superuser"], var.db_table_owner)
    error_message = "db_table_owner は管理者でも API でもない、PostgreSQL の役割の名前にする。"
  }
}

variable "state_bucket_name" {
  description = "Terraform の状態を置くバケット（土台の値と同じ）。読んだ記録を CloudTrail のデータイベントに残す"
  type        = string
}

variable "api_desired_count" {
  description = "注文 API の平常の数"
  type        = number
}

variable "api_max_count" {
  description = "注文 API の最大の数"
  type        = number
}

variable "db_instance_class" {
  description = "データベースの大きさ"
  type        = string
}

variable "db_multi_az" {
  description = "データベースを 2 つのゾーンに置くか"
  type        = bool
}

variable "db_allocated_storage" {
  description = "データベースの保存領域（GB）の初期値"
  type        = number
}

variable "backup_retention_days" {
  description = "自動バックアップ（時点復元）を残す日数"
  type        = number
}

variable "snapshot_retention_days" {
  description = "ロックした保管庫に日次の複製を残す日数"
  type        = number
}

variable "log_retention_days" {
  description = "アプリと通信のログを残す日数"
  type        = number
}

variable "audit_retention_days" {
  description = "監査ログを消せない状態で残す日数"
  type        = number
}

variable "github_repository" {
  description = "イメージを押し込んでよいリポジトリ（owner/name）"
  type        = string
}

variable "account_id" {
  description = "この環境を置く口座（架空）。検証環境と本番は別の口座にし、違う口座へは適用できないようにする"
  type        = string
  validation {
    condition     = can(regex("^[0-9]{12}$", var.account_id))
    error_message = "account_id は 12 桁の数字にする。"
  }
}

variable "alert_email" {
  description = "守りの通知を受ける SRE の当番の宛先（架空）"
  type        = string
}

variable "alert_pager_url" {
  description = "守りの通知の、メールでない 2 本目の宛先（呼び出しの仕組みの HTTPS の窓口、架空）"
  type        = string
  validation {
    condition     = startswith(var.alert_pager_url, "https://")
    error_message = "alert_pager_url は https:// で始める。"
  }
}

variable "guard_static_watch_role_arn" {
  description = "守りの口座の画面の照らしの役割（security/static-watch.tf）。画面のバケットの版と、配信の鍵の復号だけを許す"
  type        = string
  validation {
    condition     = can(regex("^arn:aws:iam::[0-9]{12}:role/orders-guard-static-watch$", var.guard_static_watch_role_arn))
    error_message = "guard_static_watch_role_arn は守りの口座の orders-guard-static-watch の役割を名指しする。"
  }
}

variable "guard_event_watch_role_arn" {
  description = "守りの口座の出来事ごとの見張りの役割（security/event-watch.tf）。DB の 2 つの像のリポジトリの像を読むことだけを許す（第 15 回）"
  type        = string
  validation {
    condition     = can(regex("^arn:aws:iam::[0-9]{12}:role/orders-guard-event-watch$", var.guard_event_watch_role_arn))
    error_message = "guard_event_watch_role_arn は守りの口座の orders-guard-event-watch の役割を名指しする。"
  }
}

variable "edge_bytes_hourly_max" {
  description = "配信が 1 時間に送るバイト数の目安（架空）。超えたら edge-bytes-out-hourly が知らせる。平常の幅から決める（9 時台の 5 人で 20〜40MB の見積もり）"
  type        = number
  default     = 50000000
  validation {
    condition     = var.edge_bytes_hourly_max >= 10000000 && var.edge_bytes_hourly_max <= 100000000
    error_message = "edge_bytes_hourly_max は 10MB〜100MB の幅で、平常の幅の上に決める。"
  }
}

variable "edge_bytes_daily_max" {
  description = "配信が 1 日に送るバイト数の目安（架空）。超えたら edge-bytes-out-daily が知らせる。平常は 1 日 60〜120MB の見積もり"
  type        = number
  default     = 150000000
  validation {
    condition     = var.edge_bytes_daily_max >= 50000000 && var.edge_bytes_daily_max <= 500000000
    error_message = "edge_bytes_daily_max は 50MB〜500MB の幅で、平常の幅の上に決める。"
  }
}

variable "guard_heartbeat_bus_arn" {
  description = "守りの口座の便りのバス（security/ の heartbeat）。棚卸しが毎時、守りの欠けが 0 のときだけ ok を送る"
  type        = string
}

variable "user_auth_issuer_url" {
  description = "利用者の認証の発行元（未確定 1）。空のあいだは本番に適用できない"
  type        = string
  default     = ""
}

variable "oncall_role_name_prefix" {
  description = "当番が IAM Identity Center で借りる役割の名前の頭（AWSReservedSSO_<権限セット>_）"
  type        = string
}

variable "manual_copy_max_days" {
  description = "手で取った複製（最後の複製と、移行の写し）を残す最長の日数。棚卸しの関数も 7〜35 の外なら落ちる"
  type        = number
  default     = 35
  validation {
    condition     = var.manual_copy_max_days >= 7 && var.manual_copy_max_days <= 35
    error_message = "manual_copy_max_days は 7〜35 日にする（0 にすると、名前の合う複製がその日に消える）。"
  }
}

variable "drill_copy_max_hours" {
  description = "復元の訓練の写しを残す最長の時間。棚卸しが 1 時間ごとに見て、超えたら消して知らせる"
  type        = number
  default     = 6
  validation {
    condition     = var.drill_copy_max_hours >= 1 && var.drill_copy_max_hours <= 24
    error_message = "drill_copy_max_hours は 1〜24 時間にする。"
  }
}

variable "api_list_daily_total" {
  description = "注文の一覧を、全部の鍵で 1 日に呼べる回数の目安（超えたら知らせる）。5 人が 30 秒ごとに 8 時間取る 4,800 回に余裕を足した架空の値"
  type        = number
  default     = 6000
}

variable "api_detail_daily_total" {
  description = "注文の詳細と書き込みを、全部の鍵で 1 日に呼べる回数の目安（超えたら知らせる）。1 日 400 件の出荷で、詳細と書き込みが平常 800〜2,000 回の見積もりに余裕を足した架空の値"
  type        = number
  default     = 3000
  validation {
    condition     = var.api_detail_daily_total >= 1000 && var.api_detail_daily_total <= 10000
    error_message = "api_detail_daily_total は 1,000〜10,000 回の幅で、平常の幅の上に決める。"
  }
}

variable "api_rate_per_key" {
  description = "利用者の鍵 1 本あたり、5 分に API を呼べる回数"
  type        = number
  default     = 300
}

variable "api_detail_rate_per_key" {
  description = "利用者の鍵 1 本あたり、5 分に注文の詳細と書き込みを呼べる回数"
  type        = number
  default     = 100
}

variable "api_list_rate_per_key" {
  description = "利用者の鍵 1 本あたり、5 分に注文の一覧を呼べる回数（超えたら止めて知らせる）"
  type        = number
  default     = 40
}

variable "clear_site_cache" {
  description = "部品を外した版を出すあいだ真にする。入口の応答に Clear-Site-Data: \"cache\" を付け、端末に残った古い html と script の控えを消す"
  type        = bool
  default     = false
}

variable "github_repository_id" {
  description = "GitHub のリポジトリの番号（架空）。OIDC の sub に入り、名前の付け替えと作り直しで変わる。信頼の条件はこの番号まで名指しする"
  type        = string
  validation {
    condition     = can(regex("^[0-9]{1,12}$", var.github_repository_id))
    error_message = "github_repository_id は数字だけにする。"
  }
}

variable "github_repository_owner_id" {
  description = "GitHub のリポジトリの持ち主（組織）の番号（架空）。組織の改名で空いた名前を外の人が取っても、この番号は合わない"
  type        = string
  validation {
    condition     = can(regex("^[0-9]{1,12}$", var.github_repository_owner_id))
    error_message = "github_repository_owner_id は数字だけにする。"
  }
}
