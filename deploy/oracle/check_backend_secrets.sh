#!/usr/bin/env bash
# Verify backend auth secrets over HTTP without printing or storing any secret value.
#
# Uses side-effect-free probes: the API token middleware runs before routing, so a GET to a
# POST-only scheduler route returns 405 when the token is accepted and 401 when it is not.
# No report is generated and no response body is printed.
#
# Usage: BACKEND_URL=... SCHEDULER_SECRET=... check_backend_secrets.sh [pre|post]
set -euo pipefail

PHASE="${1:-pre}"  # label only: pre or post
BACKEND_URL="$(printf '%s' "${BACKEND_URL:-}" | tr -d '\r\n' | sed -E 's/[[:space:]]+$//')"
BACKEND_URL="${BACKEND_URL%/}"
SCHEDULER_SECRET="$(printf '%s' "${SCHEDULER_SECRET:-}" | tr -d '\r\n')"

if [ -z "$BACKEND_URL" ] || [ -z "$SCHEDULER_SECRET" ]; then
  echo "::error::BACKEND_URL and SCHEDULER_SECRET repository secrets are required for the key check."
  exit 1
fi
case "$BACKEND_URL" in
  http://*|https://*) ;;
  *) echo "::error::BACKEND_URL must start with https:// or http://"; exit 1 ;;
esac

status_code() {
  # $1 = method, $2 = path; prints only the HTTP status code.
  curl -sS -o /dev/null -w '%{http_code}' --max-time 30 -X "$1" \
    -H "Authorization: Bearer $SCHEDULER_SECRET" "$BACKEND_URL$2" || echo "000"
}

for attempt in 1 2 3 4 5; do  # ~40s total
  if curl -fsS -o /dev/null --max-time 30 "$BACKEND_URL/health"; then
    break
  fi
  if [ "$attempt" -eq 5 ]; then
    if [ "$PHASE" = "pre" ]; then
      # Recovery path: a stopped or crashing backend must still be deployable. The strict
      # post-deploy check verifies the secrets once the new release is running.
      echo "::warning::Backend /health did not respond before deploy; skipping pre-deploy secret check (post-deploy check still runs)."
      exit 0
    fi
    echo "::error::Backend /health did not respond after deploy; cannot verify secrets."
    exit 1
  fi
  sleep 10
done

scheduler_status="$(status_code GET /api/reports/domestic/generate)"
user_api_status="$(status_code GET /api/settings)"

failed=0
echo "GitHub SCHEDULER_SECRET vs server SCHEDULER_SECRET (scheduler route probe): HTTP $scheduler_status"
case "$scheduler_status" in
  405) echo "  OK: the GitHub secret matches the server's scheduler secret." ;;
  401)
    if [ "$user_api_status" = "200" ]; then
      echo "  Rejected because the server reuses API_ACCESS_TOKEN as SCHEDULER_SECRET (see below)."
    else
      echo "::error::GitHub SCHEDULER_SECRET does not match the server's SCHEDULER_SECRET; scheduled reports would fail."
    fi
    failed=1
    ;;
  *) echo "::error::Unexpected status from the scheduler route probe."; failed=1 ;;
esac

echo "SCHEDULER_SECRET used as API_ACCESS_TOKEN (user API probe): HTTP $user_api_status"
case "$user_api_status" in
  401) echo "  OK: SCHEDULER_SECRET and API_ACCESS_TOKEN are different values." ;;
  200)
    echo "::error::SCHEDULER_SECRET equals API_ACCESS_TOKEN on the server. Rotate SCHEDULER_SECRET in /etc/alphapilot/backend.env and the GitHub secret before deploying."
    failed=1
    ;;
  *) echo "::error::Unexpected status from the user API probe."; failed=1 ;;
esac

if [ "$failed" -ne 0 ]; then
  exit 1
fi
echo "Secret checks passed ($PHASE-deploy)."
