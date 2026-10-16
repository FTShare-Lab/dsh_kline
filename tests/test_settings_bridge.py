import json
import os
import sys
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from tools.fetch import (
    _ftshare_credential_source,
    _ftshare_key_path,
    _ftshare_market_api,
    _refresh_persisted_ftshare_key,
    _resolve_persisted_ftshare_key,
    ftshare_status,
)


def write_credential(path: Path, key: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if os.name == "posix":
        os.chmod(path.parent, 0o700)
    path.write_text(json.dumps({"version": 1, "api_key": key}), encoding="utf-8")
    if os.name == "posix":
        os.chmod(path, 0o600)
    return path


class SettingsBridgeTests(unittest.TestCase):
    """The DSH host can publish its FTShare settings Key as a credential file.

    The MCP server must follow that file — including changes and removals made
    while it runs — without ever overriding a Key the host environment or a
    temporary in-process override supplied.
    """

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.home = self.root / "home"
        self.local = self.root / "local"
        self.cache = self.root / "cache"
        for directory in (self.home, self.local, self.cache):
            directory.mkdir(parents=True, exist_ok=True)
        self.bridge = write_credential(self.root / "runtime" / "credentials" / "ftshare-1.json", "bridge-key")

    @contextmanager
    def credential_env(self, **values):
        env = {
            "HOME": str(self.home),
            "LOCALAPPDATA": str(self.local),
            "APPDATA": str(self.local),
            "XDG_CACHE_HOME": str(self.cache),
            "USERPROFILE": str(self.home),
        }
        env.update(values)
        with patch.dict("os.environ", env, clear=True), patch(
            "tools.fetch._FTSHARE_RUNTIME_CREDENTIAL_SOURCE", None
        ), patch("tools.fetch._FTSHARE_RUNTIME_FILE_KEY", None):
            yield

    def store_path(self) -> Path:
        with self.credential_env():
            return _ftshare_key_path()

    def test_launcher_pointed_file_credentials_the_process(self):
        # The DSH launcher always defines FTSHARE_API_KEY, empty when the host
        # has none; an empty value must not shadow the published file.
        with self.credential_env(FTSHARE_API_KEY="", DSH_KLINE_SETTINGS_KEY_FILE=str(self.bridge)):
            _refresh_persisted_ftshare_key()
            self.assertEqual(os.environ["FTSHARE_API_KEY"], "bridge-key")
            self.assertEqual(_ftshare_credential_source(), "settings_bridge")

    def test_settings_credential_outranks_the_plugin_store(self):
        write_credential(self.store_path(), "store-key")
        with self.credential_env(FTSHARE_API_KEY="", DSH_KLINE_SETTINGS_KEY_FILE=str(self.bridge)):
            self.assertEqual(_resolve_persisted_ftshare_key(), ("bridge-key", "settings_bridge"))
            _refresh_persisted_ftshare_key()
            self.assertEqual(os.environ["FTSHARE_API_KEY"], "bridge-key")

    def test_explicit_credential_file_remains_authoritative(self):
        explicit = write_credential(self.root / "explicit" / "credentials.json", "explicit-key")
        with self.credential_env(
            FTSHARE_API_KEY="", FTSHARE_API_KEY_FILE=str(explicit), DSH_KLINE_SETTINGS_KEY_FILE=str(self.bridge)
        ):
            self.assertEqual(_resolve_persisted_ftshare_key(), ("explicit-key", "external_file"))
            self.assertEqual(_ftshare_credential_source(), "none")

    def test_host_environment_key_is_never_replaced(self):
        with self.credential_env(FTSHARE_API_KEY="host-key", DSH_KLINE_SETTINGS_KEY_FILE=str(self.bridge)):
            _refresh_persisted_ftshare_key()
            self.assertEqual(os.environ["FTSHARE_API_KEY"], "host-key")
            self.assertEqual(_ftshare_credential_source(), "environment")

    def test_temporary_override_is_never_replaced(self):
        with self.credential_env(FTSHARE_API_KEY="temporary-key", DSH_KLINE_SETTINGS_KEY_FILE=str(self.bridge)), patch(
            "tools.fetch._FTSHARE_RUNTIME_CREDENTIAL_SOURCE", "session"
        ):
            _refresh_persisted_ftshare_key()
            self.assertEqual(os.environ["FTSHARE_API_KEY"], "temporary-key")

    def test_follows_a_key_change_without_a_restart(self):
        with self.credential_env(FTSHARE_API_KEY="", DSH_KLINE_SETTINGS_KEY_FILE=str(self.bridge)):
            _refresh_persisted_ftshare_key()
            self.assertEqual(os.environ["FTSHARE_API_KEY"], "bridge-key")
            write_credential(self.bridge, "rotated-key")
            _refresh_persisted_ftshare_key()
            self.assertEqual(os.environ["FTSHARE_API_KEY"], "rotated-key")
            self.assertEqual(_ftshare_credential_source(), "settings_bridge")

    def test_same_key_still_changes_ownership_when_bridge_takes_precedence(self):
        write_credential(self.store_path(), "bridge-key")
        with self.credential_env(FTSHARE_API_KEY="bridge-key", DSH_KLINE_SETTINGS_KEY_FILE=str(self.bridge)), patch(
            "tools.fetch._FTSHARE_RUNTIME_CREDENTIAL_SOURCE", "plugin_store"
        ), patch("tools.fetch._FTSHARE_RUNTIME_FILE_KEY", "bridge-key"):
            _refresh_persisted_ftshare_key()
            self.assertEqual(_ftshare_credential_source(), "settings_bridge")
            with patch("tools.fetch.ftshare_available", return_value=True):
                self.assertFalse(ftshare_status()["can_clear"])

    def test_external_environment_replacement_after_file_load_is_not_overridden(self):
        with self.credential_env(FTSHARE_API_KEY="", DSH_KLINE_SETTINGS_KEY_FILE=str(self.bridge)):
            _refresh_persisted_ftshare_key()
            os.environ["FTSHARE_API_KEY"] = "explicit-replacement"
            _refresh_persisted_ftshare_key()
            self.assertEqual(os.environ["FTSHARE_API_KEY"], "explicit-replacement")
            self.assertEqual(_ftshare_credential_source(), "environment")

    def test_rotation_clears_provider_caches_only_when_key_changes(self):
        with self.credential_env(FTSHARE_API_KEY="", DSH_KLINE_SETTINGS_KEY_FILE=str(self.bridge)), patch(
            "tools.fetch.clear_provider_caches"
        ) as clear:
            _refresh_persisted_ftshare_key()
            clear.assert_called_once()
            _refresh_persisted_ftshare_key()
            clear.assert_called_once()
            write_credential(self.bridge, "next-key")
            _refresh_persisted_ftshare_key()
            self.assertEqual(clear.call_count, 2)

    def test_clearing_the_setting_drops_the_key(self):
        with self.credential_env(FTSHARE_API_KEY="", DSH_KLINE_SETTINGS_KEY_FILE=str(self.bridge)):
            _refresh_persisted_ftshare_key()
            self.assertTrue(_ftshare_credential_source() == "settings_bridge")
            self.bridge.unlink()
            _refresh_persisted_ftshare_key()
            self.assertNotIn("FTSHARE_API_KEY", os.environ)
            self.assertEqual(_ftshare_credential_source(), "none")
            self.assertEqual(_resolve_persisted_ftshare_key(), ("", ""))

    def test_market_api_uses_the_published_key(self):
        captured = {}

        def market_api(**kwargs):
            captured.update(kwargs)
            return SimpleNamespace()

        with self.credential_env(FTSHARE_API_KEY="", DSH_KLINE_SETTINGS_KEY_FILE=str(self.bridge)):
            with patch.dict(sys.modules, {"ftshare": SimpleNamespace(market_api=market_api)}):
                _ftshare_market_api(timeout=5)

        self.assertEqual(captured["headers"], {"FTSHARE_API_KEY": "bridge-key"})

    def test_empty_host_key_does_not_reenter_the_sdk_environment_fallback(self):
        captured = {}

        def market_api(**kwargs):
            # Mirrors the installed SDK's documented constructor fallback.
            headers = dict(kwargs.get("headers") or {})
            if os.environ.get("FTSHARE_API_KEY") is not None:
                headers["FTSHARE_API_KEY"] = os.environ["FTSHARE_API_KEY"]
            captured.update(headers)
            return SimpleNamespace()

        with self.credential_env(FTSHARE_API_KEY=""), patch(
            "tools.fetch._FTSHARE_RUNTIME_CREDENTIAL_SOURCE", "environment"
        ), patch.dict(sys.modules, {"ftshare": SimpleNamespace(market_api=market_api)}):
            _ftshare_market_api(timeout=5)
        self.assertEqual(captured, {})

    def test_status_reports_the_settings_source_without_leaking_it(self):
        with self.credential_env(FTSHARE_API_KEY="", DSH_KLINE_SETTINGS_KEY_FILE=str(self.bridge)), patch(
            "tools.fetch.ftshare_available", return_value=True
        ):
            status = ftshare_status()

        self.assertTrue(status["configured"])
        self.assertTrue(status["persistent"])
        self.assertEqual(status["credential_source"], "settings_bridge")
        # The DSH settings page owns this Key; this plugin must not clear it.
        self.assertFalse(status["can_clear"])
        self.assertNotIn("bridge-key", str(status))
        self.assertNotIn(str(self.bridge), str(status))

    def test_the_plugin_store_still_reports_its_own_source(self):
        write_credential(self.store_path(), "store-key")
        with self.credential_env(FTSHARE_API_KEY=""), patch("tools.fetch.ftshare_available", return_value=True):
            status = ftshare_status()

        self.assertEqual(status["credential_source"], "plugin_store")
        self.assertTrue(status["can_clear"])

    def test_unusable_files_are_ignored(self):
        cases = {
            "malformed": "{not json",
            "unknown version": json.dumps({"version": 2, "api_key": "bridge-key"}),
            "boolean version": json.dumps({"version": True, "api_key": "bridge-key"}),
            "numeric key": json.dumps({"version": 1, "api_key": 123}),
            "object key": json.dumps({"version": 1, "api_key": {"secret": "bridge-key"}}),
            "empty key": json.dumps({"version": 1, "api_key": ""}),
            "untrimmed blank": json.dumps({"version": 1, "api_key": "   "}),
        }
        for label, payload in cases.items():
            with self.subTest(label=label):
                self.bridge.write_text(payload, encoding="utf-8")
                with self.credential_env(FTSHARE_API_KEY="", DSH_KLINE_SETTINGS_KEY_FILE=str(self.bridge)):
                    _refresh_persisted_ftshare_key()
                    # No credential anywhere: `_ftshare_credential_source()` is
                    # the safe, path-free way to assert an unusable file was dropped.
                    self.assertEqual(_ftshare_credential_source(), "none")

    @unittest.skipUnless(os.name == "posix", "POSIX permission bits only")
    def test_a_world_readable_file_is_ignored(self):
        os.chmod(self.bridge, 0o644)
        with self.credential_env(FTSHARE_API_KEY="", DSH_KLINE_SETTINGS_KEY_FILE=str(self.bridge)):
            _refresh_persisted_ftshare_key()
            self.assertEqual(_ftshare_credential_source(), "none")

    def test_without_the_launcher_variable_nothing_changes(self):
        write_credential(self.store_path(), "store-key")
        with self.credential_env(FTSHARE_API_KEY=""):
            _refresh_persisted_ftshare_key()
            self.assertEqual(os.environ["FTSHARE_API_KEY"], "store-key")
            self.assertEqual(_ftshare_credential_source(), "plugin_store")


if __name__ == "__main__":
    unittest.main()
