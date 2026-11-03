import json
import os

def test_explicit_file_rotation_environment_precedence_and_no_key_echo(monkeypatch, tmp_path):
    monkeypatch.setenv('FT_KLINE_CODEX_MEMORY_ONLY', '1')
    import codex_server
    path = tmp_path / 'selected.json'
    def write(key):
        path.write_text(json.dumps({'version': 1, 'api_key': key}))
        path.chmod(0o600)
    write('first-file-secret')
    monkeypatch.delenv('FTSHARE_API_KEY', raising=False)
    monkeypatch.setenv('FTSHARE_API_KEY_FILE', str(path))
    with codex_server._session_credential(None) as source:
        assert source == 'external_file'
        assert os.environ['FTSHARE_API_KEY'] == 'first-file-secret'
        status = codex_server._data_source_payload(source)
        assert status['providers']['ftshare']['credential_source'] == source
        assert 'first-file-secret' not in json.dumps(status)
        assert str(path) not in json.dumps(status)
    assert 'FTSHARE_API_KEY' not in os.environ
    write('rotated-file-secret')
    with codex_server._session_credential(None):
        assert os.environ['FTSHARE_API_KEY'] == 'rotated-file-secret'
    monkeypatch.setenv('FTSHARE_API_KEY', 'environment-secret')
    with codex_server._session_credential(None) as source:
        assert source == 'environment'
        assert os.environ['FTSHARE_API_KEY'] == 'environment-secret'
    assert os.environ['FTSHARE_API_KEY'] == 'environment-secret'


def test_invalid_explicit_file_never_falls_back_to_dsh_store(monkeypatch, tmp_path):
    monkeypatch.setenv('FT_KLINE_CODEX_MEMORY_ONLY', '1')
    import codex_server
    monkeypatch.delenv('FTSHARE_API_KEY', raising=False)
    path = tmp_path / 'bad.json'
    path.write_text('{bad json')
    path.chmod(0o600)
    monkeypatch.setenv('FTSHARE_API_KEY_FILE', str(path))
    monkeypatch.setenv('DSH_KLINE_SETTINGS_KEY_FILE', str(tmp_path / 'not-selected.json'))
    assert codex_server._credential_choice() == ('', 'none')
    path.write_text(json.dumps({'version': 1, 'api_key': 'private'}))
    if os.name == 'posix':
        path.chmod(0o644)
        assert codex_server._credential_choice() == ('', 'none')
    path.unlink()
    assert codex_server._credential_choice() == ('', 'none')
