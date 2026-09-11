from pathlib import Path
import hashlib
import os
import shutil
import subprocess
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
    if 'version_info' in args[1]:
        raise SystemExit(0)
    ready = (Path(__file__).parent / '.imports-ready').exists() or (Path(__file__).parent.parent / '.imports-ready').exists()
    raise SystemExit(0 if ready else 1)
if args[:2] == ['-m', 'venv']:
    if os.environ.get('FAKE_VENV_FAILURE'):
        print('simulated install failure', file=sys.stderr)
        raise SystemExit(23)
    target = Path(args[2])
    executable = target / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    executable.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(__file__, executable)
    executable.chmod(0o755)
    (target / '.imports-ready').write_text('ready')
    print('venv completed')
    raise SystemExit(0)
if args[:2] == ['-m', 'pip']:
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
    fake_base.write_text(_fake_python_body())
    fake_base.chmod(0o755)
    venv = tmp_path / "venv"
    runtime = venv / "bin" / "python"
    if runtime_exists:
        runtime.parent.mkdir(parents=True)
        shutil.copyfile(fake_base, runtime)
        runtime.chmod(0o755)
        if imports_ready:
            (venv / ".imports-ready").write_text("ready")
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


def _run_launcher(project, env):
    return subprocess.run(
        ["node", str(project / "scripts" / "run-dsh-kline.mjs")],
        cwd=project,
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
    )


def test_bundle_mounts_sidebar_and_cross_platform_mcp():
    patch = (ROOT / "cordis.patch.yml").read_text(encoding="utf-8")

    assert "id: mcp-dsh-kline" in patch
    assert "name: '@deepseek-ai/dsh-mcp-client'" in patch
    assert "id: dsh-kline-sidebar" in patch
    assert "command: !!js process.execPath" in patch
    assert "scripts/run-dsh-kline.mjs" in patch
    assert "/bin/bash" not in patch
    assert "DSH_KLINE_RUNTIME_DIR" in patch
    assert "process.platform === 'win32'" in patch


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
        "Python 3.10 or newer",
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
    assert "release/dsh-kline.tgz" in workflow
    assert "gh release upload" in workflow
    assert "--clobber" in workflow


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
    assert "venv completed" in result.stderr
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
    assert "venv completed" in result.stderr


@pytest.mark.skipif(os.name == "nt", reason="Windows is covered by the packed-install CI smoke test")
def test_dsh_host_bootstraps_in_background_before_reconnect(tmp_path):
    project, venv, env = _prepare_launcher_fixture(tmp_path)
    env["DSH_KLINE_DEFER_BOOTSTRAP"] = "1"
    result = _run_launcher(project, env)

    assert result.returncode == 1
    assert "MCP connection will retry automatically" in result.stderr
    deadline = time.monotonic() + 5
    stamp = venv / ".dsh-kline-requirements"
    while time.monotonic() < deadline and not stamp.exists():
        time.sleep(0.05)
    assert stamp.read_text().strip() == _requirements_fingerprint(project / "requirements.txt")
    assert not (venv / ".dsh-kline-bootstrap-running").exists()
    assert not (project / ".server-launched").exists()


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
def test_explicit_ready_python_remains_the_selected_runtime(tmp_path):
    project, _venv, env = _prepare_launcher_fixture(tmp_path)
    env.pop("DSH_KLINE_VENV")
    (tmp_path / ".imports-ready").write_text("ready")
    result = _run_launcher(project, env)

    assert result.returncode == 0, result.stderr
    assert result.stdout == "mcp-ready\n"
    assert "Preparing Python runtime" not in result.stderr


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
