"""The shipped startup contract must match the real Python tools/resource."""
import hashlib
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]

def test_shipped_catalogs_match_python_definitions():
    subprocess.run([sys.executable, str(ROOT / 'scripts/generate-codex-catalog.py'), '--check'],
                   cwd=ROOT, check=True, timeout=90, capture_output=True, text=True)

def test_early_node_resource_is_identical_to_python_resource(monkeypatch):
    monkeypatch.setenv('FT_KLINE_CODEX_MEMORY_ONLY', '1')
    from codex_runtime.mcp_app import mcp_app_html
    expected = hashlib.sha256(mcp_app_html().encode()).hexdigest()
    script = "import {chartResource} from './scripts/codex-bootstrap.mjs'; import{createHash}from'node:crypto'; console.log(createHash('sha256').update(chartResource()).digest('hex'))"
    result = subprocess.run(['node', '--input-type=module', '-e', script], cwd=ROOT,
                            capture_output=True, text=True, timeout=20, check=True)
    assert result.stdout.strip() == expected
