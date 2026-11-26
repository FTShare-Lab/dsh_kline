import json
from http.client import HTTPConnection
from unittest.mock import patch

import pytest

from chart_service import ChartService


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost"])
def test_loopback_startup_and_health_do_not_require_reverse_dns(host):
    with patch("socket.getfqdn", side_effect=AssertionError("reverse DNS must not run")):
        service = ChartService(host, 0)
        connection = HTTPConnection("127.0.0.1", service.port, timeout=2)
        try:
            assert service.httpd.server_name == "127.0.0.1"
            assert service.httpd.server_port == service.port > 0
            connection.request("GET", "/healthz")
            response = connection.getresponse()
            assert response.status == 200
            assert json.loads(response.read())["ok"] is True
        finally:
            connection.close()
            service.httpd.shutdown()
            service.httpd.server_close()
            service.thread.join(timeout=2)
