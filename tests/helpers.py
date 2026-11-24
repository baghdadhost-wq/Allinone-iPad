"""Shared test helpers: a sandbox with temp data/runtime folders, a fake gateway and a fake Claude Code."""

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FAKES = ROOT / "tests" / "fakes"
sys.path.insert(0, str(ROOT))


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def port_open(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.3):
            return True
    except OSError:
        return False


class Sandbox:
    def __init__(self, extra_config=None):
        self.tmp = Path(tempfile.mkdtemp(prefix="aio-test-"))
        self.port = free_port()
        self.project = self.tmp / "project"
        self.project.mkdir()
        self.record = self.tmp / "claude-record.json"
        self.gw_log = self.tmp / "gateway.jsonl"
        self.data = self.tmp / "data"
        local = {
            "language": "en",
            "default_gateway": "fake",
            "gateways": {
                "fake": {
                    "type": "custom",
                    "title": "FakeGW",
                    "port": self.port,
                    "health_path": "/health",
                    "token": "fake-token",
                    "start": {"command": ["{{python}}", str(FAKES / "fake_gateway.py"), "--port", "{{port}}"]},
                    "claude": {"model": "fake/model-1", "env": {"EXTRA_FLAG": "yes"}},
                }
            },
            "claude": {"command": ["{{python}}", str(FAKES / "fake_claude.py")]},
        }
        if extra_config:
            local = _merge(local, extra_config)
        self.local_config = self.tmp / "local.jsonc"
        self.local_config.write_text("// test overrides\n" + json.dumps(local, indent=2), encoding="utf-8")
        self.env = dict(os.environ)
        for key in list(self.env):
            if key.startswith("ANTHROPIC_"):
                del self.env[key]
        self.env.update({
            "ALLINONE_LOCAL_CONFIG": str(self.local_config),
            "ALLINONE_DATA_DIR": str(self.data),
            "ALLINONE_RUNTIME_DIR": str(self.tmp / "runtime"),
            "ALLINONE_NONINTERACTIVE": "1",
            "FAKE_CLAUDE_RECORD": str(self.record),
            "FAKE_GATEWAY_LOG": str(self.gw_log),
            "FAKE_TOKEN": "fake-token",
            "NO_COLOR": "1",
            "PYTHONIOENCODING": "utf-8",
        })

    def run(self, *args, env=None, timeout=180):
        full_env = dict(self.env)
        if env:
            full_env.update(env)
        return subprocess.run([sys.executable, str(ROOT / "allinone.py"), *args], cwd=str(self.project),
                              env=full_env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout,
                              stdin=subprocess.DEVNULL)

    def read_record(self):
        return json.loads(self.record.read_text(encoding="utf-8"))

    def gateway_requests(self):
        if not self.gw_log.exists():
            return []
        return [json.loads(line) for line in self.gw_log.read_text(encoding="utf-8").splitlines() if line.strip()]

    def cleanup(self):
        pid_file = self.data / "run" / "fake.json"
        if pid_file.exists():
            try:
                from controller import procs

                procs.kill_tree(json.loads(pid_file.read_text())["pid"])
            except Exception:
                pass
        for _ in range(20):
            if not port_open(self.port):
                break
            time.sleep(0.1)
        shutil.rmtree(self.tmp, ignore_errors=True)


def _merge(base, override):
    if isinstance(base, dict) and isinstance(override, dict):
        out = dict(base)
        for k, v in override.items():
            out[k] = _merge(base[k], v) if k in base else v
        return out
    return override


def out(proc) -> str:
    return proc.stdout.decode("utf-8", "replace") + proc.stderr.decode("utf-8", "replace")
