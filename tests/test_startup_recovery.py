"""Real MCP survives locator failure and registers once the directory is repaired."""
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


def test_dsh_startup_catalog_matches_real_tools():
    result = subprocess.run([sys.executable, str(ROOT / 'scripts/generate-dsh-catalog.py'), '--check'],
                            cwd=ROOT, capture_output=True, text=True, timeout=45)
    assert result.returncode == 0, result.stdout + result.stderr


def test_locator_failure_retains_mcp_and_recovers_without_restart(tmp_path):
    runtime = tmp_path / 'runtime'
    runtime.mkdir()
    blocker = runtime / 'services'
    blocker.write_text('temporarily not a directory')
    env = {k:v for k,v in os.environ.items() if not k.startswith(('DSH_KLINE_', 'FTSHARE_', 'FT_KLINE_'))}
    env.update(DSH_KLINE_RUNTIME_DIR=str(runtime), DSH_KLINE_CHART_PORT='0',
               DSH_KLINE_HOST_PID=str(os.getpid()), FTSHARE_API_KEY_FILE=str(tmp_path/'no-key.json'),
               PYTHONUTF8='1', PYTHONIOENCODING='utf-8')
    stderr = (tmp_path/'stderr.log').open('w', encoding='utf-8')
    child = subprocess.Popen([sys.executable, str(ROOT/'server.py')], stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE, stderr=stderr, text=True, encoding='utf-8', env=env)
    responses = queue.Queue()
    def read():
        for line in child.stdout:
            try: responses.put(json.loads(line))
            except ValueError: responses.put({'invalid_stdout':line})
    reader = threading.Thread(target=read, daemon=True)
    reader.start()
    def send(message):
        child.stdin.write(json.dumps({'jsonrpc':'2.0', **message})+'\n'); child.stdin.flush()
    def response(expected):
        deadline = time.monotonic()+25
        while time.monotonic() < deadline:
            value = responses.get(timeout=max(0.1, deadline-time.monotonic()))
            assert 'invalid_stdout' not in value, value
            if value.get('id') == expected: return value
        raise AssertionError(f'missing response {expected}')
    try:
        send({'id':1, 'method':'initialize', 'params':{'protocolVersion':'2024-11-05', 'capabilities':{}, 'clientInfo':{'name':'recovery-test','version':'1'}}})
        assert response(1)['result']['serverInfo']['name'] == 'dsh_kline'
        send({'method':'notifications/initialized'})
        send({'id':2,'method':'tools/list'})
        assert any(t['name']=='analyze_kline' for t in response(2)['result']['tools'])
        send({'id':3,'method':'tools/call','params':{'name':'list_ta_functions','arguments':{'limit':1}}})
        assert response(3)['result']['structuredContent']['total_catalog'] == 201
        assert child.poll() is None
        blocker.unlink()
        manifest = runtime/'services'/f'{os.getpid()}.json'
        deadline = time.monotonic()+12
        while not manifest.exists() and time.monotonic() < deadline: time.sleep(0.05)
        locator = json.loads(manifest.read_text())
        assert locator['process_id'] == child.pid
        with urllib.request.urlopen(locator['service_url']+'/healthz', timeout=3) as result:
            health = json.load(result)
        assert health['ok'] is True
        assert health['process_id'] == child.pid
        assert health['instance_id'] == locator['instance_id']
        assert 'service_token' not in health
        assert 'chart_service_registration_failed' in (tmp_path/'stderr.log').read_text(encoding='utf-8')
    finally:
        child.stdin.close()
        try: child.wait(timeout=10)
        except subprocess.TimeoutExpired: child.kill(); child.wait(timeout=5)
        child.stdout.close(); stderr.close()


def test_real_backend_exit_recovers_on_the_same_node_mcp_connection(tmp_path):
    import signal
    env = {k:v for k,v in os.environ.items() if not k.startswith(('DSH_KLINE_', 'FTSHARE_', 'FT_KLINE_'))}
    env.update(DSH_KLINE_PYTHON=sys.executable, DSH_KLINE_DEFER_BOOTSTRAP='1',
               DSH_KLINE_HOST_PID=str(os.getpid()), DSH_KLINE_CHART_PORT='0',
               DSH_KLINE_CACHE_DIR=str(tmp_path/'cache'), DSH_KLINE_RUNTIME_DIR=str(tmp_path/'runtime'),
               FTSHARE_API_KEY_FILE=str(tmp_path/'no-key.json'), PYTHONUTF8='1', PYTHONIOENCODING='utf-8')
    stderr = (tmp_path/'stderr.log').open('w', encoding='utf-8')
    child = subprocess.Popen(['node', str(ROOT/'scripts/run-dsh-kline.mjs')], stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE, stderr=stderr, text=True, encoding='utf-8', env=env)
    responses = queue.Queue()
    def read():
        for line in child.stdout:
            try: responses.put(json.loads(line))
            except ValueError: responses.put({'invalid_stdout':line})
    threading.Thread(target=read, daemon=True).start()
    sequence = 0
    def request(method, params=None):
        nonlocal sequence
        sequence += 1
        child.stdin.write(json.dumps({'jsonrpc':'2.0','id':sequence,'method':method,'params':params or {}})+'\n')
        child.stdin.flush()
        deadline=time.monotonic()+25
        while time.monotonic()<deadline:
            value=responses.get(timeout=max(0.1,deadline-time.monotonic()))
            assert 'invalid_stdout' not in value
            if value.get('id')==sequence:return value
        raise AssertionError('MCP response timed out')
    manifest=tmp_path/'runtime/services'/f'{os.getpid()}.json'
    def await_backend(previous=None):
        deadline=time.monotonic()+30
        while time.monotonic()<deadline:
            status=request('tools/call',{'name':'dsh_kline_runtime_status'})['result']['structuredContent']
            if status['phase']=='ready' and manifest.exists():
                locator=json.loads(manifest.read_text())
                if locator['process_id']!=previous:return locator
            assert child.poll() is None
            time.sleep(0.05)
        raise AssertionError((tmp_path/'stderr.log').read_text(encoding='utf-8'))
    try:
        assert request('initialize',{'protocolVersion':'2024-11-05','capabilities':{},'clientInfo':{'name':'restart-test','version':'1'}})['result']['serverInfo']['name']=='dsh_kline'
        initial=request('tools/list')['result']['tools']
        first=await_backend()
        result=request('tools/call',{'name':'list_ta_functions','arguments':{'limit':1}})
        assert result['result']['structuredContent']['total_catalog']==201
        os.kill(first['process_id'],signal.SIGTERM)
        recovered=await_backend(first['process_id'])
        assert recovered['instance_id']!=first['instance_id']
        assert request('tools/list')['result']['tools']==initial
        result=request('tools/call',{'name':'list_ta_functions','arguments':{'limit':1}})
        assert result['result']['structuredContent']['total_catalog']==201
        log=(tmp_path/'cache/logs'/f'backend-{os.getpid()}.log').read_text(encoding='utf-8')
        assert 'backend_exited' in log
    finally:
        child.stdin.close()
        try:child.wait(timeout=10)
        except subprocess.TimeoutExpired:child.kill();child.wait(timeout=5)
        child.stdout.close();stderr.close()
