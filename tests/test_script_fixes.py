"""Behaviour of the smoke and report scripts that the text checks cannot see (decision 0084).

`curl`, `docker` and `sleep` are stubs on PATH over a few files, so no stack, network or wait is
involved. The smoke stub keeps a tiny fake stack: whether weather is connected, how many syncs ran.
"""

import os
import re
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
SMOKE = ROOT / "scripts" / "smoke-distributed.sh"
REPORT = ROOT / "scripts" / "report-state.sh"

STUB_SLEEP = "#!/bin/sh\nexit 0\n"
STUB_DOCKER = """#!/bin/sh
case "$*" in *" ps "*) echo container-id ;; esac
exit 0
"""
STUB_CURL = r"""#!/usr/bin/env bash
out=""; method=GET; url=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    -o) out="$2"; shift 2 ;;
    -X) method="$2"; shift 2 ;;
    -w|--max-time|-H|--data-binary) shift 2 ;;
    -*) shift ;;
    *) url="$1"; shift ;;
  esac
done
d="$FIXTURE_DIR"
syncs=$(cat "$d/syncs" 2>/dev/null || echo 0)
posts=$(cat "$d/posts" 2>/dev/null || echo 0)
code=200
case "$method $url" in
  "GET "*/v1/health) echo '{"status":"ok"}' >"$out" ;;
  "GET "*/v1/settings)
    sync=null
    [[ -f "$d/connected" && "$syncs" -gt 0 ]] &&
      sync="{\"source\":\"weather\",\"status\":\"ok\",\"message\":\"Synced\",\"at\":\"t$syncs\"}"
    set=false
    { [[ -f "$d/connected" ]] || [[ -f "$d/keys_left" ]]; } && set=true
    key="{\"latitude\":{\"set\":$set,\"last4\":null}}"
    echo "[{\"source\":\"weather\",\"keys\":$key,\"sync\":$sync}]" >"$out" ;;
  "PUT "*/v1/settings/weather)
    touch "$d/connected"; echo 1 >"$d/syncs"; echo '{"ok":true}' >"$out" ;;
  "POST "*/v1/sync)
    echo $((posts + 1)) >"$d/posts"
    from="${STUB_SYNC_FAILS_FROM:-}"
    if [[ -n "$from" && $((posts + 1)) -ge "$from" ]]; then code=500
    else echo $((syncs + 1)) >"$d/syncs"; fi
    echo '[]' >"$out" ;;
  "GET "*/v1/events*)
    if [[ -f "$d/connected" ]]; then echo '[{"source":"weather"},{"source":"weather"}]' >"$out"
    else echo '[]' >"$out"; fi ;;
  "DELETE "*/v1/settings/weather)
    rm -f "$d/connected" "$d/syncs"
    [[ -z "${STUB_LEAVE_KEYS:-}" ]] || touch "$d/keys_left"
    echo '{}' >"$out" ;;
  *) echo '{}' >"$out" ;;
esac
printf '%s' "$code"
"""


def make_stub(directory: Path, name: str, text: str) -> None:
    path = directory / name
    path.write_text(text)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


@pytest.fixture
def stack(tmp_path: Path) -> dict[str, str]:
    """An environment with stub tools first on PATH and a fresh fake stack."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    make_stub(bin_dir, "curl", STUB_CURL)
    make_stub(bin_dir, "docker", STUB_DOCKER)
    make_stub(bin_dir, "sleep", STUB_SLEEP)
    fixtures = tmp_path / "fixtures"
    fixtures.mkdir()
    env_file = tmp_path / "compose.env"
    env_file.write_text("POSTGRES_PASSWORD=fake-compose-password\n")
    return {
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "HOME": str(tmp_path),
        "TMPDIR": str(tmp_path),
        "FIXTURE_DIR": str(fixtures),
        "COMPOSE_ENV_FILE": str(env_file),
        "CC_SMOKE_SETTLE": "0",
    }


def run(script: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    bash = shutil.which("bash") or "/bin/bash"
    return subprocess.run(  # noqa: S603  (our own script, stub tools)
        [bash, str(script)], env=env, capture_output=True, text=True, check=False, timeout=120
    )


def test_the_smoke_test_passes_on_a_stack_that_behaves(stack: dict[str, str]) -> None:
    result = run(SMOKE, stack)

    assert result.returncode == 0, result.stdout
    assert "All steps passed" in result.stdout
    assert result.stdout.count("PASS  weather keys gone") == 2


def test_the_smoke_test_fails_when_a_disconnect_leaves_the_keys_behind(
    stack: dict[str, str],
) -> None:
    result = run(SMOKE, {**stack, "STUB_LEAVE_KEYS": "1"})

    assert result.returncode == 1, result.stdout
    assert "FAIL  weather keys remain" in result.stdout
    assert (
        "PASS  weather events gone after the disconnect" in result.stdout
    )  # the other checks pass


def test_the_smoke_test_fails_when_the_sync_after_the_worker_restart_is_refused(
    stack: dict[str, str],
) -> None:
    result = run(SMOKE, {**stack, "STUB_SYNC_FAILS_FROM": "2"})

    assert result.returncode == 1, result.stdout
    assert "FAIL  POST /v1/sync after the worker restart (HTTP 500)" in result.stdout
    assert "PASS  sync after the worker restart reported ok" not in result.stdout


def test_the_baseline_state_is_taken_only_after_the_state_settles() -> None:
    text = SMOKE.read_text()
    step_5 = text[text.index("# 5. kill the weather worker") :]

    assert step_5.index("settle_state") < step_5.index('BEFORE_STATE="$(weather_sync')


@pytest.fixture
def report_env(stack: dict[str, str]) -> dict[str, str]:
    fixtures = Path(stack["FIXTURE_DIR"])
    (fixtures / "settings.json").write_text("[]")
    (fixtures / "events.json").write_text("[]")
    stub = (
        "#!/usr/bin/env bash\nout=''\n"
        'while [[ $# -gt 0 ]]; do case "$1" in -o) out="$2"; shift 2 ;; -w|--max-time) shift 2 ;;'
        " -*) shift ;; *) shift ;; esac; done\n"
        'echo "[]" >"$out"; printf 200\n'
    )
    make_stub(Path(stack["PATH"].split(os.pathsep)[0]), "curl", stub)
    return stack


@pytest.mark.parametrize("name", ["CC_REPORT_PAST_DAYS", "CC_REPORT_FUTURE_DAYS"])
def test_report_state_refuses_a_day_count_that_is_not_a_number_and_runs_nothing(
    report_env: dict[str, str], tmp_path: Path, name: str
) -> None:
    marker = tmp_path / "ran"
    result = run(REPORT, {**report_env, name: f"a[$(touch {marker})]"})

    assert result.returncode == 2, result.stdout
    assert "must be whole numbers" in result.stdout
    assert not marker.exists()


def test_report_state_still_reports_when_pyproject_toml_is_missing(
    report_env: dict[str, str], tmp_path: Path
) -> None:
    copy = tmp_path / "copy" / "scripts"
    copy.mkdir(parents=True)
    shutil.copy(REPORT, copy / "report-state.sh")

    result = run(copy / "report-state.sh", report_env)

    assert result.returncode == 0, result.stdout
    assert re.search(r"^app version: unknown$", result.stdout, re.MULTILINE)
