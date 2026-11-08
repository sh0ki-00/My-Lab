# 注文一覧の管理画面の基盤（静的な見本。適用はしない）。
# 設計は skills/infra/examples/infra-design-order-list.md にある。口座番号・金額・件数はすべて架空。
# 本番と検証環境は同じコードで、違いは env/<環境>.tfvars の値だけにする。口座も環境ごとに分ける（allowed_account_ids）。
# 口座の上限（SCP）は org/、口座ごとの土台（OIDC と適用の役割）は foundation/ にある。

# Terraform の版は 1.14 より前に限る。1.14 から入った action のブロックと ephemeral の資源は、plan-gate が見ない。
# 版を上げるときは、plan-gate がそれらを守りの経路へ回してから上限を外す（守りの経路の変更）。

terraform {
  required_version = ">= 1.9.0, < 1.14.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "6.0.0"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "2.7.0"
    }
  }
  # 版は 1 つに固定する。.terraform.lock.hcl（部品の指紋）は CI が terraform providers lock で作って PR に載せ、
  # 計画と適用は terraform init -lockfile=readonly で回す（指紋の違う部品は読み込まない）。

  # 状態の置き場。値は CI が init のときに -backend-config で渡す（人の端末からは適用しない）。
  backend "s3" {}
}

provider "aws" {
  region              = var.region
  allowed_account_ids = [var.account_id]

  default_tags {
    tags = {
      service    = "orders-admin"
      env        = var.env
      managed_by = "terraform"
    }
  }
}

# CloudFront に付ける WAF は us-east-1 にしか置けない。
provider "aws" {
  alias               = "us_east_1"
  region              = "us-east-1"
  allowed_account_ids = [var.account_id]

  default_tags {
    tags = {
      service    = "orders-admin"
      env        = var.env
      managed_by = "terraform"
    }
  }
}

data "aws_caller_identity" "current" {}
data "aws_partition" "current" {}

locals {
  name       = "orders-admin-${var.env}"
  account_id = data.aws_caller_identity.current.account_id
  partition  = data.aws_partition.current.partition
}
