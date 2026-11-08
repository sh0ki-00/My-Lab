# 口座ごとの土台（検証環境と本番の口座に 1 回ずつ。土台の CI が platform-foundation の役割で適用する）。
#   GitHub の OIDC の窓口（口座に 1 つ。口座を分けたので、環境ごとに作ってもぶつからない）。
#   Terraform の計画の役割、適用の役割、守りの適用の役割、権限の境界。SCP が名前で例外にする役割（復元、バックアップ、利用者づくり）。
#   GitHub の環境（prod・stg と、承認 2 人の prod-guarded・stg-guarded）の保護の規則。main からだけ配備でき、承認者が自分の変更を承認できない。
#   口座の公開のブロックと、状態のバケットの古い版の寿命。
# 値は env/<環境>.tfvars（架空）。

terraform {
  required_version = ">= 1.9.0, < 1.14.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "6.0.0"
    }
    github = {
      source  = "integrations/github"
      version = "6.0.0"
    }
  }

  backend "s3" {}
}

provider "aws" {
  region              = var.region
  allowed_account_ids = [var.account_id]
}

provider "github" {
  owner = local.repo_owner
}

data "aws_partition" "current" {}

locals {
  name       = "orders-admin-${var.env}"
  partition  = data.aws_partition.current.partition
  repo_owner = split("/", var.github_repository)[0]
  repo_name  = split("/", var.github_repository)[1]
  # OIDC の sub の後ろに、変わらない番号（リポジトリと持ち主）を足す（org/github.tf の include_claim_keys の順）。
  # 名前の付け替えや、消した後の同じ名前の作り直しでは、番号が合わず借りられない。
  gh_ids = ":repository_id:${var.github_repository_id}:repository_owner_id:${var.github_repository_owner_id}"
  # GitHub の資格の sub（org/ で形を変えてある）。環境と、main の workflow の file まで名指しする。
  gh_sub = "repo:${var.github_repository}:environment:${var.env}:job_workflow_ref:${var.github_repository}/.github/workflows"
  # 守りの適用だけが通る環境（承認 2 人）。権限・方針・配信・監査の差分が計画に出たら、CI はこちらで適用する（plan-gate）。
  gh_guarded_sub = "repo:${var.github_repository}:environment:${var.env}-guarded:job_workflow_ref:${var.github_repository}/.github/workflows"
}
