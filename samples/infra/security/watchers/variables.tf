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

variable "watch_python_layer_sha256" {
  description = "見張りの関数の層の中身の指紋（base64 の SHA-256、架空）。層を替えたら計画の差分に出る"
  type        = string
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

variable "watch_python_layer_arn" {
  description = "見張りの関数の層（PyJWT と sigstore。架空）。層の作り方と固定は未確定 7"
  type        = string
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

variable "management_account_id" {
  description = "組織の管理の口座（架空）。出来事ごとの見張りが、この口座の書き込みを信頼の根の利用として送る。github-watch が IAM の数を読む"
  type        = string
}
