# 人の許可セット（IAM Identity Center）。この構成の口座に割り当てる人の権限は、この 2 つだけ。
#   当番（orders-oncall-<環境>）: 読むだけ。ViewOnlyAccess は設定の一覧だけでログの中身を読めないので、この構成のロググループの
#     問い合わせを読む操作を、名指しで足す（ロググループは名前の一覧）。SCP の LogReadsOnlyForOncall が、これを当番だけに残す。
#     性能の記録（Performance Insights）は付けない。SQL の本文と束ねた値が入り、問い合わせの数の目安の外で読めるからである（第 13 回）。
#     ViewOnlyAccess に入る DescribeQueries と LookupEvents（同僚の問い合わせの queryId と文）は、SCP の NoQueryHistory が拒む。
#     伏せ字を外す操作（logs:Unmask）は付けない。SCP の NoUnmask が誰にも許さない。
#     割り当ては常設のグループで、承認の仕組みは無い（一時の割り当ては未確定 28）。そのため使うたびに、守りの口座の oncall-used が
#     組織の CloudTrail から拾って鳴らし、SRE が障害の記録と突き合わせる。PT1H は 1 回の長さで、入り直すたびに鳴る。
#   緊急の管理（orders-breakglass-<環境>）: 管理の方針は付けない。復旧の操作の一覧（org/scp.tf の breakglass_actions）だけを許し、
#     SCP の entry_guard も同じ一覧の外をすべて拒む（2 段）。
#     できるのは設定を読むこと、データベースの再起動、作業の停止だけ。データの中身は読めない（data_guard）。
#     借りた瞬間に、守りの口座が組織の CloudTrail から拾って鳴らす（security/ の breakglass-used）。作業の口座の管理者は止められない。
#     作業の口座の中でも human-write が鳴る。割り当てる人の顔ぶれはセキュリティが決める（グループの番号だけをここに置く）。

data "aws_ssoadmin_instances" "this" {}

locals {
  sso_instance = tolist(data.aws_ssoadmin_instances.this.arns)[0]
  sso_sets = merge(
    { for e, acct in var.workload_accounts : "orders-oncall-${e}" => { account = acct, env = e, group = var.oncall_group_id, policy = "arn:aws:iam::aws:policy/job-function/ViewOnlyAccess" } },
    { for e, acct in var.workload_accounts : "orders-breakglass-${e}" => { account = acct, env = e, group = var.breakglass_group_id, policy = "" } },
  )
}

resource "aws_ssoadmin_permission_set" "human" {
  for_each         = local.sso_sets
  name             = each.key
  instance_arn     = local.sso_instance
  session_duration = "PT1H"
}

resource "aws_ssoadmin_managed_policy_attachment" "human" {
  for_each           = { for k, v in local.sso_sets : k => v if v.policy != "" }
  instance_arn       = local.sso_instance
  permission_set_arn = aws_ssoadmin_permission_set.human[each.key].arn
  managed_policy_arn = each.value.policy
}

resource "aws_ssoadmin_account_assignment" "human" {
  for_each           = local.sso_sets
  instance_arn       = local.sso_instance
  permission_set_arn = aws_ssoadmin_permission_set.human[each.key].arn
  principal_type     = "GROUP"
  principal_id       = each.value.group
  target_type        = "AWS_ACCOUNT"
  target_id          = each.value.account
}

# 緊急の管理は、復旧の一覧だけを許す。秘密の値を読む操作と、データベースへの IAM の接続は、一覧の外でもあり、重ねて拒む。
resource "aws_ssoadmin_permission_set_inline_policy" "breakglass" {
  for_each           = { for k, v in local.sso_sets : k => v if startswith(k, "orders-breakglass-") }
  instance_arn       = local.sso_instance
  permission_set_arn = aws_ssoadmin_permission_set.human[each.key].arn
  inline_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "RecoveryListOnly"
        Effect   = "Allow"
        Action   = local.breakglass_actions
        Resource = "*" # iac-scan:allow IAC-003 一覧の操作は設定を読む型が多く、対象を名指しできない。SCP が同じ一覧の外を拒む
      },
      {
        Sid      = "NoSecretValuesNoDbConnect"
        Effect   = "Deny"
        Action   = ["secretsmanager:GetSecretValue", "rds-db:connect"]
        Resource = "*"
      },
    ]
  })
}

# 当番が障害のときに読む物。この構成のロググループの問い合わせ（Logs Insights）だけ。
# 読めるロググループは名前の一覧で書く（型の「/orders-admin-*」にしない）。型に入ってしまう管理の記録（/<名前>/cloudtrail）と
# DNS の問い合わせの記録は一覧の外にする（第 14 回）。管理の記録には同僚の StartQuery の queryId と文が残り、NoQueryHistory で閉じた
# 「管理の記録の履歴」を別の入口から読めるからである。SCP の NoTrailAndDnsLogReads も、この 2 つの読み出しを誰にも許さない。
# DB のログのファイル（rds:DownloadDBLogFilePortion）も付けない。問い合わせの数に入らない読み方で、同じ中身はロググループの問い合わせで読める。
# ログの読み方は問い合わせだけにする。FilterLogEvents と GetLogEvents はページを送れば量に上限が無く、守りの口座の目安（問い合わせの数）に
# 入らないので許さない。問い合わせは 1 回 10,000 行までで、回数を守りの口座が数える（security/watch.tf の oncall-queries-hourly）。
resource "aws_ssoadmin_permission_set_inline_policy" "oncall" {
  for_each           = { for k, v in local.sso_sets : k => v if startswith(k, "orders-oncall-") }
  instance_arn       = local.sso_instance
  permission_set_arn = aws_ssoadmin_permission_set.human[each.key].arn
  inline_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "ReadThisStackLogs"
        Effect = "Allow"
        Action = ["logs:StartQuery", "logs:StopQuery", "logs:GetQueryResults"]
        Resource = flatten([for g in [
          "/orders-admin-${each.value.env}/orders-api",
          "/orders-admin-${each.value.env}/db-jobs/bootstrap",
          "/orders-admin-${each.value.env}/db-jobs/migrate",
          "/orders-admin-${each.value.env}/vpc-flow",
          "/aws/rds/instance/orders-admin-${each.value.env}-orders/postgresql",
          "/aws/lambda/orders-admin-${each.value.env}-copy-inventory",
          "aws-waf-logs-orders-admin-${each.value.env}",
        ] : ["arn:aws:logs:*:${each.value.account}:log-group:${g}", "arn:aws:logs:*:${each.value.account}:log-group:${g}:*"]])
      },
    ]
  })
}
