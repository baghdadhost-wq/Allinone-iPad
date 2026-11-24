"""A tiny MCP (Model Context Protocol) server over stdio — standard library only.

Write a plain Python function, decorate it with @tool, and Claude Code can call it:

    from mcp_kit import tool

    @tool
    def word_count(text: str) -> str:
        "Count the words in a text."
        return str(len(text.split()))

The function's type hints become the JSON schema (str, int, float, bool, list,
dict); parameters with defaults are optional; the docstring is the description
Claude reads to decide when to use the tool. Return a string (or anything JSON
serialisable). Raise an exception to report an error to Claude.
"""

from __future__ import annotations

import inspect
import json
import sys
import traceback
from typing import Any, Callable, Dict, List, Optional

PROTOCOL_FALLBACK = "2025-06-18"
_TOOLS: Dict[str, Dict[str, Any]] = {}

_TYPE_MAP = {str: "string", int: "integer", float: "number", bool: "boolean", list: "array", dict: "object"}
_NAME_MAP = {"str": "string", "int": "integer", "float": "number", "bool": "boolean", "list": "array",
             "dict": "object", "List": "array", "Dict": "object"}


def _schema_for(annotation: Any) -> Dict[str, Any]:
    if annotation in _TYPE_MAP:
        return {"type": _TYPE_MAP[annotation]}
    name = annotation if isinstance(annotation, str) else getattr(annotation, "__name__", "")
    base = str(name).split("[", 1)[0].replace("typing.", "").replace("Optional", "").strip("[] ")
    return {"type": _NAME_MAP.get(base, "string")}


def tool(fn: Optional[Callable] = None, *, name: Optional[str] = None, description: Optional[str] = None):
    """Register a function as an MCP tool. Usable as @tool or @tool(name=..., description=...)."""

    def register(func: Callable) -> Callable:
        sig = inspect.signature(func)
        props: Dict[str, Any] = {}
        required: List[str] = []
        for pname, param in sig.parameters.items():
            if param.kind in (param.VAR_POSITIONAL, param.VAR_KEYWORD):
                continue
            ann = param.annotation if param.annotation is not inspect.Parameter.empty else str
            props[pname] = _schema_for(ann)
            if param.default is inspect.Parameter.empty:
                required.append(pname)
            else:
                props[pname]["default"] = param.default
        doc = description or inspect.getdoc(func) or func.__name__
        _TOOLS[name or func.__name__] = {
            "fn": func,
            "spec": {
                "name": name or func.__name__,
                "description": doc,
                "inputSchema": {"type": "object", "properties": props, "required": required},
            },
        }
        return func

    return register(fn) if fn is not None else register


def tools() -> List[Dict[str, Any]]:
    return [t["spec"] for t in _TOOLS.values()]


def log(*args: Any) -> None:
    """Log to stderr (stdout is reserved for the protocol)."""
    print(*args, file=sys.stderr, flush=True)


def _reply(msg_id: Any, result: Any = None, error: Optional[Dict[str, Any]] = None) -> None:
    payload: Dict[str, Any] = {"jsonrpc": "2.0", "id": msg_id}
    if error is not None:
        payload["error"] = error
    else:
        payload["result"] = result
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _call(name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    entry = _TOOLS.get(name)
    if not entry:
        return {"content": [{"type": "text", "text": f"Unknown tool: {name}"}], "isError": True}
    try:
        value = entry["fn"](**(arguments or {}))
    except Exception as exc:  # report to Claude instead of crashing the server
        log(traceback.format_exc())
        return {"content": [{"type": "text", "text": f"{type(exc).__name__}: {exc}"}], "isError": True}
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, indent=2, default=str)
    return {"content": [{"type": "text", "text": text}], "isError": False}


def serve(server_name: str = "allinone", version: str = "1.0.0", instructions: str = "") -> None:
    try:
        sys.stdin.reconfigure(encoding="utf-8")
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        method, msg_id = msg.get("method"), msg.get("id")
        params = msg.get("params") or {}
        if msg_id is None:  # notification (e.g. notifications/initialized)
            continue
        if method == "initialize":
            result = {
                "protocolVersion": params.get("protocolVersion") or PROTOCOL_FALLBACK,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": server_name, "version": version},
            }
            if instructions:
                result["instructions"] = instructions
            _reply(msg_id, result)
        elif method == "ping":
            _reply(msg_id, {})
        elif method == "tools/list":
            _reply(msg_id, {"tools": tools()})
        elif method == "tools/call":
            _reply(msg_id, _call(params.get("name", ""), params.get("arguments") or {}))
        elif method in ("resources/list", "prompts/list"):
            _reply(msg_id, {method.split("/")[0]: []})
        else:
            _reply(msg_id, error={"code": -32601, "message": f"Method not found: {method}"})
