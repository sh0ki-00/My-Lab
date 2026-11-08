-- データベースの中の利用者と権限（ECS の db-bootstrap が管理者で流す。何度流しても同じ結果になる）。
-- 権限の正本はバックエンドの samples/api/db-access.json（表ごとの読み書きの列と、行の制限の掛け方）。この file はそれに合わせる。
-- 食い違いは skills/infra/scripts/db-grants-check.sh が落とす（JSON と、この file の GRANT・RLS・最後の検査の一覧を突き合わせる）。
-- 表を作る・変える権限は表の持ち主の役割に置き、移行の利用者 orders_migrate がその一員として流す。orders_api と orders_migrate は
-- 合言葉を持たず、IAM の認証の札で入る。
-- 店の分離は SQL の条件だけに頼らない。行の単位の制限（RLS）で、orders_api に「要求の鍵の店」の行だけを見せる。
-- 店は、API が自由に書ける値では決めない。API は取引ごとに鍵のハッシュ（SET LOCAL app.key_hash）だけを流し、DB の側で店を引く。
--   鍵で 1 行を引く表（sessions。正本の rows が token）は、鍵のハッシュが合う行だけを見せる。店では絞らない。
--     見たことのない鍵のハッシュは読めないので、注入で app.key_hash を書き換えても、他の店の鍵を知らなければ 0 行になる。
--   shop_id の列を持つ表（orders、customers、idempotency、users）は、その列を sessions と users から引いた店と比べる。
--     users は 2026-11-07 の正本で token から shop_id に変わった（注文の 3 列の EXISTS をやめ、一覧を速くする）。
--     店を引くのは関数 app_key_shop（表の持ち主の権限で動き、鍵のハッシュの合う 1 行だけを引く）。users の方針が orders を通るので、
--     orders の方針が users を直に読むと、方針が互いを呼び合って止まる。関数を通して、その輪を切る。
--   shop_id の列が無い表（order_items、order_events）は、親の表 orders を order_id で結び、親の行の制限に従わせる。
--   全店を見る値（app.shop_scope = 'all'）も、API が書ける店の値（app.shop_id）も置かない。
-- app.key_hash は流さなければ 0 行になる（条件の書き漏らしは、全店ではなく 0 件として表に出る）。
-- API は値を文に書かず、set_config('app.key_hash', $1, true) の束ねた値で渡す（実行中の文の一覧に、他の要求のハッシュを出さない）。
-- DB の側でも、実行中の文を見せる見方と関数を orders_api から取り上げる。同じ利用者の別の接続の文は、ふだんは互いに見えるからである。
-- 取り上げが効かない環境（管理者がその見方の持ち主でない場合など）では、最後の検査が止める。
-- 表の持ち主は移さない（正本の owner）。既存の表の持ち主は旧 API の側にあり、移すと旧 API が持ち主の権限と RLS の素通りを失う。
--   移行の利用者 orders_migrate（IAM の札で入る）を持ち主の役割の一員にし、移行は持ち主の役割で流す（db/migrate-run.sh が SET ROLE する）。
--   ALTER TABLE と CREATE TRIGGER が通り、足す表の持ち主も同じ役割になる。持ち主が管理者か上の権限を持つ役割なら止める。
--   持ち主には public の USAGE と CREATE を明示で付ける（PUBLIC から外した後も、店を引く関数と外部キーの確かめが持ち主の権限で動く）。
--   持ち主と書き手からデータベースの CREATE を外す（新しいスキーマで表の名前を隠させない）。orders_api の search_path は public に固定する。
-- 旧い書き手（正本の otherRoles。旧 API など）は、RLS を有効にしても前と同じに動くよう、明示の CONNECT と USAGE と、全行の方針
--   （FOR ALL の USING (true)）を持たせる。理由: 文も取引も変えない計画で、店を引く鍵のハッシュを流さない。退役したら一覧から外す。
-- 取引の上限は DB の側で掛けない（正本の sinceOverlap。書き手の取引の始まりは orders_write_horizon で返す）。
-- 移行は許す文の一覧だけを流す。DB の側でも 2 つで強制する（名前で許す例外は置かない）。
--   1. 事象のトリガー guard_migrate_ddl: 移行の接続（session_user が orders_migrate）の DDL は、CREATE TABLE・CREATE INDEX・ALTER TABLE だけ。
--      関数、トリガー、規則、スキーマ、見方、権限、方針、役割の変更は、ここで誤りになる。
--   2. 文のトリガー guard_no_migrate_dml: public の全部の表で、移行の接続の INSERT・UPDATE・DELETE・TRUNCATE を誤りにする。
--      足した表にも、事象のトリガー guard_new_table が同じトリガーを付け、移行の ALTER TABLE が守りを外したら文ごと戻す。移行の前後の行の指紋は、同時に動く書き手で揺れるので使わない。
--   3. 事象のトリガー guard_no_rewrite（table_rewrite）: 移行の接続の、表の書き直しを伴う ALTER TABLE を誤りにする。
--      型の付け直しの USING（ALTER COLUMN … TYPE … USING）、揮発の既定値や生成の列を足す文は、DML なしで全行の値を書き換える。
--      文のトリガーは書き直しでは動かず、スキーマの写しも型を変えなければ同じになるので、ここで止める。書き直しの要る移行は承認 2 人の経路。
--   4. 事象のトリガー guard_new_table（ddl_command_end）: 移行の接続の CREATE TABLE と ALTER TABLE の後の表の形を、許す形の一覧で確かめる
--      （guard.shape_problems）。継承と区分けは 0 件。指紋を取った列と制約は、名前・型・既定値・式のまま残す（足すだけ）。
--      足した列の既定値は短い定数（英小文字と数字の 32 字まで、数、真偽、時刻、順番）だけ。足した検査の制約は、変わらない関数だけを呼ぶ。
--      ALTER TABLE は許す文の型なので、型の中の INHERIT、RENAME、SET DEFAULT、pg_notify の制約を、文ではなく後の形で止める（第 13 回）。
--   5. plpgsql の USAGE を PUBLIC から外す。移行の接続は DO で文を組み立てられない（持ち主の役割へ切り替えても同じ）。
--      一覧の外の関数は、承認 2 人の経路で管理者が作り、持ち主へ渡す（ALTER FUNCTION … OWNER TO）。
-- 表の外の置き場（大きなオブジェクト）も置かせない。作る関数と書く関数の EXECUTE を PUBLIC から外し、突き合わせが件数 0 を確かめる。
--   大きなオブジェクトは表の行ではないので、文のトリガーも表の一覧の検査もスキーマの写しも数えない。
--   一覧の外の文（関数、トリガー、行の書き換え）は、利用者づくりの作業が承認 2 人の経路で、この file の前に持ち主の役割で流す。
--   この file が最後に指紋を取り直すので、そこが承認の点になる。
-- PUBLIC から権限を取り上げるのは、要る利用者へ明示で付け、取り残される入れる利用者がいないと確かめた後（cross-team 第 12 回の 1）。
-- 段 R の戻しは guard.rls_rollback（承認の記録と期限つき）だけを守りが受け付ける（cross-team 第 12 回の 2）。
-- 突き合わせ（guard.check_all）は、この file の最後と、移行の作業の最後（db/migrate-run.sh）と、毎時（pg_cron）に回す。
--   orders_api が実際に持つ権限（一員の役割を通した付与を含む）を表と列ごとに正本と比べる。public の全部の関数（トリガーの関数を含む）、
--   トリガー、事象のトリガー、スキーマ、方針、orders_api の設定の指紋を、この file が取った指紋と比べる。規則（pg_rewrite）は 0 本。
--   指紋は、取る所も比べる所も同じ関数 guard.current_fingerprints（search_path を固定）で取る。
--   毎時の回で違いを見つけたら、orders_api の入りを閉じて接続を切る（閉じる側。guardrails.tf の api-5xx が鳴る）。戻すのは、この file の流し直し。

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'orders_migrate') THEN
    CREATE ROLE orders_migrate LOGIN;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'orders_api') THEN
    CREATE ROLE orders_api LOGIN;
  END IF;
  -- orders_write_horizon の持ち主。入れない役割で、実行中の取引の始まりの時刻を読むためだけに pg_read_all_stats を持つ。
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'orders_horizon') THEN
    CREATE ROLE orders_horizon NOLOGIN;
  END IF;
END
$$;

GRANT rds_iam TO orders_migrate, orders_api;
GRANT pg_read_all_stats TO orders_horizon;
-- 管理者が orders_migrate の持つ物とスキーマに権限を付けられるよう、管理者を orders_migrate の一員にする（PostgreSQL 16）。
GRANT orders_migrate TO CURRENT_USER;

-- PUBLIC から取り上げる前に、要る利用者へ明示で付け、取り残される利用者がいないかを確かめる（cross-team 第 12 回の 1）。
--   旧い書き手（正本の otherRoles）と、入れる表の持ち主（旧 API の側）には、CONNECT と TEMPORARY とスキーマの USAGE を明示で付ける。
--   決済の通知や取り込みの一括のように、PUBLIC からだけ USAGE や TEMP を得ている書き手が、黙って止まるのを防ぐ。
--   ほかに PUBLIC の権限だけで入っている入れる利用者がいれば、取り上げる前に誤りで止める（正本の otherRoles に足すか、退役させる）。
--   2 回目からは PUBLIC がもう持たないので、この確かめは何も数えない。
DO $$
DECLARE
  other_roles text[] := ARRAY['legacy_api'];
  owner_name text;
  w text;
  stranded text;
BEGIN
  SELECT pg_get_userbyid(c.relowner) INTO owner_name FROM pg_class c
  JOIN pg_namespace n ON n.oid = c.relnamespace AND n.nspname = 'public' WHERE c.relname = 'orders';
  FOREACH w IN ARRAY other_roles || CASE WHEN owner_name IS NULL THEN ARRAY[]::text[] ELSE ARRAY[owner_name] END LOOP
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = w AND rolcanlogin AND NOT rolsuper) THEN
      EXECUTE format('GRANT CONNECT ON DATABASE orders TO %I', w);
      EXECUTE format('GRANT TEMPORARY ON DATABASE orders TO %I', w);
      EXECUTE format('GRANT USAGE ON SCHEMA public TO %I', w);
      EXECUTE format('REVOKE CREATE ON DATABASE orders FROM %I', w);
    ELSIF w = ANY (other_roles) THEN
      RAISE NOTICE 'other role % not found; skipped', w;
    END IF;
  END LOOP;
  GRANT CONNECT ON DATABASE orders TO orders_migrate, orders_api;
  GRANT USAGE ON SCHEMA public TO orders_api;
  -- PUBLIC が今も持つ権限（既定の空の ACL は PUBLIC が持つ）。
  WITH pub AS (
    SELECT p.priv FROM unnest(ARRAY['CONNECT', 'TEMPORARY']) AS p(priv), pg_database d
    WHERE d.datname = current_database()
      AND (d.datacl IS NULL OR EXISTS (SELECT 1 FROM aclexplode(d.datacl) a WHERE a.grantee = 0 AND a.privilege_type = p.priv))
    UNION ALL
    SELECT 'USAGE' FROM pg_namespace n WHERE n.nspname = 'public'
      AND (n.nspacl IS NULL OR EXISTS (SELECT 1 FROM aclexplode(n.nspacl) a WHERE a.grantee = 0 AND a.privilege_type = 'USAGE'))
  ), mine AS (
    SELECT a.grantee, a.privilege_type AS priv FROM pg_database d, aclexplode(d.datacl) a WHERE d.datname = current_database() AND a.grantee <> 0
    UNION ALL
    SELECT a.grantee, a.privilege_type FROM pg_namespace n, aclexplode(n.nspacl) a WHERE n.nspname = 'public' AND a.grantee <> 0
  )
  SELECT string_agg(DISTINCT r.rolname || ':' || pub.priv, ', ') INTO stranded
  FROM pg_roles r CROSS JOIN pub
  WHERE r.rolcanlogin AND NOT r.rolsuper AND r.rolname !~ '^(pg_|rds)' AND r.rolname <> current_user
    AND r.rolname NOT IN ('orders_api', 'orders_migrate', 'orders_horizon')
    -- この DB の表を使う利用者だけを数える（役割はクラスタ全体にあり、ほかの DB の利用者は CONNECT を失ってよい）。
    AND EXISTS (SELECT 1 FROM pg_class c JOIN pg_namespace s ON s.oid = c.relnamespace AND s.nspname = 'public'
                WHERE c.relkind IN ('r', 'p', 'v', 'm')
                  AND (has_table_privilege(r.oid, c.oid, 'SELECT, INSERT, UPDATE, DELETE, TRUNCATE')
                       OR has_any_column_privilege(r.oid, c.oid, 'SELECT, INSERT, UPDATE')))
    AND NOT EXISTS (SELECT 1 FROM mine m WHERE m.priv = pub.priv AND pg_has_role(r.oid, m.grantee, 'MEMBER'));
  IF stranded IS NOT NULL THEN
    RAISE EXCEPTION 'these login roles rely on PUBLIC privileges and would be cut off: %; add them to otherRoles in db-access.json or retire them first', stranded;
  END IF;
END
$$;

REVOKE ALL ON SCHEMA public FROM PUBLIC;
REVOKE ALL ON DATABASE orders FROM PUBLIC;
REVOKE CREATE ON DATABASE orders FROM orders_migrate, orders_api;
ALTER SCHEMA public OWNER TO orders_migrate;
-- 修飾しない表の名前は public だけで引く（既定の "$user" を外す。同じ名前のスキーマで表を隠させない）。
ALTER ROLE orders_api SET search_path = public;

-- 実行中の文（他の接続の要求と鍵のハッシュ）を見せる見方と関数を、PUBLIC から取り上げる。監視は Performance Insights で見る。
REVOKE SELECT ON pg_catalog.pg_stat_activity FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION pg_catalog.pg_stat_get_activity(integer) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION pg_catalog.pg_stat_get_backend_activity(integer) FROM PUBLIC;
-- orders_write_horizon の持ち主だけが、取引の始まりの時刻を読むために見方を読める（関数は時刻だけを返す）。
-- 見方の中の関数の EXECUTE は呼ぶ側（持ち主 orders_horizon）で確かめられる。PUBLIC から外したので、持ち主へ明示で付ける
-- （無いと一覧の要求ごとに「permission denied for function pg_stat_get_activity」で落ちる。最後の確かめで 1 回呼ぶ）。
GRANT SELECT ON pg_catalog.pg_stat_activity TO orders_horizon;
GRANT EXECUTE ON FUNCTION pg_catalog.pg_stat_get_activity(integer) TO orders_horizon;
DO $$
BEGIN
  IF has_table_privilege('orders_api', 'pg_catalog.pg_stat_activity', 'SELECT')
     OR has_function_privilege('orders_api', 'pg_catalog.pg_stat_get_activity(integer)', 'EXECUTE')
     OR has_function_privilege('orders_api', 'pg_catalog.pg_stat_get_backend_activity(integer)', 'EXECUTE') THEN
    RAISE EXCEPTION 'orders_api can still read running statements (pg_stat_activity); the key hashes of other requests would leak';
  END IF;
END
$$;

-- 大きなオブジェクト（表の外の置き場）を作る関数と書く関数を、PUBLIC から取り上げる。移行が全店の顧客を表の外へ写し、
-- 正本の行を消しても DB と保管庫に残る道を閉じる。取り上げが効かない環境では、下の確かめと最後の検査（検査 11）が止める。
REVOKE EXECUTE ON FUNCTION pg_catalog.lo_creat(integer), pg_catalog.lo_create(oid), pg_catalog.lo_from_bytea(oid, bytea),
  pg_catalog.lo_import(text), pg_catalog.lo_import(text, oid), pg_catalog.lo_put(oid, bigint, bytea), pg_catalog.lowrite(integer, bytea),
  pg_catalog.lo_truncate(integer, integer), pg_catalog.lo_truncate64(integer, bigint) FROM PUBLIC;
DO $$
BEGIN
  IF has_function_privilege('orders_migrate', 'pg_catalog.lo_from_bytea(oid, bytea)', 'EXECUTE')
     OR has_function_privilege('orders_migrate', 'pg_catalog.lo_create(oid)', 'EXECUTE')
     OR has_function_privilege('orders_api', 'pg_catalog.lo_from_bytea(oid, bytea)', 'EXECUTE') THEN
    RAISE EXCEPTION 'the migration or API user can still create large objects; copies outside the tables would not be counted';
  END IF;
END
$$;

-- 同じ DB の別の接続へ値を渡す関数を PUBLIC から取り上げる（第 15 回）。移行の文の SELECT pg_notify('c', (SELECT string_agg(name, ',')
-- FROM customers)) は、DDL でも行の書き込みでもないので、DB の守りの外で全店の氏名を LISTEN する接続へ渡せた（審査役の手元で通った）。
-- 助言のロックの番号も pg_locks で誰にでも見えるので、同じ型の道になる。要る利用者には明示で付ける（cross-team 第 12 回の 1 の順）:
--   旧い書き手（正本の otherRoles）には両方、orders_api には助言のロックだけ（前と同じ動き）。移行の利用者と表の持ち主には付けない。
--   orders_api が pg_notify を要るなら、正本の db-access.json に足してから付ける（横断事項）。NOTIFY の文は値を定数でしか書けないので残す。
DO $$
DECLARE
  other_roles text[] := ARRAY['legacy_api'];
  f regprocedure;
  w text;
BEGIN
  FOR f IN SELECT p.oid::regprocedure FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace AND n.nspname = 'pg_catalog'
           WHERE p.proname = 'pg_notify' OR p.proname ~ '^pg_(try_)?advisory_(xact_)?lock(_shared)?$' LOOP
    EXECUTE format('REVOKE EXECUTE ON FUNCTION %s FROM PUBLIC', f);
    FOREACH w IN ARRAY other_roles LOOP
      IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = w) THEN
        EXECUTE format('GRANT EXECUTE ON FUNCTION %s TO %I', f, w);
      END IF;
    END LOOP;
    IF f::text <> 'pg_notify(text,text)' THEN
      EXECUTE format('GRANT EXECUTE ON FUNCTION %s TO orders_api', f);
    END IF;
  END LOOP;
  IF has_function_privilege('orders_migrate', 'pg_catalog.pg_notify(text, text)', 'EXECUTE')
     OR has_function_privilege('orders_migrate', 'pg_catalog.pg_advisory_lock(bigint)', 'EXECUTE') THEN
    RAISE EXCEPTION 'the migration user can still pass values to other sessions (pg_notify or advisory locks)';
  END IF;
END
$$;

-- 移行の接続が DO で文を組み立てる道を閉じる。DO は plpgsql の USAGE を、そのときの役割（持ち主の役割へ切り替えた後も）で確かめる。
-- 管理者には明示で残す（この file の DO と毎時の回）。既にある plpgsql の関数を動かすのに USAGE は要らない。外せない環境では下の確かめが止める。
GRANT USAGE ON LANGUAGE plpgsql TO CURRENT_USER;
REVOKE USAGE ON LANGUAGE plpgsql FROM PUBLIC;
DO $$
DECLARE
  owner_name text;
BEGIN
  SELECT pg_get_userbyid(c.relowner) INTO owner_name FROM pg_class c
  JOIN pg_namespace n ON n.oid = c.relnamespace AND n.nspname = 'public' WHERE c.relname = 'orders';
  IF has_language_privilege('orders_migrate', 'plpgsql', 'USAGE') OR has_language_privilege('orders_api', 'plpgsql', 'USAGE')
     OR (owner_name IS NOT NULL AND has_language_privilege(owner_name, 'plpgsql', 'USAGE')) THEN
    RAISE EXCEPTION 'the migration, owner or API user can still run DO blocks (plpgsql USAGE); a migration could build statements from table data';
  END IF;
END
$$;

-- 関数の EXECUTE は既定で PUBLIC に付く。public の関数から外し、これから作る関数にも付けない。要る関数だけを名指しで渡す。
-- 表の持ち主が作る関数（トリガーの関数）にも同じ既定を置く（下の持ち主の段）。
REVOKE EXECUTE ON ALL FUNCTIONS IN SCHEMA public FROM PUBLIC;
ALTER DEFAULT PRIVILEGES FOR ROLE orders_migrate REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC;

-- 移行の利用者が作る表と順番に、orders_api の権限を自動で付けない（付けるのは下の一覧だけ）。
ALTER DEFAULT PRIVILEGES FOR ROLE orders_migrate IN SCHEMA public REVOKE ALL ON TABLES FROM orders_api;
ALTER DEFAULT PRIVILEGES FOR ROLE orders_migrate IN SCHEMA public REVOKE ALL ON SEQUENCES FROM orders_api;

-- 表の持ち主（正本の owner）。移さずに、移行の利用者と管理者を持ち主の役割の一員にする。持ち主が管理者か上の権限を持つ役割なら止める。
-- 持ち主には public の USAGE と CREATE を明示で付け、持ち主が作る関数の PUBLIC の EXECUTE を既定で外し、データベースの CREATE を外す。
DO $$
DECLARE
  want text[] := ARRAY['orders', 'order_items', 'order_events', 'customers', 'users', 'sessions', 'idempotency', 'shops'];
  o text;
BEGIN
  FOR o IN SELECT DISTINCT pg_get_userbyid(c.relowner) FROM pg_class c
           JOIN pg_namespace n ON n.oid = c.relnamespace AND n.nspname = 'public'
           WHERE c.relkind IN ('r', 'p') AND c.relname = ANY (want) LOOP
    CONTINUE WHEN o = 'orders_migrate';
    IF o = current_user OR EXISTS (SELECT 1 FROM pg_roles WHERE rolname = o AND (rolsuper OR rolcreaterole OR rolcreatedb OR rolbypassrls)) THEN
      RAISE EXCEPTION 'table owner % is an administrator; give the tables a plain owner role first', o;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'rds_superuser') THEN
      IF pg_has_role(o, 'rds_superuser', 'MEMBER') THEN
        RAISE EXCEPTION 'table owner % is a member of rds_superuser', o;
      END IF;
    END IF;
    EXECUTE format('GRANT %I TO orders_migrate', o);
    EXECUTE format('GRANT %I TO %I', o, current_user);
    EXECUTE format('GRANT USAGE, CREATE ON SCHEMA public TO %I', o);
    EXECUTE format('REVOKE CREATE ON DATABASE orders FROM %I', o);
    EXECUTE format('ALTER DEFAULT PRIVILEGES FOR ROLE %I REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC', o);
    EXECUTE format('ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA public REVOKE ALL ON TABLES FROM orders_api', o);
  END LOOP;
END
$$;

-- 突き合わせの置き場。管理者が持ち、移行の利用者は読むだけ（作る・変える・消すはできない）。
CREATE SCHEMA IF NOT EXISTS guard;
REVOKE ALL ON SCHEMA guard FROM PUBLIC;
GRANT USAGE ON SCHEMA guard TO orders_migrate;
CREATE TABLE IF NOT EXISTS guard.fingerprints (kind text NOT NULL, name text NOT NULL, fp text NOT NULL, PRIMARY KEY (kind, name));
REVOKE ALL ON guard.fingerprints FROM PUBLIC;
GRANT SELECT ON guard.fingerprints TO orders_migrate;
-- 段 R（行の制限を有効にする段）の戻しの記録（cross-team 第 12 回の 2）。戻しは表ごとに行の制限を外すが、守りとぶつからない形にする。
--   戻すのは管理者だけで、利用者づくりの作業（承認 2 人の経路）の中で guard.rls_rollback を呼ぶ。記録には承認の番号と別の 2 人と期限
--   （最長 7 日）を残す。期限の内は、毎時の検査（検査 3）と移行の DDL の後の確かめが、その表の行の制限の欠けを受け付ける。
--   期限が切れたら、毎時の検査が落ちて orders_api の入りを閉じる（閉じる側）。戻しを終えるのは guard.rls_restore か、この file の流し直し。
--   移行の接続はこの記録を書けず、手続きも呼べない。戻しの間は orders_api に全店の行が見えるので、API の文の店の条件だけが守る（段 R の前と同じ）。
CREATE TABLE IF NOT EXISTS guard.rls_waivers (
  tbl text PRIMARY KEY,
  approval text NOT NULL CHECK (approval ~ '^[A-Za-z0-9#/_.-]{3,80}$'),
  approvers text[] NOT NULL CHECK (cardinality(approvers) = 2 AND approvers[1] <> approvers[2]),
  created_at timestamptz NOT NULL DEFAULT now(),
  created_by text NOT NULL DEFAULT session_user,
  until timestamptz NOT NULL,
  CHECK (until > created_at AND until <= created_at + interval '7 days')
);
REVOKE ALL ON guard.rls_waivers FROM PUBLIC;
GRANT SELECT ON guard.rls_waivers TO orders_migrate;

CREATE OR REPLACE PROCEDURE guard.rls_rollback(t text, approval text, approvers text[], until timestamptz) LANGUAGE plpgsql
SET search_path = pg_catalog, pg_temp AS $p$
DECLARE
  want_rls text[] := ARRAY['orders', 'customers', 'idempotency', 'order_items', 'order_events', 'sessions', 'users'];
BEGIN
  IF session_user = 'orders_migrate' OR NOT (t = ANY (want_rls)) THEN
    RAISE EXCEPTION 'rls rollback is for the admin on the listed tables only';
  END IF;
  INSERT INTO guard.rls_waivers (tbl, approval, approvers, until) VALUES (t, approval, approvers, until)
  ON CONFLICT (tbl) DO UPDATE SET approval = EXCLUDED.approval, approvers = EXCLUDED.approvers, until = EXCLUDED.until,
    created_at = now(), created_by = session_user;
  EXECUTE format('ALTER TABLE public.%I DISABLE ROW LEVEL SECURITY', t);
END
$p$;
REVOKE ALL ON PROCEDURE guard.rls_rollback(text, text, text[], timestamptz) FROM PUBLIC;

CREATE OR REPLACE PROCEDURE guard.rls_restore(t text) LANGUAGE plpgsql SET search_path = pg_catalog, pg_temp AS $p$
BEGIN
  DELETE FROM guard.rls_waivers WHERE tbl = t;
  EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', t);
END
$p$;
REVOKE ALL ON PROCEDURE guard.rls_restore(text) FROM PUBLIC;

-- 前の作りの行の指紋（sessions と users だけを見ていた）は使わない。移行の行の書き込みは、下の文のトリガーで止める。
DROP FUNCTION IF EXISTS guard.rows_fingerprint();

-- 指紋を取る関数。取る所（この file の最後）と比べる所（guard.check_all）で同じ関数を使い、search_path を固定する。
-- 方針の条件の文字は search_path で変わる（public.app_key_shop() と app_key_shop()）。揃えないと、自分が残した指紋で落ちる。
CREATE OR REPLACE FUNCTION guard.current_fingerprints() RETURNS TABLE (kind text, name text, fp text)
LANGUAGE sql STABLE SET search_path = pg_catalog, pg_temp AS $f$
  SELECT 'policy', p.tablename::text || '.' || p.policyname::text, md5(concat_ws('|', p.permissive, p.roles::text, p.cmd, p.qual, p.with_check))
  FROM pg_policies p WHERE p.schemaname = 'public'
  UNION ALL
  -- public と guard の全部の関数（トリガーの関数を含む）。中身、SECURITY DEFINER、設定、持ち主、権限。名前で許す例外は置かない。
  SELECT 'function', p.oid::regprocedure::text,
         md5(concat_ws('|', p.prosrc, p.prosecdef, p.proconfig::text, pg_get_userbyid(p.proowner), p.prokind, p.provolatile, p.proacl::text))
  FROM pg_proc p JOIN pg_namespace s ON s.oid = p.pronamespace WHERE s.nspname IN ('public', 'guard')
  UNION ALL
  -- public の表のトリガー（名前、関数、有効の状態、定義）。
  SELECT 'trigger', c.relname::text || '.' || t.tgname::text,
         md5(concat_ws('|', t.tgfoid::regprocedure::text, t.tgenabled, t.tgtype, pg_get_triggerdef(t.oid)))
  FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid JOIN pg_namespace s ON s.oid = c.relnamespace AND s.nspname = 'public'
  WHERE NOT t.tgisinternal
  UNION ALL
  SELECT 'event_trigger', e.evtname::text,
         md5(concat_ws('|', e.evtevent, e.evtfoid::regprocedure::text, e.evtenabled, e.evttags::text, pg_get_userbyid(e.evtowner)))
  FROM pg_event_trigger e
  UNION ALL
  -- スキーマ（持ち主と権限）。新しいスキーマで表の名前を隠す手は、ここで一覧の外になる。
  SELECT 'schema', n.nspname::text, md5(concat_ws('|', pg_get_userbyid(n.nspowner), n.nspacl::text))
  FROM pg_namespace n WHERE n.nspname !~ '^pg_' AND n.nspname <> 'information_schema'
  UNION ALL
  SELECT 'role_setting', 'orders_api.' || d.setdatabase::text, md5(d.setconfig::text)
  FROM pg_db_role_setting d WHERE d.setrole = 'orders_api'::regrole
  UNION ALL
  -- public の表の列（名前、型、既定値）と制約（定義の全文）。足すのは許し、ある物の名前・型・既定値・式の変更と消し込みを止める
  -- （guard.shape_problems。検査 7 の外で、足すだけかを見る）。既定値の定数と制約の式（pg_notify）で他の店の行を写す道を、ここで数える。
  -- NOT NULL（attnotnull）も入れる。PostgreSQL 17 では NOT NULL が pg_constraint に入らないので、無いと DROP NOT NULL が指紋の外になる。
  SELECT 'column', c.relname::text || '.' || a.attname::text,
         md5(concat_ws('|', format_type(a.atttypid, a.atttypmod), pg_get_expr(d.adbin, d.adrelid), a.attnotnull))
  FROM pg_attribute a JOIN pg_class c ON c.oid = a.attrelid JOIN pg_namespace s ON s.oid = c.relnamespace AND s.nspname = 'public'
  LEFT JOIN pg_attrdef d ON d.adrelid = a.attrelid AND d.adnum = a.attnum
  WHERE c.relkind IN ('r', 'p') AND a.attnum > 0 AND NOT a.attisdropped
  UNION ALL
  SELECT 'constraint', c.relname::text || '.' || k.conname::text, md5(pg_get_constraintdef(k.oid))
  FROM pg_constraint k JOIN pg_class c ON c.oid = k.conrelid JOIN pg_namespace s ON s.oid = c.relnamespace AND s.nspname = 'public'
  UNION ALL
  -- 索引（名前と定義）。索引の名前も足した物の数に入れる（名前に値を埋めて渡す道を、足す数の上限で縛る）。
  SELECT 'index', c.relname::text, md5(pg_get_indexdef(c.oid))
  FROM pg_class c JOIN pg_namespace s ON s.oid = c.relnamespace AND s.nspname = 'public' WHERE c.relkind = 'i'
$f$;
REVOKE ALL ON FUNCTION guard.current_fingerprints() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION guard.current_fingerprints() TO orders_migrate;

-- 表の形の許す一覧（移行の DDL の後と、突き合わせの検査 12 で同じ関数を使う）。違いの一覧を返す。
--   継承と区分けは 0 件（子の表を親の表から読むと、子の表の行の制限が掛からず、親の方針だけが掛かる）。
--   指紋を取った列と制約は、名前・型・既定値・式のまま（RENAME、型の付け直し、SET DEFAULT、DROP は一覧の外。承認 2 人の経路）。
--   足した列の既定値は短い定数だけ（英小文字と数字の 32 字まで、数、真偽、時刻、順番）。DO で組み立てた長い定数も、ここで止まる。
--   足した検査の制約は、変わらない関数（provolatile が i）だけを呼ぶ（pg_notify、lo_、set_config のような働きのある関数を止める）。
--   足した検査の制約の中の文字の定数も、既定値と同じ型（英小文字と数字の 32 字まで）に縛る（第 14 回）。
--   指紋を取った後に足した列・制約・索引は、合わせて 12 個まで。名前は英小文字と数字の 40 字まで。列を分けて短い定数を並べる道と、
--   名前に値を埋める道を、数で縛る。12 個を超える移行は、利用者づくり（承認 2 人の経路。main の roles.sql）で指紋を取り直してから流す。
--   指紋を取った物のトリガー（有効の状態を含む）と索引も変えさせない（ALTER TABLE … DISABLE TRIGGER は ALTER TABLE の型の中にある）。
CREATE OR REPLACE FUNCTION guard.shape_problems() RETURNS text[] LANGUAGE plpgsql STABLE SET search_path = pg_catalog, pg_temp AS $f$
DECLARE
  n int;
  p text[] := ARRAY[]::text[];
BEGIN
  SELECT count(*) INTO n FROM pg_inherits i JOIN pg_class c ON c.oid IN (i.inhrelid, i.inhparent)
    JOIN pg_namespace s ON s.oid = c.relnamespace AND s.nspname = 'public';
  SELECT n + count(*) INTO n FROM pg_class c JOIN pg_namespace s ON s.oid = c.relnamespace AND s.nspname = 'public' WHERE c.relkind IN ('p', 'I');
  IF n > 0 THEN p := p || format('%s inheritance or partition link(s) on public tables', n); END IF;
  IF NOT EXISTS (SELECT 1 FROM guard.fingerprints WHERE kind = 'column') THEN
    RETURN p;  -- 指紋を取る前（移行の段 1 の前）。定数の既定値だけを migrate_ddl_end が確かめる
  END IF;
  SELECT count(*) INTO n FROM guard.fingerprints f LEFT JOIN guard.current_fingerprints() cur USING (kind, name)
  WHERE f.kind IN ('column', 'constraint', 'trigger', 'index') AND cur.fp IS DISTINCT FROM f.fp;
  IF n > 0 THEN
    p := p || format('%s column(s), constraint(s), trigger(s) or index(es) renamed, retyped, re-defaulted, disabled or dropped', n);
  END IF;
  SELECT count(*) INTO n FROM guard.current_fingerprints() cur
  WHERE cur.kind IN ('column', 'constraint', 'index')
    AND NOT EXISTS (SELECT 1 FROM guard.fingerprints f WHERE f.kind = cur.kind AND f.name = cur.name);
  IF n > 12 THEN p := p || format('%s columns, constraints and indexes added since the fingerprints (limit 12)', n); END IF;
  SELECT count(*) INTO n FROM guard.current_fingerprints() cur
  WHERE cur.kind IN ('column', 'constraint', 'index')
    AND NOT EXISTS (SELECT 1 FROM guard.fingerprints f WHERE f.kind = cur.kind AND f.name = cur.name)
    AND CASE WHEN cur.kind = 'index' THEN cur.name ELSE split_part(cur.name, '.', 2) END !~ '^[a-z][a-z0-9_]{0,39}$';
  IF n > 0 THEN p := p || format('%s added name(s) outside the short lower-case form', n); END IF;
  SELECT count(*) INTO n FROM pg_constraint k JOIN pg_class c ON c.oid = k.conrelid
    JOIN pg_namespace s ON s.oid = c.relnamespace AND s.nspname = 'public'
    CROSS JOIN LATERAL regexp_matches(pg_get_constraintdef(k.oid), '''((?:[^'']|'''')*)''', 'g') AS m(lit)
  WHERE NOT EXISTS (SELECT 1 FROM guard.fingerprints g WHERE g.kind = 'constraint' AND g.name = c.relname::text || '.' || k.conname::text)
    AND m.lit[1] !~ '^[a-z0-9_]{0,32}$';
  IF n > 0 THEN p := p || format('%s string constant(s) in added constraints outside the short-constant form', n); END IF;
  SELECT count(*) INTO n FROM pg_attrdef d JOIN pg_class c ON c.oid = d.adrelid
    JOIN pg_namespace s ON s.oid = c.relnamespace AND s.nspname = 'public'
    JOIN pg_attribute a ON a.attrelid = d.adrelid AND a.attnum = d.adnum
  WHERE NOT EXISTS (SELECT 1 FROM guard.fingerprints f WHERE f.kind = 'column' AND f.name = c.relname::text || '.' || a.attname::text)
    AND pg_get_expr(d.adbin, d.adrelid) !~ '^(NULL|true|false|-?[0-9]{1,18}(\.[0-9]{1,18})?|now\(\)|CURRENT_TIMESTAMP|''[a-z0-9_]{0,32}''::[a-z ]+|nextval\(''[a-z0-9_.]+''::regclass\))$';
  IF n > 0 THEN p := p || format('%s added column default(s) outside the short-constant form', n); END IF;
  SELECT count(*) INTO n FROM pg_constraint k JOIN pg_class c ON c.oid = k.conrelid
    JOIN pg_namespace s ON s.oid = c.relnamespace AND s.nspname = 'public'
    CROSS JOIN LATERAL regexp_matches(pg_get_constraintdef(k.oid), '([A-Za-z_][A-Za-z0-9_$]*|"[^"]+")\s*\(', 'g') AS m(f)
  WHERE k.contype = 'c'
    AND NOT EXISTS (SELECT 1 FROM guard.fingerprints g WHERE g.kind = 'constraint' AND g.name = c.relname::text || '.' || k.conname::text)
    AND EXISTS (SELECT 1 FROM pg_proc pr WHERE pr.provolatile <> 'i'
                AND pr.proname = CASE WHEN m.f[1] LIKE '"%' THEN btrim(m.f[1], '"') ELSE lower(m.f[1]) END);
  IF n > 0 THEN p := p || format('%s added check constraint call(s) to functions that are not immutable', n); END IF;
  RETURN p;
END
$f$;
REVOKE ALL ON FUNCTION guard.shape_problems() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION guard.shape_problems() TO orders_migrate;

-- 移行の接続の行の書き込みを止める（文のトリガー）。移行は行を書かない（正本の writers の migration）。
-- session_user は SET ROLE で変わらないので、持ち主の役割で流しても移行の接続と分かる。旧 API と API の書き込みは通る。
CREATE OR REPLACE FUNCTION guard.no_migrate_dml() RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog, pg_temp AS $f$
BEGIN
  IF session_user = 'orders_migrate' THEN
    RAISE EXCEPTION 'a migration must not write rows (% on %.%)', TG_OP, TG_TABLE_SCHEMA, TG_TABLE_NAME;
  END IF;
  RETURN NULL;
END
$f$;
REVOKE ALL ON FUNCTION guard.no_migrate_dml() FROM PUBLIC;

-- 移行の接続の表の書き直しを止める（事象のトリガー table_rewrite）。ALTER TABLE は許す型だが、書き直しを伴う形（型の付け直しの USING、
-- 揮発の既定値、生成の列、SET EXPRESSION）は、DML なしで全行の値を書き換える。持ち主の役割で動くので RLS も受けない。
-- 書き直しは pg_event_trigger_table_rewrite_oid で表が分かる時点（書き直しの前）に止まり、文ごと戻る。
CREATE OR REPLACE FUNCTION guard.migrate_no_rewrite() RETURNS event_trigger LANGUAGE plpgsql SET search_path = pg_catalog, pg_temp AS $f$
BEGIN
  IF session_user = 'orders_migrate' THEN
    RAISE EXCEPTION 'a migration must not rewrite a table (% on %); use the guarded route', tg_tag, pg_event_trigger_table_rewrite_oid()::regclass;
  END IF;
END
$f$;
REVOKE ALL ON FUNCTION guard.migrate_no_rewrite() FROM PUBLIC;

-- 移行の接続の DDL は、許す文の型だけ（CREATE TABLE、CREATE INDEX、ALTER TABLE）。ほかの型はここで誤りになる。
-- 守りの関数が自分で流す DDL（足した表へのトリガー）は、current_user が守りの持ち主なので通す。
CREATE OR REPLACE FUNCTION guard.migrate_ddl_gate() RETURNS event_trigger LANGUAGE plpgsql SET search_path = pg_catalog, pg_temp AS $f$
BEGIN
  IF session_user = 'orders_migrate'
     AND current_user <> (SELECT pg_get_userbyid(n.nspowner) FROM pg_namespace n WHERE n.nspname = 'guard')
     AND tg_tag NOT IN ('CREATE TABLE', 'CREATE INDEX', 'ALTER TABLE') THEN
    RAISE EXCEPTION 'migration statement % is outside the allow list; use the guarded route', tg_tag;
  END IF;
END
$f$;
REVOKE ALL ON FUNCTION guard.migrate_ddl_gate() FROM PUBLIC;

-- DDL の後の確かめ（ALTER TABLE と CREATE TABLE の後）。足した public の表に、行の書き込みを止めるトリガーを付ける。
-- 移行の接続なら、文の後の形も確かめ、外れていればその文ごと戻す。止めるのは次の 3 つ。
--   守りのトリガーを外すか無効にする（ALTER TABLE … DISABLE TRIGGER の後に行を書く手）。行の制限を外す。
--   列の既定値に、定数と時刻と順番のほかの式を置く（既定値の関数で、表を書き直すときに他の行を写す手）。
CREATE OR REPLACE FUNCTION guard.migrate_ddl_end() RETURNS event_trigger LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, pg_temp AS $f$
DECLARE
  o record;
  want_rls text[] := ARRAY['orders', 'customers', 'idempotency', 'order_items', 'order_events', 'sessions', 'users'];
BEGIN
  FOR o IN SELECT * FROM pg_event_trigger_ddl_commands() WHERE command_tag = 'CREATE TABLE' AND object_type = 'table'
           AND schema_name = 'public' LOOP
    EXECUTE format('CREATE TRIGGER guard_no_migrate_dml BEFORE INSERT OR UPDATE OR DELETE OR TRUNCATE ON %s'
                   ' FOR EACH STATEMENT EXECUTE FUNCTION guard.no_migrate_dml()', o.object_identity);
  END LOOP;
  IF session_user <> 'orders_migrate' THEN
    RETURN;
  END IF;
  IF EXISTS (SELECT 1 FROM pg_class c JOIN pg_namespace s ON s.oid = c.relnamespace AND s.nspname = 'public'
             WHERE c.relkind IN ('r', 'p') AND NOT EXISTS (
               SELECT 1 FROM pg_trigger t WHERE t.tgrelid = c.oid AND t.tgname = 'guard_no_migrate_dml' AND t.tgenabled IN ('O', 'A')))
     OR EXISTS (SELECT 1 FROM pg_class c JOIN pg_namespace s ON s.oid = c.relnamespace AND s.nspname = 'public'
                WHERE c.relname = ANY (want_rls) AND NOT c.relrowsecurity
                  AND NOT EXISTS (SELECT 1 FROM guard.rls_waivers v WHERE v.tbl = c.relname AND v.until > now()))
     OR EXISTS (SELECT 1 FROM pg_attrdef d JOIN pg_class c ON c.oid = d.adrelid
                JOIN pg_namespace s ON s.oid = c.relnamespace AND s.nspname = 'public'
                WHERE pg_get_expr(d.adbin, d.adrelid) !~ '^(''[^'']*''(::[a-z ]+)?|-?[0-9.]+|NULL|true|false|now\(\)|CURRENT_TIMESTAMP|nextval\(''[a-z_.]+''::regclass\))$') THEN
    RAISE EXCEPTION 'migration statement % turned off a guard (trigger, row-level security or a non-constant default)', tg_tag;
  END IF;
  IF cardinality(guard.shape_problems()) > 0 THEN
    RAISE EXCEPTION 'migration statement % left the table shape outside the allow list (%); use the guarded route', tg_tag,
      array_to_string(guard.shape_problems(), '; ');
  END IF;
END
$f$;
REVOKE ALL ON FUNCTION guard.migrate_ddl_end() FROM PUBLIC;

DROP EVENT TRIGGER IF EXISTS guard_migrate_ddl;
CREATE EVENT TRIGGER guard_migrate_ddl ON ddl_command_start EXECUTE FUNCTION guard.migrate_ddl_gate();
DROP EVENT TRIGGER IF EXISTS guard_new_table;
-- CREATE INDEX も後の形を確かめる（第 14 回。索引の名前と数も、足した物の上限に入る）。
CREATE EVENT TRIGGER guard_new_table ON ddl_command_end WHEN TAG IN ('CREATE TABLE', 'ALTER TABLE', 'CREATE INDEX') EXECUTE FUNCTION guard.migrate_ddl_end();
DROP EVENT TRIGGER IF EXISTS guard_no_rewrite;
CREATE EVENT TRIGGER guard_no_rewrite ON table_rewrite EXECUTE FUNCTION guard.migrate_no_rewrite();

-- 突き合わせの本体。呼んだ利用者の権限で動き、目録だけを読む。違いが 1 つでもあれば誤りで止める。
CREATE OR REPLACE PROCEDURE guard.check_all() LANGUAGE plpgsql SET search_path = pg_catalog, pg_temp AS $chk$
DECLARE
  -- 正本の表の一覧（8 表）。shops は権限なし（rows が none）。
  want text[] := ARRAY['orders', 'order_items', 'order_events', 'customers', 'users', 'sessions', 'idempotency', 'shops'];
  -- 表の単位の権限（表:操作）。読むことと消すこと。
  want_table text[] := ARRAY[
    'orders:SELECT', 'order_items:SELECT', 'order_events:SELECT', 'customers:SELECT', 'users:SELECT', 'sessions:SELECT',
    'idempotency:SELECT', 'idempotency:DELETE'
  ];
  -- 列の単位の権限（表:操作:列）。入れてよい列と、書き換えてよい列。
  want_cols text[] := ARRAY[
    'orders:UPDATE:status', 'orders:UPDATE:is_cancelled', 'orders:UPDATE:shipped_by', 'orders:UPDATE:shipped_at', 'orders:UPDATE:cancelled_by',
    'orders:UPDATE:cancelled_at',
    'order_events:INSERT:order_id', 'order_events:INSERT:at', 'order_events:INSERT:kind', 'order_events:INSERT:actor',
    'idempotency:INSERT:shop_id', 'idempotency:INSERT:user_id', 'idempotency:INSERT:key', 'idempotency:INSERT:request_sha256',
    'idempotency:INSERT:status', 'idempotency:INSERT:body', 'idempotency:INSERT:created_at',
    'idempotency:UPDATE:status', 'idempotency:UPDATE:body'
  ];
  -- 行の制限を掛ける表（鍵の表は鍵のハッシュで、店の列の表は鍵から引いた店で、子の表は親の表で絞る）。
  want_rls text[] := ARRAY['orders', 'customers', 'idempotency', 'order_items', 'order_events', 'sessions', 'users'];
  -- orders_api が呼べる関数（EXECUTE の一覧）。関数そのものは、名前ではなく指紋（検査 7）で比べる。
  want_functions text[] := ARRAY['app_key_shop', 'orders_write_horizon'];
  other_roles text[] := ARRAY['legacy_api'];
  owner_oid oid;
  n int;
  problems text[] := ARRAY[]::text[];
BEGIN
  IF (SELECT count(*) FROM pg_tables WHERE schemaname = 'public' AND tablename = ANY (want)) < array_length(want, 1) THEN
    IF EXISTS (SELECT 1 FROM guard.fingerprints) THEN
      RAISE EXCEPTION 'db-guard-check failed: tables of db-access.json are missing';
    END IF;
    RAISE NOTICE 'tables not ready; guard check skipped';
    RETURN;
  END IF;
  SELECT c.relowner INTO owner_oid FROM pg_class c JOIN pg_namespace s ON s.oid = c.relnamespace AND s.nspname = 'public'
  WHERE c.relname = 'orders';

  -- 検査 1: orders_api が実際に持つ権限を、表と列と順番ごとに正本と比べる。一員の役割（rds_iam など）を通した付与も数える。
  SELECT count(*) INTO n FROM pg_class c JOIN pg_namespace s ON s.oid = c.relnamespace AND s.nspname = 'public'
    CROSS JOIN unnest(ARRAY['SELECT', 'INSERT', 'UPDATE', 'DELETE', 'TRUNCATE', 'REFERENCES', 'TRIGGER']) AS p(priv)
  WHERE c.relkind IN ('r', 'p', 'v', 'm', 'f')
    AND has_table_privilege('orders_api', c.oid, p.priv) IS DISTINCT FROM (c.relname || ':' || p.priv = ANY (want_table));
  SELECT n + count(*) INTO n FROM pg_attribute att JOIN pg_class c ON c.oid = att.attrelid
    JOIN pg_namespace s ON s.oid = c.relnamespace AND s.nspname = 'public'
    CROSS JOIN unnest(ARRAY['SELECT', 'INSERT', 'UPDATE', 'REFERENCES']) AS p(priv)
  WHERE c.relkind IN ('r', 'p', 'v', 'm', 'f') AND att.attnum > 0 AND NOT att.attisdropped
    AND has_column_privilege('orders_api', c.oid, att.attnum, p.priv) IS DISTINCT FROM
        (c.relname || ':' || p.priv = ANY (want_table) OR c.relname || ':' || p.priv || ':' || att.attname = ANY (want_cols));
  SELECT n + count(*) INTO n FROM pg_class c JOIN pg_namespace s ON s.oid = c.relnamespace AND s.nspname = 'public'
  WHERE c.relkind = 'S' AND (has_sequence_privilege('orders_api', c.oid, 'USAGE') OR has_sequence_privilege('orders_api', c.oid, 'UPDATE'));
  IF n > 0 THEN problems := problems || format('%s privilege(s) of orders_api differ from db-access.json (member roles included)', n); END IF;
  -- PUBLIC と、既定の役割と rds の役割（名前が pg_ か rds で始まる）への付与は、public の表と列に置かない。
  SELECT count(*) INTO n FROM pg_class c JOIN pg_namespace s ON s.oid = c.relnamespace AND s.nspname = 'public',
    LATERAL aclexplode(c.relacl) a
  WHERE a.grantee = 0 OR pg_get_userbyid(a.grantee) ~ '^(pg_|rds)';
  SELECT n + count(*) INTO n FROM pg_attribute att JOIN pg_class c ON c.oid = att.attrelid
    JOIN pg_namespace s ON s.oid = c.relnamespace AND s.nspname = 'public', LATERAL aclexplode(att.attacl) a
  WHERE a.grantee = 0 OR pg_get_userbyid(a.grantee) ~ '^(pg_|rds)';
  IF n > 0 THEN problems := problems || format('%s grant(s) to PUBLIC or to pg_/rds roles on public tables', n); END IF;
  -- 検査 2: orders_api の属性と一員。rds_iam のほかの役割の一員にしない（間接の一員と、表の持ち主の一員を含む）。
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'orders_api' AND (rolsuper OR rolcreaterole OR rolcreatedb OR rolbypassrls))
     OR EXISTS (SELECT 1 FROM pg_roles g WHERE g.rolname NOT IN ('orders_api', 'rds_iam') AND pg_has_role('orders_api', g.oid, 'MEMBER')) THEN
    problems := problems || 'orders_api has extra role attributes or memberships'::text;
  END IF;
  -- 検査 3: 行の制限を掛ける表は RLS が有効で、店の分離か鍵の方針がある。方針は orders_api と旧い書き手の全行の方針だけ。
  --   段 R の戻しの記録（guard.rls_waivers。承認の番号と別の 2 人と期限）が期限の内なら、その表の RLS の欠けだけを受け付ける。
  SELECT count(*) INTO n FROM unnest(want_rls) AS w(tbl) JOIN pg_class k ON k.relname = w.tbl
    JOIN pg_namespace s ON s.oid = k.relnamespace AND s.nspname = 'public'
  WHERE (NOT k.relrowsecurity AND NOT EXISTS (SELECT 1 FROM guard.rls_waivers v WHERE v.tbl = w.tbl AND v.until > now()))
     OR NOT EXISTS (SELECT 1 FROM pg_policies p WHERE p.schemaname = 'public' AND p.tablename = w.tbl AND p.policyname IN ('shop_isolation', 'key_only'));
  IF n > 0 THEN problems := problems || format('row-level isolation missing on %s table(s)', n); END IF;
  -- 検査 4: 全店を見る値（shop_scope）と、API の書ける店の値（app.shop_id）に触れる方針が無い。
  IF EXISTS (SELECT 1 FROM pg_policies p WHERE p.schemaname = 'public'
             AND (p.qual LIKE '%shop_scope%' OR p.with_check LIKE '%shop_scope%' OR p.qual LIKE '%app.shop_id%' OR p.with_check LIKE '%app.shop_id%')) THEN
    problems := problems || 'a policy uses app.shop_scope or app.shop_id'::text;
  END IF;
  -- 検査 5: public の表・見方は正本の一覧だけ（RLS の無い写しの表を置かない）。利用者のスキーマは public と guard と cron だけ
  --   （持ち主を問わない。orders_api と同じ名のスキーマで、修飾しない表の名前を隠す手を止める）。
  SELECT count(*) INTO n FROM pg_class c JOIN pg_namespace s ON s.oid = c.relnamespace AND s.nspname = 'public'
  WHERE c.relkind IN ('r', 'p', 'v', 'm', 'f') AND NOT (c.relname = ANY (want));
  SELECT n + count(*) INTO n FROM pg_namespace s
  WHERE s.nspname !~ '^pg_' AND s.nspname NOT IN ('information_schema', 'public', 'guard', 'cron');
  IF n > 0 THEN problems := problems || format('%s table(s), view(s) or schema(s) outside db-access.json', n); END IF;
  -- 検査 6: 関数と規則とトリガー。PUBLIC の EXECUTE（proacl が空なら既定の PUBLIC）は 0。orders_api が呼べるのは一覧の関数だけ。
  --   規則（pg_rewrite）は 0 本。規則は表の持ち主の権限で動き RLS を受けないので、置かない。
  --   public の全部の表に、移行の行の書き込みを止めるトリガーがあり、有効である。事象のトリガー 3 つ（DDL の型、足した表、書き直し）も有効である。
  SELECT count(*) INTO n FROM pg_proc p JOIN pg_namespace s ON s.oid = p.pronamespace AND s.nspname = 'public',
    LATERAL aclexplode(coalesce(p.proacl, acldefault('f', p.proowner))) a
  WHERE a.grantee = 0;
  SELECT n + count(*) INTO n FROM pg_proc p JOIN pg_namespace s ON s.oid = p.pronamespace AND s.nspname = 'public'
  WHERE has_function_privilege('orders_api', p.oid, 'EXECUTE') IS DISTINCT FROM (p.proname = ANY (want_functions));
  IF n > 0 THEN problems := problems || format('%s function(s) or EXECUTE grants outside the list', n); END IF;
  SELECT count(*) INTO n FROM pg_rewrite r JOIN pg_class c ON c.oid = r.ev_class
    JOIN pg_namespace s ON s.oid = c.relnamespace AND s.nspname = 'public'
  WHERE r.rulename <> '_RETURN';
  IF n > 0 THEN problems := problems || format('%s rule(s) on public tables', n); END IF;
  SELECT count(*) INTO n FROM pg_class c JOIN pg_namespace s ON s.oid = c.relnamespace AND s.nspname = 'public'
  WHERE c.relkind IN ('r', 'p') AND NOT EXISTS (
    SELECT 1 FROM pg_trigger t WHERE t.tgrelid = c.oid AND t.tgname = 'guard_no_migrate_dml' AND t.tgenabled IN ('O', 'A')
      AND t.tgfoid = 'guard.no_migrate_dml()'::regprocedure);
  SELECT n + 3 - count(*) INTO n FROM pg_event_trigger e
  WHERE e.evtname IN ('guard_migrate_ddl', 'guard_new_table', 'guard_no_rewrite') AND e.evtenabled IN ('O', 'A');
  IF n > 0 THEN problems := problems || format('%s migration guard trigger(s) missing or disabled', n); END IF;
  -- 検査 7: 指紋（方針、public と guard の全部の関数、トリガー、事象のトリガー、スキーマ、orders_api の設定）が、この file の取った指紋と同じ。
  --   ALTER POLICY、CREATE OR REPLACE（トリガーの関数を含む）、トリガーの足し引きと無効化、スキーマの足し算は、名前が残っても止まる。
  SELECT count(*) INTO n FROM guard.current_fingerprints() cur FULL JOIN guard.fingerprints f USING (kind, name)
  WHERE cur.fp IS DISTINCT FROM f.fp AND coalesce(f.kind, cur.kind) NOT IN ('column', 'constraint', 'index');
  IF n > 0 THEN problems := problems || format('%s fingerprint(s) changed (policy, function, trigger, schema or setting)', n); END IF;
  -- 検査 8: 表の持ち主は、移行の利用者か、移行の利用者が一員の役割（正本の owner）。持ち主は public の USAGE を持つ
  --   （無いと、持ち主の権限で動く app_key_shop と外部キーの確かめが落ちる）。
  SELECT count(*) INTO n FROM pg_class c JOIN pg_namespace s ON s.oid = c.relnamespace AND s.nspname = 'public'
  WHERE c.relkind IN ('r', 'p') AND NOT pg_has_role('orders_migrate', c.relowner, 'USAGE');
  IF n > 0 THEN problems := problems || format('%s table(s) owned outside the migration owner', n); END IF;
  IF NOT has_schema_privilege(owner_oid, 'public', 'USAGE') THEN
    problems := problems || 'the table owner has no USAGE on schema public'::text;
  END IF;
  -- 検査 9: 書き手ごとの方針（cross-team の 1 と第 11 回）。表か列の権限を持つ役割のうち、orders_api と持ち主の外は、全行の方針
  --   （FOR ALL の USING (true)）と、データベースの CONNECT を持つこと。方針が無いと、旧い書き手の読みが 0 行、UPDATE が黙って 0 行になる。
  --   列の単位でしか権限を持たない書き手も数える（has_any_column_privilege は表の単位の権限も含む）。全行の方針は旧い書き手の一覧の外に付けない。
  SELECT count(*) INTO n FROM unnest(want_rls) AS w(tbl) JOIN pg_class c ON c.relname = w.tbl
    JOIN pg_namespace s ON s.oid = c.relnamespace AND s.nspname = 'public' CROSS JOIN pg_roles g
  WHERE g.rolname <> 'orders_api' AND g.rolname !~ '^(pg_|rds)' AND NOT g.rolsuper AND NOT g.rolbypassrls
    AND NOT pg_has_role(g.oid, c.relowner, 'USAGE')
    AND (has_any_column_privilege(g.oid, c.oid, 'SELECT') OR has_any_column_privilege(g.oid, c.oid, 'INSERT')
         OR has_any_column_privilege(g.oid, c.oid, 'UPDATE') OR has_table_privilege(g.oid, c.oid, 'DELETE'))
    AND (NOT has_database_privilege(g.oid, current_database(), 'CONNECT')
         OR NOT EXISTS (SELECT 1 FROM pg_policy p WHERE p.polrelid = c.oid AND p.polpermissive AND p.polcmd = '*'
                        AND g.oid = ANY (p.polroles) AND pg_get_expr(p.polqual, p.polrelid) = 'true'));
  SELECT n + count(*) INTO n FROM pg_policy p JOIN pg_class c ON c.oid = p.polrelid, unnest(p.polroles) AS r(oid)
  WHERE p.polname = 'other_roles_all'
    AND (r.oid = 0 OR NOT (pg_get_userbyid(r.oid) = ANY (other_roles) OR pg_has_role(r.oid, c.relowner, 'USAGE')));
  IF n > 0 THEN problems := problems || format('%s writer(s) without an all-rows policy or outside the list', n); END IF;
  -- 検査 10: 実行中の文を見せる見方を orders_api が読めない。orders_api の search_path は public だけ。書き手と持ち主はデータベースに
  --   スキーマを作れない（CREATE）。
  IF has_table_privilege('orders_api', 'pg_catalog.pg_stat_activity', 'SELECT')
     OR has_function_privilege('orders_api', 'pg_catalog.pg_stat_get_activity(integer)', 'EXECUTE') THEN
    problems := problems || 'orders_api can read pg_stat_activity'::text;
  END IF;
  IF NOT has_function_privilege('orders_horizon', 'pg_catalog.pg_stat_get_activity(integer)', 'EXECUTE') THEN
    problems := problems || 'orders_horizon cannot call pg_stat_get_activity (orders_write_horizon would fail on every list request)'::text;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_db_role_setting d WHERE d.setrole = 'orders_api'::regrole AND d.setdatabase = 0
                 AND 'search_path=public' = ANY (d.setconfig)) THEN
    problems := problems || 'orders_api search_path is not fixed to public'::text;
  END IF;
  SELECT count(*) INTO n FROM pg_roles g
  WHERE (g.rolname IN ('orders_api', 'orders_migrate') OR g.rolname = ANY (other_roles) OR g.oid = owner_oid)
    AND has_database_privilege(g.oid, current_database(), 'CREATE');
  IF n > 0 THEN problems := problems || format('%s writer or owner role(s) can create schemas in this database', n); END IF;
  -- 検査 11: 表の外の置き場。大きなオブジェクトは 0 件で、移行と API の利用者は作れない。
  SELECT count(*) INTO n FROM pg_catalog.pg_largeobject_metadata;
  IF n > 0 THEN problems := problems || format('%s large object(s) outside the tables', n); END IF;
  IF has_function_privilege('orders_migrate', 'pg_catalog.lo_from_bytea(oid, bytea)', 'EXECUTE')
     OR has_function_privilege('orders_migrate', 'pg_catalog.lo_create(oid)', 'EXECUTE')
     OR has_function_privilege('orders_api', 'pg_catalog.lo_from_bytea(oid, bytea)', 'EXECUTE') THEN
    problems := problems || 'the migration or API user can create large objects'::text;
  END IF;

  -- 検査 12: 表の形（継承と区分けは 0、指紋の列と制約は足すだけ、足した既定値と制約は許す形）と、DO の取り上げ（第 13 回）。
  problems := problems || guard.shape_problems();
  IF has_language_privilege('orders_migrate', 'plpgsql', 'USAGE') OR has_language_privilege('orders_api', 'plpgsql', 'USAGE')
     OR has_language_privilege(owner_oid, 'plpgsql', 'USAGE') THEN
    problems := problems || 'the migration, owner or API user can run DO blocks (plpgsql USAGE)'::text;
  END IF;

  -- 検査 13（第 15 回）: 別の接続へ値を渡す関数（pg_notify と助言のロック）を、移行の利用者と表の持ち主が呼べない。
  --   この DB に入れる上の利用者と、行の制限を素通りする利用者（BYPASSRLS）は、初めの上の利用者と rdsadmin と守りの持ち主（管理者）だけ。
  --   権限を付けない LOGIN BYPASSRLS の役割も数える（後で読む権限を付ければ、全店の行が見えるため）。
  SELECT count(*) INTO n FROM pg_proc p JOIN pg_namespace s ON s.oid = p.pronamespace AND s.nspname = 'pg_catalog'
    CROSS JOIN (VALUES ('orders_migrate'::regrole::oid), (owner_oid)) AS r(oid)
  WHERE (p.proname = 'pg_notify' OR p.proname ~ '^pg_(try_)?advisory_(xact_)?lock(_shared)?$')
    AND has_function_privilege(r.oid, p.oid, 'EXECUTE');
  IF n > 0 THEN problems := problems || format('%s session-to-session function grant(s) for the migration user or owner (pg_notify, advisory locks)', n); END IF;
  --   入れる利用者が一員として SET ROLE できる役割も数える（一員の側は上の利用者と管理者を除く。上の利用者はどの役割の一員にも見える）。
  SELECT count(*) INTO n FROM pg_roles g
  WHERE (g.rolsuper OR g.rolbypassrls) AND g.oid <> 10 AND g.rolname <> 'rdsadmin'
    AND g.oid <> (SELECT n2.nspowner FROM pg_namespace n2 WHERE n2.nspname = 'guard')
    AND ((g.rolcanlogin AND has_database_privilege(g.oid, current_database(), 'CONNECT'))
         OR EXISTS (SELECT 1 FROM pg_roles l WHERE l.rolcanlogin AND NOT l.rolsuper AND l.oid <> g.oid
                      AND l.oid <> (SELECT n3.nspowner FROM pg_namespace n3 WHERE n3.nspname = 'guard')
                      AND pg_has_role(l.oid, g.oid, 'MEMBER') AND has_database_privilege(l.oid, current_database(), 'CONNECT')));
  IF n > 0 THEN problems := problems || format('%s login role(s) that bypass row-level security or are superusers', n); END IF;

  IF array_length(problems, 1) > 0 THEN
    RAISE EXCEPTION 'db-guard-check failed: %', array_to_string(problems, '; ');
  END IF;
END
$chk$;
REVOKE ALL ON PROCEDURE guard.check_all() FROM PUBLIC;
GRANT EXECUTE ON PROCEDURE guard.check_all() TO orders_migrate;

-- 表がまだ無い最初の 1 回は、権限の付与と検査を飛ばす（移行の段 1 の後にもう一度流す）。
DO $$
DECLARE
  t text;
  -- 正本の表の一覧（8 表）。
  want text[] := ARRAY['orders', 'order_items', 'order_events', 'customers', 'users', 'sessions', 'idempotency', 'shops'];
  want_rls text[] := ARRAY['orders', 'customers', 'idempotency', 'order_items', 'order_events', 'sessions', 'users'];
  other_roles text[] := ARRAY['legacy_api'];
  owner_name text;
  all_rows text;
BEGIN
  IF (SELECT count(*) FROM pg_tables WHERE schemaname = 'public' AND tablename = ANY (want)) < array_length(want, 1) THEN
    RAISE NOTICE 'tables not ready; grants skipped';
    RETURN;
  END IF;
  SELECT pg_get_userbyid(c.relowner) INTO owner_name FROM pg_class c
  JOIN pg_namespace n ON n.oid = c.relnamespace AND n.nspname = 'public' WHERE c.relname = 'orders';

  EXECUTE 'REVOKE ALL ON ALL TABLES IN SCHEMA public FROM orders_api';
  EXECUTE 'REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM orders_api';
  FOREACH t IN ARRAY want LOOP
    EXECUTE format('REVOKE ALL (%s) ON public.%I FROM orders_api',
      (SELECT string_agg(quote_ident(attname), ', ') FROM pg_attribute
       WHERE attrelid = format('public.%I', t)::regclass AND attnum > 0 AND NOT attisdropped), t);
  END LOOP;

  -- 権限（正本の select・insert・update・delete と同じ）。
  EXECUTE 'GRANT SELECT ON public.orders TO orders_api';
  EXECUTE 'GRANT UPDATE (status, is_cancelled, shipped_by, shipped_at, cancelled_by, cancelled_at) ON public.orders TO orders_api';
  EXECUTE 'GRANT SELECT ON public.order_items TO orders_api';
  EXECUTE 'GRANT SELECT ON public.order_events TO orders_api';
  EXECUTE 'GRANT INSERT (order_id, at, kind, actor) ON public.order_events TO orders_api';
  EXECUTE 'GRANT SELECT ON public.customers TO orders_api';
  EXECUTE 'GRANT SELECT ON public.users TO orders_api';
  EXECUTE 'GRANT SELECT ON public.sessions TO orders_api';
  EXECUTE 'GRANT SELECT ON public.idempotency TO orders_api';
  EXECUTE 'GRANT INSERT (shop_id, user_id, key, request_sha256, status, body, created_at) ON public.idempotency TO orders_api';
  EXECUTE 'GRANT UPDATE (status, body) ON public.idempotency TO orders_api';
  EXECUTE 'GRANT DELETE ON public.idempotency TO orders_api';

  -- 行の単位の制限。表の持ち主（orders_migrate）には掛けない（移行の作業は全行を扱う。FORCE は付けない）。
  -- 方針は FOR ALL で USING だけを書く（WITH CHECK は USING と同じになり、書き込みも同じ店の行に限る）。
  EXECUTE 'ALTER TABLE public.orders ENABLE ROW LEVEL SECURITY';
  EXECUTE 'DROP POLICY IF EXISTS shop_isolation ON public.orders';
  EXECUTE 'ALTER TABLE public.customers ENABLE ROW LEVEL SECURITY';
  EXECUTE 'DROP POLICY IF EXISTS shop_isolation ON public.customers';
  EXECUTE 'ALTER TABLE public.idempotency ENABLE ROW LEVEL SECURITY';
  EXECUTE 'DROP POLICY IF EXISTS shop_isolation ON public.idempotency';
  EXECUTE 'ALTER TABLE public.order_items ENABLE ROW LEVEL SECURITY';
  EXECUTE 'DROP POLICY IF EXISTS shop_isolation ON public.order_items';
  EXECUTE 'ALTER TABLE public.order_events ENABLE ROW LEVEL SECURITY';
  EXECUTE 'DROP POLICY IF EXISTS shop_isolation ON public.order_events';
  EXECUTE 'ALTER TABLE public.sessions ENABLE ROW LEVEL SECURITY';
  EXECUTE 'DROP POLICY IF EXISTS key_only ON public.sessions';
  EXECUTE 'ALTER TABLE public.users ENABLE ROW LEVEL SECURITY';
  EXECUTE 'DROP POLICY IF EXISTS key_only ON public.users';
  -- 段 R の戻しの記録が期限の内の表は、流し直しても戻したままにする（戻しを終えるのは guard.rls_restore か期限切れの後の流し直し）。
  FOR t IN SELECT v.tbl FROM guard.rls_waivers v WHERE v.until > now() AND v.tbl = ANY (want_rls) LOOP
    EXECUTE format('ALTER TABLE public.%I DISABLE ROW LEVEL SECURITY', t);
  END LOOP;
  DELETE FROM guard.rls_waivers WHERE until <= now();
  -- 要求の鍵の店を引く関数。表の持ち主の権限で動くので RLS を通らず、自分で鍵のハッシュの合う 1 行だけを引く
  -- （token_sha256 は主キーなので、引ける店は多くて 1 つ）。見たことのない鍵のハッシュでは、店は引けない（NULL で 0 行）。
  -- 期限の切れた鍵でも引けない（expires_at）。乗っ取った API が過去に見た鍵のハッシュを、期限の後も使い続ける道を閉じる。
  EXECUTE 'CREATE OR REPLACE FUNCTION public.app_key_shop() RETURNS text LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, public AS $fn$ SELECT u.shop_id::text FROM public.sessions s JOIN public.users u ON u.id = s.user_id WHERE s.token_sha256 = current_setting(''app.key_hash'', true) AND s.expires_at > now() $fn$';
  -- 関数の持ち主は表の持ち主（正本の owner。RLS を受けずに sessions と users を読む）。
  EXECUTE format('ALTER FUNCTION public.app_key_shop() OWNER TO %I', owner_name);
  EXECUTE 'REVOKE ALL ON FUNCTION public.app_key_shop() FROM PUBLIC';
  EXECUTE 'GRANT EXECUTE ON FUNCTION public.app_key_shop() TO orders_api';
  -- 鍵の表。sessions は鍵のハッシュが合う 1 行だけ。
  -- 期限の切れた鍵の行は見せない（app_key_shop と同じ expires_at の条件）。
  EXECUTE 'CREATE POLICY key_only ON public.sessions FOR ALL TO orders_api USING (token_sha256 = current_setting(''app.key_hash'', true) AND expires_at > now())';
  -- 店の列の表。店は、要求の鍵から関数で引く。users も店の列で絞る（app_key_shop は持ち主の権限で users を読むので、方針は呼び合わない）。
  EXECUTE 'DROP POLICY IF EXISTS shop_isolation ON public.users';
  EXECUTE 'CREATE POLICY shop_isolation ON public.users FOR ALL TO orders_api USING (shop_id::text = public.app_key_shop())';
  EXECUTE 'CREATE POLICY shop_isolation ON public.orders FOR ALL TO orders_api USING (shop_id::text = public.app_key_shop())';
  EXECUTE 'CREATE POLICY shop_isolation ON public.customers FOR ALL TO orders_api USING (shop_id::text = public.app_key_shop())';
  EXECUTE 'CREATE POLICY shop_isolation ON public.idempotency FOR ALL TO orders_api USING (shop_id::text = public.app_key_shop())';
  -- 親の表を通す制限。副問い合わせの orders にも orders の RLS が掛かるので、見えるのは同じ店の注文の行だけ。
  EXECUTE 'CREATE POLICY shop_isolation ON public.order_items FOR ALL TO orders_api USING (EXISTS (SELECT 1 FROM public.orders p WHERE p.id = order_items.order_id))';
  EXECUTE 'CREATE POLICY shop_isolation ON public.order_events FOR ALL TO orders_api USING (EXISTS (SELECT 1 FROM public.orders p WHERE p.id = order_events.order_id))';
  -- 実行中の書き手の取引の始まり（正本の sinceOverlap.horizon）。返すのは時刻だけで、文と鍵のハッシュは返さない。
  -- 書き手は orders_api と旧い書き手（移行の利用者は行を書かないので入れない）。書いてまだコミットしていない取引（backend_xid がある）だけを見る。
  EXECUTE 'CREATE OR REPLACE FUNCTION public.orders_write_horizon() RETURNS timestamptz LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $hz$ SELECT min(a.xact_start) FROM pg_catalog.pg_stat_activity a WHERE a.usename IN (''orders_api'', ''legacy_api'') AND a.backend_xid IS NOT NULL $hz$';
  EXECUTE 'ALTER FUNCTION public.orders_write_horizon() OWNER TO orders_horizon';
  EXECUTE 'REVOKE ALL ON FUNCTION public.orders_write_horizon() FROM PUBLIC';
  EXECUTE 'GRANT EXECUTE ON FUNCTION public.orders_write_horizon() TO orders_api';
  -- public のほかの関数（持ち主が作ったトリガーの関数など）からも PUBLIC の EXECUTE を外す。
  EXECUTE 'REVOKE EXECUTE ON ALL FUNCTIONS IN SCHEMA public FROM PUBLIC';

  -- 旧い書き手の全行の方針（正本の otherRoles の rows が all）。理由: 文も取引も変えない計画で、鍵のハッシュを流さない。退役で一覧から外す。
  -- 移行の利用者と管理者も、表の持ち主の一員として表の権限を持つので、同じ方針に入れる（持ち主の一員は RLS を受けないが、検査 9 の形に揃える）。
  SELECT string_agg(quote_ident(r), ', ') INTO all_rows FROM unnest(other_roles || ARRAY['orders_migrate', current_user::text]) AS u(r)
  WHERE EXISTS (SELECT 1 FROM pg_roles WHERE rolname = u.r);
  FOREACH t IN ARRAY want_rls LOOP
    EXECUTE format('DROP POLICY IF EXISTS other_roles_all ON public.%I', t);
    EXECUTE format('CREATE POLICY other_roles_all ON public.%I AS PERMISSIVE FOR ALL TO %s USING (true) WITH CHECK (true)', t, all_rows);
  END LOOP;

  -- public の全部の表に、移行の行の書き込みを止めるトリガーを置く（無ければ作り、無効なら有効に戻す）。
  FOR t IN SELECT c.oid::regclass::text FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace AND n.nspname = 'public'
           WHERE c.relkind IN ('r', 'p') AND NOT EXISTS (SELECT 1 FROM pg_trigger g WHERE g.tgrelid = c.oid AND g.tgname = 'guard_no_migrate_dml') LOOP
    EXECUTE format('CREATE TRIGGER guard_no_migrate_dml BEFORE INSERT OR UPDATE OR DELETE OR TRUNCATE ON %s'
                   ' FOR EACH STATEMENT EXECUTE FUNCTION guard.no_migrate_dml()', t);
  END LOOP;
  FOR t IN SELECT g.tgrelid::regclass::text FROM pg_trigger g WHERE g.tgname = 'guard_no_migrate_dml' AND g.tgenabled = 'D' LOOP
    EXECUTE format('ALTER TABLE %s ENABLE TRIGGER guard_no_migrate_dml', t);
  END LOOP;

  -- 指紋を残す。毎時と移行の後の突き合わせ（検査 7）が、同じ関数で取った指紋と比べる。
  DELETE FROM guard.fingerprints;
  INSERT INTO guard.fingerprints (kind, name, fp) SELECT f.kind, f.name, f.fp FROM guard.current_fingerprints() f;

  -- 最後の検査。違いが 1 つでもあれば、この取引ごと止める。通ったら orders_api の入りを戻す（毎時の回が閉じていた場合）。
  CALL guard.check_all();
  -- 書き手の始まりの関数を 1 回呼ぶ（持ち主の権限で動くので、orders_api が呼んだときと同じ確かめになる）。
  PERFORM public.orders_write_horizon();
  EXECUTE 'ALTER ROLE orders_api LOGIN';
END
$$;

-- 毎時の突き合わせ（pg_cron。database.tf のパラメータグループで読み込む）。管理者の名で動くので、移行の利用者は止めも変えもできない。
-- 違いを見つけたら orders_api の入りを閉じ、接続を切る（閉じる側。guardrails.tf の api-5xx が鳴る）。誤りの本文はログに出さない設定なので、
-- 鳴る所は API の 5xx で、理由は cron.job_run_details の状態ではなく、この file を流し直したときの誤りで見る。
CREATE EXTENSION IF NOT EXISTS pg_cron;
SELECT cron.schedule('orders-guard-check', '7 * * * *', $cron$
DO $x$
BEGIN
  CALL guard.check_all();
EXCEPTION WHEN OTHERS THEN
  ALTER ROLE orders_api NOLOGIN;
  PERFORM pg_terminate_backend(pid) FROM pg_stat_activity WHERE usename = 'orders_api';
  RAISE WARNING 'db-guard-check failed; orders_api login closed';
END
$x$
$cron$);
