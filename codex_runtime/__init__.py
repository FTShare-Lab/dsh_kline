"""Codex-only runtime for the FT K-Line MCP App.

This package is intentionally independent of the DSH loopback server.  It is
loaded only by ``codex_server.py`` and stores all chart state in this process.
"""

from .state import APP_RESOURCE_URI, CodexChartStore

__all__ = ["APP_RESOURCE_URI", "CodexChartStore"]
