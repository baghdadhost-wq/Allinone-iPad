"""Gateways: install, start/stop, health, credentials and the Claude Code environment.

Built-in types
--------------
omniroute   OmniRoute  (npm package by default, or from source)
freellmapi  FreeLLMAPI (from source — it has no prebuilt server package)
custom      anything else: a command to start (optional) + a base URL + a token.
            Use it for LiteLLM, claude-code-router, a gateway on another PC, etc.

Every gateway is reached by Claude Code through the Anthropic Messages API
(ANTHROPIC_BASE_URL + ANTHROPIC_AUTH_TOKEN). Both OmniRoute and FreeLLMAPI
implement /v1/messages natively, so no translation layer is needed.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import netutil, procs, sources, ui
from .config import atomic_write_json, deep_merge, read_json
from .i18n import tr
from .nodejs import remove_tree

# Sent when a gateway needs no key: Claude Code then skips its login screen,
# and a gateway that does not require keys ignores the value.
NO_AUTH_TOKEN = "allinone-no-auth"


class GatewayError(RuntimeError):
    pass


@dataclass
class ProcSpec:
    cmd: List[str]
    cwd: Path
    env: Dict[str, str]


# ----------------------------------------------------------------- utilities
_PLACEHOLDER = re.compile(r"\{\{\s*([a-zA-Z0-9_:.\-]+)\s*\}\}")


def render(value: Any, mapping: Dict[str, str], secrets=None) -> Any:
    """Replace {{name}} and {{secret:section.key}} placeholders inside strings, lists and dicts."""
    if isinstance(value, str):
        def _sub(m):
            key = m.group(1)
            if key.startswith("secret:") and secrets is not None:
                return secrets.lookup(key[len("secret:"):])
            if key.startswith("env:"):
                return os.environ.get(key[4:], "")
            return str(mapping.get(key, m.group(0)))
        return _PLACEHOLDER.sub(_sub, value)
    if isinstance(value, list):
        return [render(v, mapping, secrets) for v in value]
    if isinstance(value, dict):
        return {k: render(v, mapping, secrets) for k, v in value.items()}
    return value


def parse_env_file(path: Path) -> Dict[str, str]:
    out: Dict[str, str] = {}
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError:
        return out
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        elif " #" in value:
            value = value.split(" #", 1)[0].rstrip()
        if key:
            out[key] = value
    return out


def npm_bin(pkg_dir: Path, name: str) -> Optional[Path]:
    try:
        data = json.loads((pkg_dir / "package.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    b = data.get("bin")
    if isinstance(b, str):
        return pkg_dir / b
    if isinstance(b, dict) and b:
        return pkg_dir / (b.get(name) or next(iter(b.values())))
    return None


def package_version(pkg_dir: Path) -> Optional[str]:
    try:
        return json.loads((pkg_dir / "package.json").read_text(encoding="utf-8")).get("version")
    except (OSError, ValueError):
        return None


# --------------------------------------------------------------- base class
class Gateway:
    type_name = "custom"
    no_auth_token = NO_AUTH_TOKEN
    DEFAULTS: Dict[str, Any] = {
        "host": "127.0.0.1",
        "health_path": "/",
        "dashboard_path": "/",
        "start_timeout": 120,
        "stop_timeout": 15,
        "claude": {"model": "", "tiers_follow_model": True, "env": {}},
    }

    def __init__(self, name: str, cfg: Dict[str, Any], ctx):
        self.name = name
        self.ctx = ctx
        self.cfg = deep_merge(self.DEFAULTS, cfg)
        self.title = str(self.cfg.get("title") or name)
        self.host = str(self.cfg.get("host") or "127.0.0.1")
        self.port = int(self.cfg.get("port") or 0)
        install_dir = self.cfg.get("install_dir")
        self.install_dir = ctx.cfg.abs_path(install_dir) if install_dir else ctx.cfg.runtime_dir / name
        self.data_dir = ctx.data_dir / name
        self.log_path = ctx.logs_dir / f"{name}.log"
        self.pid_path = ctx.run_dir / f"{name}.json"

    # ------------------------------------------------------------ addressing
    def mapping(self) -> Dict[str, str]:
        return {
            "name": self.name,
            "host": self.host,
            "port": str(self.port),
            "data": str(self.data_dir),
            "install": str(self.install_dir),
            "root": str(self.ctx.cfg.root),
            "node": self.ctx.node.node_path() or "node",
            "python": sys.executable,
        }

    def render(self, value: Any) -> Any:
        return render(value, self.mapping(), self.ctx.secrets)

    @property
    def base_url(self) -> str:
        explicit = self.cfg.get("base_url")
        if explicit:
            url = str(self.render(str(explicit))).rstrip("/")
        else:
            host = self.host if self.host not in ("", "0.0.0.0", "::") else "127.0.0.1"
            if ":" in host and not host.startswith("["):
                host = f"[{host}]"
            url = f"http://{host}:{self.port}"
        # Claude Code appends /v1/messages itself: the base URL must not end in /v1.
        return url[:-3] if url.endswith("/v1") else url

    def url(self, path: str) -> str:
        return self.base_url + (path if path.startswith("/") else "/" + path)

    def dashboard_url(self) -> str:
        return self.url(str(self.cfg.get("dashboard_path") or "/"))

    def dashboard_notes(self) -> List[str]:
        return []

    def is_local(self) -> bool:
        from urllib.parse import urlsplit

        return (urlsplit(self.base_url).hostname or "") in netutil.LOCAL_HOSTS

    # ---------------------------------------------------------- installation
    def install_cfg(self) -> Dict[str, Any]:
        return self.cfg.get("install") or {}

    def install_mode(self) -> str:
        return str(self.install_cfg().get("mode") or "none")

    def is_installed(self) -> bool:
        return True

    def installed_version(self) -> Optional[str]:
        info = self.ctx.state.install_info(self.name) or {}
        return info.get("version") or info.get("ref")

    def install(self, force: bool = False, latest: bool = False, rebuild: bool = False, refresh: bool = False) -> None:
        ui.say(tr("{t}: nothing to install (custom gateway).", "{t}: لا يوجد ما يُثبَّت (بوابة مخصصة).", t=self.title))

    # npm package into runtime/<name>
    def _install_npm(self, package: str, version: str, latest: bool) -> str:
        prefix = self.install_dir
        prefix.mkdir(parents=True, exist_ok=True)
        manifest = prefix / "package.json"
        if not manifest.exists():
            manifest.write_text(json.dumps({
                "name": f"allinone-{self.name}-runtime",
                "private": True,
                "description": "Managed by Allinone. Do not edit by hand.",
            }, indent=2) + "\n", encoding="utf-8")
        wanted = "latest" if latest else (version or "latest")
        try:
            self.ctx.node.npm(["install", "--save-exact", "--no-audit", "--no-fund", f"{package}@{wanted}"], cwd=prefix)
        except procs.CommandError:
            if wanted == "latest":
                raise
            ui.warn(tr("{p}@{v} could not be installed; trying the latest version.",
                       "تعذّر تثبيت {p}@{v}؛ سيتم تجربة أحدث إصدار.", p=package, v=wanted))
            self.ctx.node.npm(["install", "--save-exact", "--no-audit", "--no-fund", f"{package}@latest"], cwd=prefix)
        pkg_dir = prefix / "node_modules" / Path(*package.split("/"))
        return package_version(pkg_dir) or wanted

    # git checkout + saved patches + npm build into runtime/<name>
    def _install_source(self, force: bool, rebuild: bool, refresh: bool = False) -> str:
        inst = self.install_cfg()
        repo, ref = str(inst.get("repo") or ""), str(inst.get("ref") or "main")
        if not repo:
            raise GatewayError(f"{self.name}: install.repo is empty")
        dest = self.install_dir
        info = self.ctx.state.install_info(self.name) or {}
        same = info.get("mode") == "source" and info.get("ref") == ref and info.get("repo") == repo
        if dest.exists() and sources.is_checkout(dest) and same and not (force or refresh):
            if not rebuild and self.is_installed():
                ui.ok(tr("{t} {r} is already installed", "{t} {r} مثبت مسبقاً", t=self.title, r=ref))
                return ref
            self._build(dest)
            return ref
        if dest.exists():
            if sources.has_unsaved_changes(self.ctx.cfg.root, self.name, dest) and not force:
                raise GatewayError(tr(
                    "You have unsaved edits in {d}. Save them first with:  allinone customize save {n}\n"
                    "(or add --force to discard them)",
                    "لديك تعديلات غير محفوظة في {d}. احفظها أولاً بالأمر:  allinone customize save {n}\n"
                    "(أو أضف --force لتجاهلها)", d=dest, n=self.name))
            self.stop()
            remove_tree(dest)
        commit = sources.checkout(repo, ref, dest)
        sources.apply_patches(self.ctx.cfg.root, self.name, dest)
        self._build(dest)
        self.ctx.state.update_install(self.name, {"mode": "source", "repo": repo, "ref": ref, "commit": commit,
                                                  "version": ref, "at": time.time()})
        return ref

    def _build(self, dest: Path) -> None:
        steps = self.install_cfg().get("build")
        if steps is None:  # an explicit [] means "nothing to build"
            steps = [["ci"], ["run", "build"]]
        for step in steps:
            step = [str(s) for s in step]
            try:
                self.ctx.node.npm(step, cwd=dest)
            except procs.CommandError:
                if step and step[0] == "ci":
                    ui.warn(tr("npm ci failed; retrying with npm install", "فشل npm ci؛ إعادة المحاولة بـ npm install"))
                    self.ctx.node.npm(["install", *step[1:]], cwd=dest)
                else:
                    raise

    # --------------------------------------------------------------- process
    def start_spec(self) -> Optional[ProcSpec]:
        start = self.cfg.get("start") or {}
        if not start.get("command"):
            return None
        cmd = [str(self.render(str(c))) for c in start["command"]]
        cwd = self.ctx.cfg.abs_path(self.render(str(start.get("cwd") or self.data_dir)))
        env = self.process_env()
        env.update({str(k): str(self.render(str(v))) for k, v in (start.get("env") or {}).items()})
        return ProcSpec(cmd, cwd, env)

    def required_env(self) -> Dict[str, str]:
        return {}

    def process_env(self) -> Dict[str, str]:
        env = {k: v for k, v in os.environ.items() if not k.startswith("ANTHROPIC_")}
        env_file = self.ctx.cfg.root / "config" / "gateways" / f"{self.name}.env"
        env.update({k: str(self.render(v)) for k, v in parse_env_file(env_file).items()})
        env.update(self.required_env())
        return self.ctx.node.with_node_on_path(env)

    def health_url(self) -> str:
        return self.url(str(self.cfg.get("health_path") or "/"))

    def is_up(self) -> bool:
        status = netutil.answers(self.health_url(), timeout=2.0)
        return status is not None and status < 500

    def managed_pid(self) -> Optional[int]:
        info = read_json(self.pid_path, None)
        if not info:
            return None
        pid = int(info.get("pid") or 0)
        if procs.same_process(pid, info.get("started")):
            return pid
        self._clear_pid()
        return None

    def _clear_pid(self) -> None:
        try:
            self.pid_path.unlink()
        except OSError:
            pass

    def can_start(self) -> bool:
        return self.start_spec() is not None

    def start(self) -> str:
        """Returns 'already' if it was answering, 'started' if this call started it."""
        if self.is_up():
            return "already"
        if not self.is_installed():
            raise GatewayError(tr("{t} is not installed. Run: allinone install {n}",
                                  "{t} غير مثبت. نفّذ: allinone install {n}", t=self.title, n=self.name))
        spec = self.start_spec()
        if spec is None:
            raise GatewayError(tr("{t} does not answer at {u} and has no start command.",
                                  "{t} لا يستجيب على {u} وليس له أمر تشغيل.", t=self.title, u=self.base_url))
        if self.port and procs.port_open("127.0.0.1", self.port):
            raise GatewayError(tr("Port {p} is used by another program. Change \"port\" for {t} in config/allinone.jsonc.",
                                  "المنفذ {p} مستخدم من برنامج آخر. غيّر \"port\" الخاص بـ {t} في config/allinone.jsonc.",
                                  p=self.port, t=self.title))
        self.data_dir.mkdir(parents=True, exist_ok=True)
        spec.cwd.mkdir(parents=True, exist_ok=True)
        self.before_start()
        proc = procs.spawn_background(spec.cmd, spec.cwd, spec.env, self.log_path)
        started_at = procs.process_start_time(proc.pid) or time.time()
        atomic_write_json(self.pid_path, {"pid": proc.pid, "port": self.port, "started": started_at,
                                          "cmd": spec.cmd})
        waiter = ui.Waiter(tr("Starting {t}", "جارٍ تشغيل {t}", t=self.title))
        up = netutil.wait_until_up(self.health_url(), float(self.cfg.get("start_timeout") or 120),
                                   alive=lambda: proc.poll() is None, tick=waiter.tick)
        if not up:
            waiter.done()
            if proc.poll() is None:
                procs.kill_tree(proc.pid)
            self._clear_pid()
            log = "\n".join("    " + line for line in ui.tail_lines(self.log_path, 25))
            raise GatewayError(tr("{t} did not start. Last lines of {l}:\n{log}",
                                  "لم يبدأ {t}. آخر الأسطر من {l}:\n{log}", t=self.title, l=self.log_path, log=log))
        waiter.done(tr("{t} is running at {u}", "{t} يعمل على {u}", t=self.title, u=self.base_url))
        self.after_start()
        return "started"

    def stop(self) -> bool:
        pid = self.managed_pid()
        if not pid:
            return False
        procs.kill_tree(pid, timeout=float(self.cfg.get("stop_timeout") or 15))
        self._clear_pid()
        return True

    def before_start(self) -> None:
        pass

    def after_start(self) -> None:
        pass

    # ----------------------------------------------------------- credentials
    def token(self) -> str:
        explicit = str(self.render(str(self.cfg.get("token") or ""))).strip()
        if explicit:
            return explicit
        stored = self.ctx.secrets.get(self.name, "api_key")
        if stored:
            return stored
        return self.discover_token() or ""

    def discover_token(self) -> Optional[str]:
        return None

    def needs_token(self) -> bool:
        return False

    def auth_headers(self) -> Dict[str, str]:
        tok = self.token()
        return {"Authorization": f"Bearer {tok}", "x-api-key": tok} if tok else {}

    def models(self) -> Optional[List[str]]:
        try:
            status, data = netutil.get_json(self.url("/v1/models"), headers=self.auth_headers(), timeout=10)
        except Exception:
            return None
        if status != 200 or not isinstance(data, dict):
            return None
        items = data.get("data") or data.get("models") or []
        return [str(m["id"]) for m in items if isinstance(m, dict) and m.get("id")]

    # --------------------------------------------------- Claude Code wiring
    def claude_cfg(self) -> Dict[str, Any]:
        return self.cfg.get("claude") or {}

    def default_model(self) -> str:
        return str(self.claude_cfg().get("model") or "").strip()

    def claude_env(self, model: Optional[str] = None) -> Dict[str, str]:
        c = self.claude_cfg()
        env = {
            "ANTHROPIC_BASE_URL": self.base_url,
            "ANTHROPIC_AUTH_TOKEN": self.token() or self.no_auth_token,
            "CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY": "1",
        }
        main = (model if model is not None else self.default_model()).strip()
        if main:
            env["ANTHROPIC_MODEL"] = main
        follow = bool(c.get("tiers_follow_model", True))
        for key, var in (("opus_model", "ANTHROPIC_DEFAULT_OPUS_MODEL"),
                         ("sonnet_model", "ANTHROPIC_DEFAULT_SONNET_MODEL"),
                         ("haiku_model", "ANTHROPIC_DEFAULT_HAIKU_MODEL")):
            value = str(c.get(key) or "").strip() or (main if follow else "")
            if value:
                env[var] = value
        sub = str(c.get("subagent_model") or "").strip()
        if sub:
            env["CLAUDE_CODE_SUBAGENT_MODEL"] = sub
        for key, value in (c.get("env") or {}).items():
            env[str(key)] = str(self.render(str(value)))
        return env

    # ----------------------------------------------------------------- info
    def status(self) -> Dict[str, Any]:
        up = self.is_up()
        return {
            "name": self.name,
            "title": self.title,
            "installed": self.is_installed(),
            "version": self.installed_version(),
            "up": up,
            "managed": bool(self.managed_pid()),
            "url": self.base_url,
        }


# ------------------------------------------------------------------ OmniRoute
class OmniRouteGateway(Gateway):
    type_name = "omniroute"
    no_auth_token = "omniroute-no-auth"  # same placeholder OmniRoute's own `omniroute launch` sends
    DEFAULTS = deep_merge(Gateway.DEFAULTS, {
        "title": "OmniRoute",
        "port": 20128,
        "health_path": "/api/monitoring/health",
        "dashboard_path": "/dashboard",
        "start_timeout": 240,
        # --no-tray: a saved desktop preference could otherwise start OmniRoute as a detached
        # tray app that outlives the process Allinone supervises.
        "serve_args": ["--no-open", "--no-tray"],
        "install": {
            "mode": "npm",
            "package": "omniroute",
            "version": "latest",
            "repo": "https://github.com/diegosouzapw/OmniRoute.git",
            "ref": "main",
            "build": [["ci"], ["run", "build"]],
        },
        "claude": {"model": "auto"},
    })

    def entry(self) -> Optional[Path]:
        if self.install_mode() == "source":
            return self.install_dir / "bin" / "omniroute.mjs"
        pkg = str(self.install_cfg().get("package") or "omniroute")
        return npm_bin(self.install_dir / "node_modules" / Path(*pkg.split("/")), "omniroute")

    def is_installed(self) -> bool:
        entry = self.entry()
        return bool(entry and entry.exists())

    def install(self, force: bool = False, latest: bool = False, rebuild: bool = False, refresh: bool = False) -> None:
        inst = self.install_cfg()
        if self.install_mode() == "source":
            version = self._install_source(force, rebuild, refresh)
        else:
            if self.is_installed() and not (force or latest or refresh):
                ui.ok(tr("{t} {v} is already installed", "{t} {v} مثبت مسبقاً", t=self.title,
                         v=self.installed_version() or ""))
                return
            self.stop()
            version = self._install_npm(str(inst.get("package") or "omniroute"), str(inst.get("version") or "latest"),
                                        latest)
            self.ctx.state.update_install(self.name, {"mode": "npm", "version": version, "at": time.time()})
        self.ctx.secrets.ensure(self.name, "dashboard_password", "password")
        ui.ok(tr("{t} {v} installed", "تم تثبيت {t} {v}", t=self.title, v=version))

    def start_spec(self) -> Optional[ProcSpec]:
        custom = super().start_spec()
        if custom:
            return custom
        entry = self.entry()
        node = self.ctx.node.node_path()
        if not entry or not node:
            return None
        args = [str(a) for a in self.render(self.cfg.get("serve_args") or [])]
        cmd = [node, str(entry), "serve", "--port", str(self.port), *args]
        cwd = self.install_dir if self.install_mode() == "source" else self.data_dir
        return ProcSpec(cmd, cwd, self.process_env())

    def required_env(self) -> Dict[str, str]:
        return {
            "DATA_DIR": str(self.data_dir),
            "PORT": str(self.port),
            "OMNIROUTE_SERVER_HOST": self.host,
            # The npm package ships INITIAL_PASSWORD=CHANGEME; replace it with a private one.
            "INITIAL_PASSWORD": self.ctx.secrets.ensure(self.name, "dashboard_password", "password"),
        }

    def dashboard_notes(self) -> List[str]:
        pwd = self.ctx.secrets.get(self.name, "dashboard_password")
        notes = []
        if pwd:
            notes.append(tr("First login password: {p}   (change it later in Settings → Security)",
                            "كلمة مرور أول دخول: {p}   (غيّرها لاحقاً من Settings → Security)", p=pwd))
        notes.append(tr("Add providers in Dashboard → Providers. Claude Code uses the model \"{m}\".",
                        "أضف المزودين من Dashboard → Providers. يستخدم Claude Code النموذج \"{m}\".",
                        m=self.default_model() or "auto"))
        return notes


# ----------------------------------------------------------------- FreeLLMAPI
class FreeLLMAPIGateway(Gateway):
    type_name = "freellmapi"
    DEFAULTS = deep_merge(Gateway.DEFAULTS, {
        "title": "FreeLLMAPI",
        "port": 3001,
        "health_path": "/v1/models",
        "dashboard_path": "/",
        "start_timeout": 120,
        "install": {
            "mode": "source",
            "repo": "https://github.com/tashfeenahmed/freellmapi.git",
            "ref": "main",
            "build": [["ci"], ["run", "build"]],
        },
        "claude": {"model": "auto", "env": {"CLAUDE_CODE_AUTO_MODE_SERVER": "0"}},
    })

    def db_path(self) -> Path:
        return self.data_dir / "freellmapi.db"

    def entry(self) -> Path:
        return self.install_dir / "server" / "dist" / "index.js"

    def is_installed(self) -> bool:
        return self.entry().exists()

    def install(self, force: bool = False, latest: bool = False, rebuild: bool = False, refresh: bool = False) -> None:
        if self.install_mode() != "source":
            raise GatewayError("FreeLLMAPI can only be installed from source (install.mode = \"source\").")
        if latest:
            ui.warn(tr("--latest: set install.ref to \"main\" (or a newer tag) in config to follow upstream.",
                       "--latest: اضبط install.ref على \"main\" (أو وسم أحدث) في الإعدادات لمتابعة آخر نسخة."))
        version = self._install_source(force, rebuild, refresh)
        self.ctx.secrets.ensure(self.name, "encryption_key", "hex32")
        ui.ok(tr("{t} {v} installed", "تم تثبيت {t} {v}", t=self.title, v=version))

    def start_spec(self) -> Optional[ProcSpec]:
        custom = super().start_spec()
        if custom:
            return custom
        node = self.ctx.node.node_path()
        if not node:
            return None
        return ProcSpec([node, str(self.entry())], self.install_dir, self.process_env())

    def required_env(self) -> Dict[str, str]:
        return {
            "NODE_ENV": "production",
            "PORT": str(self.port),
            "HOST": self.host,
            # Must never change once provider keys are stored: it encrypts them at rest.
            "ENCRYPTION_KEY": self.ctx.secrets.ensure(self.name, "encryption_key", "hex32"),
            "FREEAPI_DB_PATH": str(self.db_path()),
            "FREEAPI_ENV_PATH": str(self.ctx.cfg.root / "config" / "gateways" / f"{self.name}.env"),
        }

    def needs_token(self) -> bool:
        return True

    def discover_token(self) -> Optional[str]:
        """FreeLLMAPI keeps its unified key in its own SQLite settings table."""
        db = self.db_path()
        if not db.exists():
            return None
        for uri in (f"{db.resolve().as_uri()}?mode=ro", None):
            try:
                conn = sqlite3.connect(uri, uri=True, timeout=5) if uri else sqlite3.connect(str(db), timeout=5)
                try:
                    row = conn.execute("SELECT value FROM settings WHERE key = 'unified_api_key'").fetchone()
                finally:
                    conn.close()
                if row and row[0]:
                    return str(row[0])
                return None
            except sqlite3.Error:
                continue
        return None

    def dashboard_notes(self) -> List[str]:
        return [
            tr("First visit: create the dashboard account (it is local to this computer).",
               "أول زيارة: أنشئ حساب لوحة التحكم (محلي على هذا الجهاز)."),
            tr("Add provider keys on the Keys page; Allinone reads the unified key automatically.",
               "أضف مفاتيح المزودين من صفحة Keys؛ يقرأ Allinone المفتاح الموحد تلقائياً."),
        ]


TYPES = {"omniroute": OmniRouteGateway, "freellmapi": FreeLLMAPIGateway, "custom": Gateway}


def make_gateway(name: str, cfg: Dict[str, Any], ctx) -> Gateway:
    kind = str(cfg.get("type") or (name if name in TYPES else "custom"))
    cls = TYPES.get(kind)
    if cls is None:
        raise GatewayError(f"Unknown gateway type '{kind}' for '{name}' (use omniroute, freellmapi or custom)")
    return cls(name, cfg, ctx)
