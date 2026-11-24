"""Start Allinone's selected gateway and serve its question client over local HTTPS."""
import argparse
import hashlib
import os
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import json
from pathlib import Path
import secrets
import socket
import ssl
import subprocess
import tempfile
import threading

from controller import flows
from controller.context import Context
from controller.claude import STRIP_PREFIXES, STRIP_VARS

CLIENT = Path(__file__).with_name("client.html")
MAX_BODY = 64 * 1024


def local_ip():
    # UDP connect selects the outgoing interface without sending a packet.
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.connect(("192.0.2.1", 9))
        return sock.getsockname()[0]


@contextmanager
def tls_context(address):
    with tempfile.TemporaryDirectory() as temp:
        crt = Path(temp) / "server.pem"
        key = Path(temp) / "server.key"
        subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048",
                        "-nodes", "-sha256", "-days", "7", "-subj", "/CN=Allinone",
                        "-addext", f"subjectAltName=IP:{address},IP:127.0.0.1",
                        "-keyout", str(key), "-out", str(crt)], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        ctx.load_cert_chain(crt, key)
        pin = hashlib.sha256(ssl.PEM_cert_to_DER_cert(crt.read_text())).hexdigest()
        yield ctx, pin


def handler_for(token, ask):
    busy = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        timeout = 15

        def reply(self, status, body, content_type="application/json"):
            if content_type == "application/json":
                body = json.dumps(body, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path == "/":
                self.reply(200, CLIENT.read_bytes(), "text/html; charset=utf-8")
            else:
                self.reply(404, {"error": "مسار غير موجود"})

        def do_POST(self):
            if self.path != "/ask":
                return self.reply(404, {"error": "مسار غير موجود"})
            auth = self.headers.get("Authorization", "").encode()
            if not secrets.compare_digest(auth, ("Bearer " + token).encode()):
                return self.reply(401, {"error": "تحقق من رمز الاتصال الظاهر على المضيف"})
            if self.headers.get_content_type() != "application/json":
                return self.reply(415, {"error": "يتطلب الطلب JSON"})
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= MAX_BODY:
                    return self.reply(413, {"error": "حجم الطلب غير مقبول"})
                payload = json.loads(self.rfile.read(length))
                if not isinstance(payload, dict) or not isinstance(payload.get("question"), str):
                    raise ValueError()
                question = payload["question"].strip()
                if not question:
                    raise ValueError()
            except (ValueError, RecursionError):
                return self.reply(400, {"error": "أدخل سؤالا صالحا"})
            if not busy.acquire(blocking=False):
                return self.reply(429, {"error": "المضيف يجيب عن سؤال آخر. حاول بعد قليل"})
            try:
                answer = ask(question)
            except Exception as exc:
                print("Question failed:", type(exc).__name__, flush=True)
                return self.reply(502, {"error": "تعذر الحصول على جواب. تحقق من البوابة على المضيف"})
            finally:
                busy.release()
            self.reply(200, {"answer": answer})

        def log_message(self, *args):
            pass

    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gateway", choices=["omniroute", "freellmapi"], default="omniroute")
    parser.add_argument("--model")
    parser.add_argument("--advertise-ip", type=ipaddress.IPv4Address,
                        help="iPad Wi-Fi address when using guest port forwarding")
    parser.add_argument("--port", type=int, default=8743)
    args = parser.parse_args()
    address = args.advertise_ip or local_ip()
    ctx = Context()
    gateway = ctx.gateway(args.gateway)
    flows.ensure_claude(ctx, False)

    # Clients get question/answer access only. Start the installed Claude executable
    # with a private working directory and no project hooks, MCP servers or tools.
    command = ctx.claude().command()
    env = {k: v for k, v in os.environ.items() if not k.startswith(STRIP_PREFIXES) and k not in STRIP_VARS}
    token = secrets.token_urlsafe(18)
    with tempfile.TemporaryDirectory() as work, tls_context(address) as (tls, pin):
        env["CLAUDE_CONFIG_DIR"] = work
        def ask(question):
            proc = subprocess.run([*command, "-p", "--output-format", "json", "--tools", "",
                                   "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
                                   "--setting-sources", "", "--no-session-persistence"],
                                  cwd=work, env=env, input=question, text=True,
                                  capture_output=True, timeout=240, check=True)
            result = json.loads(proc.stdout)
            if result.get("is_error") or not isinstance(result.get("result"), str):
                raise RuntimeError("Claude response")
            return result["result"]

        with ThreadingHTTPServer(("", args.port), handler_for(token, ask)) as server:
            server.socket = tls.wrap_socket(server.socket, server_side=True, do_handshake_on_connect=False)
            started = flows.bring_up(ctx, gateway, False)
            try:
                env.update(gateway.claude_env(args.model))
                print(f"Local: https://127.0.0.1:{server.server_port}/\n"
                      f"Wi-Fi: https://{address}:{server.server_port}/\n"
                      f"Pairing code: {token}\nSHA-256: {pin}", flush=True)
                server.serve_forever()
            finally:
                if started and not ctx.cfg.get("keep_gateway_running", False):
                    gateway.stop()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
