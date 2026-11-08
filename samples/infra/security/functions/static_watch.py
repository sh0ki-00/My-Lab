"""画面の照らし（static-watch）。守りの口座の関数で、画面のバケットへの書き込みのたびに動く（security/static-watch.tf）。

照らしの正は CI の外に置く。CI が書いた指紋の一覧は信じず、作りの来歴の署名をこの関数が自分で確かめる。
  起点: 組織の CloudTrail（作業の口座からは止められない）のデータイベントを、守りの口座のロググループの購読で受ける。
  照らす物: 時刻の窓は使わない。書き込みごとに、そのキーの版のうち、まだ照らしていない全部の版を照らす（照らした印は守りの口座の
    表に置く）。記録の x-amz-version-id が名指す版が、版の一覧に無ければ鳴らす。今の版（IsLatest）かどうかで照らし方を変えない。
    書いてすぐ戻した版も、戻す前に照らした版も、同じ決まりで照らす（今の版で決めると、照らす前に書き戻された古い版が ok になった）。
    分けた送り（CreateMultipartUpload と UploadPart）は、始めた時刻の版を作るので窓の外へ逃げられた。窓をやめたので逃げ場は無い。
    版を消す操作は、配る役割にも許していない（edge.tf のバケットの方針）。
  正: 版の SHA-256 で GitHub の来歴を引き（attestations の API）、Sigstore の署名を確かめ、署名した workflow が main の
    static-build.yml で、来歴の主語に「キーと同じ名前と同じ指紋」があるときだけ合うとする。
    どの版も、その版が書かれた時刻（LastModified）の「main の最新の作り」の来歴であること。最新の作りは、main の static-build の
    成功した実行のうち、やり直しでない（run_attempt が 1）実行で、その時刻までに終わった物の run_number の最大。やり直した古い実行は
    一覧の先頭に来ても最新にならない。その commit が今の main から届き、別の 2 人が承認した PR を通ったことも見る。
    承認待ちで次の作りが配られていない間の書き込みは、書いた時刻の最新と照らすので、誤って ng にしない。
    さらに、版の中身がその実行の束（作る job が上げた名前 site の束 1 つ。作る job が終わる前に作られた物）の同じ名前の file と
    同じであること（配る job と同じ決まり）。署名する job の悪い部品が、同じ実行で悪い file を主語にした 2 つ目の来歴を付けても、
    束の中身とは合わないので ng になる（第 13 回。来歴の数ではなく、作る job の束を正にする）。
  毎日の見回り（mode が sweep）: 今の版の全部の file が、今の index.html と同じ作りの来歴を持つかを照らす。配る手順は古い file を消すが、
    消し忘れと古い作りの残り（外した部品の html や script）は、書き込みが無くても毎日鳴る。
  鳴らす物: 来歴と合わない版、書かれた時刻の最新の作りでない版、配る役割の外の書き込み（拒まれた試みも）、版の番号が記録に無いか
    一覧に無い書き込み、分けた送り（配る役割は使わない）、照らしの一覧に無い書き込みの名前、今の作りの外の file。
    来歴が正しくても、置き場の一覧の外の名前（index.html と assets/ の下の外。根の /sw.js など）と、Service Worker の登録の呼び出し
    （serviceWorker の文字）を含む script と html は鳴らす。悪い部品は正規の作りの中で /sw.js を足せるので、来歴だけでは拾えない。
出力: 書き込み 1 件ごと（と見回り 1 回ごと）に {"kind": "static-check", "status": "ok"|"ng", ...} の 1 行。
  GitHub・S3・Sigstore の信頼の根に届かないときは例外で落ち、Errors が鳴る（署名の食い違いの ng と分けて、本物の ng を埋もれさせない）。
使い方: python3 static_watch.py --selftest
"""
import base64
import datetime
import gzip
import hashlib
import io
import json
import os
import re
import sys
import zipfile

# 版を作る書き込み。照らしの一覧はこの 4 つと下の 3 組だけで、ほかの名前は ng にする。
VERSIONED = {"PutObject", "CopyObject", "CompleteMultipartUpload", "PostObject"}
# 分けた送り。配る手順は分けない（static-deploy.yml で閾値を上げた）ので、配る役割が使えば ng。
MULTIPART = {"CreateMultipartUpload", "UploadPart", "UploadPartCopy", "CompleteMultipartUpload", "AbortMultipartUpload"}
DELETES = {"DeleteObject", "DeleteObjects"}
# 中身を変えない書き込み。書いた主体だけを照らす。
META = {"PutObjectAcl", "PutObjectTagging", "DeleteObjectTagging", "RestoreObject"}
KNOWN = VERSIONED | MULTIPART | DELETES | META
# 置き場の一覧。入口の index.html と、assets/ の下の名前だけ（画面の作りの決まり。横断事項でフロントエンドと揃える）。
PLACES = re.compile(r"^(index\.html|assets/[A-Za-z0-9._-]+)$")
# Service Worker の登録の呼び出し。画面は worker を使わない（edge.tf の worker-src 'none'）。
WORKER = re.compile(rb"serviceWorker|ServiceWorkerContainer")


def shape(key, body):
    """来歴と別に、置き場の名前と中身の形を照らす。食い違いの一覧を返す。"""
    out = []
    if not PLACES.match(key):
        out.append(f"置き場の一覧の外の名前（根の script など）: {key}")
    if re.search(r"\.(m?js|html?)$", key) and WORKER.search(body):
        out.append(f"Service Worker の登録の呼び出しを含む: {key}")
    return out


def records(event):
    """CloudWatch Logs の購読の形から、CloudTrail の記録を取り出す。"""
    data = json.loads(gzip.decompress(base64.b64decode(event["awslogs"]["data"])))
    return [json.loads(e["message"]) for e in data.get("logEvents", [])]


def check_record(rec, buckets, s3, judge, checked):
    """書き込み 1 件を照らす。食い違いの一覧を返す。buckets は {バケット: 配る役割の ARN}、checked は照らした版の印。"""
    p = rec.get("requestParameters") or {}
    bucket, key, name = p.get("bucketName", ""), p.get("key", ""), rec.get("eventName", "")
    issuer = (((rec.get("userIdentity") or {}).get("sessionContext") or {}).get("sessionIssuer") or {}).get("arn", "")
    out = []
    if bucket not in buckets:
        return out
    if name not in KNOWN:
        out.append(f"照らしの一覧に無い書き込みの名前: {name} {key}")
    if issuer != buckets[bucket]:
        out.append(f"配る役割の外の書き込み（{'拒まれた試み' if rec.get('errorCode') else '通った'}）: {issuer or '不明'} {name} {key}")
    if name in MULTIPART and not rec.get("errorCode"):
        out.append(f"分けた送り（配る手順は使わない）: {name} {key}")
    if rec.get("errorCode") or not key or name not in VERSIONED:
        return out
    named = ((rec.get("responseElements") or {}).get("x-amz-version-id")
             or (rec.get("additionalEventData") or {}).get("x-amz-version-id"))
    if not named:
        out.append(f"書かれた版の番号が記録に無い: {key}")
    listed = set()
    for page in s3.get_paginator("list_object_versions").paginate(Bucket=bucket, Prefix=key):
        for v in page.get("Versions", []):
            if v["Key"] != key:
                continue
            vid = v["VersionId"]
            listed.add(vid)
            mark = f"{bucket}/{key}#{vid}"
            if checked.seen(mark):
                continue
            body = s3.get_object(Bucket=bucket, Key=key, VersionId=vid)["Body"].read()
            ok, why = judge(key, hashlib.sha256(body).hexdigest(), iso(v.get("LastModified")))
            odd = shape(key, body)
            out += [f"{o} 版 {vid}" for o in odd]
            ok = ok and not odd
            if ok:
                checked.add(mark)
            elif why:
                out.append(f"{why}: {key} 版 {vid}")
    if named and named not in listed:
        out.append(f"書かれた版が版の一覧に無い: {key} 版 {named}")
    return out


def run_of(statement):
    """SLSA の来歴 v1 の runDetails から、作った実行の番号を引く。"""
    inv = (((statement.get("predicate") or {}).get("runDetails") or {}).get("metadata") or {}).get("invocationId", "")
    m = re.search(r"/actions/runs/(\d+)", inv)
    return int(m.group(1)) if m else None


def iso(t):
    """S3 の LastModified（datetime か文字）を、GitHub の時刻と同じ形（UTC の YYYY-MM-DDTHH:MM:SSZ）にする。"""
    if isinstance(t, datetime.datetime):
        return t.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if not t:
        raise LookupError("版の書かれた時刻が無い")
    return str(t)


def artifact_bundles(get, fetch, repo):
    """実行の番号から、その実行の束（名前 site の束 1 つ）の file の名前と SHA-256 の表を返す関数を作る。決まらなければ None。
    束は作る job（build）が上げた物だけを正にする。作る job が終わった後に作られた束（上げ直し）と、2 つ以上の束は認めない。"""
    cache = {}

    def bundle_of(run_id):
        if run_id not in cache:
            jobs = [j for j in get(f"/repos/{repo}/actions/runs/{run_id}/jobs").get("jobs", []) if j.get("name") == "build"]
            arts = [a for a in get(f"/repos/{repo}/actions/runs/{run_id}/artifacts").get("artifacts", []) if a.get("name") == "site"]
            if len(jobs) != 1 or len(arts) != 1 or not jobs[0].get("completed_at") \
                    or str(arts[0].get("created_at", "")) > str(jobs[0]["completed_at"]):
                cache[run_id] = None
            else:
                z = zipfile.ZipFile(io.BytesIO(fetch(f"/repos/{repo}/actions/artifacts/{arts[0]['id']}/zip")))
                cache[run_id] = {n: hashlib.sha256(z.read(n)).hexdigest() for n in z.namelist() if not n.endswith("/")}
        return cache[run_id]
    return bundle_of


def make_judge(get, repo, workflow, verify, pr_people, bundle_of=None, repo_ids=None):
    """版の指紋を、来歴（署名した workflow と主語）と、その版が書かれた時刻の main の最新の作りと、その作りの束とで照らす関数を返す。
    repo_ids（リポジトリの番号, 持ち主の番号）を渡すと、署名の証明書の番号もそれと照らす。署名者は名前の URL なので、
    名前を付け替えるか消した後に同じ名前で作り直したリポジトリの署名も、名前だけでは通ってしまう。"""
    signer = f"https://github.com/{repo}/{workflow}@refs/heads/main"
    cache, runs, checked_runs = {}, [], {}

    def hits(key, digest):
        if digest not in cache:
            items = get(f"/repos/{repo}/attestations/sha256:{digest}").get("attestations", [])
            cache[digest] = [st for st in (verify(a["bundle"], signer) for a in items) if st]
        return [st for st in cache[digest] if st.get("_signer") == signer
                and (repo_ids is None or tuple(st.get("_repo_ids") or ()) == tuple(repo_ids))
                and any(s.get("name") == key and (s.get("digest") or {}).get("sha256") == digest for s in st.get("subject", []))]

    def latest_at(at):
        if not runs:
            wf = workflow.rsplit("/", 1)[-1]
            runs.extend(get(f"/repos/{repo}/actions/workflows/{wf}/runs?branch=main&event=push&status=success&per_page=100")
                        .get("workflow_runs", []))
        done = [r for r in runs if int(r.get("run_attempt") or 1) == 1 and str(r.get("updated_at", "")) <= at]
        if not done:
            raise LookupError(f"{at} までに終わった main の static-build の実行が無い")
        run = max(done, key=lambda r: int(r["run_number"]))
        if run["id"] not in checked_runs:
            reach = get(f"/repos/{repo}/compare/{run['head_sha']}...main").get("status")
            people = pr_people(get, repo, run["head_sha"])
            checked_runs[run["id"]] = reach in ("ahead", "identical") and people is not None and len(people[1]) >= 2
        return run["id"], checked_runs[run["id"]]

    def judge(key, digest, at):
        found = hits(key, digest)
        if not found:
            return False, "来歴と合わない版"
        run_id, ok = latest_at(at)
        if not ok:
            return False, "最新の作りの commit が main に無いか、別の 2 人の承認した PR を通っていない"
        if not any(run_of(st) == run_id for st in found):
            return False, f"書かれた時刻（{at}）の main の最新の作り（実行 {run_id}）でない版（古い作りの書き戻しか、やり直した実行）"
        if bundle_of is not None:
            want = bundle_of(run_id)
            if want is None:
                return False, f"実行 {run_id} の束（site）が 1 つに決まらないか、作る job の後に作られた"
            if want.get(key) != digest:
                return False, f"実行 {run_id} の束（作る job が上げた site）と中身が違う版（同じ実行に足した 2 つ目の来歴か書き換え）"
        return True, ""
    judge.hits = hits
    judge.bundle_of = bundle_of
    return judge


def sweep(buckets, s3, hits, bundle_of=None):
    """毎日の見回り。今の版の全部の file が、今の index.html と同じ作りの来歴を持ち、その作りの束と同じ中身かを照らす。食い違いの一覧を返す。"""
    out = []
    for bucket in buckets:
        keys = []
        for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket):
            keys += [o["Key"] for o in page.get("Contents", [])]

        def runs(key, bucket=bucket):
            body = s3.get_object(Bucket=bucket, Key=key)["Body"].read()
            return {run_of(st) for st in hits(key, hashlib.sha256(body).hexdigest())}
        if "index.html" not in keys:
            out.append(f"入口の index.html が無い: {bucket}")
            continue
        now = runs("index.html")
        if len(now) != 1:
            out.append(f"今の index.html の作りが 1 つに決まらない: {bucket} {sorted(map(str, now))}")
            continue
        want = bundle_of(next(iter(now))) if bundle_of is not None else None
        if bundle_of is not None and want is None:
            out.append(f"今の作りの束（site）が 1 つに決まらない: {bucket}")
        for key in keys:
            body = s3.get_object(Bucket=bucket, Key=key)["Body"].read()
            out += shape(key, body)
            if key != "index.html" and not (runs(key) & now):
                out.append(f"今の作りの外の file（消し忘れか、外した部品の古い作りの残り）: {key}")
            elif want is not None and want.get(key) != hashlib.sha256(body).hexdigest():
                out.append(f"今の作りの束と中身が違う file（同じ実行に足した 2 つ目の来歴）: {key}")
    return out


def verify_bundle(bundle, signer):  # pragma: no cover  層に入れる sigstore で確かめる（API の確かめは未確定 7）
    """Sigstore の束を確かめ、来歴の文（in-toto の statement）を返す。署名が合わなければ None。
    信頼の根に届かないなど、確かめ自体ができないときは例外を上げる（ng ではなく Errors で鳴らす）。
    非公開のリポジトリの来歴は GitHub の Sigstore で署名されるので、信頼の根は SIGSTORE_TRUSTED_ROOT（層に入れた GitHub の信頼の根）を使う。"""
    from sigstore.errors import VerificationError  # noqa: PLC0415
    from sigstore.models import Bundle, ClientTrustConfig  # noqa: PLC0415
    from sigstore.verify import Verifier, policy  # noqa: PLC0415
    root = os.environ.get("SIGSTORE_TRUSTED_ROOT", "")
    verifier = Verifier(trusted_root=ClientTrustConfig.from_json(open(root, encoding="utf-8").read()).trusted_root) if root \
        else Verifier.production()
    try:
        _, payload = verifier.verify_dsse(
            Bundle.from_json(json.dumps(bundle)),
            policy.Identity(identity=signer, issuer="https://token.actions.githubusercontent.com"))
    except VerificationError:
        return None
    statement = json.loads(payload)
    if not str(statement.get("predicateType", "")).startswith("https://slsa.dev/provenance/v1"):
        return None
    statement["_signer"] = signer
    cert = Bundle.from_json(json.dumps(bundle)).signing_certificate
    statement["_repo_ids"] = cert_repo_ids(cert)
    # 走った機械と、呼んだ側の workflow（再利用の workflow が署名したときに、呼んだ側を名指しして照らす。event_watch.py）。
    statement["_runner"], statement["_build_config"] = cert_text(cert, OID_RUNNER_ENV), cert_text(cert, OID_BUILD_CONFIG)
    return statement


# 署名の証明書（Fulcio）の拡張。リポジトリの番号と持ち主の番号（どちらも DER の UTF8String）。番号は名前の付け替えで変わらない。
OID_REPO_ID, OID_OWNER_ID = "1.3.6.1.4.1.57264.1.15", "1.3.6.1.4.1.57264.1.17"


# 走った機械（github-hosted か self-hosted）と、作りの設定の URI（呼んだ側の workflow の file と ref）。
OID_RUNNER_ENV, OID_BUILD_CONFIG = "1.3.6.1.4.1.57264.1.11", "1.3.6.1.4.1.57264.1.18"


def cert_text(cert, oid):  # pragma: no cover  証明書の拡張を読む（拡張の番号の確かめは未確定 7）
    from cryptography.x509.oid import ObjectIdentifier  # noqa: PLC0415
    try:
        der = cert.extensions.get_extension_for_oid(ObjectIdentifier(oid)).value.value
    except Exception:  # noqa: BLE001  拡張が無ければ空（照らしで ng になる）
        return ""
    return der[2:].decode("utf-8", "replace") if der[:1] == b"\x0c" and der[1] < 0x80 else ""


def cert_repo_ids(cert):  # pragma: no cover  証明書の拡張を読む（拡張の番号の確かめは未確定 7）
    return (cert_text(cert, OID_REPO_ID), cert_text(cert, OID_OWNER_ID))


class Checked:  # pragma: no cover  守りの口座の DynamoDB の表（照らした版の印）。書くのはこの関数の役割だけ
    def __init__(self, table):
        import boto3  # noqa: PLC0415
        self.t, self.db = table, boto3.client("dynamodb")

    def seen(self, mark):
        return "Item" in self.db.get_item(TableName=self.t, Key={"mark": {"S": mark}}, ConsistentRead=True)

    def add(self, mark):
        self.db.put_item(TableName=self.t, Item={"mark": {"S": mark}})


def handler(event, context):  # pragma: no cover  守りの口座の Lambda の入口
    import boto3  # noqa: PLC0415

    import gh_app  # noqa: PLC0415
    from github_watch import pr_people  # noqa: PLC0415

    env = os.environ
    buckets = json.loads(env["STATIC_BUCKETS"])
    token = gh_app.app_token(env["APP_KEY_SECRET"], env["APP_ID"], env["APP_INSTALLATION_ID"])
    get = gh_app.getter(token)
    bundle_of = artifact_bundles(get, gh_app.fetcher(token), env["REPOSITORY"])
    judge = make_judge(get, env["REPOSITORY"], env["SIGNER_WORKFLOW"], verify_bundle, pr_people, bundle_of,
                       (env["REPOSITORY_ID"], env["REPOSITORY_OWNER_ID"]))
    s3 = boto3.client("s3", region_name=env["WORKLOAD_REGION"])
    if event.get("mode") == "sweep":
        found = sweep(buckets, s3, judge.hits, judge.bundle_of)
        print(json.dumps({"kind": "static-check", "status": "ng" if found else "ok", "event": "sweep", "findings": found[:50]},
                         ensure_ascii=False))
        return
    checked = Checked(env["CHECKED_TABLE"])
    for rec in records(event):
        found = check_record(rec, buckets, s3, judge, checked)
        print(json.dumps({"kind": "static-check", "status": "ng" if found else "ok", "account": rec.get("recipientAccountId"),
                          "event": rec.get("eventName"), "key": (rec.get("requestParameters") or {}).get("key"), "findings": found[:20]},
                         ensure_ascii=False))


def selftest():
    role = "arn:aws:iam::111122223333:role/orders-admin-prod-ci-push-static"
    bucket = "orders-admin-prod-static-111122223333"
    buckets = {bucket: role}
    good, old, bad = b"<script>ok</script>", b"<script>v1</script>", b"<script>location.href='x'</script>"
    idx, old_html = b"<html>9</html>", b"<html>3</html>"
    sha = lambda b: hashlib.sha256(b).hexdigest()  # noqa: E731
    signer = "https://github.com/o/r/.github/workflows/static-build.yml@refs/heads/main"
    k = "assets/app-1a2b.js"
    t_now, t_next = "2026-11-07T00:00:00Z", "2026-11-08T00:00:00Z"

    def st(body, run, name=k, attempt=1, ids=("100000001", "100000002")):
        return {"_signer": signer, "_repo_ids": ids, "subject": [{"name": name, "digest": {"sha256": sha(body)}}],
                "predicate": {"runDetails": {"metadata": {"invocationId": f"https://github.com/o/r/actions/runs/{run}/attempts/{attempt}"}}}}
    kw = "assets/reg-7c.js"
    # 消した後に同じ名前で作り直したリポジトリ（番号が違う）の main の static-build.yml が署名した版
    remade = b"<script>remade</script>"
    sw, reg = b"self.addEventListener('fetch',e=>{})", b"navigator.serviceWorker.register('/sw.js',{scope:'/'})"
    bad_idx = b"<html><script src=assets/x.js></script></html>"
    statements = {sha(good): [st(good, 9)], sha(old): [st(old, 3), st(old, 3, attempt=2)], sha(idx): [st(idx, 9, "index.html")],
                  sha(old_html): [st(old_html, 3, "assets/old-9f.html")], sha(sw): [st(sw, 9, "sw.js")], sha(reg): [st(reg, 9, kw)],
                  # 署名する job の悪い部品が、同じ実行 9 で悪い index.html と assets/x.js を主語にした 2 つ目の来歴を付けた
                  sha(bad_idx): [st(bad_idx, 9, "index.html")], sha(bad): [st(bad, 9, "assets/x.js")],
                  sha(remade): [st(remade, 9, ids=("200000009", "100000002"))]}
    # 作る job が上げた束（実行ごとの file の名前と指紋）。2 つ目の来歴の file は入らない。
    bundles = {9: {k: sha(good), "index.html": sha(idx), "sw.js": sha(sw), kw: sha(reg)}, 3: {k: sha(old), "assets/old-9f.html": sha(old_html)}}
    base_runs = [{"id": 9, "run_number": 9, "run_attempt": 1, "updated_at": "2026-11-06T00:00:00Z", "head_sha": "c" * 40},
                 {"id": 3, "run_number": 3, "run_attempt": 1, "updated_at": "2026-11-01T00:00:00Z", "head_sha": "b" * 40}]
    rerun = [{"id": 3, "run_number": 3, "run_attempt": 2, "updated_at": "2026-11-06T23:00:00Z", "head_sha": "b" * 40}] + base_runs[:1]
    pending = [{"id": 10, "run_number": 10, "run_attempt": 1, "updated_at": "2026-11-07T12:00:00Z", "head_sha": "d" * 40}] + base_runs

    class S3:
        def __init__(self, versions, current=None):
            self.v = [(x + (t_now,))[:5] for x in versions]  # (key, vid, latest, body, LastModified)
            self.cur = current or {}

        def get_paginator(self, name):
            self.mode = name
            return self

        def paginate(self, **_):
            if self.mode == "list_objects_v2":
                return [{"Contents": [{"Key": key} for key in self.cur]}]
            return [{"Versions": [{"Key": key, "VersionId": vid, "IsLatest": latest, "LastModified": at}
                                  for key, vid, latest, _, at in self.v]}]

        def get_object(self, Key, VersionId=None, **_):
            body = self.cur[Key] if VersionId is None else next(b for key, vid, _, b, _ in self.v if key == Key and vid == VersionId)
            return {"Body": type("B", (), {"read": lambda self: body})()}

    class Marks:
        def __init__(self, seen=()):
            self.s = set(seen)

        def seen(self, m):
            return m in self.s

        def add(self, m):
            self.s.add(m)

    def world(runs=None, reach="ahead", approvals=2):
        def get(path):
            if "/attestations/" in path:
                return {"attestations": [{"bundle": s} for s in statements.get(path.rsplit(":", 1)[-1], [])]}
            if "/actions/workflows/" in path:
                return {"workflow_runs": runs or base_runs}
            if "/compare/" in path:
                return {"status": reach}
            raise KeyError(path)
        people = lambda g, r, s: ("dev", {f"rev{i}" for i in range(approvals)})  # noqa: E731
        return make_judge(get, "o/r", ".github/workflows/static-build.yml", lambda b, s: b, people, bundles.get, ("100000001", "100000002"))

    def rec(name="PutObject", issuer=role, key=k, err=None, vid="v1"):
        r = {"eventName": name, "requestParameters": {"bucketName": bucket, "key": key},
             "userIdentity": {"sessionContext": {"sessionIssuer": {"arn": issuer}}}, "responseElements": {"x-amz-version-id": vid}}
        if err:
            r["errorCode"] = err
        return r

    back = [(k, "v1", False, good), (k, "v2", False, old), (k, "v3", True, good)]
    cases = [
        ("最新の作りの版", rec(), S3([(k, "v1", True, good)]), world(), Marks(), 0, ""),
        ("配る役割が悪い版を書いた", rec(), S3([(k, "v1", True, bad)]), world(), Marks(), 1, "来歴と合わない"),
        ("作り直した同じ名前のリポジトリの署名の版（番号が違う）", rec(), S3([(k, "v1", True, remade)]), world(), Marks(), 1, "来歴と合わない"),
        ("書いて戻した（前の版が悪い）", rec(vid="v2"), S3([(k, "v1", False, bad), (k, "v2", True, good)]), world(), Marks(), 1, "来歴と合わない"),
        ("分けた送りで始めた時刻の悪い版（窓の外）", rec(name="CompleteMultipartUpload", vid="v0"),
         S3([(k, "v0", True, bad), (k, "v1", False, good)]), world(), Marks({f"{bucket}/{k}#v1"}), 2, "来歴と合わない"),
        ("分けた送りを始めただけ", rec(name="CreateMultipartUpload"), S3([]), world(), Marks(), 1, "分けた送り"),
        ("古い作りの版を書き戻した", rec(), S3([(k, "v1", True, old)]), world(), Marks(), 1, "最新の作り"),
        ("古い作りを書いてすぐ戻した（記録は古い版、照らす時の今の版は戻した版）", rec(vid="v2"), S3(back), world(),
         Marks({f"{bucket}/{k}#v1"}), 1, "最新の作り"),
        ("戻した版の記録が先に届いた", rec(vid="v3"), S3(back), world(), Marks({f"{bucket}/{k}#v1"}), 1, "最新の作り"),
        ("やり直した古い実行が一覧の先頭に来た", rec(), S3([(k, "v1", True, old)]), world(runs=rerun), Marks(), 1, "やり直した"),
        ("承認待ちの次の作りがある間に今の作りを書いた（誤って ng にしない）", rec(), S3([(k, "v1", True, good)]),
         world(runs=pending), Marks(), 0, ""),
        ("次の作りが終わった後に前の作りを書いた", rec(), S3([(k, "v1", True, good, t_next)]), world(runs=pending), Marks(), 1, "最新の作り"),
        ("最新の作りの commit が main から届かない", rec(), S3([(k, "v1", True, good)]), world(reach="diverged"), Marks(), 1, "main に無い"),
        ("最新の作りの PR の承認が 1 人", rec(), S3([(k, "v1", True, good)]), world(approvals=1), Marks(), 1, "2 人"),
        ("照らした古い版は照らし直さない", rec(vid="v2"), S3([(k, "v1", False, old), (k, "v2", True, good)]), world(),
         Marks({f"{bucket}/{k}#v1"}), 0, ""),
        ("来歴に無い名前の file（_manifest/x.js）", rec(key="_manifest/x.js"), S3([("_manifest/x.js", "v1", True, good)]), world(), Marks(), 2, "来歴と合わない"),
        ("正規の作りが根に /sw.js を足した（来歴は合う）", rec(key="sw.js"), S3([("sw.js", "v1", True, sw)]), world(), Marks(), 1, "置き場の一覧の外"),
        ("正規の作りの script が Service Worker を登録する（来歴は合う）", rec(key=kw), S3([(kw, "v1", True, reg)]), world(), Marks(), 1,
         "Service Worker"),
        ("配る役割の外の書き込みの試み", rec(issuer="arn:aws:iam::111122223333:role/orders-admin-prod-apply", err="AccessDenied"), S3([]), world(), Marks(), 1, "配る役割の外"),
        ("記録の版が一覧に無い", rec(vid="v9"), S3([(k, "v1", True, good)]), world(), Marks(), 1, "版の一覧に無い"),
        ("照らしの一覧に無い名前", rec(name="PutObjectLegalHold"), S3([]), world(), Marks(), 1, "一覧に無い書き込みの名前"),
        ("配る役割が古い file を消した", rec(name="DeleteObject"), S3([]), world(), Marks(), 0, ""),
        ("同じ実行に足した 2 つ目の来歴の index.html（起点 2 つ）", rec(key="index.html"), S3([("index.html", "v1", True, bad_idx)]), world(), Marks(), 1,
         "束（作る job が上げた site）と中身が違う"),
        ("同じ実行に足した 2 つ目の来歴の assets/x.js（起点 2 つ）", rec(key="assets/x.js"), S3([("assets/x.js", "v1", True, bad)]), world(), Marks(), 1,
         "束（作る job が上げた site）と中身が違う"),
    ]
    bad_n = 0
    for name, r, s3, judge, marks, want, word in cases:
        got = check_record(r, buckets, s3, judge, marks)
        ok = len(got) == want and (not word or any(word in g for g in got))
        bad_n += 0 if ok else 1
        print(f"{'PASS' if ok else 'FAIL'} static-watch {name}（期待 {want} 件、実際 {len(got)} 件）{'' if ok else got}")
    sweeps = [
        ("見回り: 今の作りの file だけ", {"index.html": idx, k: good}, 0, ""),
        ("見回り: 外した部品の古い html が残っている", {"index.html": idx, k: good, "assets/old-9f.html": old_html}, 1, "今の作りの外"),
        ("見回り: 入口が無い", {k: good}, 1, "index.html が無い"),
        ("見回り: 今の作りの根の /sw.js", {"index.html": idx, k: good, "sw.js": sw}, 1, "置き場の一覧の外"),
        ("見回り: 2 つ目の来歴の index.html と x.js に置き換えた", {"index.html": bad_idx, k: good, "assets/x.js": bad}, 2, "束と中身が違う"),
    ]
    for name, cur, want, word in sweeps:
        j = world()
        got = sweep(buckets, S3([], cur), j.hits, j.bundle_of)
        ok = len(got) == want and (not word or any(word in g for g in got))
        bad_n += 0 if ok else 1
        print(f"{'PASS' if ok else 'FAIL'} static-watch {name}（期待 {want} 件、実際 {len(got)} 件）{'' if ok else got}")
    n = len(cases) + len(sweeps)
    print(f"RESULT: {'PASS' if bad_n == 0 else 'FAIL'} static-watch selftest ({n - bad_n}/{n})")
    return 0 if bad_n == 0 else 1


if __name__ == "__main__":
    if sys.argv[1:2] == ["--selftest"]:
        sys.exit(selftest())
    print(__doc__.strip().splitlines()[-1], file=sys.stderr)
    sys.exit(2)
