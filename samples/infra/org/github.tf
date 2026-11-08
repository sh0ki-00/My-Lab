# GitHub の決まり（リポジトリに 1 回）。
#   OIDC の資格の sub を「repo・context・job_workflow_ref」の形にする。AWS の役割の信頼の条件は、環境の名前に加えて
#   「main の、どの workflow の file か」まで名指しできる。main 以外のブランチから prod の環境を名指ししても、sub が合わない。
#   使える Actions の部品は、40 桁の SHA で固定した var.pinned_actions だけにする。GitHub の部品も札（@v4 など）では通さない。
#   上流の札を差し替えられても、固定した SHA の中身は変わらない。
#   main の保護: PR と別の 2 人の承認と、署名した commit が要り、管理者も越えられない。計画の検査（plan-gate）と、
#   部品の一覧の差分（deps-diff）が通らないと入れない。構成コード（/infra/）は全部セキュリティが持ち主なので、2 人のうち 1 人はセキュリティ。
#   守りの差分の適用は、さらに <env>-guarded の環境でセキュリティの承認が要る（foundation/github.tf）。
#   守りの仕組みそのもの（plan-gate、workflow、SCP と土台、通知とアラーム、棚卸しの関数）は、持ち主の欄（CODEOWNERS）で
#   セキュリティのチームの承認を要る形にする。配備のチームの 1 人だけでは、関所と例外と通知を書き換えられない。

# sub の後ろに、変わらない番号（repository_id と repository_owner_id）を足す（第 14 回）。名前だけの sub は、リポジトリの名前を
# 付け替えるか消した後に同じ名前で作り直したリポジトリと、組織の改名で空いた名前を外の人が取った組織からも作れる。
# どの役割の信頼も、番号まで名指しする（locals の gh_ids）。sub の中の並びは、この一覧の順と読む（確かめは未確定 7）。
resource "github_actions_repository_oidc_subject_claim_customization_template" "repo" {
  repository         = local.repo_name
  use_default        = false
  include_claim_keys = ["repo", "context", "job_workflow_ref", "repository_id", "repository_owner_id"]
}

# 組織の一員によるリポジトリの作成を止める（GitHub の既定は許す）。消した名前と付け替えた名前を、一員が取り直す道を閉じる。
# 作成・付け替え・削除・移譲は、監査ログの流し出しで 1 件ずつ鳴る（security/functions/event_watch.py の NAME_ACTIONS）。
resource "github_organization_settings" "org" {
  billing_email                            = var.github_billing_email
  members_can_create_repositories          = false
  members_can_create_public_repositories   = false
  members_can_create_private_repositories  = false
  members_can_create_internal_repositories = false
  members_can_fork_private_repositories    = false
  default_repository_permission            = "none"
}

resource "github_actions_repository_permissions" "repo" {
  repository      = local.repo_name
  enabled         = true
  allowed_actions = "selected"

  allowed_actions_config {
    github_owned_allowed = false
    verified_allowed     = false
    patterns_allowed     = var.pinned_actions
  }
}

# 必須の検査は、名前（context）に加えて出す仕組み（GitHub Actions の App）まで縛る（checks の「名前:App の番号」）。
# 名前だけだと、書き込みの権限で同じ名前の commit status を付けて検査を満たせる。出どころを縛れば、ほかの出どころの成功は数えない。
# github-watch も、名前と App の番号の組で照らす（functions/github-expected.json の status_checks）。
resource "github_branch_protection_v3" "main" {
  repository             = local.repo_name
  branch                 = "main"
  enforce_admins         = true
  require_signed_commits = true

  required_pull_request_reviews {
    required_approving_review_count = 2
    require_code_owner_reviews      = true
    dismiss_stale_reviews           = true
    require_last_push_approval      = true
  }

  required_status_checks {
    strict = true
    checks = [for c in ["infra-plan-run / plan-gate", "deps-diff / sbom-diff", "egress-check / web-egress", "migrate-gate / migrate-gate"] : "${c}:${var.actions_app_id}"]
  }
}

# 前の名前だけの保護は、状態から外して上の資源へ替える（GitHub の側の保護は上の資源が上書きする）。
removed {
  from = github_branch_protection.main
  lifecycle {
    destroy = false
  }
}

# 守りの仕組みの持ち主。require_code_owner_reviews（上）と合わせて、ここに並べた場所の変更はセキュリティのチームの承認が要る。
# 並べるのは「許す物の一覧」の逆で、構成コードは /infra/ を丸ごと並べる。file を 1 つずつ並べると、並べ忘れた file
# （役割や方針を書いた file）が配備の側の承認だけで main に入るからである。
# 部品の lock の file（画面と API の npm、Terraform の部品の指紋）も並べる。悪い版の部品は、入る所で 2 人目の目を通す。
# この file 自体も並べるので、持ち主の欄を外す変更にもセキュリティの承認が要る。
resource "github_repository_file" "codeowners" {
  repository          = local.repo_name
  branch              = "main"
  file                = ".github/CODEOWNERS"
  overwrite_on_create = true
  commit_message      = "Guard owners: plan-gate, workflows, SCP, foundation, alarms, inventory"
  content             = join("\n", [for path in concat(var.guard_paths, var.lock_paths) : "${path} @${local.repo_owner}/${var.security_team_slug}"])
}

# 部品が入る所の検査と、画面の file を配る手順。どちらも workflow の file をここでコードにし、持ち主の欄の内側に置く。
#   deps-diff.yml: PR ごとに部品の一覧（SBOM）の差分を出す。新しい部品と版の変更は注記で鳴らし、危ない形は止める（必須の検査）。
#   static-build.yml: 画面の束を作り、file ごとの指紋に来歴の署名を付ける。AWS の資格は持たない。
#   static-deploy.yml: 別の file で、配る job だけが資格を借りる。照らしの正は守りの口座の画面の照らし（security/static-watch.tf）。
#   egress-check.yml: 自前のコード（web/ と API）の外へ移る処理と外へ送る処理を落とす（必須の検査）。判定の本体は tools/ に置く。
#   migrate-gate.yml: 移行の文を許す文の一覧で確かめる（必須の検査）。置かないと、必須の検査に名前だけが残り、満たす仕組みが無い。
# GitHub の見張りは、このリポジトリにも別のリポジトリにも置かない。守りの口座の関数が回す（security/github-watch.tf）。
resource "github_repository_file" "workflows" {
  for_each            = toset(["deps-diff.yml", "static-build.yml", "static-deploy.yml", "egress-check.yml", "migrate-gate.yml"])
  repository          = local.repo_name
  branch              = "main"
  file                = ".github/workflows/${each.value}"
  overwrite_on_create = true
  commit_message      = "Supply chain checks: dependency diff and provenance before deploy"
  content             = file("${path.module}/../ci/${each.value}")
}

# 外へ移る処理の検査の本体（見本は skills/infra/scripts/）。tools/ は持ち主の欄でセキュリティの承認が要る。
resource "github_repository_file" "egress_check" {
  for_each            = toset(["egress-check.sh", "egress_check.py"])
  repository          = local.repo_name
  branch              = "main"
  file                = "tools/${each.value}"
  overwrite_on_create = true
  commit_message      = "Egress check for own code: navigation and outbound calls"
  content             = file("${path.module}/../../../skills/infra/scripts/${each.value}")
}

# 資格を借りる job の道具の本体の固定（版と SHA-256）と、その取り出し。外の部品（setup-terraform）は使わない。
# 資格を借りる job の手順の本体（cred-steps.sh。第 16 回）も置く。その job の run は、この file を取る行と呼ぶ行だけにする。
# 置き場は持ち主の欄（guard_paths の /tools/）の内側で、変えるにはセキュリティの承認が要る。
resource "github_repository_file" "ci_tools" {
  for_each            = toset(["pinned-tools.json", "fetch-terraform.sh", "cred-steps.sh"])
  repository          = local.repo_name
  branch              = "main"
  file                = "tools/ci/${each.value}"
  overwrite_on_create = true
  commit_message      = "Pin the terraform binary by version and SHA-256 for jobs that borrow credentials"
  content             = file("${path.module}/../ci/${each.value}")
}

# 部品の差分と移行の文の検査の本体（見本は skills/infra/scripts/）。workflow が呼ぶ tools/deps-diff/ と tools/migrate-gate/ を置く。
# 置き場は持ち主の欄（guard_paths の /tools/）の内側で、変えるにはセキュリティの承認が要る。
resource "github_repository_file" "gate_tools" {
  for_each = {
    "tools/deps-diff/deps-diff.sh"       = "deps-diff.sh"
    "tools/deps-diff/deps_diff.py"       = "deps_diff.py"
    "tools/migrate-gate/migrate-gate.sh" = "migrate-gate.sh"
    "tools/migrate-gate/migrate_gate.py" = "migrate_gate.py"
  }
  repository          = local.repo_name
  branch              = "main"
  file                = each.key
  overwrite_on_create = true
  commit_message      = "Gate tools: dependency diff and migration statement allowlist"
  content             = file("${path.module}/../../../skills/infra/scripts/${each.value}")
}
