variable "management_account_id" {
  description = "組織の管理の口座（架空）"
  type        = string
}

variable "workload_ou_id" {
  description = "検証環境と本番の口座を入れた組織の単位（OU）"
  type        = string
}

variable "allowed_regions" {
  description = "使ってよい地域。東京と、CloudFront の WAF を置く us-east-1"
  type        = list(string)
  default     = ["ap-northeast-1", "us-east-1"]
}

variable "github_repository" {
  description = "この構成の配備を持つリポジトリ（owner/name）"
  type        = string
}

variable "org_id" {
  description = "組織の番号（架空）。データの境界（外の資源へ書かない、外の主体に使わせない）の条件に使う"
  type        = string
}

variable "workload_envs" {
  description = "この構成の環境の名前。例外の役割の名前は、ここから 1 つずつ組み立てる"
  type        = list(string)
  default     = ["stg", "prod"]
}

variable "pinned_actions" {
  description = "使ってよい Actions の部品。どれも 40 桁の SHA で固定する（版の札は通さない）"
  type        = list(string)
  validation {
    condition     = alltrue([for a in var.pinned_actions : can(regex("^[A-Za-z0-9_.-]+/[A-Za-z0-9_./-]+@[0-9a-f]{40}$", a))])
    error_message = "pinned_actions は owner/repo@<40 桁の SHA> の形にする。"
  }
}

variable "workload_accounts" {
  description = "環境ごとの口座（架空）"
  type        = map(string)
}

variable "oncall_group_id" {
  description = "当番の許可セットを割り当てる IAM Identity Center のグループ（架空）"
  type        = string
}

variable "breakglass_group_id" {
  description = "緊急の管理の許可セットを割り当てるグループ（架空）。人数と顔ぶれはセキュリティが決める"
  type        = string
}

variable "security_team_slug" {
  description = "守りの仕組みの変更を承認するセキュリティのチームの名前（架空）"
  type        = string
}

variable "guard_paths" {
  description = "守りの仕組みの置き場と、データを読む・外へ出す自前のコード。どれもセキュリティのチームが持ち主になる（CODEOWNERS）。画面（/web/）と API（/api/）は、データを読む処理と外へ移る処理を足す差分にセキュリティの承認を要るようにする。DB の権限の正本（db-access.json）と、run が呼びうる実行の file（script、Makefile、package.json、Dockerfile）も並べる"
  type        = list(string)
  default = [
    "/.github/", "/infra/", "/tools/", "/web/", "/api/", "**/db-access.json",
    # 第 15 回: run が呼びうる repo の実行の file（script、Makefile、npm の scripts、像の作り方）も持ち主の欄に入れる。
    "/scripts/", "**/Makefile", "**/package.json", "**/Dockerfile*", "**/*.sh",
  ]
}

variable "lock_paths" {
  description = "部品の版を決める lock の file。変更にはセキュリティのチームの承認が要る（CODEOWNERS）"
  type        = list(string)
  default     = ["package-lock.json", "**/package-lock.json", "**/.terraform.lock.hcl", "**/requirements*.txt", "**/uv.lock", "**/poetry.lock"]
}

variable "security_account_id" {
  description = "守りの口座（架空）。組織の CloudTrail を受け、緊急の管理の利用と守りの経路の変更を、作業の口座の外から鳴らす"
  type        = string
}

variable "security_reviewer_team_id" {
  description = "org-guarded の環境を承認するセキュリティのチームの番号（架空）。組織の土台の適用は、このチームの 1 人の承認を通る"
  type        = number
}

variable "security_ou_id" {
  description = "守りの口座が入る OU（架空）。守りの口座の芯（org/guard-core.tf の StackSet）を、この OU の守りの口座 1 つにだけ置く"
  type        = string
}

variable "guard_core_email" {
  description = "守りの口座の芯が鳴らすセキュリティのメール（架空）。守りの口座の外（管理の口座の話題）から送る"
  type        = string
}

variable "guard_core_pager_url" {
  description = "守りの口座の芯が鳴らす呼び出しの仕組みの HTTPS の窓口（架空）。メールでない 2 本目"
  type        = string
  validation {
    condition     = startswith(var.guard_core_pager_url, "https://")
    error_message = "guard_core_pager_url は https:// で始める。"
  }
}

variable "actions_app_id" {
  description = "必須の検査を出す GitHub Actions の App の番号。必須の検査を、この App が出した結果だけに縛る（名前だけで縛らない）"
  type        = number
  default     = 15368
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

variable "github_billing_email" {
  description = "GitHub の組織の請求の宛先（架空）。組織の設定の資源が必ず求める値"
  type        = string
}
