"""出来事ごとの見張り（event-watch）。守りの口座の関数で、2 つの起点の出来事 1 件ごとに動く（security/event-watch.tf）。

状態が変わったときだけ鳴るアラームに頼らない。人の入りと GitHub の設定の変更は、出来事 1 件ごとに宛先へ送る。
  起点 1: 組織の CloudTrail の購読（作業の口座からは止められない）。人と信頼の根の入り（当番・緊急の管理の AssumeRoleWithSAML、
    守りの適用・土台・守りの口座の適用の役割の借り入れ、管理の口座の root とコンソールへの入り）。
    1 件ごとに、セキュリティの宛先（当番の外）へ送る。当番の入りは、作業の口座の障害の記録（アラームが ALARM になった出来事。
    作業の口座の規則が守りの口座のバスへ送り、ロググループ INCIDENT_LOG_GROUP に残る）と突き合わせ、前後 2 時間に記録が無ければ ng。
    送る記録は、当番を呼ぶ障害のアラームの一覧だけ（guardrails.tf の incident_alarms）。ok の便りにも照らした記録の名を載せ、
    セキュリティが「どの障害の入りか」を見分けられるようにする。
  起点 2: GitHub の監査ログの流し出し（守りの口座のバケットに届く file）。main の保護・規則・環境・自前の走る機械・公開の状態・
    実行の消去とやり直し・team の顔ぶれ・main への直の push の出来事を、1 件ごとに ng で送る（毎時の照らしの間に外して戻す手も鳴る）。
    やり直し（re-run）は、外した部品の入った古い作りを、もう一度成功させて配らせる手に使える。
  起点 1 の続き（第 14 回）: DB の管理者を使う作業は利用者づくり（db-bootstrap）の 1 本だけで、その起動（RunTask）を 1 件ごとに送る。
    移行と利用者づくりのイメージの押し込み（ECR の PutImage）は、押し込んだダイジェストの来歴と、像の中身を確かめる（第 15 回）。
    来歴: 主語は像のダイジェスト。署名者は信頼する再利用の workflow（attest-image.yml@refs/heads/main）の job だけで、呼んだ側は main の
      db-image-push.yml、走った機械は GitHub の機械（証明書の拡張 1.3.6.1.4.1.57264.1.11 が github-hosted）、リポジトリの番号は決めた値。
      押し込む job は来歴を書けない（attestations: write を持たない）。作る job が申告した file の指紋は使わない。
    中身: 守りの口座の関数が、自分の役割で像を取る（作業の口座の 2 つの DB の像のリポジトリの方針が、読むことだけを許す。app.tf）。
      層を自分で開いて比べる。土台の層は main の db/image-lock.json の固定の値と同じ。土台の上の file は、lock が並べる file
      （roles.sql、移行の入口と SQL）と同じ集まりで、どの file も今の main の file と同じ指紋。入口と利用者と環境変数（config）も lock と同じ。
      札の土台、入口の差し替え、足した file、緩めた roles.sql は、どれも ng になり、起動の承認の前に鳴る。
    第 16 回: 層の名前は頭の ./ か / を 1 回だけ外し、形の変わる名前・揃えた後に重なる名前・白抜き（.wh.）を ng にする（layer_files。
      前の lstrip('./') は .app/roles.sql を app/roles.sql と同じ鍵にした）。config は像の全部の欄を lock と比べる（Env を含む）。
      利用者づくりの起動も、起動した像を今の main に照らす（judge_db_admin）。15 分ごとに見張りの欠けを数え、欠けが 0 のときだけ便りを送る。
出力: 出来事ごとに {"kind": "entry"|"github-audit", "status": "ok"|"ng", ...} の 1 行。届いた file の数も "github-audit-file" で数える。
  AWS に届かないときは例外で落ち、Errors が鳴る。
使い方: python3 event_watch.py --selftest
"""
import base64
import datetime
import gzip
import json
import os
import posixpath
import sys

# GitHub の監査ログで、守りを外すか変える出来事。頭の一致で拾う（名前の型ごと。並べ忘れた細かい名前も拾う）。
GITHUB_ALERT_PREFIXES = (
    "protected_branch.", "repository_ruleset.", "environment.", "repo.register_self_hosted_runner",
    "org.register_self_hosted_runner", "enterprise.register_self_hosted_runner", "repo.access", "repo.transfer",
    "workflows.delete_workflow_run", "workflows.rerun", "repo.actions_enabled", "org.update_actions_settings", "repo.update_actions_settings",
    "integration_installation.", "team.add_member", "team.remove_member", "team.add_repository", "repo.add_member",
    "repo.update_member", "org.update_member", "org.add_member", "repo.change_merge_setting", "repo_actions_oidc",
    "org.actions_oidc", "org.audit_log_stream", "business.audit_log_stream",
    # リポジトリと組織の名前の付け替え、作成、削除（第 14 回）。OIDC の sub は番号まで名指しするが、名前の空きと作り直しは鳴らす。
    "repo.rename", "repo.create", "repo.destroy", "repo.archived", "repo.unarchived", "org.rename",
)
NAME_ACTIONS = ("repo.rename", "repo.create", "repo.destroy", "repo.transfer")
ENTRY_ROLES = ("AWSReservedSSO_orders-oncall-", "AWSReservedSSO_orders-breakglass-")


def github_findings(lines, repo):
    """監査ログの file の行（JSON）から、鳴らす出来事を返す。"""
    out = []
    for line in lines:
        if not line.strip():
            continue
        e = json.loads(line)
        action, where = e.get("action", ""), e.get("repo", "") or e.get("repository", "")
        # 名前の付け替え・作成・削除・移譲は、記録のリポジトリ名が新しい名前でも古い名前でも鳴らす（組織の中の全部を数える）。
        if where and where != repo and not action.startswith(("org.", "team.", "business.", "enterprise.", "integration_installation.")) \
                and action not in NAME_ACTIONS:
            continue
        if action.startswith(GITHUB_ALERT_PREFIXES):
            out.append(f"{action} by {e.get('actor', '不明')} on {where or e.get('org', '')}")
        elif action == "git.push" and e.get("ref") in ("refs/heads/main", "main"):
            out.append(f"main への直の push（force push を含む）by {e.get('actor', '不明')}")
    return out


def entry_of(rec):
    """記録 1 件が、人か信頼の根の入りなら、その種類を返す。"""
    p = rec.get("requestParameters") or {}
    role = p.get("roleArn") or ""
    name = rec.get("eventName", "")
    if name == "AssumeRoleWithSAML":
        for prefix in ENTRY_ROLES:
            if prefix in role:
                return "oncall" if "oncall" in prefix else "breakglass"
    # 管理の口座から借りる役割（OrganizationAccountAccessRole）は、どの口座でも信頼の根の使い方として送る（第 16 回）。
    if name.startswith("AssumeRole") and role.endswith(":role/OrganizationAccountAccessRole"):
        return "trust-root"
    if name.startswith("AssumeRole") and (role.endswith("-apply-guarded") or role.endswith(":role/platform-foundation")
                                          or role.endswith(":role/orders-guard-apply")):
        return "guarded-apply"
    if name == "RunTask" and "-db-bootstrap" in str(p.get("taskDefinition") or ""):
        return "db-admin"
    if name == "PutImage" and str(p.get("repositoryName") or "").endswith(("/db-bootstrap", "/db-migrate")):
        return "db-image"
    ut = (rec.get("userIdentity") or {}).get("type")
    if ut == "IAMUser":
        return "long-term-key"
    if ut == "Root" or name == "ConsoleLogin":
        return "trust-root"
    mgmt = os.environ.get("MANAGEMENT_ACCOUNT_ID", "")
    # 管理の口座の借り入れ（AssumeRole*）は readOnly の値によらず送る（第 16 回。STS の出来事が読むだけと記されても漏らさない）。
    if mgmt and rec.get("recipientAccountId") == mgmt and ut != "AWSService" and (rec.get("readOnly") is False or name == "AssumeRoot"
                                                                                  or name.startswith("AssumeRole")):
        return "trust-root"
    return None


ATTEST_WORKFLOW = ".github/workflows/attest-image.yml@refs/heads/main"
CALLER_WORKFLOW = ".github/workflows/db-image-push.yml@refs/heads/main"


def compare_image(view, lock, main_files):
    """像の中身を lock と main の file に照らす。view は {"layers": [層のダイジェスト], "config": {...}, "files": {像の中の道: sha256},
    "problems": [層を読むときに見つけた誤り]}（files は土台の上の層だけを数えた物。layer_files）。lock は db/image-lock.json の 1 つの像の項。
    main_files は {repo の道: sha256}（lock の files と dirs の下の、今の main の file の全部）。比べた結果の誤りの一覧を返す。
    第 16 回: config は lock の鍵だけでなく、像の config の全部の欄を比べる（Env を含む。lock に無い欄が像にあれば ng）。"""
    out = list(view.get("problems") or [])
    base = list(lock.get("base_layers") or [])
    if not base or view.get("layers", [])[:len(base)] != base:
        out.append("土台の層が lock の固定の値と違う（札で引いた土台か、差し替えた土台）")
    want_cfg, got_cfg = lock.get("config") or {}, view.get("config") or {}
    if "Env" not in want_cfg:
        out.append("lock の config に Env が無い（環境変数を照らせない）")
    for k in sorted(set(want_cfg) | set(got_cfg)):
        if got_cfg.get(k) != want_cfg.get(k):
            out.append(f"像の設定 {k} が lock と違う（入口・利用者・環境変数の差し替え）")
    expect = {img: main_files.get(src) for img, src in (lock.get("files") or {}).items()}
    for img_dir, src_dir in (lock.get("dirs") or {}).items():
        for path, sha in main_files.items():
            if path.startswith(src_dir):
                expect[img_dir + path[len(src_dir):]] = sha
    got = view.get("files") or {}
    for path in sorted(set(got) - set(expect)):
        out.append(f"lock に無い file が土台の上にある: {path}")
    for path in sorted(set(expect) - set(got)):
        out.append(f"lock の file が像に無い: {path}")
    for path in sorted(set(expect) & set(got)):
        if expect[path] is None or got[path] != expect[path]:
            out.append(f"file が今の main と違う: {path}")
    return out


def norm_member(name):
    """層の tar の名前を 1 つの形に揃える。頭の ./ か / を 1 回だけ外す。形の変わる名前は (None, 理由) を返す。"""
    raw = name
    if name.startswith("./"):
        name = name[2:]
    elif name.startswith("/"):
        name = name[1:]
    name = name.rstrip("/") if name.endswith("/") and name.count("/") >= 1 else name
    if not name or name in (".", ".."):
        return None, f"空か点だけの名前: {raw!r}"
    parts = name.split("/")
    if any(p in ("", ".", "..") for p in parts) or posixpath.normpath(name) != name:
        return None, f"形の変わる名前（.. や // や ./ を含む）: {raw!r}"
    return name, None


def layer_files(layer_tars):
    """土台の上の層（tar の bytes の並び）を開き、{道: sha256} と誤りの一覧を返す。展開と同じ順で後の層が前の層を上書きする。
    名前は norm_member で揃え、形の変わる名前、1 つの層の中で揃えた後に重なる名前、白抜き（.wh. と .wh..wh..opq。土台の file を消す）は
    どれも誤りにする（第 16 回。前の lstrip('./') は .app/roles.sql を app/roles.sql と同じ鍵にし、後の行が前の指紋を上書きした）。"""
    import hashlib  # noqa: PLC0415
    import io  # noqa: PLC0415
    import tarfile  # noqa: PLC0415
    files, problems = {}, []
    for n, data in enumerate(layer_tars):
        seen = set()
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:*") as t:
            for m in t.getmembers():
                name, why = norm_member(m.name)
                if why:
                    problems.append(f"層 {n}: {why}")
                    continue
                if name in seen:
                    problems.append(f"層 {n}: 揃えた後に重なる名前: {m.name!r}")
                    continue
                seen.add(name)
                leaf = name.rsplit("/", 1)[-1]
                if leaf.startswith(".wh."):
                    problems.append(f"層 {n}: 白抜き（土台の file を消す印）: {m.name!r}")
                elif m.isfile():
                    files[name] = hashlib.sha256(t.extractfile(m).read()).hexdigest()
                elif not m.isdir():
                    files[name] = "link:" + m.linkname  # リンクと特別な file は、lock に無いので ng になる
    return files, problems


def task_image(rec):
    """RunTask の記録から、起動した像の (リポジトリの名, ダイジェスト) を返す。分からなければ (None, None)。"""
    for task in ((rec.get("responseElements") or {}).get("tasks") or []):
        for c in task.get("containers") or []:
            img = str(c.get("image") or "")
            if "@sha256:" in img:
                repo_url, digest = img.split("@", 1)
                return repo_url.split("/", 1)[-1], digest
    return None, None


def judge_db_image(rec, provenance, image_problems):
    """移行と利用者づくりのイメージの押し込み 1 件の判定。provenance(digest) は、確かめた来歴の
    {"signer", "build_config", "runner", "subject"}（主語の sha256 の一覧）か None を返す。image_problems(repo, digest) は
    像の中身を lock と main に照らした誤りの一覧を返す（compare_image。第 3 引数は押し込みの口座）。"""
    p = rec.get("requestParameters") or {}
    image = ((rec.get("responseElements") or {}).get("image") or {}).get("imageId") or {}
    digest = image.get("imageDigest") or p.get("imageDigest") or ""
    repo = str(p.get("repositoryName") or "")
    findings = []
    if rec.get("errorCode"):
        return None
    st = provenance(digest) if digest else None
    if not st:
        findings.append(f"来歴の無いイメージの押し込み: {repo}@{digest or '不明'}（信頼する再利用の workflow の来歴でない）")
    else:
        if not str(st.get("signer", "")).endswith("/" + ATTEST_WORKFLOW):
            findings.append(f"来歴の署名者が attest-image.yml の job でない: {st.get('signer')}")
        if not str(st.get("build_config", "")).endswith("/" + CALLER_WORKFLOW):
            findings.append(f"来歴を呼んだ workflow が main の db-image-push.yml でない: {st.get('build_config')}")
        if st.get("runner") != "github-hosted":
            findings.append(f"来歴の作りが GitHub の機械の外: {st.get('runner')}")
        if digest.split(":")[-1] not in (st.get("subject") or []):
            findings.append("来歴の主語が押し込んだ像のダイジェストでない")
    if digest:
        findings += [f"{repo}@{digest}: {f}" for f in image_problems(repo, digest, str(rec.get("recipientAccountId") or ""))]
    return {"kind": "entry", "entry": "db-image", "status": "ng" if findings else "ok", "account": rec.get("recipientAccountId"),
            "who": ((rec.get("userIdentity") or {}).get("sessionContext") or {}).get("sessionIssuer", {}).get("userName", "不明"),
            "at": rec.get("eventTime"), "records": [], "findings": findings}


def judge_db_admin(rec, provenance, image_problems):
    """利用者づくりの起動 1 件の判定（第 16 回）。起動した像のダイジェストを記録から引き、来歴と中身を今の main に照らす。
    ダイジェストを 1 つ前の像へ戻した PR（古い版も当時の正しい来歴を持つ）は、古い roles.sql が今の main と違うので ng になる。
    起動の上書き（命令、入口、環境変数）も ng にする。"""
    if rec.get("errorCode"):
        return None
    findings = []
    repo, digest = task_image(rec)
    if not digest:
        findings.append("起動した像のダイジェストが記録から引けない（札の像か、記録の形の外）")
    else:
        if not provenance(digest):
            findings.append(f"来歴の無い像の起動: {repo}@{digest}")
        findings += [f"{repo}@{digest}: {f}" for f in image_problems(repo, digest, str(rec.get("recipientAccountId") or ""))]
    for o in (((rec.get("requestParameters") or {}).get("overrides") or {}).get("containerOverrides") or []):
        if any(o.get(k) for k in ("command", "environment", "environmentFiles", "entryPoint")):
            findings.append("起動の上書き（命令か環境変数）")
    who = ((rec.get("userIdentity") or {}).get("sessionContext") or {}).get("sessionIssuer", {}).get("userName", "不明")
    return {"kind": "entry", "entry": "db-admin", "status": "ng" if findings else "ok", "account": rec.get("recipientAccountId"),
            "who": who, "at": rec.get("eventTime"), "records": [], "findings": findings}


def judge_entry(rec, incidents, db_checks=None):
    """入り 1 件の判定。当番の入りは、前後 2 時間の障害の記録が無ければ ng。incidents(account, t) は記録の名の一覧を返す。"""
    kind = entry_of(rec)
    if kind is None:
        return None
    if kind == "db-image":
        return judge_db_image(rec, *(db_checks or (lambda d: None, lambda r, d, a: ["像を確かめる仕組みが無い"])))
    if kind == "db-admin":
        return judge_db_admin(rec, *(db_checks or (lambda d: None, lambda r, d, a: ["像を確かめる仕組みが無い"])))
    at = datetime.datetime.strptime(rec["eventTime"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.timezone.utc)
    who = ((rec.get("userIdentity") or {}).get("userName") or (rec.get("userIdentity") or {}).get("principalId") or "不明")
    findings, records = [], []
    if kind == "oncall":
        records = sorted(set(incidents(rec.get("recipientAccountId", ""), at)))
        if not records:
            findings.append(f"障害の記録の無い当番の入り: {who} {rec['eventTime']}")
    if kind == "long-term-key":
        # 長く使える鍵は置かない決め（信頼の根の節）。使われた時点で、どの口座でも ng にする。
        findings.append(f"IAM の利用者の長く使える鍵で動いた: {who} {rec.get('eventName')} {rec['eventTime']}")
    return {"kind": "entry", "entry": kind, "status": "ng" if findings else "ok", "account": rec.get("recipientAccountId"),
            "who": who, "at": rec["eventTime"], "records": records[:10], "findings": findings}


def db_image_checks(env):  # pragma: no cover  来歴は GitHub の来歴の API と層の sigstore、中身は ECR の読むだけの役割で確かめる
    import hashlib  # noqa: PLC0415

    import gh_app  # noqa: PLC0415
    from static_watch import verify_bundle  # noqa: PLC0415
    token = gh_app.app_token(env["APP_KEY_SECRET"], env["APP_ID"], env["APP_INSTALLATION_ID"])
    get, repo = gh_app.getter(token), env["REPOSITORY"]
    signer = f"https://github.com/{repo}/{ATTEST_WORKFLOW}"
    ids = (env["REPOSITORY_ID"], env["REPOSITORY_OWNER_ID"])

    def provenance(digest):
        for a in get(f"/repos/{repo}/attestations/{digest}").get("attestations", []):
            st = verify_bundle(a["bundle"], signer)
            if st and tuple(st.get("_repo_ids") or ()) == ids:
                return {"signer": st.get("_signer"), "build_config": st.get("_build_config"), "runner": st.get("_runner"),
                        "subject": [(x.get("digest") or {}).get("sha256") for x in st.get("subject", [])]}
        return None

    def main_file(path):
        c = get(f"/repos/{repo}/contents/{path}?ref=main")
        return hashlib.sha256(base64.b64decode(c.get("content", ""))).hexdigest()

    def image_problems(repo_name, digest, account):
        lock_all = json.loads(base64.b64decode(get(f"/repos/{repo}/contents/{env.get('IMAGE_LOCK_PATH', 'infra/db/image-lock.json')}?ref=main")
                                               .get("content", "")))
        lock = lock_all.get(repo_name.split("/")[-1])
        if not lock:
            return ["lock に無い像のリポジトリ"]
        files = {src: main_file(src) for src in (lock.get("files") or {}).values()}
        for src_dir in (lock.get("dirs") or {}).values():
            for item in get(f"/repos/{repo}/contents/{src_dir.rstrip('/')}?ref=main"):
                if item.get("type") == "file":
                    files[item["path"]] = main_file(item["path"])
        view = ecr_image_view(env, account, repo_name, digest, len(lock.get("base_layers") or []))
        return compare_image(view, lock, files)
    return provenance, image_problems


def ecr_image_view(env, account, repo_name, digest, skip):  # pragma: no cover  作業の口座の読むだけの役割で、像の層を自分で開く
    """像の manifest と config と、土台（前から skip 個の層）の上の層の file を返す。層の読み方は layer_files（自己試験で回す）。"""
    import urllib.request  # noqa: PLC0415

    import boto3  # noqa: PLC0415
    if account not in env["WORKLOAD_ACCOUNTS"].split(","):  # 作業の口座の番号の一覧。ほかの口座の像は読まない
        raise ValueError(f"作業の口座の外の押し込み: {account}")
    owner = account
    # 作業の口座の役割は借りない。像のリポジトリの方針が、この関数の役割（orders-guard-event-watch）に読むことだけを許す（app.tf）。
    # 作業の口座の SCP の名指しの主体の一覧に、守りの口座の役割を足さずに済む（静的な画面のバケットの照らしと同じ形）。
    ecr = boto3.client("ecr")
    types = ["application/vnd.oci.image.manifest.v1+json", "application/vnd.docker.distribution.manifest.v2+json"]
    img = ecr.batch_get_image(registryId=owner, repositoryName=repo_name, imageIds=[{"imageDigest": digest}], acceptedMediaTypes=types)
    manifest = json.loads(img["images"][0]["imageManifest"])

    def blob(d):
        url = ecr.get_download_url_for_layer(registryId=owner, repositoryName=repo_name, layerDigest=d)["downloadUrl"]
        with urllib.request.urlopen(url, timeout=60) as r:  # noqa: S310  ECR の層の置き場（期限つきの URL）
            return r.read()
    config = json.loads(blob(manifest["config"]["digest"])).get("config") or {}
    layers = [x["digest"] for x in manifest.get("layers", [])]
    files, problems = layer_files([blob(d) for d in layers[skip:]])
    # config は全部の欄を返す（Env、ExposedPorts、Volumes、StopSignal、Labels、Healthcheck、OnBuild も lock と比べる）。
    return {"layers": layers, "config": {k: v for k, v in config.items() if v not in (None, {}, [])}, "files": files, "problems": problems}


def guard_heartbeat(state, expected):
    """守りの口座の見張りの欠けを数える（第 16 回。15 分ごと）。欠けが 0 のときだけ、AWS の外の受け手へ便りを送る。
    state は {"alarms": {名: {"actions_enabled": bool, "alarm_actions": [ARN]}}, "metric_filters": [名], "topics": {名: 確かめた購読の数},
    "subscription_filters": [名]}。expected は functions/guard-expected.json。欠けの一覧を返す（空なら便りを送ってよい）。"""
    out = []
    for name in expected.get("alarms", []):
        a = (state.get("alarms") or {}).get(name)
        if a is None:
            out.append(f"アラームが無い: {name}")
            continue
        if not a.get("actions_enabled"):
            out.append(f"アラームの通知が止まっている: {name}")
        topics = [str(x).rsplit(":", 1)[-1] for x in a.get("alarm_actions") or []]
        if not set(expected.get("alarm_topics", [])) & set(topics):
            out.append(f"アラームの宛先が決めた話題でない: {name} {topics}")
    for name in expected.get("metric_filters", []):
        if name not in (state.get("metric_filters") or []):
            out.append(f"メトリクスフィルタが無い: {name}")
    for name in expected.get("subscription_filters", []):
        if name not in (state.get("subscription_filters") or []):
            out.append(f"記録の購読が無い: {name}")
    for name, want in (expected.get("topics") or {}).items():
        got = (state.get("topics") or {}).get(name)
        if got is None:
            out.append(f"話題が無い: {name}")
        elif got < want:
            out.append(f"話題の確かめた購読が足りない: {name}（{got} < {want}）")
    return out


def guard_state(env, expected):  # pragma: no cover  守りの口座の見張りの今の形を、読むだけの呼び出しで数える
    import boto3  # noqa: PLC0415
    cw, logs, sns = boto3.client("cloudwatch"), boto3.client("logs"), boto3.client("sns")
    alarms = {}
    for page in cw.get_paginator("describe_alarms").paginate(AlarmNamePrefix=env["NAME_PREFIX"]):
        for a in page.get("MetricAlarms", []):
            alarms[a["AlarmName"]] = {"actions_enabled": a.get("ActionsEnabled"), "alarm_actions": a.get("AlarmActions", [])}
    filters = [f["filterName"] for page in logs.get_paginator("describe_metric_filters").paginate() for f in page.get("metricFilters", [])]
    subs = [f["filterName"] for f in logs.describe_subscription_filters(logGroupName=env["ORG_TRAIL_LOG_GROUP"]).get("subscriptionFilters", [])]
    topics = {}
    for page in sns.get_paginator("list_topics").paginate():
        for t in page.get("Topics", []):
            arn = t["TopicArn"]
            if arn.rsplit(":", 1)[-1] not in (expected.get("topics") or {}):
                continue
            # 確かめた購読だけを数える（確かめ待ちの購読の ARN は PendingConfirmation）。
            n = sum(1 for x in sns.list_subscriptions_by_topic(TopicArn=arn).get("Subscriptions", [])
                    if x.get("SubscriptionArn", "").startswith("arn:"))
            topics[arn.rsplit(":", 1)[-1]] = n
    return {"alarms": alarms, "metric_filters": filters, "topics": topics, "subscription_filters": subs}


def handler(event, context):  # pragma: no cover  守りの口座の Lambda の入口
    import boto3  # noqa: PLC0415

    env = os.environ
    sns = boto3.client("sns")
    if event.get("kind") == "guard-heartbeat":
        # 15 分ごとの便り。欠けが 0 のときだけ、2 つの話題（その先は AWS の外の受け手。security/heartbeat-receiver.json）へ送る。
        # 欠けがあれば送らない。受け手は 20 分便りが無ければ、セキュリティと SRE を呼ぶ。管理の口座が SCP を外して見張りを消しても、ここで鳴る。
        here = os.path.dirname(os.path.abspath(__file__))
        with open(os.path.join(here, "guard-expected.json"), encoding="utf-8") as f:
            expected = json.load(f)
        missing = guard_heartbeat(guard_state(env, expected), expected)
        print(json.dumps({"kind": "guard-heartbeat", "status": "ng" if missing else "ok", "missing": missing[:20]}, ensure_ascii=False))
        if not missing:
            for topic in (env["SECURITY_TOPIC"], env["WATCH_TOPIC"]):
                sns.publish(TopicArn=topic, Subject="orders-guard heartbeat ok", Message=json.dumps({"kind": "orders-guard-heartbeat", "status": "ok"}))
        return
    if "awslogs" in event:
        logs = boto3.client("logs")

        def incidents(account, at):
            start = int((at - datetime.timedelta(hours=2)).timestamp() * 1000)
            end = int((at + datetime.timedelta(minutes=10)).timestamp() * 1000)
            resp = logs.filter_log_events(logGroupName=env["INCIDENT_LOG_GROUP"], startTime=start, endTime=end,
                                          filterPattern=f'{{ $.account = "{account}" }}', limit=20)
            return [(json.loads(e["message"]).get("detail") or {}).get("alarmName", "不明") for e in resp.get("events", [])]
        data = json.loads(gzip.decompress(base64.b64decode(event["awslogs"]["data"])))
        for e in data.get("logEvents", []):
            result = judge_entry(json.loads(e["message"]), incidents, db_image_checks(env))
            if result is None:
                continue
            print(json.dumps(result, ensure_ascii=False))
            sns.publish(TopicArn=env["SECURITY_TOPIC"], Subject=f"orders-guard {result['entry']} {result['status']}",
                        Message=json.dumps(result, ensure_ascii=False))
        return
    s3 = boto3.client("s3")
    for r in event.get("Records", []):
        obj = s3.get_object(Bucket=r["s3"]["bucket"]["name"], Key=r["s3"]["object"]["key"])["Body"].read()
        text = gzip.decompress(obj).decode() if obj[:2] == b"\x1f\x8b" else obj.decode()
        findings = github_findings(text.splitlines(), env["REPOSITORY"])
        print(json.dumps({"kind": "github-audit-file", "status": "ok"}))
        for f in findings:
            msg = {"kind": "github-audit", "status": "ng", "findings": [f]}
            print(json.dumps(msg, ensure_ascii=False))
            for topic in (env["SECURITY_TOPIC"], env["WATCH_TOPIC"]):
                sns.publish(TopicArn=topic, Subject="orders-guard github-audit ng", Message=json.dumps(msg, ensure_ascii=False))


def selftest():
    os.environ.setdefault("MANAGEMENT_ACCOUNT_ID", "999988887777")
    repo = "o/r"
    gh = [
        ("保護を外した", {"action": "protected_branch.update_admin_enforced", "repo": repo, "actor": "adm"}, 1),
        ("環境の承認者を替えた", {"action": "environment.update_protection_rule", "repo": repo}, 1),
        ("自前の走る機械を登録", {"action": "repo.register_self_hosted_runner", "repo": repo}, 1),
        ("main へ直に push", {"action": "git.push", "repo": repo, "ref": "refs/heads/main"}, 1),
        ("実行の記録を消した", {"action": "workflows.delete_workflow_run", "repo": repo}, 1),
        ("公開の状態を変えた", {"action": "repo.access", "repo": repo}, 1),
        ("承認の team に人を足した", {"action": "team.add_member", "org": "o"}, 1),
        ("流し出しを止めた", {"action": "org.audit_log_stream_destroy", "org": "o"}, 1),
        ("古い実行をやり直した", {"action": "workflows.rerun_workflow_run", "repo": repo}, 1),
        ("リポジトリの名前を付け替えた", {"action": "repo.rename", "repo": repo}, 1),
        ("付け替えた後の新しい名前の記録", {"action": "repo.rename", "repo": "o/r-old"}, 1),
        ("同じ名前のリポジトリを作った", {"action": "repo.create", "repo": repo}, 1),
        ("リポジトリを消した", {"action": "repo.destroy", "repo": repo}, 1),
        ("組織の名前を付け替えた", {"action": "org.rename", "org": "o"}, 1),
        ("別のブランチへの push", {"action": "git.push", "repo": repo, "ref": "refs/heads/feature"}, 0),
        ("ふだんの実行の終わり", {"action": "workflows.completed_workflow_run", "repo": repo}, 0),
        ("別のリポジトリの保護", {"action": "protected_branch.destroy", "repo": "o/other"}, 0),
    ]
    bad = 0
    for name, ev, want in gh:
        got = github_findings([json.dumps(ev)], repo)
        ok = len(got) == want
        bad += 0 if ok else 1
        print(f"{'PASS' if ok else 'FAIL'} event-watch GitHub {name}（期待 {want} 件、実際 {len(got)} 件）")
    oncall = {"eventName": "AssumeRoleWithSAML", "eventTime": "2026-11-07T03:00:00Z", "recipientAccountId": "111122223333",
              "requestParameters": {"roleArn": "arn:aws:iam::111122223333:role/aws-reserved/sso.amazonaws.com/AWSReservedSSO_orders-oncall-prod_0123456789abcdef"},
              "userIdentity": {"userName": "taro"}}
    entries = [
        ("障害の記録のある当番の入り", oncall, lambda a, t: ["orders-admin-prod-api-5xx"], "ok"),
        ("障害の記録の無い当番の入り", oncall, lambda a, t: [], "ng"),
        ("緊急の管理の入り（毎回送る）", {**oncall, "requestParameters": {"roleArn": "x/AWSReservedSSO_orders-breakglass-prod_0123456789abcdef"}}, lambda a, t: [], "ok"),
        ("守りの口座の適用の役割", {**oncall, "eventName": "AssumeRoleWithWebIdentity", "requestParameters": {"roleArn": "arn:aws:iam::777766665555:role/orders-guard-apply"}}, lambda a, t: [], "ok"),
        ("管理の口座から OrganizationAccountAccessRole を借りた（毎回送る）", {**oncall, "eventName": "AssumeRole", "readOnly": True, "recipientAccountId": "777766665555",
                                                                    "requestParameters": {"roleArn": "arn:aws:iam::777766665555:role/OrganizationAccountAccessRole"}}, lambda a, t: [], "ok"),
        ("管理の口座の人が役割を借りた（readOnly が真でも送る）", {**oncall, "eventName": "AssumeRole", "readOnly": True, "recipientAccountId": "999988887777",
                                                     "userIdentity": {"type": "AssumedRole"}, "requestParameters": {"roleArn": "arn:aws:iam::777766665555:role/x"}}, lambda a, t: [], "ok"),
        ("関係の無い借り入れ", {**oncall, "eventName": "AssumeRole", "requestParameters": {"roleArn": "arn:aws:iam::111122223333:role/orders-admin-prod-plan"}}, lambda a, t: [], None),
        # 第 15 回: 管理の口座の長く使える鍵、StackSet の書き換え、AssumeRoot。
        ("管理の口座の IAM の利用者の鍵で StackSet を書き換えた", {**oncall, "eventName": "UpdateStackSet", "recipientAccountId": "999988887777", "readOnly": False,
                                                  "userIdentity": {"type": "IAMUser", "userName": "old-admin"}, "requestParameters": {}}, lambda a, t: [], "ng"),
        ("作業の口座の IAM の利用者の鍵で読んだ", {**oncall, "eventName": "DescribeInstances", "readOnly": True,
                                          "userIdentity": {"type": "IAMUser", "userName": "x"}, "requestParameters": {}}, lambda a, t: [], "ng"),
        ("管理の口座で芯の購読を外した（毎回送る）", {**oncall, "eventName": "Unsubscribe", "recipientAccountId": "999988887777", "readOnly": False,
                                            "userIdentity": {"type": "AssumedRole", "principalId": "AROA:admin"}, "requestParameters": {}}, lambda a, t: [], "ok"),
        ("管理の口座で root の一時の資格を借りた（毎回送る）", {**oncall, "eventName": "AssumeRoot", "recipientAccountId": "999988887777", "readOnly": True,
                                                 "userIdentity": {"type": "AssumedRole"}, "requestParameters": {}}, lambda a, t: [], "ok"),
        ("管理の口座の読むだけの出来事", {**oncall, "eventName": "DescribeStackSet", "recipientAccountId": "999988887777", "readOnly": True,
                                    "userIdentity": {"type": "AssumedRole"}, "requestParameters": {}}, lambda a, t: [], None),
        ("管理の口座の AWS のサービスの書き込み", {**oncall, "eventName": "CreateStackInstances", "recipientAccountId": "999988887777", "readOnly": False,
                                          "userIdentity": {"type": "AWSService"}, "requestParameters": {}}, lambda a, t: [], None),
    ]
    for name, rec, inc, want in entries:
        got = judge_entry(rec, inc)
        status = got["status"] if got else None
        ok = status == want and (not got or got["entry"] != "oncall" or status != "ok" or got["records"])
        bad += 0 if ok else 1
        print(f"{'PASS' if ok else 'FAIL'} event-watch 入り {name}（期待 {want}、実際 {status}）")
    d = "sha256:" + "d" * 64
    sig = "https://github.com/o/r/" + ATTEST_WORKFLOW
    cfg = "https://github.com/o/r/" + CALLER_WORKFLOW
    good_prov = {"signer": sig, "build_config": cfg, "runner": "github-hosted", "subject": ["d" * 64]}
    push = {"eventName": "PutImage", "eventTime": "2026-11-07T03:00:00Z", "recipientAccountId": "111122223333",
            "requestParameters": {"repositoryName": "orders-admin-prod/db-bootstrap"},
            "responseElements": {"image": {"imageId": {"imageDigest": d}}}}
    lock = {"base_layers": ["sha256:b1", "sha256:b2"], "files": {"app/roles.sql": "infra/db/roles.sql"},
            "config": {"Entrypoint": ["/bin/sh", "-c", "psql -f /app/roles.sql"], "User": "10001", "Env": ["PATH=/usr/bin"]}}
    mlock = {"base_layers": ["sha256:b1"], "files": {"app/migrate-run.sh": "infra/db/migrate-run.sh"},
             "dirs": {"migrations/": "infra/db/migrations/"}, "config": {"Entrypoint": ["/app/migrate-run.sh"], "Env": ["PATH=/usr/bin"]}}
    main = {"infra/db/roles.sql": "a" * 64, "infra/db/migrate-run.sh": "e" * 64, "infra/db/migrations/0001.sql": "f" * 64}
    view = {"layers": ["sha256:b1", "sha256:b2", "sha256:top"], "config": dict(lock["config"]), "files": {"app/roles.sql": "a" * 64}}
    mview = {"layers": ["sha256:b1", "sha256:top"], "config": dict(mlock["config"]),
             "files": {"app/migrate-run.sh": "e" * 64, "migrations/0001.sql": "f" * 64}}

    def probe(v, lk=lock):
        return lambda r, x, a: compare_image(v, lk, main)
    images = [
        ("来歴と中身が lock と main に合う押し込み", push, lambda x: good_prov, probe(view), "ok"),
        ("来歴の無い差し替えた像", push, lambda x: None, probe(view), "ng"),
        ("roles.sql を書き換えた像（来歴はある）", push, lambda x: good_prov, probe({**view, "files": {"app/roles.sql": "b" * 64}}), "ng"),
        ("札で引いた悪い土台（土台の層が違う）", push, lambda x: good_prov, probe({**view, "layers": ["sha256:evil", "sha256:b2", "sha256:top"]}), "ng"),
        ("土台の上に入口の script を足した像", push, lambda x: good_prov, probe({**view, "files": {**view["files"], "app/entry.sh": "c" * 64}}), "ng"),
        ("入口（Entrypoint）を差し替えた像", push, lambda x: good_prov, probe({**view, "config": {**view["config"], "Entrypoint": ["/bin/sh", "-c", "psql -c 'ALTER POLICY'"]}}), "ng"),
        ("押し込む job が自分で署名した来歴（署名者が attest-image.yml でない）", push,
         lambda x: {**good_prov, "signer": "https://github.com/o/r/.github/workflows/db-image-push.yml@refs/heads/main"}, probe(view), "ng"),
        ("自前の機械で作った来歴", push, lambda x: {**good_prov, "runner": "self-hosted"}, probe(view), "ng"),
        ("別の workflow から呼んだ来歴", push, lambda x: {**good_prov, "build_config": "https://github.com/o/r/.github/workflows/x.yml@refs/heads/main"}, probe(view), "ng"),
        ("主語が別のダイジェストの来歴", push, lambda x: {**good_prov, "subject": ["e" * 64]}, probe(view), "ng"),
        ("移行の像が lock と main に合う", {**push, "requestParameters": {"repositoryName": "orders-admin-prod/db-migrate"}}, lambda x: good_prov, probe(mview, mlock), "ok"),
        ("移行の入口を書き換えた像", {**push, "requestParameters": {"repositoryName": "orders-admin-prod/db-migrate"}}, lambda x: good_prov,
         probe({**mview, "files": {**mview["files"], "app/migrate-run.sh": "0" * 64}}, mlock), "ng"),
        ("環境変数を足した像（PGOPTIONS）", push, lambda x: good_prov, probe({**view, "config": {**view["config"], "Env": ["PATH=/usr/bin", "PGOPTIONS=-c row_security=off"]}}), "ng"),
        ("lock に無い設定の欄を足した像（Healthcheck）", push, lambda x: good_prov, probe({**view, "config": {**view["config"], "Healthcheck": {"Test": ["CMD", "x"]}}}), "ng"),
        ("lock に Env の無い lock で照らした像", push, lambda x: good_prov,
         probe({**view, "config": {k: v for k, v in view["config"].items() if k != "Env"}}, {**lock, "config": {k: v for k, v in lock["config"].items() if k != "Env"}}), "ng"),
        ("移行の SQL を足した像（main に無い）", {**push, "requestParameters": {"repositoryName": "orders-admin-prod/db-migrate"}}, lambda x: good_prov,
         probe({**mview, "files": {**mview["files"], "migrations/0002.sql": "9" * 64}}, mlock), "ng"),
    ]
    for name, rec, prov, img, want in images:
        got = judge_entry(rec, lambda a, t: [], (prov, img))
        status = got["status"] if got else None
        ok = status == want
        bad += 0 if ok else 1
        print(f"{'PASS' if ok else 'FAIL'} event-watch 像 {name}（期待 {want}、実際 {status}）")
    # 第 16 回: 層の tar を実際に作って読む（前は pragma no cover で回していなかった）。攻撃者役の並び [app/roles.sql=悪い, .app/roles.sql=main]。
    import io  # noqa: PLC0415
    import tarfile  # noqa: PLC0415

    def tar_of(members):
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w") as t:
            for name, body in members:
                info = tarfile.TarInfo(name)
                data = body.encode()
                info.size = len(data)
                t.addfile(info, io.BytesIO(data))
        return buf.getvalue()
    good_sql, evil_sql = "-- roles\n", "ALTER POLICY p ON customers USING (true);\n"
    sha_good = __import__("hashlib").sha256(good_sql.encode()).hexdigest()
    tmain = {"infra/db/roles.sql": sha_good}
    layers = [
        ("並びで指紋を上書きする層（app/roles.sql=悪い、.app/roles.sql=main）", [[("app/roles.sql", evil_sql), (".app/roles.sql", good_sql)]], "ng"),
        ("頭に ./ の付いた正しい層", [[("./app/roles.sql", good_sql)]], "ok"),
        ("頭に / の付いた正しい層", [[("/app/roles.sql", good_sql)]], "ok"),
        ("揃えると重なる名前の層（app/roles.sql と ./app/roles.sql）", [[("app/roles.sql", evil_sql), ("./app/roles.sql", good_sql)]], "ng"),
        (".. を含む名前の層", [[("app/../app/roles.sql", good_sql)]], "ng"),
        ("// を含む名前の層", [[("app//roles.sql", good_sql)]], "ng"),
        ("土台の file を消す白抜きの層", [[("app/roles.sql", good_sql), ("usr/bin/.wh.psql", "")]], "ng"),
        ("不透明の白抜きの層", [[("app/roles.sql", good_sql), ("etc/.wh..wh..opq", "")]], "ng"),
        ("後の層が悪い中身で上書きする像", [[("app/roles.sql", good_sql)], [("app/roles.sql", evil_sql)]], "ng"),
    ]
    for name, tars, want in layers:
        files, problems = layer_files([tar_of(m) for m in tars])
        v = {**view, "files": files, "problems": problems}
        status = "ng" if compare_image(v, lock, tmain) else "ok"
        ok = status == want
        bad += 0 if ok else 1
        print(f"{'PASS' if ok else 'FAIL'} event-watch 層 {name}（期待 {want}、実際 {status}）")
    # 第 16 回: 利用者づくりの起動ごとに、起動した像を今の main に照らす（1 つ前の像へ戻した PR を止める）。
    run = {"eventName": "RunTask", "eventTime": "2026-11-08T03:00:00Z", "recipientAccountId": "111122223333",
           "requestParameters": {"taskDefinition": "orders-admin-prod-db-bootstrap:7"},
           "responseElements": {"tasks": [{"containers": [{"image": "111122223333.dkr.ecr.ap-northeast-1.amazonaws.com/orders-admin-prod/db-bootstrap@" + d}]}]}}
    runs = [
        ("今の main に合う像の起動", run, probe(view), "ok"),
        ("1 つ前の像へ戻した起動（古い roles.sql）", run, probe({**view, "files": {"app/roles.sql": "0" * 64}}), "ng"),
        ("ダイジェストの無い起動", {**run, "responseElements": {"tasks": [{"containers": [{"image": "x/db-bootstrap:latest"}]}]}}, probe(view), "ng"),
        ("命令を上書きした起動", {**run, "requestParameters": {**run["requestParameters"], "overrides": {"containerOverrides": [{"command": ["psql", "-c", "x"]}]}}}, probe(view), "ng"),
    ]
    for name, rec, img, want in runs:
        got = judge_entry(rec, lambda a, t: [], (lambda x: good_prov, img))
        status = got["status"] if got else None
        ok = status == want
        bad += 0 if ok else 1
        print(f"{'PASS' if ok else 'FAIL'} event-watch 起動 {name}（期待 {want}、実際 {status}）")
    # 第 16 回: 守りの口座の見張りの欠けを数える便り。欠けが 0 のときだけ送る。
    exp = {"alarms": ["orders-guard-entry-ng"], "alarm_topics": ["orders-guard-security"], "metric_filters": ["entry-ng"],
           "subscription_filters": ["orders-guard-event-watch"], "topics": {"orders-guard-security": 2}}
    full = {"alarms": {"orders-guard-entry-ng": {"actions_enabled": True, "alarm_actions": ["arn:aws:sns:ap-northeast-1:777766665555:orders-guard-security"]}},
            "metric_filters": ["entry-ng"], "subscription_filters": ["orders-guard-event-watch"], "topics": {"orders-guard-security": 2}}
    beats = [
        ("全部ある", full, 0),
        ("話題を消した", {**full, "topics": {}}, 1),
        ("アラームを宛先なしで上書きした", {**full, "alarms": {"orders-guard-entry-ng": {"actions_enabled": True, "alarm_actions": []}}}, 1),
        ("アラームの通知を止めた", {**full, "alarms": {"orders-guard-entry-ng": {"actions_enabled": False, "alarm_actions": full["alarms"]["orders-guard-entry-ng"]["alarm_actions"]}}}, 1),
        ("メトリクスフィルタを消した", {**full, "metric_filters": []}, 1),
        ("購読を外した", {**full, "topics": {"orders-guard-security": 1}}, 1),
        ("記録の購読を外した", {**full, "subscription_filters": []}, 1),
    ]
    for name, st, want in beats:
        got = guard_heartbeat(st, exp)
        ok = (len(got) > 0) == (want > 0)
        bad += 0 if ok else 1
        print(f"{'PASS' if ok else 'FAIL'} event-watch 便り {name}（期待 {'欠け' if want else '欠け 0'}、実際 {len(got)} 件）")
    total = len(gh) + len(entries) + len(images) + len(layers) + len(runs) + len(beats)
    print(f"RESULT: {'PASS' if bad == 0 else 'FAIL'} event-watch selftest ({total - bad}/{total})")
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    if sys.argv[1:2] == ["--selftest"]:
        sys.exit(selftest())
    print(__doc__.strip().splitlines()[-1], file=sys.stderr)
    sys.exit(2)
