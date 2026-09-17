"""Exercise the real entrypoint without Python's automatic script path."""

import os
from pathlib import Path
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]


class IsolatedEntrypointTest(unittest.TestCase):
    def test_help_from_unrelated_directory(self):
        # -I ignores PYTHONPATH and excludes the script directory, like ._pth.
        # --help imports the actual server but exits before starting services.
        result = subprocess.run(
            [sys.executable, "-I", "-B", str(ROOT / "server.py"), "--help"],
            cwd=ROOT.parent,
            env={
                **os.environ,
                "PYTHONPATH": str(ROOT.parent),
                # Avoid Wine's unsupported getppid/PssCaptureSnapshot path.
                "DSH_KLINE_HOST_PID": str(os.getpid()),
            },
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Standalone dsh_kline MCP server", result.stdout)


if __name__ == "__main__":
    if sys.platform != "win32":
        import resource

        resource.setrlimit(resource.RLIMIT_AS, (1024**3, 1024**3))
        resource.setrlimit(resource.RLIMIT_CPU, (30, 30))
    unittest.main()
