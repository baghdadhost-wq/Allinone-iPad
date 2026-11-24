"""Node.js runtime used by the gateways, npm and the Claude Code installer.

Both gateways are Node applications with narrow engine ranges:

    OmniRoute  : node >=22.22.2 <23  or  >=24 <27
    FreeLLMAPI : node >=20.18   <25

The only versions both accept are 22.22.2+ (22.x) and 24.x, while the newest LTS
can fall outside that range. To keep the three components compatible no matter
what the machine already has, Allinone downloads an official portable Node.js
24 into runtime/node (checksum-verified) and uses it only for its own processes.
Set "node.mode": "system" in config to use the Node.js on your PATH instead.
"""

from __future__ import annotations

import json
import os
import platform
import re
import shutil
import subprocess
import tarfile
import tempfile
import zipfile
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from . import netutil, procs, ui
from .i18n import tr

IS_WINDOWS = os.name == "nt"


def parse_version(text: str) -> Optional[Tuple[int, int, int]]:
    m = re.search(r"v?(\d+)\.(\d+)\.(\d+)", text or "")
    return (int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None


def supported(ver: Optional[Tuple[int, int, int]]) -> bool:
    if not ver:
        return False
    return (22, 22, 2) <= ver < (23, 0, 0) or (24, 0, 0) <= ver < (25, 0, 0)


class NodeError(RuntimeError):
    pass


class NodeRuntime:
    def __init__(self, cfg, state):
        node_cfg = cfg.get("node") or {}
        self.mode = str(node_cfg.get("mode") or "portable")
        self.version_spec = str(node_cfg.get("version") or "24").lstrip("v")
        self.dist_url = str(node_cfg.get("dist_url") or "https://nodejs.org/dist").rstrip("/")
        self.dir = cfg.runtime_dir / "node"
        self.state = state

    # ------------------------------------------------------------------ paths
    def portable_node(self) -> Path:
        return self.dir / "node.exe" if IS_WINDOWS else self.dir / "bin" / "node"

    def node_path(self) -> Optional[str]:
        if self.mode == "portable" and self.portable_node().exists():
            return str(self.portable_node())
        if self.mode == "system":
            return procs.which("node")
        return None

    def npm_cli(self) -> Optional[List[str]]:
        node = self.node_path()
        if not node:
            return None
        candidates = []
        for base in {Path(node).parent, Path(os.path.realpath(node)).parent}:
            candidates.append(base / "node_modules" / "npm" / "bin" / "npm-cli.js")
            candidates.append(base.parent / "lib" / "node_modules" / "npm" / "bin" / "npm-cli.js")
        for cand in candidates:
            if cand.exists():
                return [node, str(cand)]
        npm = procs.which("npm")
        return [npm] if npm else None

    def bin_dir(self) -> Optional[str]:
        node = self.node_path()
        return str(Path(node).parent) if node else None

    def with_node_on_path(self, env: Dict[str, str]) -> Dict[str, str]:
        env = dict(env)
        bindir = self.bin_dir()
        if bindir:
            key = next((k for k in env if k.upper() == "PATH"), "PATH")
            env[key] = bindir + os.pathsep + env.get(key, "")
        return env

    # --------------------------------------------------------------- versions
    def version(self) -> Optional[Tuple[int, int, int]]:
        node = self.node_path()
        if not node:
            return None
        try:
            out = subprocess.run([node, "--version"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=20)
        except (OSError, subprocess.TimeoutExpired):
            return None
        return parse_version(out.stdout.decode("utf-8", "replace"))

    def ready(self) -> bool:
        return supported(self.version())

    # ------------------------------------------------------------------ npm
    def npm(self, args: Sequence[str], cwd: Path, extra_env: Optional[Dict[str, str]] = None) -> None:
        npm = self.npm_cli()
        if not npm:
            raise NodeError(tr("npm was not found. Run: allinone install node",
                               "لم يتم العثور على npm. نفّذ: allinone install node"))
        env = self.with_node_on_path(dict(os.environ))
        env.update({
            "npm_config_update_notifier": "false",
            "npm_config_fund": "false",
            "npm_config_audit": "false",
            # Native modules (better-sqlite3, Claude Code's binary) need their install scripts.
            "npm_config_ignore_scripts": "false",
        })
        if extra_env:
            env.update(extra_env)
        ui.step("npm " + " ".join(args) + ui.dim(f"   ({cwd})"))
        procs.run([*npm, *args], cwd=cwd, env=env)

    # ------------------------------------------------------- portable install
    def installed_portable_version(self) -> Optional[str]:
        try:
            return (self.dir / ".allinone-node-version").read_text(encoding="utf-8").strip() or None
        except OSError:
            return None

    def ensure(self, force: bool = False, refresh: bool = False) -> None:
        if self.mode == "system":
            ver = self.version()
            if not ver:
                raise NodeError(tr("Node.js is not installed (node.mode = system).",
                                   "Node.js غير مثبت (node.mode = system)."))
            if not supported(ver):
                ui.warn(tr("Node.js {v} is outside the range both gateways support (22.22.2+ or 24.x).",
                           "إصدار Node.js {v} خارج النطاق الذي تدعمه البوابتان (22.22.2+ أو 24.x).",
                           v=".".join(map(str, ver))))
            return
        if not force and self.ready():
            if refresh:
                try:
                    newest = self.resolve_version()
                except Exception:
                    newest = None
                if newest and newest != self.installed_portable_version():
                    self._download_portable(newest)
                    return
            ui.ok(tr("Node.js {v} (portable) is ready", "Node.js {v} (نسخة محمولة) جاهز",
                     v=".".join(map(str, self.version() or ()))))
            return
        self._download_portable()

    def _platform(self) -> Tuple[str, str, str]:
        system = platform.system()
        machine = platform.machine().lower()
        arch = {"amd64": "x64", "x86_64": "x64", "arm64": "arm64", "aarch64": "arm64"}.get(machine)
        if not arch:
            raise NodeError(f"Unsupported CPU architecture for portable Node.js: {machine}")
        if system == "Windows":
            return "win", arch, "zip"
        if system == "Darwin":
            return "darwin", arch, "tar.gz"
        if system == "Linux":
            if any(Path("/lib").glob("ld-musl-*")):
                raise NodeError(tr("Official Node.js builds do not support musl (Alpine). Install nodejs with your "
                                   "package manager and set node.mode to \"system\".",
                                   "إصدارات Node.js الرسمية لا تدعم musl (Alpine). ثبّت nodejs من مدير الحزم "
                                   "واضبط node.mode على \"system\"."))
            return "linux", arch, "tar.xz"
        raise NodeError(f"Unsupported operating system: {system}")

    def resolve_version(self) -> str:
        spec = self.version_spec
        if re.fullmatch(r"\d+\.\d+\.\d+", spec):
            return spec
        index = json.loads(netutil.fetch_text(f"{self.dist_url}/index.json"))
        for entry in index:  # newest first
            v = str(entry.get("version", "")).lstrip("v")
            if v == spec or v.startswith(spec + "."):
                return v
        raise NodeError(f"No Node.js release matches '{spec}'")

    def _download_portable(self, version: Optional[str] = None) -> None:
        osname, arch, ext = self._platform()
        version = version or self.resolve_version()
        folder = f"node-v{version}-{osname}-{arch}"
        filename = f"{folder}.{ext}"
        base = f"{self.dist_url}/v{version}"
        ui.step(tr("Downloading Node.js {v} ({f})", "تنزيل Node.js {v} ({f})", v=version, f=filename))
        sums = netutil.fetch_text(f"{base}/SHASUMS256.txt")
        expected = None
        for line in sums.splitlines():
            parts = line.split()
            if len(parts) == 2 and parts[1] == filename:
                expected = parts[0].lower()
        if not expected:
            raise NodeError(f"{filename} is not listed in SHASUMS256.txt")

        self.dir.parent.mkdir(parents=True, exist_ok=True)
        tmp = Path(tempfile.mkdtemp(prefix="node-", dir=str(self.dir.parent)))
        try:
            archive = tmp / filename
            waiter = ui.Waiter(tr("Downloading", "جارٍ التنزيل"))
            digest = netutil.download(f"{base}/{filename}", archive,
                                      progress=lambda d, t: waiter.tick(f"{d // (1024 * 1024)} MB"))
            waiter.done()
            if digest.lower() != expected:
                raise NodeError(tr("Checksum mismatch for {f} — download rejected.",
                                   "بصمة الملف {f} غير مطابقة — تم رفض التنزيل.", f=filename))
            extract_to = tmp / "x"
            if ext == "zip":
                with zipfile.ZipFile(archive) as zf:
                    zf.extractall(extract_to)
            else:
                with tarfile.open(archive) as tf:
                    try:
                        tf.extractall(extract_to, filter="data")
                    except TypeError:  # Python < 3.12 without the filter backport
                        tf.extractall(extract_to)
            src = extract_to / folder
            if not src.exists():
                raise NodeError(f"Unexpected archive layout in {filename}")
            if self.dir.exists():
                remove_tree(self.dir)
            os.replace(str(src), str(self.dir))
            (self.dir / ".allinone-node-version").write_text(version + "\n", encoding="utf-8")
        finally:
            remove_tree(tmp)
        self.state.update_install("node", {"mode": "portable", "version": version})
        ui.ok(tr("Node.js {v} installed in {d}", "تم تثبيت Node.js {v} في {d}", v=version, d=self.dir))


def remove_tree(path: Path) -> None:
    """rmtree that also removes read-only files (common inside node_modules on Windows)."""

    def _retry(func, p, _exc):
        try:
            os.chmod(p, 0o700)
            func(p)
        except OSError:
            pass

    if not path.exists():
        return
    import sys

    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=_retry)
    else:
        shutil.rmtree(path, onerror=_retry)
