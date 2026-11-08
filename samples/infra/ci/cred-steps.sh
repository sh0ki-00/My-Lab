#!/usr/bin/env bash
# 資格を借りる job の手順の本体（第 16 回）。資格を借りる job の run は、この file を取る 1 行と呼ぶ 1 行だけにする（deps-diff の --uses）。
#   置き場: repo の tools/ci/（org/github.tf の ci_tools）。持ち主の欄（guard_paths の /tools/）の内側で、変えるにはセキュリティの承認が要る。
#   取り方: 資格を借りる job は checkout（外の部品）を使わない。機械に入っている gh で、この実行の SHA（main）の file を取る。
#     gh api -H "Accept: application/vnd.github.raw" "repos/${GITHUB_REPOSITORY}/contents/tools/ci/cred-steps.sh?ref=${GITHUB_SHA}" > "${RUNNER_TEMP}/cred-steps.sh"
#   束（site と db-images）は自分の repo のこの実行か、名指しした build の実行からだけ落とす（--repo は GITHUB_REPOSITORY に固定）。
#   束の中の file は動かさない（working-directory を使わず、置き場を "${RUNNER_TEMP}" の下に決める）。
# 使い方: bash cred-steps.sh <手順の名>   /   bash cred-steps.sh --selftest
#   手順の名: assume-role、deploy-pick、deploy-fetch、deploy-verify、deploy-sync、site-subjects、db-fetch、db-push、digest-form
set -euo pipefail

own_repo() {
  # 落とす元は自分の repo だけ（env の REPO を信じない）。
  printf '%s' "${GITHUB_REPOSITORY:?}"
}

digest_ok() {
  printf '%s' "$1" | grep -Eq '^sha256:[0-9a-f]{64}$'
}

step="${1:-}"
case "$step" in
  --selftest)
    bad=0
    digest_ok "sha256:$(printf 'a%.0s' $(seq 64))" || { echo "FAIL cred-steps: 64 桁のダイジェストを通さない"; bad=1; }
    if digest_ok "sha256:abc"; then echo "FAIL cred-steps: 短いダイジェストを通す"; bad=1; fi
    if digest_ok "latest"; then echo "FAIL cred-steps: 札を通す"; bad=1; fi
    if (bash "$0" no-such-step >/dev/null 2>&1); then echo "FAIL cred-steps: 一覧の外の手順の名を通す"; bad=1; fi
    echo "RESULT: $([ "$bad" = 0 ] && echo PASS || echo FAIL) cred-steps --selftest (4 例)"
    exit "$bad"
    ;;
  assume-role)
    # 札は機械の窓口（ACTIONS_ID_TOKEN_REQUEST_URL）から取り、機械に入っている aws で借りる。値は job の環境にだけ置き、ログに出さない。
    tok=$(curl -fsS -H "Authorization: bearer ${ACTIONS_ID_TOKEN_REQUEST_TOKEN}" "${ACTIONS_ID_TOKEN_REQUEST_URL}&audience=sts.amazonaws.com" | jq -r .value)
    echo "::add-mask::${tok}"
    creds=$(aws sts assume-role-with-web-identity --role-arn "${ROLE_ARN:?}" --role-session-name "${SESSION:?}" \
      --web-identity-token "$tok" --duration-seconds 900 --region ap-northeast-1 --output json)
    for k in AccessKeyId SecretAccessKey SessionToken; do echo "::add-mask::$(printf '%s' "$creds" | jq -r ".Credentials.${k}")"; done
    {
      echo "AWS_ACCESS_KEY_ID=$(printf '%s' "$creds" | jq -r .Credentials.AccessKeyId)"
      echo "AWS_SECRET_ACCESS_KEY=$(printf '%s' "$creds" | jq -r .Credentials.SecretAccessKey)"
      echo "AWS_SESSION_TOKEN=$(printf '%s' "$creds" | jq -r .Credentials.SessionToken)"
      echo "AWS_REGION=ap-northeast-1"
    } >> "$GITHUB_ENV"
    ;;
  deploy-pick)
    # 配る実行が main の static-build の最新の作りかを確かめる。やり直し（run_attempt が 1 でない）は配らない。
    repo=$(own_repo)
    [ "${RUN_ATTEMPT:?}" = "1" ] || { echo "a re-run of build ${RUN_ID} (attempt ${RUN_ATTEMPT}); stop"; exit 1; }
    latest="$(gh api "repos/${repo}/actions/workflows/static-build.yml/runs?branch=main&event=push&status=success&per_page=100" \
      --jq '[.workflow_runs[] | select(.run_attempt == 1)] | max_by(.run_number) | .id')"
    [ "$latest" = "${RUN_ID:?}" ] || { echo "not the latest build (${RUN_ID} vs ${latest}); stop"; exit 1; }
    ;;
  deploy-fetch)
    # 名前 site の束が 1 つだけで、作る job（build）が終わる前に作られたことを、GitHub の記録で確かめてから落とす。
    repo=$(own_repo)
    built=$(gh api "repos/${repo}/actions/runs/${RUN_ID:?}/jobs" --jq '[.jobs[] | select(.name == "build")] | if length == 1 then .[0].completed_at else "" end')
    arts=$(gh api "repos/${repo}/actions/runs/${RUN_ID}/artifacts" --jq '[.artifacts[] | select(.name == "site")]')
    [ -n "$built" ] && [ "$(printf '%s' "$arts" | jq length)" = "1" ] || { echo "the bundle is not exactly one artifact of one build job; stop"; exit 1; }
    made=$(printf '%s' "$arts" | jq -r '.[0].created_at')
    [ "$(printf '%s\n%s\n' "$made" "$built" | sort | head -1)" = "$made" ] || { echo "the bundle was made after the build job (${made} > ${built}); stop"; exit 1; }
    gh run download "$RUN_ID" --repo "$repo" --name site --dir "${RUNNER_TEMP}/site"
    ;;
  deploy-verify)
    # 来歴は、この実行の署名が 1 つだけで、その主語が束の全部の file と同じであること（任意の指紋に足した 2 つ目の署名を拒む）。
    repo=$(own_repo)
    cd "${RUNNER_TEMP}/site"
    find . -type f -printf '%P\0' | LC_ALL=C sort -z | xargs -0 sha256sum | awk '{print $1}' | sort > "${RUNNER_TEMP}/files.txt"
    gh attestation verify index.html --repo "$repo" --signer-workflow "${repo}/.github/workflows/static-build.yml" --format json \
      | jq --arg run "/runs/${RUN_ID:?}/" '[.[] | select(.verificationResult.statement.predicate.runDetails.metadata.invocationId | contains($run))]' \
      > "${RUNNER_TEMP}/this-run.json"
    [ "$(jq length "${RUNNER_TEMP}/this-run.json")" = "1" ] || { echo "not exactly one attestation for run ${RUN_ID}; stop"; exit 1; }
    jq -r '.[0].verificationResult.statement.subject[].digest.sha256' "${RUNNER_TEMP}/this-run.json" | sort > "${RUNNER_TEMP}/subjects.txt"
    cmp -s "${RUNNER_TEMP}/files.txt" "${RUNNER_TEMP}/subjects.txt" || { echo "the attested subjects differ from the bundle; stop"; exit 1; }
    find . -type f -printf '%P\n' | while IFS= read -r f; do
      gh attestation verify "$f" --repo "$repo" --signer-workflow "${repo}/.github/workflows/static-build.yml" \
        --source-ref refs/heads/main --deny-self-hosted-runners > /dev/null
    done
    ;;
  deploy-sync)
    # 分けた送りは使わない。指紋を名前に入れた file を先に、入口を最後に書き、控えが切れてから今の作りに無い file を消す。
    site="${RUNNER_TEMP}/site"
    aws configure set default.s3.multipart_threshold 5GB
    aws s3 sync "$site" "s3://${BUCKET:?}/" --exclude index.html --only-show-errors
    aws s3 cp "$site/index.html" "s3://${BUCKET}/index.html" --only-show-errors
    sleep 90
    aws s3 sync "$site" "s3://${BUCKET}/" --delete --only-show-errors
    ;;
  site-subjects)
    # 署名する job: この実行の束を落とし、file ごとの SHA-256 を来歴の主語の一覧にする。束の中の file は動かさない。
    repo=$(own_repo)
    gh run download "${GITHUB_RUN_ID:?}" --repo "$repo" --name site --dir "${RUNNER_TEMP}/site"
    cd "${RUNNER_TEMP}/site"
    find . -type f -printf '%P\0' | LC_ALL=C sort -z | xargs -0 sha256sum > "${RUNNER_TEMP}/subjects.txt"
    ;;
  db-fetch)
    repo=$(own_repo)
    gh run download "${GITHUB_RUN_ID:?}" --repo "$repo" --name db-images --dir "${RUNNER_TEMP}/images"
    ;;
  db-push)
    # 押し込んだダイジェストを次の job へ渡すだけ。来歴は attest-image.yml が付ける（この job は attestations: write を持たない）。
    aws ecr get-login-password | docker login --username AWS --password-stdin "${REGISTRY:?}"
    for name in db-bootstrap db-migrate; do
      docker load -i "${RUNNER_TEMP}/images/${name}.tar"
      docker tag "$name" "${REGISTRY}/${PREFIX:?}/${name}:${GITHUB_SHA}"
      docker push "${REGISTRY}/${PREFIX}/${name}:${GITHUB_SHA}"
      d=$(docker inspect --format '{{index .RepoDigests 0}}' "${REGISTRY}/${PREFIX}/${name}:${GITHUB_SHA}" | cut -d@ -f2)
      digest_ok "$d" || { echo "::error::digest form"; exit 1; }
      echo "${name#db-}=${d}" >> "$GITHUB_OUTPUT"
    done
    ;;
  digest-form)
    digest_ok "${DIGEST:-}" || { echo "::error::digest form"; exit 1; }
    ;;
  *)
    echo "使い方: cred-steps.sh <assume-role|deploy-pick|deploy-fetch|deploy-verify|deploy-sync|site-subjects|db-fetch|db-push|digest-form> | --selftest" >&2
    exit 2
    ;;
esac
