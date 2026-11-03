"""The shipped startup contract must match the real Python tools/resource."""
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import shutil
import pytest

ROOT = Path(__file__).resolve().parents[1]

def test_shipped_catalogs_match_python_definitions():
    subprocess.run([sys.executable, str(ROOT / 'scripts/generate-codex-catalog.py'), '--check'],
                   cwd=ROOT, check=True, timeout=90, capture_output=True, text=True)

@pytest.mark.parametrize('newline', [b'\n', b'\r\n'])
def test_early_node_resource_is_identical_to_python_resource(monkeypatch, tmp_path, newline):
    monkeypatch.setenv('FT_KLINE_CODEX_MEMORY_ONLY', '1')
    from codex_runtime.mcp_app import mcp_app_html
    expected = hashlib.sha256(mcp_app_html().encode()).hexdigest()
    # Reproduce checkout line endings without changing the shared working tree.
    for name in ('scripts/codex-bootstrap.mjs', 'codex_runtime/catalog-desktop.json',
                 'codex_runtime/catalog-cli.json', 'package.json', 'view/ft-logo.jpg'):
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, target)
    for name in ('view/kline.html', 'view/vendor/klinecharts.min.js'):
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        text = (ROOT / name).read_text(encoding='utf-8')
        target.write_bytes(text.encode('utf-8').replace(b'\n', newline))
    script = "import {chartResource} from './scripts/codex-bootstrap.mjs'; import{createHash}from'node:crypto'; console.log(createHash('sha256').update(chartResource()).digest('hex'))"
    result = subprocess.run(['node', '--input-type=module', '-e', script], cwd=tmp_path,
                            capture_output=True, text=True, timeout=20, check=True)
    assert result.stdout.strip() == expected
