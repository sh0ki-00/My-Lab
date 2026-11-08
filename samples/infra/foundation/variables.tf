variable "env" {
  description = "環境の名前。stg か prod"
  type        = string
  validation {
    condition     = contains(["stg", "prod"], var.env)
    error_message = "env は stg か prod にする。"
  }
}

variable "account_id" {
  description = "この環境の口座（架空）"
  type        = string
}

variable "region" {
  description = "主に置く地域"
  type        = string
  default     = "ap-northeast-1"
}

variable "github_repository" {
  description = "配備を持つリポジトリ（owner/name）"
  type        = string
}

variable "deploy_reviewer_team_id" {
  description = "配備を承認する GitHub のチームの番号（架空）"
  type        = number
}

variable "state_bucket_name" {
  description = "Terraform の状態を置くバケット（土台が作る）"
  type        = string
}

variable "security_reviewer_team_id" {
  description = "守りの適用（権限・方針・配信・監査の差分）を、配備の承認と別に承認するセキュリティのチームの番号（架空）"
  type        = number
}

variable "plan_from_pull_requests" {
  description = "PR から計画の役割を借りてよいか。検証環境（合成のデータ）だけ true。本番は main に入った後にだけ計画を出す"
  type        = bool
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
