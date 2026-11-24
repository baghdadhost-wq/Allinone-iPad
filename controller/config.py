"""Configuration, persistent state and locally stored secrets.

* config/allinone.jsonc  — tracked in git, the main settings (edit freely)
* config/local.jsonc     — optional, NOT tracked: personal overrides merged on top
* data/state.json        — written by the program (language, last gateway, installs)
* data/secrets.json      — generated secrets (dashboard password, encryption key)
"""

from __future__ import annotations

import copy
import json
import os
import secrets as _secrets
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional

from . import jsonc

ROOT = Path(__file__).resolve().parent.parent


def deep_merge(base: Any, override: Any) -> Any:
    if isinstance(base, dict) and isinstance(override, dict):
        out = dict(base)
        for key, value in override.items():
            out[key] = deep_merge(base[key], value) if key in base else copy.deepcopy(value)
        return out
    return copy.deepcopy(override)


def atomic_write_json(path: Path, data: Any, private: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name, dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
        if private and os.name != "nt":
            os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def read_json(path: Path, default: Any) -> Any:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return copy.deepcopy(default)


class Config:
    def __init__(self, root: Path = ROOT):
        self.root = Path(root)
        base = os.environ.get("ALLINONE_CONFIG")
        self.base_path = Path(base) if base else self.root / "config" / "allinone.jsonc"
        local = os.environ.get("ALLINONE_LOCAL_CONFIG")
        self.local_path = Path(local) if local else self.base_path.with_name("local.jsonc")
        data = jsonc.load(self.base_path)
        if self.local_path.exists():
            data = deep_merge(data, jsonc.load(self.local_path))
        self.data: Dict[str, Any] = data
        paths = data.get("paths") or {}
        self.data_dir = self.abs_path(os.environ.get("ALLINONE_DATA_DIR") or paths.get("data") or "data")
        self.runtime_dir = self.abs_path(os.environ.get("ALLINONE_RUNTIME_DIR") or paths.get("runtime") or "runtime")

    def abs_path(self, value: Any) -> Path:
        p = Path(os.path.expandvars(os.path.expanduser(str(value))))
        return p if p.is_absolute() else (self.root / p)

    def get(self, dotted: str, default: Any = None) -> Any:
        node: Any = self.data
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def gateway_configs(self) -> Dict[str, Dict[str, Any]]:
        gws = self.data.get("gateways") or {}
        return {name: cfg for name, cfg in gws.items() if isinstance(cfg, dict) and cfg.get("enabled", True)}


class State:
    """Small JSON document the program owns (never edited by hand)."""

    def __init__(self, path: Path):
        self.path = path
        self.data: Dict[str, Any] = read_json(path, {})

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self.data[key] = value
        atomic_write_json(self.path, self.data)

    def update_install(self, component: str, info: Dict[str, Any]) -> None:
        installs = self.data.setdefault("installed", {})
        installs[component] = info
        atomic_write_json(self.path, self.data)

    def install_info(self, component: str) -> Optional[Dict[str, Any]]:
        return (self.data.get("installed") or {}).get(component)


class Secrets:
    """Generated credentials kept out of git (data/secrets.json, mode 0600)."""

    def __init__(self, path: Path):
        self.path = path
        self.data: Dict[str, Dict[str, str]] = read_json(path, {})

    def get(self, section: str, key: str, default: str = "") -> str:
        return (self.data.get(section) or {}).get(key, default) or default

    def set(self, section: str, key: str, value: str) -> None:
        self.data.setdefault(section, {})[key] = value
        atomic_write_json(self.path, self.data, private=True)

    def ensure(self, section: str, key: str, kind: str = "hex32") -> str:
        value = self.get(section, key)
        if not value:
            if kind == "hex32":
                value = _secrets.token_hex(32)
            elif kind == "password":
                value = _secrets.token_urlsafe(12).replace("-", "x").replace("_", "y")
            else:
                value = _secrets.token_urlsafe(24)
            self.set(section, key, value)
        return value

    def lookup(self, dotted: str) -> str:
        section, _, key = dotted.partition(".")
        return self.get(section, key)
