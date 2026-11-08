# 組織の土台（組織の管理の口座から、土台の CI の役割 orders-org-apply が適用する。信頼と鳴る所は ci.tf）。この構成の口座の上限と、GitHub の決まりを置く。
#   SCP（口座の上限）: 口座の管理者でも越えられない拒否。複製の共有と持ち出し、手の複製、承認なしの復元、
#   外への網、鍵の破壊、監査と守りの停止、長期のアクセスキー、決めた地域の外、を止める。
#   GitHub: OIDC の資格の sub に workflow の場所を入れ、使える Actions の部品を絞る。
# 値は org.tfvars（架空）。

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
  region              = "us-east-1"
  allowed_account_ids = [var.management_account_id]
}

provider "github" {
  owner = local.repo_owner
}

locals {
  repo_owner = split("/", var.github_repository)[0]
  repo_name  = split("/", var.github_repository)[1]
  # OIDC の sub の後ろに、変わらない番号（リポジトリと持ち主）を足す（org/github.tf の include_claim_keys の順）。
  # 名前の付け替えや、消した後の同じ名前の作り直しでは、番号が合わず借りられない。
  gh_ids = ":repository_id:${var.github_repository_id}:repository_owner_id:${var.github_repository_owner_id}"
}
