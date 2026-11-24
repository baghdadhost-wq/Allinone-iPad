#!/usr/bin/env python3
"""A stand-in for the `claude` CLI, for tests.

It does what matters for the integration and records everything to
$FAKE_CLAUDE_RECORD (JSON):
  * reads --settings / --mcp-config / --plugin-dir like Claude Code would,
  * runs the SessionStart hook from the settings file (exec form),
  * starts every stdio MCP server from the MCP config and calls tools on "allinone",
  * in -p mode, sends the stdin prompt to ANTHROPIC_BASE_URL/v1/messages and
    prints a JSON result like `claude -p --output-format json`.
"""

import json
import os
import subprocess
import sys
import urllib.request


def arg_values(argv, flag):
    return [argv[i + 1] for i, a in enumerate(argv[:-1]) if a == flag]


# Like the MCP SDK's stdio transport: servers get only a small safe subset of the parent
# environment plus their configured "env", so every variable a server needs must be in mcp.json.
SAFE_ENV = ["HOME", "LOGNAME", "PATH", "SHELL", "TERM", "USER", "APPDATA", "HOMEDRIVE", "HOMEPATH",
            "LOCALAPPDATA", "PROCESSOR_ARCHITECTURE", "SYSTEMDRIVE", "SYSTEMROOT", "TEMP", "USERNAME",
            "USERPROFILE", "PROGRAMFILES"]


def call_mcp(spec, calls):
    env = {k: v for k, v in os.environ.items() if k.upper() in SAFE_ENV}
    env.update(spec.get("env") or {})
    proc = subprocess.Popen([spec["command"], *spec.get("args", [])], stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    msgs = [{"jsonrpc": "2.0", "id": 1, "method": "initialize",
             "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "fake", "version": "0"}}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}]
    for i, (name, args) in enumerate(calls, start=3):
        msgs.append({"jsonrpc": "2.0", "id": i, "method": "tools/call", "params": {"name": name, "arguments": args}})
    payload = "".join(json.dumps(m) + "\n" for m in msgs).encode()
    out, err = proc.communicate(payload, timeout=60)
    replies = [json.loads(line) for line in out.decode().splitlines() if line.strip()]
    return {"replies": replies, "stderr": err.decode()[-2000:]}


def main():
    argv = sys.argv[1:]
    if "--version" in argv:
        print("9.9.9 (Claude Code)")
        return 0
    record = {"argv": argv, "cwd": os.getcwd(),
              "env": {k: v for k, v in os.environ.items()
                      if k.startswith(("ANTHROPIC_", "CLAUDE_", "ALLINONE_", "DISABLE_"))}}
    settings_path = arg_values(argv, "--settings")[0]
    mcp_path = arg_values(argv, "--mcp-config")[0]
    with open(settings_path, encoding="utf-8") as fh:
        settings = json.load(fh)
    with open(mcp_path, encoding="utf-8") as fh:
        mcp = json.load(fh)
    record.update(settings=settings, mcp=mcp, plugin_dirs=arg_values(argv, "--plugin-dir"))

    hook_env = dict(os.environ)
    hook_env.update(settings.get("env") or {})
    hooks = []
    for group in (settings.get("hooks") or {}).get("SessionStart", []):
        for h in group.get("hooks", []):
            res = subprocess.run([h["command"], *h.get("args", [])], input=json.dumps({"source": "startup"}).encode(),
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=hook_env, timeout=30)
            hooks.append({"code": res.returncode, "stdout": res.stdout.decode("utf-8"), "stderr": res.stderr.decode()})
    record["hooks"] = hooks

    calls = json.loads(os.environ.get("FAKE_MCP_CALLS", "[]"))
    record["mcp_results"] = {name: call_mcp(spec, calls) for name, spec in mcp["mcpServers"].items()
                             if spec.get("command")}

    if "-p" in argv:
        prompt = sys.stdin.read()
        record["prompt"] = prompt
        req = urllib.request.Request(
            os.environ["ANTHROPIC_BASE_URL"] + "/v1/messages",
            data=json.dumps({"model": os.environ.get("ANTHROPIC_MODEL", "claude-x"), "max_tokens": 64,
                             "messages": [{"role": "user", "content": prompt}]}).encode(),
            headers={"Authorization": "Bearer " + os.environ["ANTHROPIC_AUTH_TOKEN"],
                     "Content-Type": "application/json"})
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(req, timeout=30) as resp:
            reply = json.loads(resp.read())
        text = reply["content"][0]["text"]
        print(json.dumps({"type": "result", "subtype": "success", "is_error": False, "result": text,
                          "session_id": "sess-" + str(abs(hash(prompt)) % 10000), "num_turns": 1,
                          "duration_ms": 12, "total_cost_usd": 0}))
    with open(os.environ["FAKE_CLAUDE_RECORD"], "w", encoding="utf-8") as fh:
        json.dump(record, fh, ensure_ascii=False, indent=2)
    return int(os.environ.get("FAKE_CLAUDE_EXIT", "0"))


if __name__ == "__main__":
    sys.exit(main())
