variable "region" {
  description = "守りの口座の住みかの地域"
  type        = string
  default     = "ap-northeast-1"
}

variable "security_account_id" {
  description = "守りの口座（架空）。組織の CloudTrail の委任された管理者"
  type        = string
}

variable "workload_accounts" {
  description = "見張る作業の口座（環境ごと、架空）"
  type        = map(string)
}

variable "alert_email" {
  description = "SRE の当番の宛先（架空）。見張りの全部の通知が届く"
  type        = string
}

variable "security_email" {
  description = "セキュリティの宛先（架空）。当番の外。人と信頼の根の入りは、出来事ごとにここへ届く（見張られる当番と宛先を分ける）"
  type        = string
}

variable "security_pager_url" {
  description = "セキュリティの呼び出しの仕組みの HTTPS の窓口（架空）"
  type        = string
  validation {
    condition     = startswith(var.security_pager_url, "https://")
    error_message = "security_pager_url は https:// で始める。"
  }
}

variable "oncall_queries_hourly_max" {
  description = "当番が 1 時間に流す Logs Insights の問い合わせ（StartQuery）の目安（架空）。障害の調べで平常 5〜15 回。1 回は 10,000 行まで返す"
  type        = number
  default     = 20
  validation {
    condition     = var.oncall_queries_hourly_max >= 5 && var.oncall_queries_hourly_max <= 100
    error_message = "oncall_queries_hourly_max は 5〜100 回の幅で決める。"
  }
}

variable "github_enterprise" {
  description = "GitHub の監査ログを流す enterprise の名前（架空）。流し出しの OIDC の sub に入る"
  type        = string
}

variable "pager_url" {
  description = "メールでない 2 本目の宛先。呼び出しの仕組みの HTTPS の窓口（架空）"
  type        = string
  validation {
    condition     = startswith(var.pager_url, "https://")
    error_message = "pager_url は https:// で始める。"
  }
}

variable "trail_retention_days" {
  description = "組織の記録を消せない日数"
  type        = number
  default     = 400
}

variable "github_repository" {
  description = "見張る配備のリポジトリ（owner/name、架空）。画面の照らしは、このリポジトリの main の static-build.yml の署名だけを正とする"
  type        = string
}

variable "github_app_id" {
  description = "見張りの GitHub App の番号（架空）。権限は配備のリポジトリと組織を読むだけ。鍵は守りの口座の秘密に置く"
  type        = number
}

variable "github_app_installation_id" {
  description = "見張りの GitHub App を組織に入れた番号（架空）"
  type        = number
}

variable "management_account_id" {
  description = "組織の管理の口座（架空）。信頼の根なので、root とコンソールへの入りを鳴らす"
  type        = string
}

variable "oncall_query_results_hourly_max" {
  description = "当番が 1 時間に問い合わせの結果を取る回数（GetQueryResults）の目安（架空）。1 回の問い合わせで結果が揃うまで数回取る"
  type        = number
  default     = 100
  validation {
    condition     = var.oncall_query_results_hourly_max >= 10 && var.oncall_query_results_hourly_max <= 500
    error_message = "oncall_query_results_hourly_max は 10〜500 回の幅で決める。"
  }
}
