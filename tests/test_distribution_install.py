from pathlib import Path
import hashlib
import os
import shutil
import subprocess
import tarfile


ROOT = Path(__file__).resolve().parents[1]


def _requirements_fingerprint(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _prepare_runner_fixture(tmp_path, *, python_body=None, stamp=None):
    project = tmp_path / "安装 package"
    scripts = project / "scripts"
    scripts.mkdir(parents=True)
    runner = scripts / "run-dsh-kline.sh"
    shutil.copyfile(ROOT / "scripts" / "run-dsh-kline.sh", runner)
    runner.chmod(0o644)
    shutil.copyfile(ROOT / "requirements.txt", project / "requirements.txt")
    (project / "server.py").write_text("# exercised by the fake Python executable\n")

    bootstrap = scripts / "bootstrap.sh"
    bootstrap.write_text('''#!/usr/bin/env bash
set -eu
mkdir -p "$DSH_KLINE_VENV/bin"
printf '#!/bin/sh\\nif [ "${1:-}" = "-c" ]; then exit 0; fi\\nprintf "mcp-ready\\\\n"\\n' > "$DSH_KLINE_VENV/bin/python"
chmod 755 "$DSH_KLINE_VENV/bin/python"
printf '%s\\n' "$DSH_KLINE_REQUIREMENTS_FINGERPRINT" > "$DSH_KLINE_VENV/.dsh-kline-requirements"
printf 'bootstrap completed\\n'
''')
    bootstrap.chmod(0o644)

    venv = tmp_path / "venv"
    if python_body is not None:
        (venv / "bin").mkdir(parents=True)
        python = venv / "bin" / "python"
        python.write_text(python_body)
        python.chmod(0o755)
    if stamp is not None:
        venv.mkdir(parents=True, exist_ok=True)
        (venv / ".dsh-kline-requirements").write_text(f"{stamp}\n")

    env = {key: value for key, value in os.environ.items() if not key.startswith(('DSH_KLINE_', 'FTSHARE_'))}
    env.update(XDG_CACHE_HOME=str(tmp_path / 'cache'), DSH_KLINE_VENV=str(venv))
    return project, runner, venv, env


def _run_runner(runner, env):
    return subprocess.run(['bash', str(runner)], env=env, capture_output=True, text=True, timeout=10)


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
    assert 'bash "$PROJECT_ROOT/scripts/bootstrap.sh"' in runner
    assert ".dsh-kline-requirements" in runner
    assert "import ftshare, mcp, pydantic, pydantic_settings" in runner
    assert "bootstrap.log" in runner
    assert "python3.10" in bootstrap
    assert "Python 3.10 or newer" in bootstrap
    assert ".dsh-kline-requirements" in bootstrap


def test_release_package_is_bounded_and_attached_with_a_stable_name():
    manifest = (ROOT / "package.json").read_text(encoding="utf-8")
    packer = (ROOT / "scripts" / "build-release-package.mjs").read_text(encoding="utf-8")
    workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")

    assert '"files"' in manifest
    for required in ('"lib"', '"view"', '"requirements.txt"', '"scripts/run-dsh-kline.sh"'):
        assert required in manifest
    assert 'dsh-kline-release-' in packer
    assert 'RELEASE_TAG' in workflow
    assert 'does not match package' in workflow
    assert 'release/dsh-kline.tgz' in workflow
    assert 'gh release upload' in workflow
    assert '--clobber' in workflow


def test_release_packer_ignores_files_outside_the_allowlist(tmp_path):
    archive = tmp_path / 'dsh-kline.tgz'
    result = subprocess.run(
        ['node', str(ROOT / 'scripts' / 'build-release-package.mjs'), str(archive)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    assert archive.is_file()
    with tarfile.open(archive, 'r:gz') as packed:
        names = set(packed.getnames())
    assert 'package/package.json' in names
    assert 'package/lib/index.js' in names
    assert 'package/scripts/run-dsh-kline.sh' in names
    assert 'package/requirements.txt' in names
    assert not any('/node_modules/' in name or '/tests/' in name or '/.venv' in name for name in names)


def test_first_launch_can_bootstrap_without_executable_script_bits(tmp_path):
    # npm/pnpm pack may reset both scripts to 0644. Exercise the real runner
    # in a path with spaces/Unicode, using a network-free bootstrap fixture.
    project, runner, venv, env = _prepare_runner_fixture(tmp_path)
    result = _run_runner(runner, env)

    assert result.returncode == 0, result.stderr
    assert result.stdout == 'mcp-ready\n'
    assert 'bootstrap completed' in result.stderr
    assert (venv / '.dsh-kline-requirements').read_text().strip() == _requirements_fingerprint(project / 'requirements.txt')
    assert (tmp_path / 'cache' / 'dsh_kline' / 'bootstrap.log').is_file()


def test_changed_requirements_repair_an_existing_user_runtime(tmp_path):
    working_python = '#!/bin/sh\nif [ "${1:-}" = "-c" ]; then exit 0; fi\nprintf "old-runtime\\n"\n'
    project, runner, venv, env = _prepare_runner_fixture(
        tmp_path,
        python_body=working_python,
        stamp='previous-requirements',
    )

    result = _run_runner(runner, env)

    assert result.returncode == 0, result.stderr
    assert result.stdout == 'mcp-ready\n'
    assert 'dependency requirements changed' in result.stderr
    assert 'bootstrap completed' in result.stderr
    assert (venv / '.dsh-kline-requirements').read_text().strip() == _requirements_fingerprint(project / 'requirements.txt')


def test_incomplete_install_is_repaired_on_the_next_launch(tmp_path):
    broken_python = '#!/bin/sh\nif [ "${1:-}" = "-c" ]; then exit 1; fi\nprintf "broken-runtime\\n"\n'
    project, runner, _venv, env = _prepare_runner_fixture(
        tmp_path,
        python_body=broken_python,
        stamp=_requirements_fingerprint(ROOT / 'requirements.txt'),
    )

    result = _run_runner(runner, env)

    assert result.returncode == 0, result.stderr
    assert result.stdout == 'mcp-ready\n'
    assert 'installed dependencies are incomplete' in result.stderr
    assert 'bootstrap completed' in result.stderr


def test_healthy_matching_runtime_starts_without_bootstrap(tmp_path):
    working_python = '#!/bin/sh\nif [ "${1:-}" = "-c" ]; then exit 0; fi\nprintf "existing-runtime\\n"\n'
    project, runner, _venv, env = _prepare_runner_fixture(
        tmp_path,
        python_body=working_python,
        stamp=_requirements_fingerprint(ROOT / 'requirements.txt'),
    )

    result = _run_runner(runner, env)

    assert result.returncode == 0, result.stderr
    assert result.stdout == 'existing-runtime\n'
    assert 'bootstrap completed' not in result.stderr


def test_checked_out_project_venv_is_diagnosed_but_not_modified(tmp_path):
    project, runner, _managed_venv, env = _prepare_runner_fixture(tmp_path)
    project_venv = project / '.venv'
    (project_venv / 'bin').mkdir(parents=True)
    project_python = project_venv / 'bin' / 'python'
    original_python = '#!/bin/sh\nexit 1\n'
    project_python.write_text(original_python)
    project_python.chmod(0o755)
    env.pop('DSH_KLINE_VENV')

    result = _run_runner(runner, env)

    assert result.returncode == 1
    assert 'project .venv is incomplete' in result.stderr
    assert 'bootstrap completed' not in result.stderr
    assert project_python.read_text() == original_python


def test_bootstrap_failure_is_reported_and_saved_to_the_log(tmp_path):
    project, runner, _venv, env = _prepare_runner_fixture(tmp_path)
    (project / 'scripts' / 'bootstrap.sh').write_text(
        '#!/usr/bin/env bash\nprintf "simulated install failure\\n"\nexit 23\n'
    )

    result = _run_runner(runner, env)

    log = tmp_path / 'cache' / 'dsh_kline' / 'bootstrap.log'
    assert result.returncode == 1
    assert 'Runtime preparation failed' in result.stderr
    assert 'simulated install failure' in result.stderr
    assert log.read_text() == 'simulated install failure\n'
