"""Small units: JSONC parsing, the SQLite store, process control, Node.js download and version checks."""

import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import unittest
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from helpers import ROOT, free_port, port_open

from controller import jsonc, procs
from controller.config import Config, State
from controller.nodejs import NodeError, NodeRuntime, parse_version, supported
from controller.store import Store


class JsoncTests(unittest.TestCase):
    def test_comments_and_trailing_commas(self):
        text = '''﻿// head
        {
          "url": "http://x//not-a-comment", /* block
          comment */ "list": [1, 2, ],
          "s": "a,}",   // tail
        }'''
        self.assertEqual(jsonc.loads(text), {"url": "http://x//not-a-comment", "list": [1, 2], "s": "a,}"})

    def test_shipped_files_parse(self):
        for rel in ("config/allinone.jsonc", "config/mcp.jsonc", "claude/settings.json",
                    "claude/plugins/allinone/.claude-plugin/plugin.json"):
            self.assertIsInstance(jsonc.load(ROOT / rel), dict, rel)


class StoreTests(unittest.TestCase):
    def test_tasks_and_memory(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            s = Store(tmp / "x.db")
            t = s.add_task("do it", "omniroute", "auto", "/p")
            self.assertEqual(s.next_pending()["id"], t)
            s.mark_running(t)
            self.assertIsNone(s.next_pending())
            self.assertEqual(s.reset_stuck(), 1)
            s.finish_task(t, {"result": "ok", "is_error": False, "session_id": "abc", "exit_code": 0})
            self.assertEqual(s.get_task(t)["status"], "done")
            s.remember("قاعدة البيانات PostgreSQL", tags="db")
            s.remember("frontend uses React", tags="web")
            self.assertEqual(len(s.search_memory("postgresql")), 1)
            self.assertEqual(len(s.search_memory("قاعدة")), 1)
            self.assertEqual(s.search_memory("web")[0]["text"], "frontend uses React")
            self.assertEqual(len(s.recent_memory(5)), 2)
            s.conn.close()
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class ProcTests(unittest.TestCase):
    def test_background_process_survives_and_is_killed_with_children(self):
        tmp = Path(tempfile.mkdtemp())
        port = free_port()
        script = ("import subprocess,sys,http.server,socketserver;"
                  "subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)']);"
                  f"http.server.ThreadingHTTPServer(('127.0.0.1',{port}),http.server.SimpleHTTPRequestHandler).serve_forever()")
        try:
            p = procs.spawn_background([sys.executable, "-c", script], tmp, dict(os.environ), tmp / "log.txt")
            for _ in range(50):
                if port_open(port):
                    break
                time.sleep(0.1)
            self.assertTrue(procs.pid_alive(p.pid))
            started = procs.process_start_time(p.pid)
            self.assertIsNotNone(started)
            self.assertLess(abs(started - time.time()), 60)
            self.assertTrue(procs.same_process(p.pid, started))
            # a PID file from long ago (e.g. before a reboot) must not match this process
            self.assertFalse(procs.same_process(p.pid, started - 3600))
            procs.kill_tree(p.pid, timeout=5)
            self.assertFalse(procs.pid_alive(p.pid))
            self.assertFalse(port_open(port))
            p.wait(timeout=5)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class NodeVersionTests(unittest.TestCase):
    def test_supported_range(self):
        self.assertTrue(supported((24, 11, 1)))
        self.assertTrue(supported((22, 22, 2)))
        self.assertFalse(supported((22, 22, 1)))
        self.assertFalse(supported((23, 5, 0)))
        self.assertFalse(supported((26, 0, 0)))  # newest LTS, too new for FreeLLMAPI
        self.assertFalse(supported((20, 18, 0)))
        self.assertEqual(parse_version("v24.11.1\n"), (24, 11, 1))


@unittest.skipIf(os.name == "nt", "builds a POSIX tarball")
class PortableNodeDownload(unittest.TestCase):
    """Serves a fake nodejs.org/dist and checks resolve + checksum + extraction."""

    def setUp(self):
        import platform

        self.tmp = Path(tempfile.mkdtemp(prefix="aio-node-"))
        self.dist = self.tmp / "dist"
        machine = {"x86_64": "x64", "amd64": "x64", "aarch64": "arm64", "arm64": "arm64"}[platform.machine().lower()]
        osname = "darwin" if sys.platform == "darwin" else "linux"
        ext = "tar.gz" if osname == "darwin" else "tar.xz"
        self.version = "24.99.1"
        folder = f"node-v{self.version}-{osname}-{machine}"
        buf = io.BytesIO()
        mode = "w:gz" if ext == "tar.gz" else "w:xz"
        with tarfile.open(fileobj=buf, mode=mode) as tf:
            script = f"#!/bin/sh\necho v{self.version}\n".encode()
            info = tarfile.TarInfo(f"{folder}/bin/node")
            info.size, info.mode = len(script), 0o755
            tf.addfile(info, io.BytesIO(script))
        data = buf.getvalue()
        (self.dist / f"v{self.version}").mkdir(parents=True)
        (self.dist / f"v{self.version}" / f"{folder}.{ext}").write_bytes(data)
        self.sha = hashlib.sha256(data).hexdigest()
        (self.dist / f"v{self.version}" / "SHASUMS256.txt").write_text(f"{self.sha}  {folder}.{ext}\n")
        (self.dist / "index.json").write_text(json.dumps([{"version": "v26.1.0"}, {"version": f"v{self.version}"},
                                                          {"version": "v24.1.0"}]))
        dist_dir = str(self.dist)

        class Quiet(SimpleHTTPRequestHandler):
            def __init__(self, *a, **kw):
                super().__init__(*a, directory=dist_dir, **kw)

            def log_message(self, *a):
                pass

        self.port = free_port()
        self.server = ThreadingHTTPServer(("127.0.0.1", self.port), Quiet)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _runtime(self):
        os.environ["ALLINONE_RUNTIME_DIR"] = str(self.tmp / "runtime")
        os.environ["ALLINONE_DATA_DIR"] = str(self.tmp / "data")
        os.environ["ALLINONE_LOCAL_CONFIG"] = str(self.tmp / "local.jsonc")
        (self.tmp / "local.jsonc").write_text(json.dumps({"node": {"dist_url": f"http://127.0.0.1:{self.port}"}}))
        try:
            cfg = Config()
        finally:
            for k in ("ALLINONE_RUNTIME_DIR", "ALLINONE_DATA_DIR", "ALLINONE_LOCAL_CONFIG"):
                os.environ.pop(k)
        return NodeRuntime(cfg, State(self.tmp / "state.json"))

    def test_download_verify_extract(self):
        rt = self._runtime()
        self.assertEqual(rt.resolve_version(), self.version)  # newest 24.x, not 26
        rt.ensure()
        self.assertEqual(rt.version(), (24, 99, 1))
        self.assertTrue(rt.ready())
        self.assertEqual(rt.installed_portable_version(), self.version)

    def test_checksum_mismatch_is_rejected(self):
        sums = next(self.dist.glob("v*/SHASUMS256.txt"))
        sums.write_text(sums.read_text().replace(self.sha, "0" * 64))
        rt = self._runtime()
        with self.assertRaises(NodeError):
            rt.ensure()
        self.assertFalse(rt.portable_node().exists())


if __name__ == "__main__":
    unittest.main()
