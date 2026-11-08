"""GitHub の見張り（github-watch）。守りの口座の関数で、1 時間に 1 回動く（security/github-watch.tf）。

配備のリポジトリの管理者と GitHub の組織の持ち主（信頼の根）が、守りを外したか、守りの外の経路で変更を入れたかを確かめる。
見張りは GitHub の中にも、配備のリポジトリにも置かない。コード・決めた値・鍵・前回の印は、どれも守りの口座にある。
  設定: 環境の承認者と自分の承認の禁止と main だけの配備と管理者の越えの禁止（can_admins_bypass）、main の保護（古い承認の取り消しを含む）、持ち主の欄（CODEOWNERS）、Actions の部品と OIDC の sub の形、
    リポジトリの公開の状態、自前の走る機械（リポジトリと組織。決めた数は 0 台）。決めた値は github-expected.json。
  main の続き: 前回の main の先頭（守りの口座の印）から今の先頭へ、履歴が続いているか（force push で戻していないか）。
    その間の commit の全部が、別の 2 人が承認した PR を通ったか。commit の日時では絞らない（日時はずらせる）。
  配備: 直近 HOURS 時間の配備は、環境の承認を通ったか。承認者は決めた team の人か。配った SHA が今の main から届き、別の 2 人が
    承認した PR を通ったか（保護を外して押し込み、同じ SHA へ戻す手は、ここで鳴る）。-guarded の承認者は、同じ commit の PR の作者と
    承認者の外の人か。
  AWS の側との突き合わせ: 組織の CloudTrail に残った CI の役割の借り入れ（AssumeRoleWithWebIdentity）ごとに、借り入れの名前
    （gh-<実行の番号>-<試みの番号>。どの workflow も 機械の OIDC の札で借りるときの role-session-name で付ける）から GitHub の実行を引き、
    同じ workflow の file か、main の実行か、その commit が今の main から届き PR を通ったか、job が GitHub の機械で動いたか、
    同じ実行の同じ役割を 2 回借りていないかを確かめる。sub の無い借り入れと、名前の無い借り入れは ng にする（黙って飛ばさない）。
    GitHub の管理者は実行と配備の記録を消せるが、AWS の側の記録は消せない。
  出来事ごとの見張り（保護の外し、force push、自前の走る機械の登録、公開の状態の変更）は、GitHub の監査ログの流し出しを受ける
    event_watch.py が受け持つ。この関数は、毎時の照らしで、流し出しが止まっても残る型の守りを見る。
出力: 標準出力に {"kind": "github-watch", "status": "ok"|"ng", "findings": [...]} の 1 行。API に届かないときも ng にする（黙って ok にしない）。
使い方: python3 github_watch.py --selftest
"""
import base64
import datetime
import hashlib
import json
import os
import re
import sys

HOURS = 2


def check_settings(get, exp, findings):
    repo = exp["repository"]
    for name, team in exp["environments"].items():
        e = get(f"/repos/{repo}/environments/{name}")
        rules = [x for x in e.get("protection_rules", []) if x.get("type") == "required_reviewers"]
        teams = sorted(r["reviewer"].get("slug", "") for x in rules for r in x.get("reviewers", []))
        if teams != [team]:
            findings.append(f"環境 {name} の承認者が {teams}（決めた値 [{team}]）")
        if not all(x.get("prevent_self_review") for x in rules) or not rules:
            findings.append(f"環境 {name} で自分の承認を止めていない")
        if e.get("can_admins_bypass") is not False:
            findings.append(f"環境 {name} で管理者が承認を越えられる（can_admins_bypass）")
        pol = e.get("deployment_branch_policy") or {}
        names = sorted(p["name"] for p in get(f"/repos/{repo}/environments/{name}/deployment-branch-policies").get("branch_policies", []))
        if not pol.get("custom_branch_policies") or names != ["main"]:
            findings.append(f"環境 {name} に main の外から配備できる（{names}）")
    p = get(f"/repos/{repo}/branches/main/protection")
    rv = p.get("required_pull_request_reviews") or {}
    want = {
        "enforce_admins": (p.get("enforce_admins") or {}).get("enabled") is True,
        "required_signatures": (p.get("required_signatures") or {}).get("enabled") is True,
        "approvals>=2": rv.get("required_approving_review_count", 0) >= 2,
        "code_owner_reviews": rv.get("require_code_owner_reviews") is True,
        "dismiss_stale_reviews": rv.get("dismiss_stale_reviews") is True,
        "last_push_approval": rv.get("require_last_push_approval") is True,
        # 名前と出どころ（App の番号）の組で照らす。名前だけの必須の検査は、書き込みの権限で付けた同じ名前の状態で満たせる。
        "status_checks": {(c["context"], c["app_id"]) for c in exp["status_checks"]}
        <= {(c.get("context"), c.get("app_id")) for c in (p.get("required_status_checks") or {}).get("checks", [])},
    }
    findings += [f"main の保護が外れている: {k}" for k, ok in want.items() if not ok]
    c = get(f"/repos/{repo}/contents/.github/CODEOWNERS?ref=main")
    body = base64.b64decode(c.get("content", "")).decode()
    if hashlib.sha256(body.encode()).hexdigest() != exp["codeowners_sha256"]:
        findings.append("持ち主の欄（CODEOWNERS）が決めた値と違う")
    a = get(f"/repos/{repo}/actions/permissions")
    sel = get(f"/repos/{repo}/actions/permissions/selected-actions") if a.get("allowed_actions") == "selected" else {}
    if a.get("allowed_actions") != "selected" or sorted(sel.get("patterns_allowed", [])) != sorted(exp["pinned_actions"]) \
            or sel.get("github_owned_allowed") or sel.get("verified_allowed"):
        findings.append("Actions の使える部品が、SHA で固定した一覧と違う")
    # Actions に PR の承認を許すと、PR の作者が足した workflow の bot の承認で、別の 2 人の承認の 1 人分を満たせる。
    wf = get(f"/repos/{repo}/actions/permissions/workflow")
    if wf.get("can_approve_pull_request_reviews") is not False or wf.get("default_workflow_permissions") != "read":
        findings.append("Actions が PR を承認できるか、既定の札が読みだけでない（actions/permissions/workflow）")
    sub = get(f"/repos/{repo}/actions/oidc/customization/sub")
    if sub.get("use_default") or sub.get("include_claim_keys") != exp["oidc_claim_keys"]:
        findings.append(f"OIDC の sub の形が決めた値と違う（{sub.get('include_claim_keys')}）")
    r = get(f"/repos/{repo}")
    if r.get("visibility") != exp["visibility"]:
        findings.append(f"リポジトリの公開の状態が決めた値（{exp['visibility']}）と違う")
    # 名前で引いたリポジトリが、決めた番号の物か（付け替えか、消した後の作り直しなら番号が違う。OIDC の sub も番号で縛る）。
    if "repository_id" in exp and (str(r.get("id")) != str(exp["repository_id"])
                                   or str((r.get("owner") or {}).get("id")) != str(exp["repository_owner_id"])):
        findings.append(f"名前 {repo} のリポジトリの番号が決めた値と違う（付け替えか作り直し）: {r.get('id')}")
    org = repo.split("/", 1)[0]
    if get(f"/orgs/{org}").get("members_can_create_repositories") is not False:
        findings.append("組織の一員がリポジトリを作れる（消した名前と付け替えた名前を取り直せる）")
    owner = repo.split("/")[0]
    for scope, path in (("リポジトリ", f"/repos/{repo}/actions/runners"), ("組織", f"/orgs/{owner}/actions/runners")):
        n = get(path).get("total_count", -1)
        if n != exp["self_hosted_runners"]:
            findings.append(f"{scope}の自前の走る機械が {n} 台（決めた数 {exp['self_hosted_runners']} 台）")


def pr_people(get, repo, sha):
    """commit を main に入れた PR の作者と、別の人の承認者。PR が無ければ None。"""
    for pr in get(f"/repos/{repo}/commits/{sha}/pulls"):
        if pr.get("merged_at") and pr.get("base", {}).get("ref") == "main":
            author = pr["user"]["login"]
            # 承認に数えるのは人だけ（user.type が User）。bot（github-actions[bot] など）の承認は数えない。
            ok = {r["user"]["login"] for r in get(f"/repos/{repo}/pulls/{pr['number']}/reviews")
                  if r.get("state") == "APPROVED" and r["user"].get("type", "User") == "User"}
            return author, ok - {author}
    return None


def check_main(get, exp, state, findings):
    """前回の先頭から今の先頭へ、履歴が続くか。間の commit が全部 PR を通ったか。新しい先頭を返す。"""
    repo = exp["repository"]
    head = get(f"/repos/{repo}/branches/main")["commit"]["sha"]
    prev = state.get("main_sha")
    if not prev:
        findings.append("前回の main の先頭の印が無い（最初の 1 回か、印を消された）")
        return head
    if prev == head:
        return head
    cmp = get(f"/repos/{repo}/compare/{prev}...{head}")
    if cmp.get("status") != "ahead":
        findings.append(f"main が前回の先頭 {prev[:12]} から続いていない（{cmp.get('status')}。force push のおそれ）")
    commits = cmp.get("commits", [])
    if cmp.get("total_commits", len(commits)) > len(commits):
        findings.append(f"前回からの commit が {cmp.get('total_commits')} 件で、確かめ切れない")
    for c in commits:
        people = pr_people(get, repo, c["sha"])
        if people is None:
            findings.append(f"PR を通らずに main へ入った commit: {c['sha'][:12]}")
        elif len(people[1]) < 2:
            findings.append(f"別の 2 人の承認が無い PR で入った commit: {c['sha'][:12]}")
    return head


def on_main(get, repo, sha):
    """sha が今の main から届くか（main の先祖か、同じか）。"""
    return get(f"/repos/{repo}/compare/{sha}...main").get("status") in ("ahead", "identical")


def check_commit(get, repo, sha, what, findings):
    """配った commit と、CI の役割を借りた実行の commit が、今の main にあり、別の 2 人の承認した PR を通ったか。"""
    if not on_main(get, repo, sha):
        findings.append(f"{what} の commit {sha[:12]} が今の main から届かない（押し込んで戻したおそれ）")
    people = pr_people(get, repo, sha)
    if people is None or len(people[1]) < 2:
        findings.append(f"{what} の commit {sha[:12]} が、別の 2 人の承認した PR を通っていない")


def check_deployments(get, exp, since, findings):
    repo = exp["repository"]
    owner = repo.split("/")[0]
    for env, team in exp["environments"].items():
        members = None
        for d in get(f"/repos/{repo}/deployments?environment={env}&per_page=100"):
            if d.get("created_at", "") < since:
                continue
            runs = {m for s in get(f"/repos/{repo}/deployments/{d['id']}/statuses")
                    for m in re.findall(r"/actions/runs/(\d+)", (s.get("log_url") or "") + (s.get("target_url") or ""))}
            approvers = {a["user"]["login"] for run in runs for a in get(f"/repos/{repo}/actions/runs/{run}/approvals")
                         if a.get("state") == "approved" and env in [e.get("name") for e in a.get("environments", [])]}
            if not approvers:
                findings.append(f"環境 {env} の承認の無い配備: {d['id']}（{d.get('sha', '')[:12]}）")
                continue
            if members is None:
                members = {m["login"] for m in get(f"/orgs/{owner}/teams/{team}/members?per_page=100")}
            if approvers - members:
                findings.append(f"環境 {env} の承認者が決めた team（{team}）の外: {sorted(approvers - members)}")
            check_commit(get, repo, d.get("sha", ""), f"環境 {env} の配備 {d['id']}", findings)
            if env.endswith("-guarded"):
                people = pr_people(get, repo, d.get("sha", ""))
                if people and approvers & ({people[0]} | people[1]):
                    findings.append(f"環境 {env} の承認者が、同じ commit の PR の作者か承認者と重なる: {sorted(approvers & ({people[0]} | people[1]))}")


def _workflow_path(sub):
    """sub（repo:…:job_workflow_ref:<owner>/<repo>/.github/workflows/x.yml@refs/heads/main）から workflow の file を引く。"""
    m = re.search(r"job_workflow_ref:[^/]+/[^/]+/(\.github/workflows/[^@]+)@", sub or "")
    return m.group(1) if m else None


def check_aws_runs(get, exp, since, trail, findings):
    """AWS の側で CI の役割が借りられたごとに、借り入れの名前の実行を GitHub で引いて照らす。"""
    repo = exp["repository"]
    used = set()
    for ev in trail:
        sub = (ev.get("userIdentity") or {}).get("userName", "")
        req = ev.get("requestParameters") or {}
        role = (req.get("roleArn") or "").rsplit("/", 1)[-1]
        at = ev.get("eventTime", "")
        if not sub.startswith("repo:"):
            findings.append(f"AWS で {role} が {at} に借りられたが、記録に GitHub の sub が無い（照らせない借り入れ）")
            continue
        if not sub.startswith(f"repo:{repo}:"):
            # 別のリポジトリの sub で借りた。信頼を書き換えて自分のリポジトリから借りる手を、黙って飛ばさずに鳴らす。
            findings.append(f"AWS で {role} が {at} に、別のリポジトリの sub（{sub[:80]}）で借りられた（信頼の書き換えのおそれ）")
            continue
        ids = f":repository_id:{exp['repository_id']}:repository_owner_id:{exp['repository_owner_id']}" if "repository_id" in exp else ""
        if ids and not sub.endswith(ids):
            # 番号の無い sub か、別の番号の sub。名前を付け替えるか作り直したリポジトリから借りた手を鳴らす（信頼の書き換えのおそれ）。
            findings.append(f"AWS で {role} が {at} に、決めた番号の無い sub で借りられた（作り直したリポジトリか、信頼の書き換え）")
            continue
        m = re.fullmatch(r"gh-(\d+)-(\d+)", req.get("roleSessionName") or "")
        if not m:
            findings.append(f"AWS で {role} が {at} に借りられたが、借り入れの名前に実行の番号が無い（{req.get('roleSessionName')}）")
            continue
        run_id, attempt = m.group(1), m.group(2)
        if (role, run_id, attempt) in used:
            findings.append(f"同じ実行 {run_id} の試み {attempt} で {role} を 2 回借りた（盗んだ札の使い回しのおそれ）")
            continue
        used.add((role, run_id, attempt))
        try:
            run = get(f"/repos/{repo}/actions/runs/{run_id}")
        except Exception:  # noqa: BLE001  消された実行は引けない
            run = {}
        path = _workflow_path(sub)
        # 再利用の workflow（第 15 回）: sub の job_workflow_ref は呼ばれた側、実行の path は呼んだ側になる。呼ばれた側が main の版で、
        # 実行の referenced_workflows に入っているときだけ、呼んだ側の path を受ける。PR から借りてよいのは決めた役割（検証環境の計画）だけで、
        # そのときは PR の実行（event が pull_request）であることを求め、commit が main から届くかは見ない（PR の commit なので）。
        called = f"{repo}/{path}@refs/heads/main"
        reused = bool(run) and run.get("path") != path and any(
            (w or {}).get("path") == called for w in (run.get("referenced_workflows") or []))
        from_pr = ":pull_request:" in sub
        if from_pr and not any(re.fullmatch(p, role) for p in exp.get("pr_roles", [])):
            findings.append(f"AWS で {role} が {at} に PR の sub で借りられた（PR から借りてよい役割の一覧の外）")
            continue
        branch_ok = (run.get("event") == "pull_request") if from_pr else (run.get("head_branch") == "main")
        if not run or not (run.get("path") == path or reused) or not branch_ok:
            findings.append(f"AWS で {role} が {at} に借りられたのに、GitHub に main の {path} の実行 {run_id} が無い（消されたおそれ）")
            continue
        if not from_pr:
            check_commit(get, repo, run.get("head_sha", ""), f"実行 {run_id}", findings)
        jobs = get(f"/repos/{repo}/actions/runs/{run_id}/attempts/{attempt}/jobs").get("jobs", [])
        hosted = [j for j in jobs if j.get("runner_group_name") == exp["hosted_runner_group"]]
        if len(hosted) != len(jobs) or not jobs:
            findings.append(f"実行 {run_id} の job が GitHub の機械の外で動いた（自前の走る機械のおそれ）")


def check_mgmt_summary(summary, findings):
    """管理の口座の IAM の数（第 15 回。信頼の根の「長く使える鍵を持たない」）。利用者 0、root の鍵 0、root の MFA 1 を求める。"""
    m = summary()
    if m.get("Users", 1) != 0:
        findings.append(f"管理の口座に IAM の利用者が {m.get('Users')} 人いる（長く使える鍵を置かない決めの外）")
    if m.get("AccountAccessKeysPresent", 1) != 0:
        findings.append("管理の口座の root にアクセスキーがある")
    if m.get("AccountMFAEnabled", 0) != 1:
        findings.append("管理の口座の root に MFA が無い")


def run(get, exp, now, state, trail, mgmt_summary=None):
    findings, new_state = [], dict(state)
    since = (now - datetime.timedelta(hours=HOURS)).strftime("%Y-%m-%dT%H:%M:%SZ")

    def main_step():
        new_state["main_sha"] = check_main(get, exp, state, findings)

    steps = (lambda: check_settings(get, exp, findings), main_step,
             lambda: check_deployments(get, exp, since, findings), lambda: check_aws_runs(get, exp, since, trail, findings))
    if mgmt_summary is not None:
        steps += (lambda: check_mgmt_summary(mgmt_summary, findings),)
    for step in steps:
        try:
            step()
        except Exception as e:  # noqa: BLE001  届かない、権限が無い、App を外された、形が違う。どれも黙って ok にしない
            findings.append(f"見張りが確かめ切れなかった: {type(e).__name__}: {e}"[:300])
    return {"kind": "github-watch", "status": "ng" if findings else "ok", "findings": findings}, new_state


def handler(event, context):  # pragma: no cover  守りの口座の Lambda の入口
    import boto3  # noqa: PLC0415

    import gh_app  # noqa: PLC0415

    env = os.environ
    with open(os.path.join(os.path.dirname(__file__), "github-expected.json"), encoding="utf-8") as f:
        exp = json.load(f)
    now = datetime.datetime.now(datetime.timezone.utc)
    ssm = boto3.client("ssm")
    state = json.loads(ssm.get_parameter(Name=env["STATE_PARAMETER"])["Parameter"]["Value"] or "{}")
    logs = boto3.client("logs")
    start = int((now - datetime.timedelta(hours=HOURS)).timestamp() * 1000)
    trail = []
    for page in logs.get_paginator("filter_log_events").paginate(
            logGroupName=env["ORG_TRAIL_LOG_GROUP"], startTime=start,
            filterPattern='{ ($.eventName = "AssumeRoleWithWebIdentity") && ($.userIdentity.identityProvider = "*token.actions.githubusercontent.com*") }'):
        trail += [json.loads(e["message"]) for e in page.get("events", [])]
    try:
        get = gh_app.getter(gh_app.app_token(env["APP_KEY_SECRET"], env["APP_ID"], env["APP_INSTALLATION_ID"]))
    except Exception as e:  # noqa: BLE001  App を外された、鍵が無い。ng で鳴らす
        print(json.dumps({"kind": "github-watch", "status": "ng", "findings": [f"GitHub App の札を作れない: {type(e).__name__}"]}, ensure_ascii=False))
        return {"status": "ng"}
    def mgmt_summary():
        # 管理の口座の数を読む役割を借りる。借りられない（消された、信頼を変えられた）ときは例外で ng になる。
        c = boto3.client("sts").assume_role(RoleArn=env["MGMT_SUMMARY_ROLE"], RoleSessionName="github-watch-summary")["Credentials"]
        iam = boto3.client("iam", aws_access_key_id=c["AccessKeyId"], aws_secret_access_key=c["SecretAccessKey"],
                           aws_session_token=c["SessionToken"])
        return iam.get_account_summary()["SummaryMap"]
    result, new_state = run(get, exp, now, state, trail, mgmt_summary)
    ssm.put_parameter(Name=env["STATE_PARAMETER"], Value=json.dumps(new_state), Overwrite=True)
    print(json.dumps(result, ensure_ascii=False))
    return {"status": result["status"]}


def selftest():
    now = datetime.datetime(2026, 11, 7, 12, 0, tzinfo=datetime.timezone.utc)
    owners = "/infra/ @example-org/security\n"
    a, b = "a" * 40, "b" * 40
    exp = {"repository": "o/r", "environments": {"prod": "deploy", "prod-guarded": "security"},
           "status_checks": [{"context": "infra-plan-run / plan-gate", "app_id": 15368}], "codeowners_sha256": hashlib.sha256(owners.encode()).hexdigest(),
           "pinned_actions": ["actions/checkout@" + "0" * 40], "oidc_claim_keys": ["repo", "context", "job_workflow_ref"],
           "visibility": "private", "self_hosted_runners": 0, "hosted_runner_group": "GitHub Actions", "pr_roles": ["orders-admin-stg-plan"],
           "repository_id": "100000001", "repository_owner_id": "100000002"}
    sub = "repo:o/r:environment:prod:job_workflow_ref:o/r/.github/workflows/static-deploy.yml@refs/heads/main:repository_id:100000001:repository_owner_id:100000002"
    trail_ok = [{"eventTime": "2026-11-07T11:30:00Z", "userIdentity": {"userName": sub},
                 "requestParameters": {"roleArn": "arn:aws:iam::111122223333:role/orders-admin-prod-ci-push-static", "roleSessionName": "gh-56-1"}}]

    def world(**over):
        env = lambda slug: {"protection_rules": [{"type": "required_reviewers", "prevent_self_review": True,  # noqa: E731
                                                  "reviewers": [{"reviewer": {"slug": slug}}]}],
                            "deployment_branch_policy": {"custom_branch_policies": True}, "can_admins_bypass": False}
        w = {
            "/repos/o/r/environments/prod": env("deploy"), "/repos/o/r/environments/prod-guarded": env("security"),
            "/repos/o/r/environments/prod/deployment-branch-policies": {"branch_policies": [{"name": "main"}]},
            "/repos/o/r/environments/prod-guarded/deployment-branch-policies": {"branch_policies": [{"name": "main"}]},
            "/repos/o/r/branches/main/protection": {
                "enforce_admins": {"enabled": True}, "required_signatures": {"enabled": True},
                "required_pull_request_reviews": {"required_approving_review_count": 2, "require_code_owner_reviews": True,
                                                  "dismiss_stale_reviews": True, "require_last_push_approval": True},
                "required_status_checks": {"contexts": ["infra-plan-run / plan-gate"],
                                           "checks": [{"context": "infra-plan-run / plan-gate", "app_id": 15368}]}},
            "/repos/o/r/contents/.github/CODEOWNERS?ref=main": {"content": base64.b64encode(owners.encode()).decode()},
            "/repos/o/r/actions/permissions": {"allowed_actions": "selected"},
            "/repos/o/r/actions/permissions/selected-actions": {"patterns_allowed": exp["pinned_actions"]},
            "/repos/o/r/actions/oidc/customization/sub": {"use_default": False, "include_claim_keys": exp["oidc_claim_keys"]},
            "/repos/o/r/actions/permissions/workflow": {"default_workflow_permissions": "read", "can_approve_pull_request_reviews": False},
            "/repos/o/r": {"visibility": "private", "id": 100000001, "owner": {"id": 100000002}},
            "/orgs/o": {"members_can_create_repositories": False},
            "/repos/o/r/actions/runners": {"total_count": 0}, "/orgs/o/actions/runners": {"total_count": 0},
            "/repos/o/r/branches/main": {"commit": {"sha": b}},
            f"/repos/o/r/compare/{a}...{b}": {"status": "ahead", "total_commits": 1, "commits": [{"sha": b}]},
            f"/repos/o/r/commits/{b}/pulls": [{"number": 7, "merged_at": "x", "base": {"ref": "main"}, "user": {"login": "dev"}}],
            "/repos/o/r/pulls/7/reviews": [{"state": "APPROVED", "user": {"login": "rev1"}}, {"state": "APPROVED", "user": {"login": "sec1"}}],
            "/repos/o/r/deployments?environment=prod&per_page=100": [],
            "/repos/o/r/deployments?environment=prod-guarded&per_page=100": [{"id": 9, "sha": b, "created_at": "2026-11-07T11:00:00Z"}],
            "/repos/o/r/deployments/9/statuses": [{"log_url": "https://github.com/o/r/actions/runs/55/job/1"}],
            "/repos/o/r/actions/runs/55/approvals": [{"state": "approved", "user": {"login": "sec2"}, "environments": [{"name": "prod-guarded"}]}],
            f"/repos/o/r/compare/{b}...main": {"status": "identical"},
            "/orgs/o/teams/security/members?per_page=100": [{"login": "sec2"}],
            "/repos/o/r/actions/runs/56": {"path": ".github/workflows/static-deploy.yml", "head_branch": "main", "head_sha": b},
            "/repos/o/r/actions/runs/56/attempts/1/jobs": {"jobs": [{"runner_group_name": "GitHub Actions"}]},
        }
        w.update(over)
        return lambda path: w[path]

    st = {"main_sha": a}
    cases = [
        ("全部が決めた値", world(), st, trail_ok, "ok", ""),
        ("-guarded の承認者に配備のチーム", world(**{"/repos/o/r/environments/prod-guarded": {"protection_rules": [{"type": "required_reviewers", "prevent_self_review": True, "reviewers": [{"reviewer": {"slug": "deploy"}}]}], "deployment_branch_policy": {"custom_branch_policies": True}}}), st, trail_ok, "ng", "承認者"),
        ("管理者が main の保護を越えられる", world(**{"/repos/o/r/branches/main/protection": {"enforce_admins": {"enabled": False}}}), st, trail_ok, "ng", "enforce_admins"),
        ("必須の検査が名前だけ（出どころの App を縛らない）", world(**{"/repos/o/r/branches/main/protection": {**world()("/repos/o/r/branches/main/protection"), "required_status_checks": {"contexts": ["infra-plan-run / plan-gate"], "checks": [{"context": "infra-plan-run / plan-gate", "app_id": None}]}}}), st, trail_ok, "ng", "status_checks"),
        ("PR を通らない commit", world(**{f"/repos/o/r/commits/{b}/pulls": []}), st, trail_ok, "ng", "PR を通らず"),
        ("force push で main を戻した", world(**{f"/repos/o/r/compare/{a}...{b}": {"status": "diverged", "total_commits": 0, "commits": []}}), st, trail_ok, "ng", "続いていない"),
        ("前回の印を消された", world(), {}, trail_ok, "ng", "印が無い"),
        ("承認の無い配備", world(**{"/repos/o/r/actions/runs/55/approvals": []}), st, trail_ok, "ng", "承認の無い配備"),
        ("PR の承認者が -guarded も承認", world(**{"/repos/o/r/actions/runs/55/approvals": [{"state": "approved", "user": {"login": "sec1"}, "environments": [{"name": "prod-guarded"}]}]}), st, trail_ok, "ng", "重なる"),
        ("持ち主の欄を書き換え", world(**{"/repos/o/r/contents/.github/CODEOWNERS?ref=main": {"content": base64.b64encode(b"* @o/deploy\n").decode()}}), st, trail_ok, "ng", "CODEOWNERS"),
        ("自前の走る機械を登録", world(**{"/repos/o/r/actions/runners": {"total_count": 1}}), st, trail_ok, "ng", "走る機械"),
        ("リポジトリを公開に変えた", world(**{"/repos/o/r": {"visibility": "public"}}), st, trail_ok, "ng", "公開の状態"),
        ("消した後に同じ名前で作り直したリポジトリ", world(**{"/repos/o/r": {"visibility": "private", "id": 200000009, "owner": {"id": 100000002}}}), st, trail_ok, "ng", "番号"),
        ("組織の一員がリポジトリを作れる", world(**{"/orgs/o": {"members_can_create_repositories": True}}), st, trail_ok, "ng", "一員がリポジトリを作れる"),
        ("AWS で借りたのに実行の記録が無い", world(**{"/repos/o/r/actions/runs/56": {}}), st, trail_ok, "ng", "実行 56 が無い"),
        ("環境で管理者が承認を越えられる", world(**{"/repos/o/r/environments/prod": {**world()("/repos/o/r/environments/prod"), "can_admins_bypass": True}}), st, trail_ok, "ng", "can_admins_bypass"),
        ("古い承認を残す（dismiss_stale_reviews なし）", world(**{"/repos/o/r/branches/main/protection": {**world()("/repos/o/r/branches/main/protection"), "required_pull_request_reviews": {"required_approving_review_count": 2, "require_code_owner_reviews": True, "require_last_push_approval": True}}}), st, trail_ok, "ng", "dismiss_stale_reviews"),
        ("押し込んで同じ SHA へ戻した配備", world(**{f"/repos/o/r/compare/{b}...main": {"status": "diverged"}}), st, trail_ok, "ng", "今の main から届かない"),
        ("承認者が決めた team の外", world(**{"/orgs/o/teams/security/members?per_page=100": [{"login": "other"}]}), st, trail_ok, "ng", "team"),
        ("sub の無い借り入れ", world(), st, [{**trail_ok[0], "userIdentity": {"userName": "x"}}], "ng", "sub が無い"),
        ("借り入れの名前に実行の番号が無い", world(), st, [{**trail_ok[0], "requestParameters": {"roleArn": "r/x", "roleSessionName": "GitHubActions"}}], "ng", "実行の番号が無い"),
        ("同じ実行で 2 回借りた", world(), st, trail_ok + trail_ok, "ng", "2 回借りた"),
        ("作り直した同じ名前のリポジトリの sub で借りた", world(), st, [{**trail_ok[0], "userIdentity": {"userName": sub.replace("100000001", "200000009")}}], "ng", "決めた番号の無い sub"),
        ("別のリポジトリの sub で借りた", world(), st, [{**trail_ok[0], "userIdentity": {"userName": "repo:evil/x:environment:prod"}}], "ng", "別のリポジトリ"),
        ("job が自前の走る機械で動いた", world(**{"/repos/o/r/actions/runs/56/attempts/1/jobs": {"jobs": [{"runner_group_name": "Default"}]}}), st, trail_ok, "ng", "GitHub の機械の外"),
        ("Actions に PR の承認を許した", world(**{"/repos/o/r/actions/permissions/workflow": {"default_workflow_permissions": "read", "can_approve_pull_request_reviews": True}}), st, trail_ok, "ng", "承認できる"),
        ("承認の 1 人が bot", world(**{"/repos/o/r/pulls/7/reviews": [{"state": "APPROVED", "user": {"login": "sec1", "type": "User"}}, {"state": "APPROVED", "user": {"login": "github-actions[bot]", "type": "Bot"}}]}), st, trail_ok, "ng", "別の 2 人の承認が無い"),
        ("API に届かない", lambda path: (_ for _ in ()).throw(OSError("unreachable")), st, trail_ok, "ng", "確かめ切れなかった"),
    ]
    # 第 15 回: 再利用の workflow（PR の検証環境の計画）と、管理の口座の IAM の数。
    pr_sub = "repo:o/r:pull_request:job_workflow_ref:o/r/.github/workflows/infra-plan-run.yml@refs/heads/main:repository_id:100000001:repository_owner_id:100000002"
    pr_trail = [{**trail_ok[0], "userIdentity": {"userName": pr_sub},
                 "requestParameters": {"roleArn": "arn:aws:iam::444455556666:role/orders-admin-stg-plan", "roleSessionName": "gh-57-1"}}]
    pr_run = {"/repos/o/r/actions/runs/57": {"path": ".github/workflows/infra-plan.yml", "head_branch": "feature-x", "event": "pull_request",
                                             "head_sha": "e" * 40, "referenced_workflows": [{"path": "o/r/.github/workflows/infra-plan-run.yml@refs/heads/main"}]},
              "/repos/o/r/actions/runs/57/attempts/1/jobs": {"jobs": [{"runner_group_name": "GitHub Actions"}]}}
    cases += [
        ("PR から main の再利用の計画を呼んだ（検証環境）", world(**pr_run), st, pr_trail, "ok", None),
        ("PR の実行が main の再利用の workflow を呼んでいない", world(**{**pr_run, "/repos/o/r/actions/runs/57": {**pr_run["/repos/o/r/actions/runs/57"], "referenced_workflows": []}}), st, pr_trail, "ng", "実行 57 が無い"),
        ("PR の sub で本番の適用の役割を借りた", world(**pr_run), st, [{**pr_trail[0], "requestParameters": {"roleArn": "arn:aws:iam::111122223333:role/orders-admin-prod-apply", "roleSessionName": "gh-57-1"}}], "ng", "一覧の外"),
        ("呼ばれた側が main でない再利用の workflow", world(**{**pr_run, "/repos/o/r/actions/runs/57": {**pr_run["/repos/o/r/actions/runs/57"], "referenced_workflows": [{"path": "o/r/.github/workflows/infra-plan-run.yml@refs/heads/feature-x"}]}}), st, pr_trail, "ng", "実行 57 が無い"),
    ]
    mg = [("管理の口座に IAM の利用者が 1 人", {"Users": 1, "AccountAccessKeysPresent": 0, "AccountMFAEnabled": 1}, "ng", "IAM の利用者"),
          ("管理の口座の root の鍵", {"Users": 0, "AccountAccessKeysPresent": 1, "AccountMFAEnabled": 1}, "ng", "アクセスキー"),
          ("管理の口座の数が決めのとおり", {"Users": 0, "AccountAccessKeysPresent": 0, "AccountMFAEnabled": 1}, "ok", None)]
    bad = 0
    for name, m, want, word in mg + [("管理の口座の数を読む役割を借りられない", None, "ng", "確かめ切れなかった")]:
        fn = (lambda m=m: m) if m is not None else (lambda: (_ for _ in ()).throw(PermissionError("AccessDenied")))
        got, _ = run(world(), exp, now, st, trail_ok, fn)
        ok = got["status"] == want and (not word or any(word in f for f in got["findings"]))
        bad += 0 if ok else 1
        print(f"{'PASS' if ok else 'FAIL'} github-watch {name}（期待 {want}、実際 {got['status']}）")
    for name, get, state, trail, want, word in cases:
        got, _ = run(get, exp, now, state, trail)
        ok = got["status"] == want and any(word in f for f in got["findings"]) if word else got["status"] == want
        bad += 0 if ok else 1
        print(f"{'PASS' if ok else 'FAIL'} github-watch {name}（期待 {want}、実際 {got['status']}）")
    total = len(cases) + len(mg) + 1
    print(f"RESULT: {'PASS' if bad == 0 else 'FAIL'} github-watch selftest ({total - bad}/{total})")
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    if sys.argv[1:2] == ["--selftest"]:
        sys.exit(selftest())
    print(__doc__.strip().splitlines()[-1], file=sys.stderr)
    sys.exit(2)
