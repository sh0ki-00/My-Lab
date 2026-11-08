"""複製の棚卸し（copy-inventory）。samples/infra/inventory.tf が 1 時間に 1 回起動する。

1 行 1 複製の JSON を標準出力に書き、それが台帳（Lambda のロググループ）になる。全部の点検が通ったら、最後に kind=summary の行を書く。
summary の行が 2 時間届かなければ、inventory.tf のアラームが鳴る（中身を空にされても、途中で落ちても鳴る）。
点検は 1 つずつ動かし、1 つが落ちても残りを続ける。落ちた点検は守りの欠けとして知らせに載せ、知らせと便り（ng）を出してから
例外で終わる（Errors が数える）。落ち続けても、毎時の知らせが SNS へ出るので、最初の 1 回だけで黙ることはない。
名前が NAME_PREFIX で始まる手の複製のうち、MAX_DAYS 日を過ぎたものを消す（住みかの地域だけ）。
名前が RESTORE_MARK で始まる訓練の写しは、RESTORE_HOURS 時間を超えたら消して知らせる（住みかの地域だけ）。
札（managed_by など）は判定に使わない。札は付け替えられるので、名前・日数・地域・設定で決める。
設定の値は起動のたびに確かめ、決めた幅の外なら例外で落とす（Errors のアラームが鳴る）。目を潰す設定の書き換えを、黙って通さない。
知らせるもの:
  - 名前の分からない手とクラスタの複製（どの地域でも）
  - 訓練の写しの消し忘れ（消した物も知らせる）
  - KNOWN_DBS の外のデータベースとクラスタ（どの地域でも）、外から届くデータベース
  - 住みかの地域の外にある自動バックアップ（別の地域への複製）
  - KNOWN_BUCKETS の外のバケット（書き出しや複製の置き場）
  - WAF の付いていない配信と、EDGE_ID の外で VPC オリジンを使う配信
  - アドレスの範囲（CIDR とプレフィックスの一覧）で受ける通信の規則（VPC_ID の中。この構成の受け口は、どれもグループの名指し）
  - VAULT_NAME の外の保管庫（既定の保管庫と、us-east-1 を含む許した全部の地域の保管庫）にある復旧点
  - 守りそのものの欠け: 動作の止まったアラーム、宛先の無いアラーム、MIN_ALARMS より少ないアラーム、
    確認済みの購読の数が EXPECTED_SUBS と違う話題、絞り込み（FilterPolicy）の付いた購読、止められた起動の規則、落ちた点検
  - 鳴り続けているアラーム（アラームは状態が変わったときだけ知らせるので、ALARM のままのものを毎時並べ直す）
画面のバケットの中身の照らしは、ここでは行わない。書き込みのたびに、守りの口座の関数が来歴と照らす（security/static-watch.tf）。
守りの欠けが 0 のときだけ、守りの口座のバス（HEARTBEAT_BUS）へ status=ok の便りを送る。欠けがあれば status=ng を送る。
ok が 2 時間届かなければ、守りの口座が鳴らす。作業の口座の SNS を潰されても、外の見張りは残る。
"""
import datetime
import json
import os

import boto3


def _now():
    return datetime.datetime.now(datetime.timezone.utc)


def _ledger(kind, region, ident, created, delete_by, action):
    print(json.dumps({
        "kind": kind, "region": region, "id": ident,
        "created": created.isoformat() if created else None,
        "delete_by": delete_by.isoformat() if hasattr(delete_by, "isoformat") else delete_by,
        "action": action,
    }, ensure_ascii=False))


def _env_list(name):
    return [x for x in os.environ.get(name, "").split(",") if x]


# 設定の幅。この外の値は、目を潰す書き換えとみなして落とす。
BOUNDS = {"MAX_DAYS": (7, 35), "RESTORE_HOURS": (1, 24), "MIN_ALARMS": (1, 500), "EXPECTED_SUBS": (2, 5)}


def validate(env):
    for key, (lo, hi) in BOUNDS.items():
        v = int(env[key])
        if not lo <= v <= hi:
            raise ValueError(f"{key}={v} は決めた幅 {lo}〜{hi} の外")
    regions = set(_env_list("REGIONS"))
    if not {env["HOME_REGION"], "us-east-1"} <= regions:
        raise ValueError(f"REGIONS={sorted(regions)} に住みかの地域か us-east-1 が無い")
    prefix = env["NAME_PREFIX"]
    if len(prefix) < 8 or not env["RESTORE_MARK"].startswith(prefix):
        raise ValueError("NAME_PREFIX か RESTORE_MARK の形が違う")
    if not env.get("HEARTBEAT_BUS", "").startswith("arn:"):
        raise ValueError("HEARTBEAT_BUS が ARN でない")
    for key in ("KNOWN_DBS", "KNOWN_BUCKETS", "ALERT_TOPIC", "ALERT_TOPIC_USE1", "WEB_ACL_ARN", "EDGE_ID", "VAULT_NAME", "RULE_NAME", "VPC_ID"):
        if not env.get(key):
            raise ValueError(f"{key} が空")


def check_region(region, env, now, notices):
    rds = boto3.client("rds", region_name=region)
    prefix, max_days = env["NAME_PREFIX"], int(env["MAX_DAYS"])
    home = region == env["HOME_REGION"]
    delete = home and env.get("DELETE_EXPIRE") == "true"
    known_dbs = set(_env_list("KNOWN_DBS"))
    restore_mark = env["RESTORE_MARK"]
    restore_age = datetime.timedelta(hours=int(env["RESTORE_HOURS"]))

    for page in rds.get_paginator("describe_db_snapshots").paginate(SnapshotType="manual"):
        for snap in page["DBSnapshots"]:
            ident, created = snap["DBSnapshotIdentifier"], snap["SnapshotCreateTime"]
            delete_by = created + datetime.timedelta(days=max_days)
            if not ident.startswith(prefix) or not home:
                notices.append(f"[{region}] 名前か地域の分からない手の複製: {ident}")
                _ledger("manual-snapshot", region, ident, created, delete_by, "notify")
            elif now > delete_by and delete:
                rds.delete_db_snapshot(DBSnapshotIdentifier=ident)
                _ledger("manual-snapshot", region, ident, created, delete_by, "deleted")
            else:
                _ledger("manual-snapshot", region, ident, created, delete_by, "kept")

    for page in rds.get_paginator("describe_db_cluster_snapshots").paginate(SnapshotType="manual"):
        for snap in page["DBClusterSnapshots"]:
            ident = snap["DBClusterSnapshotIdentifier"]
            notices.append(f"[{region}] この構成に無いクラスタの複製: {ident}")
            _ledger("cluster-snapshot", region, ident, snap.get("SnapshotCreateTime"), None, "notify")

    for page in rds.get_paginator("describe_db_instances").paginate():
        for db in page["DBInstances"]:
            ident, created = db["DBInstanceIdentifier"], db["InstanceCreateTime"]
            action = "kept"
            if db.get("PubliclyAccessible"):
                notices.append(f"[{region}] 外から届くデータベース: {ident}")
                action = "notify"
            if ident.startswith(restore_mark):
                if now - created > restore_age:
                    hours = int((now - created).total_seconds() // 3600)
                    if home and not db.get("DeletionProtection") and db.get("DBInstanceStatus") == "available":
                        rds.delete_db_instance(DBInstanceIdentifier=ident, SkipFinalSnapshot=True, DeleteAutomatedBackups=True)
                        notices.append(f"[{region}] 訓練の写しが {hours} 時間残っていたので消した: {ident}")
                        action = "deleted"
                    else:
                        notices.append(f"[{region}] 訓練の写しが {hours} 時間残っている（消せない状態）: {ident}")
                        action = "notify"
            elif ident not in known_dbs or not home:
                notices.append(f"[{region}] 知らないデータベース: {ident}")
                action = "notify"
            _ledger("db-instance", region, ident, created, None, action)

    for page in rds.get_paginator("describe_db_clusters").paginate():
        for cl in page["DBClusters"]:
            notices.append(f"[{region}] この構成に無いクラスタ: {cl['DBClusterIdentifier']}")
            _ledger("db-cluster", region, cl["DBClusterIdentifier"], cl.get("ClusterCreateTime"), None, "notify")

    if not home:
        for page in rds.get_paginator("describe_db_instance_automated_backups").paginate():
            for ab in page["DBInstanceAutomatedBackups"]:
                ident = ab.get("DBInstanceAutomatedBackupsArn") or ab.get("DBInstanceIdentifier")
                notices.append(f"[{region}] 住みかの外の自動バックアップ（別の地域への複製）: {ident}")
                _ledger("automated-backup", region, ident, None, None, "notify")


def check_vault(env, notices):
    """許した全部の地域の保管庫を数える。住みかの地域の VAULT_NAME の外（既定の保管庫と、別の地域の保管庫）に復旧点があれば知らせる。
    バックアップの計画の写しの規則（copy_action）で別の地域へ写す手は、サービスが写すので SCP の StartCopyJob の拒否に頼れない。"""
    home = env["HOME_REGION"]
    for region in _env_list("REGIONS"):
        backup = boto3.client("backup", region_name=region)
        for page in backup.get_paginator("list_backup_vaults").paginate():
            for vault in page["BackupVaultList"]:
                name = vault["BackupVaultName"]
                if region == home and name == env["VAULT_NAME"]:
                    continue
                if vault.get("NumberOfRecoveryPoints", 0) > 0:
                    notices.append(f"[{region}] 知らない保管庫に復旧点がある: {name}（{vault['NumberOfRecoveryPoints']} 件）")
                    _ledger("backup-vault", region, name, vault.get("CreationDate"), None, "notify")
    backup = boto3.client("backup", region_name=home)
    for page in backup.get_paginator("list_recovery_points_by_backup_vault").paginate(BackupVaultName=env["VAULT_NAME"]):
        for rp in page["RecoveryPoints"]:
            delete_at = rp.get("CalculatedLifecycle", {}).get("DeleteAt")
            _ledger("recovery-point", home, rp["RecoveryPointArn"], rp["CreationDate"], delete_at, "kept")


def check_buckets(env, notices):
    known = set(_env_list("KNOWN_BUCKETS"))
    for b in boto3.client("s3").list_buckets().get("Buckets", []):
        action = "kept" if b["Name"] in known else "notify"
        if action == "notify":
            notices.append(f"知らないバケット（書き出しや複製の置き場のおそれ）: {b['Name']}")
        _ledger("bucket", "global", b["Name"], b.get("CreationDate"), None, action)


def check_edge(env, notices):
    cf = boto3.client("cloudfront", region_name="us-east-1")
    for page in cf.get_paginator("list_distributions").paginate():
        for d in page.get("DistributionList", {}).get("Items", []):
            ident, action = d["Id"], "kept"
            if d.get("WebACLId") != env["WEB_ACL_ARN"]:
                notices.append(f"この構成の WAF が付いていない配信: {ident}")
                action = "notify"
            uses_vpc_origin = any("VpcOriginConfig" in o for o in d.get("Origins", {}).get("Items", []))
            if uses_vpc_origin and ident != env["EDGE_ID"]:
                notices.append(f"内部のロードバランサーへつなぐ 2 本目の配信: {ident}")
                action = "notify"
            _ledger("distribution", "global", ident, d.get("LastModifiedTime"), None, action)


def check_network(env, notices):
    """受ける通信の規則を数える。アドレスの範囲で受ける規則は、この構成には無い（どれもグループの名指し）。"""
    ec2 = boto3.client("ec2", region_name=env["HOME_REGION"])
    for page in ec2.get_paginator("describe_security_group_rules").paginate(Filters=[{"Name": "vpc-id", "Values": [env["VPC_ID"]]}]):
        for rule in page["SecurityGroupRules"]:
            if rule.get("IsEgress"):
                continue
            src = rule.get("CidrIpv4") or rule.get("CidrIpv6") or rule.get("PrefixListId")
            if src:
                notices.append(f"アドレスの範囲で受ける規則: {rule['GroupId']} {rule.get('IpProtocol')} {rule.get('FromPort')} から {src}")
                _ledger("ingress-rule", env["HOME_REGION"], rule["SecurityGroupRuleId"], None, None, "notify")


def check_subscriptions(sns, topic, region, expected, notices):
    """確認済みの購読の数と、絞り込みの無いことを確かめる。絞り込みが付くと、通知は黙って捨てられる。"""
    subs = sns.list_subscriptions_by_topic(TopicArn=topic).get("Subscriptions", [])
    confirmed = [x["SubscriptionArn"] for x in subs if x.get("SubscriptionArn", "").startswith("arn:")]
    if len(confirmed) != expected:
        notices.append(f"[{region}] 守りの通知の確認済みの購読が {len(confirmed)} 本（決めた数 {expected} 本）: {topic}")
    for arn in confirmed:
        attrs = sns.get_subscription_attributes(SubscriptionArn=arn).get("Attributes", {})
        if attrs.get("FilterPolicy", "").strip() not in ("", "{}"):
            notices.append(f"[{region}] 守りの通知の購読に絞り込みが付いている: {arn}")


def check_guards(env, notices, ringing):
    """守りそのものを数える。アラームの数と動作、購読の数と絞り込み、起動の規則。ALARM のままのアラームは ringing に並べる。"""
    prefix = env["NAME_PREFIX"]
    for region in (env["HOME_REGION"], "us-east-1"):
        cw = boto3.client("cloudwatch", region_name=region)
        alarms = []
        for page in cw.get_paginator("describe_alarms").paginate(AlarmNamePrefix=prefix, AlarmTypes=["MetricAlarm"]):
            alarms += page["MetricAlarms"]
        for a in alarms:
            if not a.get("ActionsEnabled") or not a.get("AlarmActions"):
                notices.append(f"[{region}] 宛先の無いか、動作を止めたアラーム: {a['AlarmName']}")
            if a.get("StateValue") == "ALARM":
                ringing.append(f"[{region}] 鳴り続けているアラーム: {a['AlarmName']}（{a.get('StateUpdatedTimestamp')} から）")
        if region == env["HOME_REGION"] and len(alarms) < int(env["MIN_ALARMS"]):
            notices.append(f"[{region}] アラームが {len(alarms)} 本しかない（決めた数 {env['MIN_ALARMS']} 本）")
        _ledger("alarms", region, prefix, None, None, f"count={len(alarms)}")
    for topic, region in ((env["ALERT_TOPIC"], env["HOME_REGION"]), (env["ALERT_TOPIC_USE1"], "us-east-1")):
        check_subscriptions(boto3.client("sns", region_name=region), topic, region, int(env["EXPECTED_SUBS"]), notices)
    rule = boto3.client("events", region_name=env["HOME_REGION"]).describe_rule(Name=env["RULE_NAME"])
    if rule.get("State") != "ENABLED":
        notices.append(f"棚卸しの起動の規則が止まっている: {env['RULE_NAME']}")


def _send(env, notices, guard_notices):
    """外への便りと知らせ。どちらも、片方が落ちても、もう片方は出す。出せなかった物の名前を返す。"""
    lost = []
    region = env.get("HOME_REGION", "ap-northeast-1")
    try:
        # 外への便り。守りの欠けが 0 のときだけ ok。宛先は守りの口座のバスで、作業の口座の通知の経路を通らない。
        boto3.client("events", region_name=region).put_events(Entries=[{
            "Source": "orders-admin.copy-inventory", "DetailType": "guard-heartbeat", "EventBusName": env["HEARTBEAT_BUS"],
            "Detail": json.dumps({"status": "ng" if guard_notices else "ok", "guard_notices": len(guard_notices), "notices": len(notices)}),
        }])
    except Exception as e:  # noqa: BLE001  便りが出なければ、守りの口座が途絶で鳴らす。ここでは記録して続ける
        lost.append(f"heartbeat: {type(e).__name__}")
    if notices:
        try:
            boto3.client("sns", region_name=region).publish(
                TopicArn=env["ALERT_TOPIC"], Subject="copy-inventory", Message="\n".join(notices)[:250000])
        except Exception as e:  # noqa: BLE001
            lost.append(f"notice: {type(e).__name__}")
    return lost


def handler(event, context):
    env, now, notices, guard_notices, ringing, failed = os.environ, _now(), [], [], [], []
    try:
        validate(env)
        steps = [(f"check_region {r}", lambda r=r: check_region(r, env, now, notices)) for r in _env_list("REGIONS")]
        steps += [
            ("check_vault", lambda: check_vault(env, notices)),
            ("check_buckets", lambda: check_buckets(env, notices)),
            ("check_edge", lambda: check_edge(env, notices)),
            ("check_network", lambda: check_network(env, notices)),
            ("check_guards", lambda: check_guards(env, guard_notices, ringing)),
        ]
    except (KeyError, ValueError) as e:
        failed.append(f"設定の検査: {e}")
        steps = []
    # 点検は 1 つずつ。1 つが落ちても（権限の不足など）残りを続け、落ちた点検は守りの欠けとして知らせる。
    for name, step in steps:
        try:
            step()
        except Exception as e:  # noqa: BLE001
            failed.append(f"{name}: {type(e).__name__}: {e}"[:400])
    guard_notices += [f"棚卸しの点検が落ちた: {f}" for f in failed]
    notices += guard_notices + ringing
    lost = _send(env, notices, guard_notices)
    if failed or lost:
        # 途中までの知らせと便り（ng）は出した。最後まで動いた印は書かず、例外で Errors に数えさせる。
        print(json.dumps({"kind": "partial", "failed": len(failed), "lost": lost, "notices": len(notices), "at": now.isoformat()}))
        raise RuntimeError(f"copy-inventory: 点検の失敗 {len(failed)}、出せなかった物 {lost}")
    # 最後まで動いた印。inventory.tf のメトリクスフィルタがこの行を数え、2 時間届かなければ鳴る。
    print(json.dumps({"kind": "summary", "notices": len(notices), "at": now.isoformat()}))
    return {"notices": len(notices)}
