"""HTTP helpers built on urllib (no third-party packages)."""

from __future__ import annotations

import hashlib
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Callable, Dict, Optional, Tuple

LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "[::1]", "0.0.0.0"}

_direct = urllib.request.build_opener(urllib.request.ProxyHandler({}))
_default = urllib.request.build_opener()


def _opener(url: str):
    host = (urllib.parse.urlsplit(url).hostname or "").lower()
    # Never send local gateway traffic through a corporate HTTP(S) proxy.
    return _direct if host in LOCAL_HOSTS else _default


def request(method: str, url: str, headers: Optional[Dict[str, str]] = None, body: Optional[dict] = None,
            timeout: float = 5.0) -> Tuple[int, bytes]:
    """Return (status, body). Raises urllib.error.URLError when nothing answers."""
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with _opener(url).open(req, timeout=timeout) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read() or b""


def get_json(url: str, headers: Optional[Dict[str, str]] = None, timeout: float = 5.0):
    status, body = request("GET", url, headers=headers, timeout=timeout)
    try:
        return status, json.loads(body.decode("utf-8") or "null")
    except ValueError:
        return status, None


def answers(url: str, timeout: float = 2.0) -> Optional[int]:
    """HTTP status if something answers at url, else None."""
    try:
        status, _ = request("GET", url, timeout=timeout)
        return status
    except (urllib.error.URLError, OSError, ValueError):
        return None


def wait_until_up(url: str, timeout: float, alive: Callable[[], bool], tick: Callable[[], None]) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        status = answers(url)
        if status is not None and status < 500:
            return True
        if not alive():
            return False
        tick()
        time.sleep(0.7)
    return False


def download(url: str, dest: Path, progress: Optional[Callable[[int, int], None]] = None) -> str:
    """Download to dest; returns the sha256 hex digest."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    sha = hashlib.sha256()
    req = urllib.request.Request(url, headers={"User-Agent": "allinone-installer"})
    with _opener(url).open(req, timeout=60) as resp, open(tmp, "wb") as fh:
        total = int(resp.headers.get("Content-Length") or 0)
        done = 0
        while True:
            chunk = resp.read(256 * 1024)
            if not chunk:
                break
            fh.write(chunk)
            sha.update(chunk)
            done += len(chunk)
            if progress:
                progress(done, total)
    tmp.replace(dest)
    return sha.hexdigest()


def fetch_text(url: str, timeout: float = 30.0) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "allinone-installer"})
    with _opener(url).open(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8")
