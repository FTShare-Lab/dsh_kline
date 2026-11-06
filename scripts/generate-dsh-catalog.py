#!/usr/bin/env python3
"""Export the DSH startup catalog from the actual FastMCP definitions."""
import argparse
import json
import inspect
import difflib
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def canonical(value):
    # Python 3.13 strips docstring indentation at compilation; 3.11/3.12
    # retain it. Normalize descriptions only, keeping schemas and tool names
    # strict so the same semantic catalog is portable across supported Python.
    if isinstance(value, list):
        return [canonical(item) for item in value]
    if isinstance(value, dict):
        return {key: inspect.cleandoc(item) if key == 'description' and isinstance(item, str)
                else canonical(item) for key, item in value.items()}
    return value

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--export', action='store_true')
    args = parser.parse_args()
    if args.export:
        sys.path.insert(0, str(ROOT))
        import anyio
        import server
        async def collect():
            return {'version': json.loads((ROOT / 'package.json').read_text())['version'],
                    'instructions': server.mcp.instructions,
                    'tools': [tool.model_dump(mode='json', by_alias=True, exclude_none=True) for tool in await server.mcp.list_tools()]}
        print(json.dumps(canonical(anyio.run(collect)), ensure_ascii=False, sort_keys=True, indent=2))
        return
    env = {k: v for k, v in os.environ.items() if not k.startswith(('DSH_KLINE_', 'FTSHARE_', 'FT_KLINE_'))}
    env.update(PYTHONUTF8='1', PYTHONIOENCODING='utf-8')
    result = subprocess.run([sys.executable, __file__, '--export'], env=env, capture_output=True, text=True, encoding='utf-8', check=True, timeout=30)
    target = ROOT / 'config/dsh-tool-catalog.json'
    if args.check:
        if target.read_text(encoding='utf-8') != result.stdout:
            diff = list(difflib.unified_diff(target.read_text(encoding='utf-8').splitlines(),
                        result.stdout.splitlines(), fromfile='shipped', tofile='actual', lineterm=''))
            print('\n'.join(diff[:100]), file=sys.stderr)
            raise SystemExit('Stale DSH catalog; run scripts/generate-dsh-catalog.py')
    else:
        target.write_text(result.stdout, encoding='utf-8')
    print('DSH startup catalog verified' if args.check else 'DSH startup catalog generated')

if __name__ == '__main__':
    main()
