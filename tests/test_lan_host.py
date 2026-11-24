import hashlib
import http.client
import json
import ssl
import threading
import unittest
from contextlib import ExitStack
from http.server import ThreadingHTTPServer

import host


class LANHostTests(unittest.TestCase):
    def test_encrypted_question_flow(self):
        received = []

        def answer(question):
            received.append(question)
            return "جواب الاختبار"

        with ExitStack() as stack:
            tls, pin = stack.enter_context(host.tls_context("127.0.0.1"))
            server = stack.enter_context(ThreadingHTTPServer(("127.0.0.1", 0), host.handler_for("paired", answer)))
            server.socket = tls.wrap_socket(server.socket, server_side=True, do_handshake_on_connect=False)
            threading.Thread(target=server.serve_forever, daemon=True).start()
            stack.callback(server.shutdown)

            def call(method, path, token="", body=None):
                ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
                conn = http.client.HTTPSConnection("127.0.0.1", server.server_port, context=ctx, timeout=3)
                try:
                    conn.connect()
                    self.assertEqual(hashlib.sha256(conn.sock.getpeercert(binary_form=True)).hexdigest(), pin)
                    conn.request(method, path, body, {"Authorization": "Bearer " + token, "Content-Type": "application/json"})
                    resp = conn.getresponse()
                    return resp.status, resp.read()
                finally:
                    conn.close()

            self.assertEqual(call("GET", "/")[0], 200)
            self.assertEqual(call("POST", "/ask", "wrong", "{}")[0], 401)
            self.assertEqual(call("POST", "/ask", "paired", "[]")[0], 400)
            status, data = call("POST", "/ask", "paired", json.dumps({"question": "سؤال عربي"}))
            self.assertEqual(status, 200)
            self.assertEqual(json.loads(data)["answer"], "جواب الاختبار")
            self.assertEqual(received, ["سؤال عربي"])
