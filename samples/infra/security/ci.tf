# 守りの口座へ適用する CI（信頼の根の 1 つ）。ここに残すのは GitHub の OIDC の窓口だけ。
#   CI の役割 orders-guard-apply の信頼と権限は、組織の StackSet（org/guard-core.tf）に移した。この役割が自分の信頼と方針を書き換え、
#   見張りの宛先と型と購読を 1 回で黙らせる道を閉じるため。守りの口座の誰も、この役割と芯の経路を変えられない（SCP の orders-guard-core）。
#   借りられるのは、セキュリティだけが承認する環境 security-guarded を通った main の security-apply.yml だけ（org/ci.tf が環境を置く）。
#   使ったら鳴る: 借りた瞬間と、その資格の書き込みの 1 件ずつが、管理の口座のバスを通って AWS の外の宛先へ鳴る（org/guard-core.tf）。
#     この口座の中の同じ型の見張り（前の guard-ci-used）は、この CI が黙らせられるので消した。event-watch の入りの通知は残る。
#   ログの中身と記録と秘密を読む操作は、この役割に許さない（SCP の DataReadsOnlyForWatch）。
#   見張りの関数と役割と出来事の宛先は、この役割の外（watchers/ を適用する orders-guard-core-watch-apply）に置く（SCP の
#   WatchCodeOnlyByWatchApply と WatchRolesOnlyByWatchApply）。見張りの役割でコードを動かし、その例外で読む道を閉じる。
#   移す日は、この構成の状態から役割を外し（下の removed）、StackSet が同じ名前で作り直す。その 1 回は承認 2 人の経路で行う（未確定 7）。

resource "aws_iam_openid_connect_provider" "github_actions" {
  url            = "https://token.actions.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"]
}

removed {
  from = aws_iam_role.guard_apply
  lifecycle {
    destroy = false
  }
}

removed {
  from = aws_iam_role_policy_attachment.guard_apply_read
  lifecycle {
    destroy = false
  }
}

removed {
  from = aws_iam_role_policy.guard_apply
  lifecycle {
    destroy = false
  }
}
