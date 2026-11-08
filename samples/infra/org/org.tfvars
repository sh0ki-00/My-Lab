# 組織の土台の値。番号はすべて架空。
management_account_id      = "999988887777"
security_account_id        = "777766665555"
security_ou_id             = "ou-abcd-33334444"
guard_core_email           = "guard-core@example.com"
github_billing_email       = "billing@example.com"
guard_core_pager_url       = "https://pager.example.com/hooks/guard-core"
workload_ou_id             = "ou-abcd-11112222"
github_repository          = "example-org/orders-admin"
github_repository_id       = "100000001"
github_repository_owner_id = "100000002"
org_id                     = "o-a1b2c3d4e5"
workload_accounts          = { stg = "444455556666", prod = "111122223333" }
oncall_group_id            = "00000000-0000-0000-0000-00000000aaaa"
breakglass_group_id        = "00000000-0000-0000-0000-00000000bbbb"
security_team_slug         = "security-reviewers"
security_reviewer_team_id  = 1000002
# SHA はどれも架空（本物の版の SHA に置き換えるのは未確定 7）。
# setup-terraform は一覧から外した。動くときに取る terraform の本体が固まらないため。本体は ci/pinned-tools.json の版と SHA-256 で取る。
pinned_actions = [
  "actions/checkout@0000000000000000000000000000000000000001",
  "actions/attest-build-provenance@0000000000000000000000000000000000000004",
  "actions/upload-artifact@0000000000000000000000000000000000000005",
  "actions/download-artifact@0000000000000000000000000000000000000006",
]
