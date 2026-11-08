# GitHub の環境の保護の規則。CI の役割の信頼の条件（環境の名前）が頼る守りを、ここでコードにする。
#   配備できるのは main だけ。自分の変更は自分で承認できない。
#   <env>: 配備のチームの 1 人が承認する。適用の役割（作る・変える）だけが借りられる。
#   <env>-guarded: セキュリティのチームの 1 人だけが承認する。配備のチームは並べない。守りの適用の役割だけが借りられる。
#   GitHub の環境の承認は「並べた承認者のうち 1 人」で通る。配備のチームを並べると、PR を通した人と同じ側の 1 人で適用まで進めてしまう。
#   main へ入る PR は、別の 2 人の承認が要り、構成コードの変更ではうち 1 人がセキュリティ（org/github.tf の main の保護と持ち主の欄）。
#   そのため守りの差分は、PR の 2 人と、-guarded の環境のセキュリティの 1 人を通る。移行のイメージの押し込み（db-image-push.yml）も同じ。
#   権限・信頼・方針・配信・WAF・監査の差分は、AWS の側で守りの適用の役割にしか許していない。CI の手順を書き換えても、承認 1 人では通らない。

locals {
  environments = {
    (var.env)            = [var.deploy_reviewer_team_id]
    "${var.env}-guarded" = [var.security_reviewer_team_id]
  }
}

resource "github_repository_environment" "deploy" {
  for_each            = local.environments
  repository          = local.repo_name
  environment         = each.key
  prevent_self_review = true
  # 管理者が承認を越えられない（GitHub の既定は越えられる）。守りの口座の見張りも毎時確かめる（github_watch.py の check_settings）。
  can_admins_bypass = false

  reviewers {
    teams = each.value
  }

  deployment_branch_policy {
    protected_branches     = false
    custom_branch_policies = true
  }
}

resource "github_repository_environment_deployment_policy" "main_only" {
  for_each       = github_repository_environment.deploy
  repository     = local.repo_name
  environment    = each.value.environment
  branch_pattern = "main"
}
