"""Tests for alexa-skill/lambda_function.py (stdlib only, local fake HA server)."""

from __future__ import annotations

import importlib.util
import json
import os
import pathlib
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest import mock

LAMBDA = pathlib.Path(__file__).resolve().parents[1] / "alexa-skill" / "lambda_function.py"
spec = importlib.util.spec_from_file_location("lambda_function", LAMBDA)
lambda_function = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lambda_function)


class FakeHomeAssistant(BaseHTTPRequestHandler):
    status = 200
    received: list = []

    def do_POST(self):  # noqa: N802 (http.server API)
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        FakeHomeAssistant.received.append((self.path, self.headers["Authorization"], body))
        self.send_response(FakeHomeAssistant.status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"event": {"header": {"name": "Response"}}}).encode())

    def log_message(self, *args):
        pass


def directive(name="TurnOn", token="abc", where="endpoint"):
    d = {
        "header": {"namespace": "Alexa.PowerController", "name": name, "payloadVersion": "3",
                   "messageId": "1", "correlationToken": "corr"},
        "endpoint": {"endpointId": "switch#tv"},
        "payload": {},
    }
    if token and where == "endpoint":
        d["endpoint"]["scope"] = {"type": "BearerToken", "token": token}
    if token and where == "grantee":
        d["payload"]["grantee"] = {"type": "BearerToken", "token": token}
    return {"directive": d}


class LambdaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = HTTPServer(("127.0.0.1", 0), FakeHomeAssistant)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.url = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def setUp(self):
        FakeHomeAssistant.received = []
        FakeHomeAssistant.status = 200

    def call(self, event, **env):
        with mock.patch.dict(os.environ, {"BASE_URL": self.url + "/", **env}, clear=True):
            return lambda_function.lambda_handler(event, None)

    def test_forwards_directive_with_bearer_token(self):
        event = directive()
        result = self.call(event)
        self.assertEqual(result, {"event": {"header": {"name": "Response"}}})
        path, auth, body = FakeHomeAssistant.received[0]
        self.assertEqual(path, "/api/alexa/smart_home")
        self.assertEqual(auth, "Bearer abc")
        self.assertEqual(body, event)

    def test_accept_grant_token_from_grantee(self):
        self.call(directive(name="AcceptGrant", where="grantee"))
        self.assertEqual(FakeHomeAssistant.received[0][1], "Bearer abc")

    def test_missing_token_gives_auth_error_without_request(self):
        result = self.call(directive(token=None))
        self.assertEqual(result["event"]["payload"]["type"], "INVALID_AUTHORIZATION_CREDENTIAL")
        self.assertEqual(result["event"]["header"]["correlationToken"], "corr")
        self.assertEqual(FakeHomeAssistant.received, [])

    def test_long_lived_token_only_with_debug(self):
        self.call(directive(token=None), DEBUG="true", LONG_LIVED_ACCESS_TOKEN="llat")
        self.assertEqual(FakeHomeAssistant.received[0][1], "Bearer llat")
        result = self.call(directive(token=None), LONG_LIVED_ACCESS_TOKEN="llat")
        self.assertEqual(result["event"]["payload"]["type"], "INVALID_AUTHORIZATION_CREDENTIAL")

    def test_ha_rejects_token(self):
        FakeHomeAssistant.status = 401
        result = self.call(directive())
        self.assertEqual(result["event"]["payload"]["type"], "INVALID_AUTHORIZATION_CREDENTIAL")
        self.assertEqual(result["event"]["endpoint"]["endpointId"], "switch#tv")

    def test_ha_unreachable(self):
        with mock.patch.dict(os.environ, {"BASE_URL": "http://127.0.0.1:1"}, clear=True):
            result = lambda_function.lambda_handler(directive(), None)
        self.assertEqual(result["event"]["payload"]["type"], "ENDPOINT_UNREACHABLE")

    def test_rejects_non_alexa_events(self):
        with self.assertRaises(ValueError):
            self.call({"foo": "bar"})


if __name__ == "__main__":
    unittest.main()
