#!/bin/sh
# 移行の作業の入口（移行のイメージの ENTRYPOINT。app.tf の db_migrate が起動する）。
# イメージに入れるのは、この file と、移行の SQL と、移行の後のスキーマの写し（schema-expected.sql）だけ。
#   1. 流す前に、移行の file に逆斜線（psql の命令）とドルの引用が無いことを確かめる。\! と \copy … to program は、DB ではなく
#      このタスクの中で命令を動かすので、DB の側の守りでは止まらない。許す文の一覧の全部は、PR の必須の検査
#      （ci/migrate-gate.yml。判定は skills/infra/scripts/migrate-gate.sh）と、イメージを押し込む前の同じ検査で確かめ済み。
#   2. 表の持ち主の役割（正本の owner。DB_TABLE_OWNER）で流す。orders_migrate はその一員で、IAM の札で入る（db/roles.sql）。
#      DB の側でも、移行の接続の DDL は CREATE TABLE・CREATE INDEX・ALTER TABLE だけで、行の書き込みは全部の表で誤りになる
#      （roles.sql の guard_migrate_ddl・guard_new_table・guard_no_migrate_dml）。表の書き直し（型の付け直しの USING など）も誤りになり
#      （guard_no_rewrite）、大きなオブジェクトは作れない。PR の文の検査を通らずに届く悪い版のイメージにも、DB の側でこれが効く。
#   3. 移行の SQL を名前の順に流す。誤りの本文は出さず、SQLSTATE だけを出す（値を引用する誤りをログに混ぜない）。
#   4. 最後に突き合わせ（guard.check_all）を回し、スキーマの丸ごとの写し（pg_dump --schema-only）を schema-expected.sql と比べる。
#      どれかが違えば誤りで終わり、guardrails.tf の db-job-failed が鳴る。守りの適用の CI も、作業の終わりの印（exit code）で止まる。
#      schema-expected.sql は、PR の検査が使い捨ての DB で同じ移行を流して作り、PR の差分として別の 2 人が読む（写しの作り方は未確定 10）。
# 一覧の外の文（関数、トリガー、規則、権限、行の書き換え）は、この入口では流せない。利用者づくりの作業が承認 2 人の経路で流し、
# roles.sql が指紋を取り直す。
# 使い方: 移行のイメージの中で動く。手で流さない（人の DB への接続は 0）。
set -eu
: "${DB_HOST:?}" "${DB_NAME:?}" "${DB_USER:?}" "${DB_TABLE_OWNER:?}" "${AWS_REGION:?}"
MIGRATIONS_DIR="${MIGRATIONS_DIR:-/migrations}"
EXPECTED="${MIGRATIONS_DIR}/schema-expected.sql"
export LC_ALL=C PGHOST="$DB_HOST" PGDATABASE="$DB_NAME" PGUSER="$DB_USER" PGSSLMODE=verify-full
export PGSSLROOTCERT="${PGSSLROOTCERT:-/etc/ssl/rds-ca.pem}"
# 移行の SQL だけを表の持ち主の役割で流す（足す表の持ち主も同じ役割になる）。突き合わせは orders_migrate のまま回す。
OWNER_OPTIONS="-c role=${DB_TABLE_OWNER}"

auth() {
  # IAM の認証の札（15 分で切れる）。ファイルごとに取り直す。値は出力しない。
  PGPASSWORD="$(aws rds generate-db-auth-token --hostname "$DB_HOST" --port 5432 --username "$DB_USER" --region "$AWS_REGION")"
  export PGPASSWORD
}
run() { auth; PGOPTIONS="" psql -X -q -At -v ON_ERROR_STOP=1 -v VERBOSITY=sqlstate "$@" 2>/dev/null; }
# スキーマの写しを、版と時刻と流し方の行（注釈、psql の命令、SET）を外した形の指紋にする。
BS="$(printf '\134')"
schema_digest() { grep -v -e '^--' -e "^${BS}${BS}" -e '^SET ' -e '^SELECT pg_catalog.set_config' -e '^$' | sha256sum | cut -c1-64; }

[ -f "$EXPECTED" ] || { echo "migrate: schema-expected.sql is missing"; exit 1; }
for f in "$MIGRATIONS_DIR"/*.sql; do
  [ -e "$f" ] || continue
  [ "$f" = "$EXPECTED" ] && continue
  if grep -q -F -e "$BS" -e '$' "$f"; then
    echo "migrate: $(basename "$f") has a psql command or dollar quoting; use the guarded route"
    exit 1
  fi
done
for f in "$MIGRATIONS_DIR"/*.sql; do
  [ -e "$f" ] || continue
  [ "$f" = "$EXPECTED" ] && continue
  auth
  if ! err="$(PGOPTIONS="$OWNER_OPTIONS" psql -X -q -v ON_ERROR_STOP=1 -v VERBOSITY=sqlstate -f "$f" 2>&1 > /dev/null)"; then
    # VERBOSITY=sqlstate は誤りの本文を出さず、5 字の SQLSTATE だけを出す。それ以外の字は捨てる。
    echo "migrate: failed at $(basename "$f") sqlstate $(printf '%s' "$err" | grep -o '[0-9A-Z]\{5\}' | tail -n 1)"
    exit 1
  fi
done
run -c 'CALL guard.check_all()' > /dev/null || { echo "migrate: guard check failed after the migration"; exit 1; }
auth
got="$(pg_dump --schema-only --exclude-schema=cron 2>/dev/null | schema_digest)" || { echo "migrate: cannot dump the schema"; exit 1; }
want="$(schema_digest < "$EXPECTED")"
[ "$got" = "$want" ] || { echo "migrate: the schema differs from schema-expected.sql"; exit 1; }
echo "migrate: ok"
