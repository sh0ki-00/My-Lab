"""GitHub App のその場限りの札（installation token）を作る。github_watch.py と static_watch.py が共に使う。

鍵は守りの口座の秘密（security/github-watch.tf の github_app_key）に置き、値はログにも戻り値にも出さない。
札の権限は App の権限（配備のリポジトリと組織を読むだけ）で、1 時間で切れる。App を外されたら札が作れず、呼ぶ側は ng で鳴らす。
JWT の署名には PyJWT と cryptography を使う（関数の層に入れる。層の作り方と固定は未確定 7）。
"""
import json
import time
import urllib.error
import urllib.request

API = "https://api.github.com"


def app_token(secret_arn, app_id, installation_id):
    import boto3  # noqa: PLC0415  Lambda の実行環境にある
    import jwt  # noqa: PLC0415  層に入れる PyJWT

    key = boto3.client("secretsmanager").get_secret_value(SecretId=secret_arn)["SecretString"]
    now = int(time.time())
    assertion = jwt.encode({"iat": now - 60, "exp": now + 540, "iss": str(app_id)}, key, algorithm="RS256")
    req = urllib.request.Request(f"{API}/app/installations/{installation_id}/access_tokens", method="POST", headers={
        "Authorization": f"Bearer {assertion}", "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"})
    with urllib.request.urlopen(req, timeout=20) as r:  # noqa: S310  宛先は api.github.com だけ
        return json.loads(r.read().decode())["token"]


def getter(token):
    """GitHub の API を読む関数を返す。宛先は api.github.com だけ。"""
    def get(path):
        req = urllib.request.Request(API + path, headers={
            "Authorization": "Bearer " + token, "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"})
        with urllib.request.urlopen(req, timeout=20) as r:  # noqa: S310
            return json.loads(r.read().decode())
    return get


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):  # noqa: ANN002, ANN003
        return None


def fetcher(token):
    """GitHub の API から file（束の zip）を落とす関数を返す。API は短い期限の URL へ送り返すので、
    送り返し先には札を付けずに取りに行く（札を GitHub の外へ出さない）。"""
    opener = urllib.request.build_opener(_NoRedirect)

    def fetch(path):
        req = urllib.request.Request(API + path, headers={
            "Authorization": "Bearer " + token, "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"})
        try:
            with opener.open(req, timeout=20) as r:  # noqa: S310
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code not in (301, 302, 303, 307, 308):
                raise
            with urllib.request.urlopen(e.headers["Location"], timeout=60) as r:  # noqa: S310  GitHub の束の置き場（期限つきの URL）
                return r.read()
    return fetch
