from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_bundle_mounts_sidebar_and_mcp_for_standard_installs():
    patch = (ROOT / "cordis.patch.yml").read_text(encoding="utf-8")

    assert "id: mcp-dsh-kline" in patch
    assert "name: '@deepseek-ai/dsh-mcp-client'" in patch
    assert "id: dsh-kline-sidebar" in patch
    assert "new URL('./node_modules/@ftshare-lab/dsh-kline/', ctx.baseUrl).pathname" in patch


def test_runner_prepares_a_user_runtime_without_a_project_venv():
    runner = (ROOT / "scripts" / "run-dsh-kline.sh").read_text(encoding="utf-8")
    bootstrap = (ROOT / "scripts" / "bootstrap.sh").read_text(encoding="utf-8")

    assert "${XDG_CACHE_HOME:-$HOME/.cache}/dsh_kline" in runner
    assert '"$PROJECT_ROOT/scripts/bootstrap.sh" >&2' in runner
    assert "python3.10" in bootstrap
    assert "Python 3.10 or newer" in bootstrap
