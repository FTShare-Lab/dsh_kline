from pathlib import Path
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import time

import pytest


ROOT = Path(__file__).resolve().parents[1]


def _requirements_fingerprint(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fake_python_body():
    return r'''#!/usr/bin/env python3
import os
from pathlib import Path
import shutil
import sys

args = sys.argv[1:]
if args[:1] == ['-c']:
    if 'print(f"{sys.version_info.major}.{sys.version_info.minor}")' in args[1]:
        print('3.10' if os.environ.get('FAKE_OLD_PYTHON') else '3.12')
        raise SystemExit(0)
    if 'version_info' in args[1]:
        raise SystemExit(1 if os.environ.get('FAKE_OLD_PYTHON') else 0)
    if args[1] == 'import venv, ensurepip':
        raise SystemExit(1 if os.environ.get('FAKE_NO_VENV_MODULES') else 0)
    if args[1] in ('import pip', 'import ensurepip'):
        raise SystemExit(0)
    if 'installed_version' in args[1] and os.environ.get('FAKE_PIN_MISMATCH') and not (Path(__file__).parent.parent / '.pins-ready').exists():
        raise SystemExit(1)
    if os.environ.get('FAKE_IMPORT_FAILURE'):
        raise SystemExit(1)
    ready = (Path(__file__).parent / '.imports-ready').exists() or (Path(__file__).parent.parent / '.imports-ready').exists()
    raise SystemExit(0 if ready else 1)
if args[:2] == ['-m', 'venv']:
    if os.environ.get('FAKE_VENV_FAILURE'):
        print('simulated install failure', file=sys.stderr)
        raise SystemExit(23)
    target = Path(args[-1])
    executable = target / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    executable.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(__file__, executable)
    executable.chmod(0o755)
    (target / '.imports-ready').write_text('ready')
    (target / 'pyvenv.cfg').write_text('version = 3.12.0\n')
    print('venv completed')
    raise SystemExit(0)
if args[:2] == ['-m', 'pip']:
    if os.environ.get('FAKE_PIP_FAILURE'):
        print('simulated pip failure', file=sys.stderr)
        raise SystemExit(24)
    (Path(__file__).parent.parent / '.imports-ready').write_text('ready')
    (Path(__file__).parent.parent / '.pins-ready').write_text('ready')
    print('pip completed')
    raise SystemExit(0)
if args and args[0].endswith('server.py'):
    (Path.cwd() / '.server-launched').write_text('unexpected server launch')
print('mcp-ready')
'''


def _prepare_launcher_fixture(tmp_path, *, runtime_exists=False, stamp=None, imports_ready=True):
    project = tmp_path / "安装 package"
    scripts = project / "scripts"
    scripts.mkdir(parents=True)
    shutil.copyfile(ROOT / "scripts" / "run-dsh-kline.mjs", scripts / "run-dsh-kline.mjs")
    shutil.copyfile(ROOT / "requirements.txt", project / "requirements.txt")
    (project / "server.py").write_text("# exercised by the fake Python executable\n")

    fake_base = tmp_path / "fake-python"
    fake_base.write_text(_fake_python_body().replace('#!/usr/bin/env python3', f'#!{sys.executable}'))
    fake_base.chmod(0o755)
    venv = tmp_path / "venv"
    runtime = venv / "bin" / "python"
    if runtime_exists:
        runtime.parent.mkdir(parents=True)
        shutil.copyfile(fake_base, runtime)
        runtime.chmod(0o755)
        if imports_ready:
            (venv / ".imports-ready").write_text("ready")
        (venv / "pyvenv.cfg").write_text("version = 3.12.0\n")
    if stamp is not None:
        venv.mkdir(parents=True, exist_ok=True)
        (venv / ".dsh-kline-requirements").write_text(f"{stamp}\n")

    env = {key: value for key, value in os.environ.items() if not key.startswith(("DSH_KLINE_", "FTSHARE_"))}
    env.update(
        DSH_KLINE_PYTHON=str(fake_base),
        DSH_KLINE_VENV=str(venv),
        DSH_KLINE_CACHE_DIR=str(tmp_path / "cache"),
        DSH_KLINE_RUNTIME_DIR=str(tmp_path / "runtime"),
    )
    return project, venv, env


def _run_launcher(project, env, *args):
    return subprocess.run(
        ["node", str(project / "scripts" / "run-dsh-kline.mjs"), *args],
        cwd=project,
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
    )


def _environment_fingerprint(project, venv, env):
    code = 'const m=await import(process.argv[1]); console.log(await m.bootstrapEnvironmentFingerprint(process.argv[2]))'
    return subprocess.check_output(['node', '--input-type=module', '-e', code,
        (project / 'scripts/run-dsh-kline.mjs').as_uri(), str(venv)], env=env, text=True).strip()


def test_bundle_mounts_sidebar_and_cross_platform_mcp():
    patch = (ROOT / "cordis.patch.yml").read_text(encoding="utf-8")

    assert "id: mcp-dsh-kline" in patch
    assert "name: './scripts/dsh-mcp-plugin.mjs'" in patch
    assert "id: dsh-kline-sidebar" in patch
    assert "command: !!js process.execPath" in patch
    assert "scripts/dsh-mcp-plugin.mjs" in patch
    assert "/bin/bash" not in patch
    assert "DSH_KLINE_RUNTIME_DIR" in patch
    assert "ctx.baseUrl" not in patch
    assert "scripts/dsh-mcp-plugin.mjs" in (ROOT / 'package.json').read_text()


def test_launcher_contains_native_windows_runtime_support():
    launcher = (ROOT / "scripts" / "run-dsh-kline.mjs").read_text(encoding="utf-8")

    for marker in (
        "LOCALAPPDATA",
        "Scripts', 'python.exe",
        "{ command: 'py'",
        "windowsHide: true",
        "detached: true",
        "BOOTSTRAP_RUNNING",
        "DSH_KLINE_RUNTIME_DIR",
        "bootstrap.log",
        "Python 3.11 or newer",
        "--isolated",
    ):
        assert marker in launcher


def test_release_package_is_bounded_and_attached_with_a_stable_name():
    manifest = (ROOT / "package.json").read_text(encoding="utf-8")
    packer = (ROOT / "scripts" / "build-release-package.mjs").read_text(encoding="utf-8")
    workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")

    assert '"files"' in manifest
    for required in ('"lib"', '"view"', '"requirements.txt"', '"scripts/run-dsh-kline.mjs"'):
        assert required in manifest
    assert "dsh-kline-release-" in packer
    assert "npm.cmd" in packer
    assert "RELEASE_TAG" in workflow
    assert "does not match package" in workflow
    assert "release/dsh-kline-v${VERSION}.tgz" in workflow
    assert "release/ft-kline-v${VERSION}.zip" in workflow
    assert "--draft" in workflow
    assert "types: [published]" not in workflow


def test_codex_package_has_an_explicit_isolated_allowlist_and_plugin_manifest():
    packer = (ROOT / "scripts" / "build-codex-package.mjs").read_text(encoding="utf-8")
    verifier = (ROOT / "scripts" / "verify-codex-package.mjs").read_text(encoding="utf-8")
    manifest = (ROOT / "plugins" / "ft-kline" / "mcp.json").read_text(encoding="utf-8")
    assert "chart_service.py" not in packer
    assert "${PLUGIN_ROOT}/scripts/run-ft-kline.mjs" in manifest
    assert '"name": "ft-kline"' in (ROOT / "plugins" / "ft-kline" / "plugin.json").read_text(encoding="utf-8")
    assert "chart_service.py" in verifier


def test_release_packer_ignores_files_outside_the_allowlist(tmp_path):
    archive = tmp_path / "dsh-kline.tgz"
    result = subprocess.run(
        ["node", str(ROOT / "scripts" / "build-release-package.mjs"), str(archive)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    assert archive.is_file()
    with tarfile.open(archive, "r:gz") as packed:
        names = set(packed.getnames())
    assert "package/package.json" in names
    assert "package/lib/index.js" in names
    assert "package/scripts/run-dsh-kline.mjs" in names
    assert "package/requirements.txt" in names
    assert not any("/node_modules/" in name or "/tests/" in name or "/.venv" in name for name in names)
    assert not any("/__pycache__/" in name or name.endswith((".pyc", ".pyo", ".pyd")) for name in names)


def test_launcher_path_contracts_run_in_node():
    result = subprocess.run(
        ["node", "--test", str(ROOT / "tests" / "launcher-paths.test.mjs")],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr or result.stdout


@pytest.mark.skipif(os.name == "nt", reason="Windows is covered by the packed-install CI smoke test")
def test_first_launch_bootstraps_through_the_node_launcher(tmp_path):
    project, venv, env = _prepare_launcher_fixture(tmp_path)
    result = _run_launcher(project, env)

    assert result.returncode == 0, result.stderr
    assert result.stdout == "mcp-ready\n"
    assert "venv completed" in result.stderr
    assert (venv / ".dsh-kline-requirements").read_text().strip() == _requirements_fingerprint(project / "requirements.txt")
    assert (tmp_path / "cache" / "bootstrap.log").is_file()


@pytest.mark.skipif(os.name == "nt", reason="Windows is covered by the packed-install CI smoke test")
def test_changed_requirements_repair_an_existing_runtime(tmp_path):
    project, venv, env = _prepare_launcher_fixture(tmp_path, runtime_exists=True, stamp="previous-requirements")
    result = _run_launcher(project, env)

    assert result.returncode == 0, result.stderr
    assert "dependency requirements changed" in result.stderr
    assert "Reusing the existing Python environment" in result.stderr
    assert "pip completed" in result.stderr
    assert "venv completed" not in result.stderr
    assert (venv / ".dsh-kline-requirements").read_text().strip() == _requirements_fingerprint(project / "requirements.txt")


@pytest.mark.skipif(os.name == "nt", reason="Windows is covered by the packed-install CI smoke test")
def test_incomplete_install_is_repaired_on_next_launch(tmp_path):
    project, _venv, env = _prepare_launcher_fixture(
        tmp_path,
        runtime_exists=True,
        stamp=_requirements_fingerprint(ROOT / "requirements.txt"),
        imports_ready=False,
    )
    result = _run_launcher(project, env)

    assert result.returncode == 0, result.stderr
    assert "Python runtime is missing or incomplete" in result.stderr
    assert "Reusing the existing Python environment" in result.stderr
    assert "pip completed" in result.stderr


@pytest.mark.skipif(os.name == "nt", reason="Windows is covered by the packed-install CI smoke test")
def test_dsh_host_preparation_retains_mcp_connection(tmp_path):
    project, venv, env = _prepare_launcher_fixture(tmp_path)
    shutil.copyfile(ROOT / "scripts/dsh-bootstrap.mjs", project / "scripts/dsh-bootstrap.mjs")
    (project / 'config').mkdir()
    shutil.copyfile(ROOT / 'config/dsh-tool-catalog.json', project / 'config/dsh-tool-catalog.json')
    env["DSH_KLINE_DEFER_BOOTSTRAP"] = "1"
    child = subprocess.Popen(['node', str(project / 'scripts/run-dsh-kline.mjs')], cwd=project,
                             env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        child.stdin.write(json.dumps({'jsonrpc':'2.0','id':1,'method':'initialize',
            'params':{'protocolVersion':'2024-11-05','capabilities':{},'clientInfo':{'name':'test','version':'1'}}})+'\n')
        child.stdin.write(json.dumps({'jsonrpc':'2.0','id':2,'method':'tools/list'})+'\n')
        child.stdin.flush()
        # Fake Python does not speak MCP: the front connection still completes
        # discovery and starts installation without asking the host to reconnect.
        assert json.loads(child.stdout.readline())['result']['serverInfo']['name'] == 'dsh_kline'
        tools = json.loads(child.stdout.readline())['result']['tools']
        assert any(tool['name'] == 'analyze_kline' for tool in tools)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and not (project / '.server-launched').exists():
            time.sleep(0.05)
        assert (project / '.server-launched').exists()
        assert (venv / '.dsh-kline-requirements').exists()
        assert child.poll() is None, 'MCP front must remain connected after backend exit'
    finally:
        child.stdin.close()
        child.wait(timeout=10)
        child.stdout.close()
        child.stderr.close()


@pytest.mark.skipif(os.name == "nt", reason="Windows is covered by the packed-install CI smoke test")
def test_healthy_matching_runtime_starts_without_bootstrap(tmp_path):
    project, _venv, env = _prepare_launcher_fixture(
        tmp_path,
        runtime_exists=True,
        stamp=_requirements_fingerprint(ROOT / "requirements.txt"),
    )
    result = _run_launcher(project, env)

    assert result.returncode == 0, result.stderr
    assert result.stdout == "mcp-ready\n"
    assert "venv completed" not in result.stderr


@pytest.mark.skipif(os.name == "nt", reason="POSIX fake executable integration test")
def test_ready_runtime_recovers_from_an_interrupted_bootstrap(tmp_path):
    project, venv, env = _prepare_launcher_fixture(tmp_path, runtime_exists=True)
    fingerprint = _requirements_fingerprint(project / "requirements.txt")
    failure = venv / ".dsh-kline-bootstrap-failed"
    failure.write_text(json.dumps({"fingerprint": fingerprint, "at": "2026-10-01T00:00:00.000Z", "error": "interrupted"}))

    result = _run_launcher(project, env)

    assert result.returncode == 0, result.stderr
    assert result.stdout == "mcp-ready\n"
    assert (venv / ".dsh-kline-requirements").read_text().strip() == fingerprint
    assert not failure.exists()
    assert "venv completed" not in result.stderr


@pytest.mark.skipif(os.name == "nt", reason="POSIX fake executable integration test")
def test_expired_bootstrap_failure_is_retried_automatically(tmp_path):
    project, venv, env = _prepare_launcher_fixture(tmp_path)
    fingerprint = _requirements_fingerprint(project / "requirements.txt")
    failure = venv / ".dsh-kline-bootstrap-failed"
    venv.mkdir(parents=True, exist_ok=True)
    failure.write_text(json.dumps({"fingerprint": fingerprint, "at": "2000-01-01T00:00:00.000Z", "error": "network unavailable"}))

    result = _run_launcher(project, env)

    assert result.returncode == 0, result.stderr
    assert "venv completed" in result.stderr
    assert not failure.exists()


@pytest.mark.skipif(os.name == "nt", reason="POSIX fake executable integration test")
def test_recent_bootstrap_failure_reports_its_log_and_defers_retry(tmp_path):
    project, venv, env = _prepare_launcher_fixture(tmp_path)
    fingerprint = _requirements_fingerprint(project / "requirements.txt")
    venv.mkdir(parents=True, exist_ok=True)
    (venv / ".dsh-kline-bootstrap-failed").write_text(json.dumps({
        "fingerprint": fingerprint,
        "environment": _environment_fingerprint(project, venv, env),
        "at": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime()),
        "error": "network unavailable",
    }))

    result = _run_launcher(project, env)

    assert result.returncode == 1
    assert "recently failed" in result.stderr
    assert str(tmp_path / "cache" / "bootstrap.log") in result.stderr
    assert "venv completed" not in result.stderr


@pytest.mark.skipif(os.name == "nt", reason="POSIX fake executable integration test")
def test_inconsistent_venv_metadata_is_cleared_and_rebuilt(tmp_path):
    project, venv, env = _prepare_launcher_fixture(
        tmp_path,
        runtime_exists=True,
        stamp=_requirements_fingerprint(ROOT / "requirements.txt"),
    )
    (venv / "pyvenv.cfg").write_text("version = 3.11.9\n")

    result = _run_launcher(project, env)

    assert result.returncode == 0, result.stderr
    assert "interpreter metadata is inconsistent" in result.stderr
    assert "venv completed" in result.stderr
    assert (venv / "pyvenv.cfg").read_text() == "version = 3.12.0\n"


@pytest.mark.skipif(os.name == "nt", reason="POSIX fake executable integration test")
@pytest.mark.parametrize("mode", ["", "auto"])
def test_explicit_ready_python_remains_the_selected_runtime(tmp_path, mode):
    project, _venv, env = _prepare_launcher_fixture(tmp_path)
    env.pop("DSH_KLINE_VENV")
    env["DSH_KLINE_RUNTIME_MODE"] = mode
    (tmp_path / ".imports-ready").write_text("ready")
    result = _run_launcher(project, env)

    assert result.returncode == 0, result.stderr
    assert result.stdout == "mcp-ready\n"
    assert "Preparing Python runtime" not in result.stderr


@pytest.mark.skipif(os.name == "nt", reason="POSIX fake executable integration test")
def test_external_runtime_starts_without_managing_dependencies(tmp_path):
    project, venv, env = _prepare_launcher_fixture(tmp_path)
    env.pop("DSH_KLINE_VENV")
    env["DSH_KLINE_RUNTIME_MODE"] = "external"
    env["DSH_KLINE_DEFER_BOOTSTRAP"] = "1"
    (tmp_path / ".imports-ready").write_text("ready")
    # An external runtime does not need the bootstrap dependency fingerprint.
    (project / "requirements.txt").unlink()
    result = _run_launcher(project, env)

    assert result.returncode == 0, result.stderr
    assert result.stdout == "mcp-ready\n"
    assert (project / ".server-launched").exists()
    assert not venv.exists()
    assert not (tmp_path / "cache").exists()


@pytest.mark.skipif(os.name == "nt", reason="POSIX fake executable integration test")
@pytest.mark.parametrize("failure, message", [
    ("missing_python", "requires DSH_KLINE_PYTHON"),
    ("broken_python", "working Python 3.11 or newer"),
    ("old_python", "working Python 3.11 or newer"),
    ("dependencies", "missing required dependencies"),
    ("venv", "cannot be combined"),
    ("prepare", "cannot be combined"),
    ("bootstrap", "cannot be combined"),
])
def test_external_runtime_fails_without_installation_or_fallback(tmp_path, failure, message):
    project, venv, env = _prepare_launcher_fixture(tmp_path)
    env.pop("DSH_KLINE_VENV")
    env["DSH_KLINE_RUNTIME_MODE"] = "external"
    env["DSH_KLINE_DEFER_BOOTSTRAP"] = "1"
    args = []
    if failure != "dependencies":
        (tmp_path / ".imports-ready").write_text("ready")
    if failure == "missing_python":
        env.pop("DSH_KLINE_PYTHON")
    elif failure == "broken_python":
        env["DSH_KLINE_PYTHON"] = str(tmp_path / "missing-python")
    elif failure == "old_python":
        env["FAKE_OLD_PYTHON"] = "1"
    elif failure == "venv":
        env["DSH_KLINE_VENV"] = str(venv)
    elif failure == "prepare":
        args = ["--prepare-project"]
    elif failure == "bootstrap":
        args = ["--bootstrap-runtime"]
    result = _run_launcher(project, env, *args)

    assert result.returncode == 1, result.stderr
    assert message in result.stderr
    assert not (project / ".server-launched").exists()
    assert not (project / ".venv").exists()
    assert not venv.exists()
    assert not (tmp_path / "cache").exists()
    assert not (tmp_path / "runtime").exists()


@pytest.mark.parametrize("mode", ["0", "false", "desktop", "packaged", "typo"])
def test_unknown_runtime_mode_is_rejected_before_preparation(tmp_path, mode):
    project, venv, env = _prepare_launcher_fixture(tmp_path)
    env["DSH_KLINE_RUNTIME_MODE"] = mode
    result = _run_launcher(project, env)

    assert result.returncode == 1
    assert "must be auto or external" in result.stderr
    assert not venv.exists()
    assert not (tmp_path / "cache").exists()


@pytest.mark.skipif(os.name == "nt", reason="POSIX development-venv compatibility test")
def test_checked_out_project_venv_is_diagnosed_but_not_modified(tmp_path):
    project, _venv, env = _prepare_launcher_fixture(tmp_path)
    env.pop("DSH_KLINE_VENV")
    project_runtime = project / ".venv" / "bin" / "python"
    project_runtime.parent.mkdir(parents=True)
    project_runtime.write_text(_fake_python_body())
    project_runtime.chmod(0o755)
    original = project_runtime.read_text()

    result = _run_launcher(project, env)

    assert result.returncode == 1
    assert "project .venv is incomplete" in result.stderr
    assert "venv completed" not in result.stderr
    assert project_runtime.read_text() == original


@pytest.mark.skipif(os.name == "nt", reason="Windows is covered by the packed-install CI smoke test")
def test_bootstrap_failure_is_reported_and_saved(tmp_path):
    project, _venv, env = _prepare_launcher_fixture(tmp_path)
    env["FAKE_VENV_FAILURE"] = "1"
    result = _run_launcher(project, env)

    log = tmp_path / "cache" / "bootstrap.log"
    assert result.returncode == 1
    assert "Runtime preparation failed" in result.stderr
    assert "simulated install failure" in result.stderr
    assert "simulated install failure" in log.read_text()


def test_credentials_do_not_apply_posix_modes_on_windows_model(tmp_path, monkeypatch):
    from tools import fetch

    credential = tmp_path / "credentials.json"
    monkeypatch.setenv("FTSHARE_API_KEY_FILE", str(credential))
    monkeypatch.setattr(fetch, "_uses_posix_permissions", lambda: False)
    monkeypatch.setattr(fetch.os, "chmod", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("chmod called")))
    monkeypatch.setattr(
        fetch.os,
        "fchmod",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("fchmod called")),
        raising=False,
    )

    fetch._write_persisted_ftshare_key("windows-test-key")

    assert fetch._read_persisted_ftshare_key() == "windows-test-key"


@pytest.mark.skipif(os.name != "nt", reason="Windows default path assertion")
def test_windows_credentials_default_to_local_app_data(tmp_path, monkeypatch):
    from tools import fetch

    monkeypatch.delenv("FTSHARE_API_KEY_FILE", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert fetch._ftshare_key_path() == tmp_path / "dsh_kline" / "ftshare-credentials.json"


@pytest.mark.skipif(os.name == 'nt', reason='POSIX fake executable integration test')
def test_existing_venv_upgrade_does_not_require_a_base_python(tmp_path):
    project, venv, env = _prepare_launcher_fixture(tmp_path, runtime_exists=True, stamp='old-pins')
    env['DSH_KLINE_PYTHON'] = str(tmp_path / 'missing-base-python')
    result = _run_launcher(project, env)
    assert result.returncode == 0, result.stderr
    assert 'pip completed' in result.stderr
    assert 'venv completed' not in result.stderr
    assert (venv / '.dsh-kline-requirements').read_text().strip() == _requirements_fingerprint(project / 'requirements.txt')


@pytest.mark.skipif(os.name == 'nt', reason='POSIX fake executable integration test')
def test_failed_dependency_upgrade_never_certifies_old_importable_packages(tmp_path):
    project, venv, env = _prepare_launcher_fixture(tmp_path, runtime_exists=True, stamp='old-pins')
    env['FAKE_PIP_FAILURE'] = '1'
    first = _run_launcher(project, env)
    second = _run_launcher(project, env)
    assert first.returncode == second.returncode == 1
    assert 'simulated pip failure' in first.stderr
    failure = json.loads((venv / '.dsh-kline-bootstrap-failed').read_text())
    assert failure['failureCode'] == 'PYTHON_DEPENDENCY_INSTALL_FAILED'
    assert 'recently failed' in second.stderr
    assert (venv / '.dsh-kline-requirements').read_text().strip() == 'old-pins'
    assert not (project / '.server-launched').exists()


@pytest.mark.skipif(os.name == 'nt', reason='POSIX fake executable integration test')
def test_changed_interpreter_configuration_retries_without_waiting(tmp_path):
    project, venv, env = _prepare_launcher_fixture(tmp_path)
    env['DSH_KLINE_PYTHON'] = str(tmp_path / 'missing-base-python')
    first = _run_launcher(project, env)
    assert first.returncode == 1 and 'No usable Python' in first.stderr
    env['DSH_KLINE_PYTHON'] = str(tmp_path / 'fake-python')
    second = _run_launcher(project, env)
    assert second.returncode == 0, second.stderr
    assert 'venv completed' in second.stderr
    assert not (venv / '.dsh-kline-bootstrap-failed').exists()


@pytest.mark.skipif(os.name == 'nt', reason='POSIX fake executable integration test')
def test_interpreter_installed_at_the_same_path_retries_immediately(tmp_path):
    project, _venv, env = _prepare_launcher_fixture(tmp_path)
    installed = tmp_path / 'new-python'
    env['DSH_KLINE_PYTHON'] = str(installed)
    assert _run_launcher(project, env).returncode == 1
    shutil.copyfile(tmp_path / 'fake-python', installed)
    installed.chmod(0o755)
    result = _run_launcher(project, env)
    assert result.returncode == 0, result.stderr


@pytest.mark.skipif(os.name == 'nt', reason='POSIX fake executable integration test')
def test_pinned_version_mismatch_repairs_even_with_a_matching_stamp(tmp_path):
    project, venv, env = _prepare_launcher_fixture(tmp_path, runtime_exists=True,
        stamp=_requirements_fingerprint(ROOT / 'requirements.txt'))
    env['FAKE_PIN_MISMATCH'] = '1'
    result = _run_launcher(project, env)
    assert result.returncode == 0, result.stderr
    assert 'pip completed' in result.stderr
    assert (venv / '.pins-ready').exists()


@pytest.mark.skipif(os.name == 'nt', reason='POSIX fake executable integration test')
def test_base_python_is_recovered_from_pyvenv_home_without_path_python(tmp_path):
    project, venv, env = _prepare_launcher_fixture(tmp_path)
    env.pop('DSH_KLINE_PYTHON')
    base = tmp_path / 'python base 中文'
    base.mkdir()
    shutil.copyfile(tmp_path / 'fake-python', base / 'python3')
    (base / 'python3').chmod(0o755)
    venv.mkdir()
    (venv / 'pyvenv.cfg').write_text(f'home = {base}\nversion = 3.12.0\n')
    path = tmp_path / 'node-only-path'
    path.mkdir()
    (path / 'node').symlink_to(shutil.which('node'))
    env['PATH'] = str(path)
    result = _run_launcher(project, env)
    assert result.returncode == 0, result.stderr
    assert 'venv completed' in result.stderr


@pytest.mark.skipif(os.name == 'nt', reason='POSIX fake executable integration test')
def test_trimmed_base_python_reports_missing_venv_instead_of_wrong_version(tmp_path):
    project, _venv, env = _prepare_launcher_fixture(tmp_path)
    env['FAKE_NO_VENV_MODULES'] = '1'
    result = _run_launcher(project, env)
    assert result.returncode == 1
    assert 'venv/ensurepip missing' in result.stderr
    assert 'PYTHON_VENV_UNAVAILABLE' in result.stderr
    assert 'No usable Python' not in result.stderr


def test_native_venv_upgrade_without_a_base_interpreter_or_network(tmp_path):
    """Exercise actual Windows/POSIX Python and pip, without market dependencies."""
    project = tmp_path / '安装 package'
    scripts = project / 'scripts'
    scripts.mkdir(parents=True)
    shutil.copyfile(ROOT / 'scripts/run-dsh-kline.mjs', scripts / 'run-dsh-kline.mjs')
    (project / 'requirements.txt').write_text('# offline environment upgrade\n')
    (project / 'server.py').write_text('print("native-mcp-ready")\n')
    venv = tmp_path / '已有 Python 环境'
    subprocess.run([sys.executable, '-m', 'venv', str(venv)], check=True, capture_output=True, timeout=60)
    python = venv / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    site = Path(subprocess.check_output([str(python), '-c', 'import sysconfig; print(sysconfig.get_path("purelib"))'], text=True).strip())
    for module in ('ftshare', 'mcp', 'pydantic', 'pydantic_settings'):
        (site / f'{module}.py').write_text('# offline import fixture\n')
    (site / 'talib.py').write_text('__version__="0.8.2"\ndef get_functions(): return list(range(201))\n')
    stamp = venv / '.dsh-kline-requirements'
    stamp.write_text('previous-requirements\n')
    env = {k: v for k, v in os.environ.items() if not k.startswith(('DSH_KLINE_', 'FTSHARE_', 'PYTHONPATH', 'PYTHONHOME'))}
    env.update(DSH_KLINE_PYTHON=str(tmp_path / 'missing-base-python'), DSH_KLINE_VENV=str(venv),
        DSH_KLINE_CACHE_DIR=str(tmp_path / 'cache'), DSH_KLINE_RUNTIME_DIR=str(tmp_path / 'runtime'))
    result = _run_launcher(project, env)
    assert result.returncode == 0, result.stderr
    assert result.stdout == 'native-mcp-ready\n'
    assert 'Reusing the existing Python environment' in result.stderr
    assert stamp.read_text().strip() == _requirements_fingerprint(project / 'requirements.txt')


@pytest.mark.skipif(os.name == 'nt', reason='POSIX fake executable integration test')
def test_import_verification_failure_does_not_stamp_or_launch(tmp_path):
    project, venv, env = _prepare_launcher_fixture(tmp_path, runtime_exists=True, stamp='old-pins')
    env['FAKE_IMPORT_FAILURE'] = '1'
    result = _run_launcher(project, env)
    assert result.returncode == 1
    assert 'PYTHON_IMPORT_CHECK_FAILED' in result.stderr
    assert (venv / '.dsh-kline-requirements').read_text().strip() == 'old-pins'
    assert json.loads((venv / '.dsh-kline-bootstrap-failed').read_text())['failureCode'] == 'PYTHON_IMPORT_CHECK_FAILED'
    assert not (project / '.server-launched').exists()


@pytest.mark.skipif(os.name == 'nt', reason='POSIX fake executable integration test')
def test_old_base_interpreter_is_classified_in_the_bootstrap_log(tmp_path):
    project, venv, env = _prepare_launcher_fixture(tmp_path)
    env['FAKE_OLD_PYTHON'] = '1'
    result = _run_launcher(project, env)
    assert result.returncode == 1
    assert 'PYTHON_VERSION_TOO_OLD' in result.stderr
    failure = json.loads((venv / '.dsh-kline-bootstrap-failed').read_text())
    assert failure['failureCode'] == 'PYTHON_VERSION_TOO_OLD'
    log = (tmp_path / 'cache/bootstrap.log').read_text()
    assert 'Python candidate:' in log and '3.10' in log
    assert 'PYTHON_VERSION_TOO_OLD' in log
