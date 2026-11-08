# 守りの口座（1 回だけ。守りの口座の土台の CI が適用する）。作業の口座（検証環境と本番）の外から、守りが働いているかを見る。
#   組織の CloudTrail（org/ で守りの口座を委任された管理者にした）を受け、次を鳴らす。作業の口座の管理者は、どれも止めも変えもできない。
#     1. 緊急の管理の許可セットを借りた瞬間（breakglass-used）。
#     2. 通知の経路と守りの仕組みの変更（購読と絞り込み、話題の方針、ログの変換と口座単位の方針と配送、アラームと規則、守りの関数）。
#     3. 組織の上限と人の許可セットの変更（SCP、委任、許可セットの方針と割り当て）。
#     4. 作業の口座の記録の途絶と、棚卸しの便りの途絶（棚卸しが動かないか、守りの欠けを見つけた）。
#     5. 一覧の外の役割を借りたこと（outside-principal）と、守りの適用と土台の役割を借りたこと（guarded-apply-used）。
#     6. GitHub の見張り（github-watch.tf）。この口座の関数が 1 時間ごとに、設定・main の続き・配備・CI の役割の借り入れを確かめる。
#     7. 画面の照らし（static-watch.tf）。画面のバケットへの書き込みのたびに、書かれた版を作りの来歴と照らす。
#     8. 信頼の根の利用（trust-root-used）、組織の形の変更（org-guard-change）、人の入口の変更（human-access-change）、当番の利用（oncall-used）、
#        見張りそのものの変更（watch-change と watch-path-change）、作業の口座の窓口の方針で拒まれた要求（network-endpoint-denied）。
#     9. 出来事ごとの見張り（event-watch.tf）。人と信頼の根の入りを 1 件ごとにセキュリティへ送り、当番の入りを障害の記録と照らす。
#        GitHub の監査ログの流し出しを受け、保護の外し・force push・自前の走る機械の登録を出来事ごとに鳴らす。
#     10. 守りの口座へ適用する CI の役割は、この口座の外（org/guard-core.tf の StackSet と SCP）が持つ。借り入れと書き込みは、
#         管理の口座の芯が 1 件ずつ AWS の外へ鳴らす。この口座の中の見張りは、その CI では黙らせられても、芯は残る。
#   宛先は守りの口座の SNS の 2 つ。SRE の当番（メールと呼び出しの窓口）と、当番の外のセキュリティ（メールと呼び出しの窓口）。
#   宛先が生きているかは、毎時の便り（notify-heartbeat）が AWS の外の呼び出しの仕組みに届くかで見る。
# 値は security.tfvars（架空）。

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
  name      = "orders-guard"
  partition = data.aws_partition.current.partition
  # 守りの口座の役割は、芯の StackSet が置く権限の境界（許す物の一覧）を付けたときだけ作れる（org/guard-core.tf の RolesWithBoundary）。
  guard_boundary_arn = "arn:${local.partition}:iam::${var.security_account_id}:policy/orders-guard-core-boundary"
}
