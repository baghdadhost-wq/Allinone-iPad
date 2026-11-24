"""Claude Code: installation, per-session configuration and launching.

For every session the controller generates, under data/run/session-*/ :

* settings.json — claude/settings.json (hooks, permissions, env) + the chosen
  gateway's connection variables, passed with --settings so it outranks any
  ANTHROPIC_* left in other settings files;
* mcp.json      — the enabled servers from config/mcp.jsonc, passed with --mcp-config.

Plugins (skills, agents, commands) under claude/plugins/* are loaded with
--plugin-dir. The session folder is deleted when Claude Code exits.
"""

from __future__ import annotations

import json
import os
import secrets as _secrets
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import i18n, jsonc, procs, ui
from .config import atomic_write_json
from .gateways import Gateway, npm_bin, package_version, render
from .i18n import tr

IS_WINDOWS = os.name == "nt"
STRIP_PREFIXES = ("ANTHROPIC_",)
STRIP_VARS = ("CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_USE_FOUNDRY",
              "CLAUDE_CODE_USE_ANTHROPIC_AWS", "CLAUDE_CODE_OAUTH_TOKEN")


class ClaudeError(RuntimeError):
    pass


@dataclass
class Session:
    cmd: List[str]
    env: Dict[str, str]
    cwd: Path
    run_dir: Path
    info: Dict[str, Any] = field(default_factory=dict)

    def cleanup(self) -> None:
        shutil.rmtree(self.run_dir, ignore_errors=True)


def _is_js(path: Path) -> bool:
    if path.suffix.lower() in (".js", ".mjs", ".cjs"):
        return True
    try:
        with open(path, "rb") as fh:
            head = fh.read(128)
    except OSError:
        return False
    return head.startswith(b"#!") and b"node" in head.split(b"\n", 1)[0]


class ClaudeRuntime:
    def __init__(self, ctx):
        self.ctx = ctx
        self.cfg: Dict[str, Any] = ctx.cfg.get("claude") or {}
        inst = self.cfg.get("install") or {}
        self.mode = str(inst.get("mode") or "npm")  # npm | system
        self.package = str(inst.get("package") or "@anthropic-ai/claude-code")
        self.version_spec = str(inst.get("version") or "latest")
        self.prefix = ctx.cfg.runtime_dir / "claude-code"

    # ------------------------------------------------------------ locating
    def _mapping(self) -> Dict[str, str]:
        return {"root": str(self.ctx.cfg.root), "python": self.ctx.python, "data": str(self.ctx.data_dir),
                "node": self.ctx.node.node_path() or "node"}

    def command(self) -> Optional[List[str]]:
        custom = self.cfg.get("command")
        if custom:
            return [str(x) for x in render(list(custom), self._mapping(), self.ctx.secrets)]
        if self.mode == "npm":
            found = self._npm_command()
            if found:
                return found
        exe = procs.which("claude")
        return [exe] if exe else None

    def _npm_command(self) -> Optional[List[str]]:
        """Find the executable the npm package installed (a native binary, or a JS launcher)."""
        pkg_dir = self.prefix / "node_modules" / Path(*self.package.split("/"))
        target = npm_bin(pkg_dir, "claude")
        if target is not None:
            candidates = [target]
            if IS_WINDOWS:
                candidates = [target.with_suffix(".exe"), Path(str(target) + ".exe"), target]
            for cand in candidates:
                if not cand.is_file():
                    continue
                if _is_js(cand):
                    node = self.ctx.node.node_path() or procs.which("node")
                    if node:
                        return [node, str(cand)]
                elif not IS_WINDOWS or cand.suffix.lower() == ".exe":
                    # Windows cannot start a native program whose name lacks .exe; the npm shim below can.
                    return [str(cand)]
        bin_dir = self.prefix / "node_modules" / ".bin"
        for name in (("claude.exe", "claude.cmd") if IS_WINDOWS else ("claude",)):
            if (bin_dir / name).exists():
                return [str(bin_dir / name)]
        return None

    def is_installed(self) -> bool:
        return self.command() is not None

    def version(self) -> Optional[str]:
        cmd = self.command()
        if not cmd:
            return None
        try:
            out = subprocess.run([*cmd, "--version"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=60)
        except (OSError, subprocess.TimeoutExpired):
            return None
        text = out.stdout.decode("utf-8", "replace").strip().splitlines()
        return text[-1] if text else None

    # ------------------------------------------------------------ install
    def install(self, force: bool = False, latest: bool = False) -> None:
        if self.cfg.get("command"):
            ui.ok(tr("Claude Code: using the custom command from config", "Claude Code: يُستخدم الأمر المخصص من الإعدادات"))
            return
        if self.mode == "system":
            if not procs.which("claude"):
                raise ClaudeError(tr(
                    "claude.install.mode is \"system\" but `claude` is not on PATH. Install it from "
                    "https://code.claude.com/docs/en/setup or switch the mode to \"npm\".",
                    "claude.install.mode مضبوط على \"system\" لكن الأمر `claude` غير موجود. ثبّته من "
                    "https://code.claude.com/docs/en/setup أو غيّر الوضع إلى \"npm\"."))
            ui.ok(tr("Claude Code (system install): {v}", "Claude Code (مثبت على النظام): {v}", v=self.version() or "?"))
            return
        if self._npm_command() and not (force or latest):
            ui.ok(tr("Claude Code {v} is already installed", "Claude Code {v} مثبت مسبقاً", v=self.installed_version() or ""))
            return
        self.prefix.mkdir(parents=True, exist_ok=True)
        manifest = self.prefix / "package.json"
        if not manifest.exists():
            manifest.write_text(json.dumps({"name": "allinone-claude-code-runtime", "private": True,
                                            "description": "Managed by Allinone."}, indent=2) + "\n", encoding="utf-8")
        wanted = "latest" if latest else self.version_spec
        # The native binary arrives as an optional dependency + install script: make sure neither is disabled.
        self.ctx.node.npm(["install", "--save-exact", "--no-audit", "--no-fund", "--include=optional",
                           f"{self.package}@{wanted}"], cwd=self.prefix)
        version = self.installed_version() or wanted
        self.ctx.state.update_install("claude", {"mode": "npm", "version": version, "at": time.time()})
        if not self._npm_command():
            raise ClaudeError(tr("Claude Code was installed but its executable was not found. Your npm must allow "
                                 "optional dependencies (the native binary is one).",
                                 "تم تثبيت Claude Code لكن ملفه التنفيذي غير موجود. يجب أن يسمح npm "
                                 "بالاعتماديات الاختيارية (الملف التنفيذي الأصلي واحد منها)."))
        ui.ok(tr("Claude Code {v} installed", "تم تثبيت Claude Code {v}", v=version))

    def installed_version(self) -> Optional[str]:
        return package_version(self.prefix / "node_modules" / Path(*self.package.split("/")))

    # ------------------------------------------------------------ sessions
    def plugin_dirs(self) -> List[Path]:
        dirs: List[Path] = []
        base = self.ctx.cfg.abs_path(self.cfg.get("plugins_dir") or "claude/plugins")
        if base.is_dir():
            for d in sorted(base.iterdir()):
                if (d / ".claude-plugin" / "plugin.json").is_file():
                    dirs.append(d)
        for extra in self.cfg.get("extra_plugin_dirs") or []:
            p = self.ctx.cfg.abs_path(extra)
            if p.exists():
                dirs.append(p)
        return dirs

    def build_session(self, gw: Gateway, model: Optional[str], project: Path) -> Session:
        root = self.ctx.cfg.root
        sid = time.strftime("%Y%m%d-%H%M%S") + "-" + _secrets.token_hex(3)
        run_dir = self.ctx.run_dir / f"session-{sid}"
        run_dir.mkdir(parents=True, exist_ok=True)

        gw_env = gw.claude_env(model)
        mapping = {
            "root": str(root),
            "python": self.ctx.python,
            "data": str(self.ctx.data_dir),
            "db": str(self.ctx.data_dir / "allinone.db"),
            "project": str(project),
            "gateway": gw.name,
            "gateway_title": gw.title,
            "gateway_url": gw.base_url,
            "gateway_token": gw_env["ANTHROPIC_AUTH_TOKEN"],
            "model": gw_env.get("ANTHROPIC_MODEL", ""),
            "lang": i18n.language(),
            "session_dir": str(run_dir),
        }
        allinone_env = {
            "ALLINONE_ROOT": str(root),
            "ALLINONE_PYTHON": self.ctx.python,
            "ALLINONE_DB": mapping["db"],
            "ALLINONE_GATEWAY": gw.name,
            "ALLINONE_GATEWAY_TITLE": gw.title,
            "ALLINONE_GATEWAY_URL": gw.base_url,
            "ALLINONE_MODEL": mapping["model"],
            "ALLINONE_LANG": mapping["lang"],
        }

        # settings.json for this session
        settings_src = self.ctx.cfg.abs_path(self.cfg.get("settings_file") or "claude/settings.json")
        settings: Dict[str, Any] = jsonc.load(settings_src) if settings_src.exists() else {}
        settings = render(settings, mapping, self.ctx.secrets)
        env_block: Dict[str, str] = {str(k): str(v) for k, v in (settings.get("env") or {}).items()}
        env_block.update({str(k): str(render(str(v), mapping, self.ctx.secrets))
                          for k, v in (self.cfg.get("env") or {}).items()})
        env_block.update(gw_env)
        env_block.update(allinone_env)
        settings["env"] = env_block
        settings_path = run_dir / "settings.json"
        atomic_write_json(settings_path, settings, private=True)

        # mcp.json for this session
        mcp_src = self.ctx.cfg.abs_path(self.cfg.get("mcp_file") or "config/mcp.jsonc")
        servers: Dict[str, Any] = {}
        if mcp_src.exists():
            raw = jsonc.load(mcp_src)
            for name, spec in (raw.get("mcpServers") or raw).items():
                if not isinstance(spec, dict) or not spec.get("enabled", True):
                    continue
                only = spec.get("only_with_gateway")
                if only and only != gw.name:
                    continue
                clean = {k: v for k, v in spec.items() if k not in ("enabled", "only_with_gateway", "description")}
                servers[name] = render(clean, mapping, self.ctx.secrets)
        mcp_path = run_dir / "mcp.json"
        atomic_write_json(mcp_path, {"mcpServers": servers}, private=True)

        cmd = self.command()
        if not cmd:
            raise ClaudeError(tr("Claude Code is not installed. Run: allinone install claude",
                                 "Claude Code غير مثبت. نفّذ: allinone install claude"))
        args = ["--settings", str(settings_path), "--mcp-config", str(mcp_path)]
        for d in self.plugin_dirs():
            args += ["--plugin-dir", str(d)]
        args += [str(a) for a in render(list(self.cfg.get("extra_args") or []), mapping, self.ctx.secrets)]

        env = {k: v for k, v in os.environ.items()
               if not k.startswith(STRIP_PREFIXES) and k not in STRIP_VARS}
        env.update(env_block)
        if self.cfg.get("isolated_config", True):
            home = self.ctx.cfg.abs_path(self.cfg.get("config_dir") or (self.ctx.data_dir / "claude-home"))
            home.mkdir(parents=True, exist_ok=True)
            env["CLAUDE_CONFIG_DIR"] = str(home)
        return Session(cmd=[*cmd, *args], env=env, cwd=project, run_dir=run_dir,
                       info={"model": mapping["model"], "servers": list(servers), "plugins": len(self.plugin_dirs())})

    def run_interactive(self, gw: Gateway, model: Optional[str], project: Path, extra_args: List[str]) -> int:
        session = self.build_session(gw, model, project)
        try:
            return procs.run_foreground([*session.cmd, *extra_args], project, session.env)
        finally:
            session.cleanup()

    def run_headless(self, gw: Gateway, model: Optional[str], project: Path, prompt: str,
                     resume: Optional[str] = None, permission_mode: Optional[str] = None,
                     allowed_tools: Optional[List[str]] = None, max_turns: int = 0,
                     timeout: Optional[float] = None) -> Dict[str, Any]:
        session = self.build_session(gw, model, project)
        args = ["-p", "--output-format", "json"]
        if permission_mode:
            args += ["--permission-mode", permission_mode]
        if allowed_tools:
            args += ["--allowedTools", ",".join(allowed_tools)]
        if max_turns:
            args += ["--max-turns", str(max_turns)]
        if resume:
            args += ["--resume", resume]
        started = time.time()
        try:
            # The prompt goes through stdin: no quoting problems with any characters, on any OS.
            proc = subprocess.run([*session.cmd, *args], cwd=str(project), env=session.env,
                                  input=prompt.encode("utf-8"), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                  timeout=timeout)
        finally:
            session.cleanup()
        out = proc.stdout.decode("utf-8", "replace")
        err = proc.stderr.decode("utf-8", "replace")
        data = _parse_result(out)
        result = {
            "exit_code": proc.returncode,
            "result": (data or {}).get("result") if data else out.strip(),
            "session_id": (data or {}).get("session_id"),
            "cost_usd": (data or {}).get("total_cost_usd"),
            "num_turns": (data or {}).get("num_turns"),
            "duration_ms": (data or {}).get("duration_ms") or int((time.time() - started) * 1000),
            "is_error": bool((data or {}).get("is_error")) or proc.returncode != 0,
            "stderr": "\n".join(err.strip().splitlines()[-20:]),
        }
        if result["is_error"] and not result["result"]:
            result["result"] = result["stderr"]
        return result


def _parse_result(stdout: str) -> Optional[Dict[str, Any]]:
    text = stdout.strip()
    if not text:
        return None
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else None
    except ValueError:
        pass
    for line in reversed(text.splitlines()):
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            try:
                data = json.loads(line)
                if isinstance(data, dict):
                    return data
            except ValueError:
                continue
    return None
