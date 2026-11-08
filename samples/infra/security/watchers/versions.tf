# 見張りの関数の構成（守りの口座）。適用するのは orders-guard-core-watch-apply だけ（functions.tf の頭の注釈）。

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

  backend "s3" {}
}

provider "aws" {
  region              = var.region
  allowed_account_ids = [var.security_account_id]
}

data "aws_partition" "current" {}

locals {
  name               = "orders-guard"
  partition          = data.aws_partition.current.partition
  guard_boundary_arn = "arn:${local.partition}:iam::${var.security_account_id}:policy/orders-guard-core-boundary"
}
