#!/bin/sh
# Run every check this project has and print one verdict.
#
#   ./scripts/test-all.sh            # everything, including Docker
#   ./scripts/test-all.sh --skip-docker
#
# The container steps use `run --rm`, so the containers are removed as soon
# as they finish and leave nothing behind.

set -u

ROOT=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT" || exit 1

SKIP_DOCKER=0
for arg in "$@"; do
    case "$arg" in
        --skip-docker) SKIP_DOCKER=1 ;;
        *) echo "unknown option: $arg" >&2; exit 2 ;;
    esac
done

if [ -x "$ROOT/venv/bin/python" ]; then
    PYTHON="$ROOT/venv/bin/python"
else
    PYTHON=python
fi

RESULTS=""
FAILED=0
STEP_NO=0

run_step() {
    name=$1
    shift
    STEP_NO=$((STEP_NO + 1))
    echo ""
    echo "=== $name ==="
    start=$(date +%s)
    "$@"
    code=$?
    end=$(date +%s)
    if [ "$code" -eq 0 ]; then
        verdict=PASS
    else
        verdict=FAIL
        FAILED=$((FAILED + 1))
    fi
    RESULTS="${RESULTS}${name}|${code}|$((end - start))s|${verdict}
"
    return 0
}

run_step "pytest (local)" "$PYTHON" -m pytest tests -q -p no:cacheprovider \
    --cov=app --cov=main --cov-report=term --cov-fail-under=74
run_step "ruff" "$PYTHON" -m ruff check .
run_step "mypy" "$PYTHON" -m mypy
run_step "vitest (local)" sh -c "cd webui && npm test"
run_step "eslint (local)" sh -c "cd webui && npm run lint"

if [ "$SKIP_DOCKER" -eq 0 ]; then
    # The Docker daemon is reachable only while the host can route to the
    # engine VM. A VPN tunnel that installs a 192.168.0.0/16 route takes
    # 192.168.65.x with it, and the daemon stops answering. Say so instead
    # of reporting a green run that skipped the container checks.
    if ! docker version --format '{{.Server.Version}}' >/dev/null 2>&1; then
        echo ""
        echo "!!! Docker daemon 不可达：容器内验证无法执行（标记为 SKIP，不算通过）"
        echo "!!! 宿主到引擎 VM 的路由被隧道网卡（192.168.0.0/16）劫持；重启 Docker Desktop 或临时断开该隧道后重试。"
        STEP_NO=$((STEP_NO + 1))
        RESULTS="${RESULTS}docker (容器内验证)|skip|0s|SKIP
"
        FAILED=$((FAILED + 1))
    else
        run_step "pytest (docker)" docker compose --profile test run --rm --no-deps backend-test
        run_step "vitest (docker)" docker compose --profile test run --rm --no-deps webui-test
        run_step "docker build (runtime image)" docker build --tag biliarchive-pro:local .
    fi
fi

echo ""
echo "================ TEST SUMMARY ================"
printf "%-32s %-6s %-8s %s\n" "STEP" "EXIT" "TIME" "RESULT"
printf "%s" "$RESULTS" | while IFS='|' read -r name code secs verdict; do
    [ -z "$name" ] && continue
    printf "%-32s %-6s %-8s %s\n" "$name" "$code" "$secs" "$verdict"
done

TOTAL=$STEP_NO
if [ "$FAILED" -gt 0 ]; then
    echo "OVERALL: INCOMPLETE ($FAILED of $TOTAL steps failed or skipped; 未完成的验证不算通过)"
    exit 1
fi
echo "OVERALL: PASS ($TOTAL of $TOTAL steps green)"
exit 0
