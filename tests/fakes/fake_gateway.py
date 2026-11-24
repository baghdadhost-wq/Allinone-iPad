#!/usr/bin/env python3
"""A stand-in gateway speaking the Anthropic Messages API, for tests.

GET  /health          200
GET  /v1/models       200 with Bearer FAKE_TOKEN (401 otherwise)
POST /v1/messages     echoes the last user message
Every request is appended to $FAKE_GATEWAY_LOG as a JSON line.
"""

import argparse
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

TOKEN = os.environ.get("FAKE_TOKEN", "fake-token")
LOG = os.environ.get("FAKE_GATEWAY_LOG")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _log(self, body=None):
        if LOG:
            with open(LOG, "a", encoding="utf-8") as fh:
                fh.write(json.dumps({"method": self.command, "path": self.path,
                                     "auth": self.headers.get("Authorization", ""),
                                     "body": body}) + "\n")

    def _send(self, code, payload):
        data = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _authorized(self):
        return self.headers.get("Authorization") == f"Bearer {TOKEN}" or self.headers.get("x-api-key") == TOKEN

    def do_GET(self):
        self._log()
        if self.path == "/health":
            return self._send(200, {"ok": True})
        if self.path == "/v1/models":
            if not self._authorized():
                return self._send(401, {"error": "unauthorized"})
            return self._send(200, {"data": [{"id": "auto"}, {"id": "fake/model-1"}, {"id": "fake/model-2"}]})
        return self._send(404, {"error": "not found"})

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length) or b"{}")
        self._log(body)
        if self.path != "/v1/messages":
            return self._send(404, {"error": "not found"})
        if not self._authorized():
            return self._send(401, {"type": "error", "error": {"type": "authentication_error"}})
        last = body["messages"][-1]["content"]
        if isinstance(last, list):
            last = " ".join(b.get("text", "") for b in last if isinstance(b, dict))
        return self._send(200, {
            "id": "msg_fake", "type": "message", "role": "assistant", "model": body.get("model"),
            "content": [{"type": "text", "text": f"echo: {last}"}],
            "stop_reason": "end_turn", "usage": {"input_tokens": 1, "output_tokens": 1},
        })


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, required=True)
    args = ap.parse_args()
    ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
