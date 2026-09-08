from pathlib import Path
import os
import shutil
import subprocess


ROOT = Path(__file__).resolve().parents[1]


def test_bundle_mounts_sidebar_and_mcp_for_standard_installs():
    patch = (ROOT / "cordis.patch.yml").read_text(encoding="utf-8")

    assert "id: mcp-dsh-kline" in patch
    assert "name: '@deepseek-ai/dsh-mcp-client'" in patch
    assert "id: dsh-kline-sidebar" in patch
    assert "DSH_KLINE_HOST_PID: !!js String(process.pid)" in patch
    assert "decodeURIComponent(new URL('./node_modules/@ftshare-lab/dsh-kline/', ctx.baseUrl).pathname)" in patch


def test_runner_prepares_a_user_runtime_without_a_project_venv():
    runner = (ROOT / "scripts" / "run-dsh-kline.sh").read_text(encoding="utf-8")
    bootstrap = (ROOT / "scripts" / "bootstrap.sh").read_text(encoding="utf-8")

    assert "${XDG_CACHE_HOME:-$HOME/.cache}/dsh_kline" in runner
    assert 'bash "$PROJECT_ROOT/scripts/bootstrap.sh" >&2' in runner
    assert "python3.10" in bootstrap
    assert "Python 3.10 or newer" in bootstrap


def test_first_launch_can_bootstrap_without_executable_script_bits(tmp_path):
    # npm/pnpm pack may reset both scripts to 0644. Exercise the real runner
    # in a path with spaces/Unicode, using a network-free bootstrap fixture.
    project = tmp_path / "安装 package"
    scripts = project / "scripts"
    scripts.mkdir(parents=True)
    runner = scripts / "run-dsh-kline.sh"
    shutil.copyfile(ROOT / "scripts" / "run-dsh-kline.sh", runner)
    runner.chmod(0o644)
    bootstrap = scripts / "bootstrap.sh"
    bootstrap.write_text('''#!/usr/bin/env bash
set -eu
mkdir -p "$DSH_KLINE_VENV/bin"
printf '#!/bin/sh\\nprintf "mcp-ready\\\\n"\\n' > "$DSH_KLINE_VENV/bin/python"
chmod 755 "$DSH_KLINE_VENV/bin/python"
printf 'bootstrap completed\\n'
''')
    bootstrap.chmod(0o644)
    env = {key: value for key, value in os.environ.items() if not key.startswith(('DSH_KLINE_', 'FTSHARE_'))}
    env.update(XDG_CACHE_HOME=str(tmp_path / 'cache'), DSH_KLINE_VENV=str(tmp_path / 'venv'))
    result = subprocess.run(['bash', str(runner)], env=env, capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert result.stdout == 'mcp-ready\n'
    assert 'bootstrap completed' in result.stderr
