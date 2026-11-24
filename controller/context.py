"""Shared runtime context: config, state, secrets, Node.js, gateways, Claude Code."""

from __future__ import annotations

import shutil
import sys
import time
from collections import OrderedDict
from pathlib import Path
from typing import Dict, Optional

from .config import Config, Secrets, State
from .gateways import Gateway, GatewayError, make_gateway
from .i18n import tr
from .nodejs import NodeRuntime


class Context:
    def __init__(self, cfg: Optional[Config] = None):
        self.cfg = cfg or Config()
        self.data_dir: Path = self.cfg.data_dir
        self.run_dir = self.data_dir / "run"
        self.logs_dir = self.data_dir / "logs"
        for d in (self.data_dir, self.run_dir, self.logs_dir):
            d.mkdir(parents=True, exist_ok=True)
        self.state = State(self.data_dir / "state.json")
        self.secrets = Secrets(self.data_dir / "secrets.json")
        self.node = NodeRuntime(self.cfg, self.state)
        self._gateways: Optional[Dict[str, Gateway]] = None
        self._claude = None
        self._store = None
        self.python = sys.executable
        self.cleanup_stale_sessions()

    # ------------------------------------------------------------- gateways
    def gateways(self) -> Dict[str, Gateway]:
        if self._gateways is None:
            self._gateways = OrderedDict(
                (name, make_gateway(name, cfg, self)) for name, cfg in self.cfg.gateway_configs().items()
            )
        return self._gateways

    def gateway(self, name: Optional[str]) -> Gateway:
        gws = self.gateways()
        if not gws:
            raise GatewayError(tr("No gateway is enabled in config/allinone.jsonc.",
                                  "لا توجد بوابة مفعّلة في config/allinone.jsonc."))
        if not name:
            name = self.state.get("last_gateway") or self.cfg.get("default_gateway") or next(iter(gws))
        key = str(name).lower()
        for gname, gw in gws.items():
            if gname.lower() == key or gw.title.lower() == key:
                return gw
        raise GatewayError(tr("Unknown gateway '{n}'. Available: {a}", "بوابة غير معروفة '{n}'. المتاح: {a}",
                              n=name, a=", ".join(gws)))

    # ---------------------------------------------------------- components
    def claude(self):
        if self._claude is None:
            from .claude import ClaudeRuntime

            self._claude = ClaudeRuntime(self)
        return self._claude

    def store(self):
        if self._store is None:
            from .store import Store

            self._store = Store(self.data_dir / "allinone.db")
        return self._store

    # ------------------------------------------------------------- cleanup
    def cleanup_stale_sessions(self, max_age_hours: float = 24.0) -> None:
        """Remove per-session files (they hold the gateway token) left by crashed runs."""
        cutoff = time.time() - max_age_hours * 3600
        for path in self.run_dir.glob("session-*"):
            try:
                if path.is_dir() and path.stat().st_mtime < cutoff:
                    shutil.rmtree(path, ignore_errors=True)
            except OSError:
                pass
