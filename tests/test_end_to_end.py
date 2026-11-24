"""Full chain: controller -> (fake) Claude Code -> (fake) gateway, plus MCP tools and hooks."""

import json
import os
import unittest

from helpers import Sandbox, out, port_open

MCP_CALLS = [
    ["memory_save", {"text": "The project uses PostgreSQL 16", "tags": "db"}],
    ["memory_search", {"query": "PostgreSQL"}],
    ["gateway_info", {}],
    ["ask_model", {"prompt": "ping from tool"}],
    ["current_time", {"timezone_offset_hours": 3}],
]


class EndToEnd(unittest.TestCase):
    def setUp(self):
        self.sb = Sandbox()

    def tearDown(self):
        self.sb.cleanup()

    def test_interactive_start_wires_everything(self):
        proc = self.sb.run("start", "fake", "--", "--debug", env={"FAKE_MCP_CALLS": json.dumps(MCP_CALLS)})
        self.assertEqual(proc.returncode, 0, out(proc))
        rec = self.sb.read_record()
        env = rec["env"]

        # gateway connection
        self.assertEqual(env["ANTHROPIC_BASE_URL"], f"http://127.0.0.1:{self.sb.port}")
        self.assertEqual(env["ANTHROPIC_AUTH_TOKEN"], "fake-token")
        self.assertEqual(env["ANTHROPIC_MODEL"], "fake/model-1")
        self.assertEqual(env["ANTHROPIC_DEFAULT_HAIKU_MODEL"], "fake/model-1")
        self.assertEqual(env["CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY"], "1")
        self.assertEqual(env["DISABLE_AUTOUPDATER"], "1")
        self.assertTrue(env["CLAUDE_CONFIG_DIR"].endswith("claude-home"))
        self.assertEqual(rec["settings"]["env"]["EXTRA_FLAG"], "yes")
        self.assertEqual(rec["settings"]["env"]["ANTHROPIC_BASE_URL"], env["ANTHROPIC_BASE_URL"])
        self.assertEqual(os.path.realpath(rec["cwd"]), os.path.realpath(str(self.sb.project)))

        # extra args passed through, plugin loaded
        self.assertEqual(rec["argv"][-1], "--debug")
        self.assertTrue(any(p.replace("\\", "/").endswith("claude/plugins/allinone") for p in rec["plugin_dirs"]))

        # MCP config: only the enabled server, placeholders rendered
        self.assertEqual(list(rec["mcp"]["mcpServers"]), ["allinone"])
        allinone = rec["mcp"]["mcpServers"]["allinone"]
        self.assertNotIn("{{", json.dumps(allinone))
        self.assertNotIn("description", allinone)

        # SessionStart hook ran and injected context
        self.assertEqual(rec["hooks"][0]["code"], 0, rec["hooks"])
        self.assertIn("FakeGW", rec["hooks"][0]["stdout"])

        # MCP server answered real tool calls
        replies = {r["id"]: r for r in rec["mcp_results"]["allinone"]["replies"]}
        tool_names = {t["name"] for t in replies[2]["result"]["tools"]}
        for name in ("memory_save", "memory_search", "ask_model", "gateway_models", "current_time"):
            self.assertIn(name, tool_names)
        texts = {i: replies[i]["result"]["content"][0]["text"] for i in range(3, 3 + len(MCP_CALLS))}
        self.assertIn("Saved memory #", texts[3])
        self.assertIn("PostgreSQL 16", texts[4])
        self.assertIn("FakeGW", texts[5])
        self.assertIn("echo: ping from tool", texts[6])
        self.assertIn("UTC+0300", texts[7])
        self.assertFalse(any(replies[i]["result"]["isError"] for i in texts), texts)

        # the gateway saw the ask_model call with the right token
        msgs = [r for r in self.sb.gateway_requests() if r["path"] == "/v1/messages"]
        self.assertTrue(msgs and msgs[0]["auth"] == "Bearer fake-token")

        # we started the gateway, so we stopped it afterwards
        self.assertFalse(port_open(self.sb.port))
        self.assertFalse((self.sb.data / "run" / "fake.json").exists())
        # per-session files (they contain the token) are removed
        self.assertEqual(list((self.sb.data / "run").glob("session-*")), [])

    def test_headless_run_and_task_queue(self):
        proc = self.sb.run("run", "-g", "fake", "مرحبا", "world")
        self.assertEqual(proc.returncode, 0, out(proc))
        self.assertIn("echo: مرحبا world", proc.stdout.decode("utf-8"))
        rec = self.sb.read_record()
        self.assertEqual(rec["prompt"], "مرحبا world")
        self.assertIn("-p", rec["argv"])
        self.assertIn("--permission-mode", rec["argv"])

        listing = self.sb.run("task", "list")
        self.assertIn("done", listing.stdout.decode())

        self.sb.run("task", "add", "-g", "fake", "first job")
        self.sb.run("task", "add", "-g", "fake", "second job")
        work = self.sb.run("task", "work")
        self.assertEqual(work.returncode, 0, out(work))
        text = work.stdout.decode("utf-8")
        self.assertIn("echo: first job", text)
        self.assertIn("echo: second job", text)
        show = self.sb.run("task", "show", "3")
        self.assertIn("echo: second job", show.stdout.decode("utf-8"))
        self.assertFalse(port_open(self.sb.port))

        # resume by task number passes the stored session id
        again = self.sb.run("run", "--resume", "1", "follow up")
        self.assertEqual(again.returncode, 0, out(again))
        argv = self.sb.read_record()["argv"]
        self.assertEqual(argv[argv.index("--resume") + 1].split("-")[0], "sess")

    def test_gateway_commands_and_keys(self):
        start = self.sb.run("gateway", "start", "fake")
        self.assertEqual(start.returncode, 0, out(start))
        self.assertTrue(port_open(self.sb.port))
        status = self.sb.run("gateway", "status").stdout.decode()
        self.assertIn("running", status)
        models = self.sb.run("models", "fake")
        self.assertIn("fake/model-2", models.stdout.decode())
        # a gateway that is already running is reused and left running
        run = self.sb.run("run", "hi")
        self.assertEqual(run.returncode, 0, out(run))
        self.assertTrue(port_open(self.sb.port))
        stop = self.sb.run("gateway", "stop", "fake")
        self.assertEqual(stop.returncode, 0, out(stop))
        self.assertFalse(port_open(self.sb.port))
        logs = self.sb.run("gateway", "logs", "fake")
        self.assertIn("start:", logs.stdout.decode())

        self.sb.run("key", "omniroute-manage", "secret-123")
        secrets = json.loads((self.sb.data / "secrets.json").read_text())
        self.assertEqual(secrets["omniroute-manage"]["api_key"], "secret-123")

    def test_memory_commands(self):
        self.sb.run("memory", "add", "نستخدم", "Django", "--tags", "web")
        found = self.sb.run("memory", "search", "Django")
        self.assertIn("نستخدم Django", found.stdout.decode("utf-8"))
        self.assertIn("[web]", found.stdout.decode("utf-8"))
        self.assertEqual(self.sb.run("memory", "forget", "1").returncode, 0)
        self.assertIn("Nothing found", self.sb.run("memory", "list").stdout.decode())

    def test_failed_gateway_reports_log(self):
        sb = Sandbox({"gateways": {"fake": {"start": {"command": ["{{python}}", "-c", "import sys; print('boom'); sys.exit(3)"]}}}})
        try:
            proc = sb.run("run", "x")
            self.assertEqual(proc.returncode, 1)
            self.assertIn("boom", out(proc))
        finally:
            sb.cleanup()

    def test_shortcut_options_and_claude_args(self):
        proc = self.sb.run("fake", "--model", "fake/model-2", "--", "--continue", "--verbose")
        self.assertEqual(proc.returncode, 0, out(proc))
        rec = self.sb.read_record()
        self.assertEqual(rec["env"]["ANTHROPIC_MODEL"], "fake/model-2")
        self.assertEqual(rec["argv"][-2:], ["--continue", "--verbose"])
        self.assertNotIn("--model", rec["argv"])
        bad = self.sb.run("doctor", "--", "x")
        self.assertNotEqual(bad.returncode, 0)

    def test_queue_survives_a_broken_task(self):
        gone = self.sb.tmp / "deleted-project"
        gone.mkdir()
        self.sb.run("task", "add", "-g", "fake", "-p", str(gone), "will fail")
        gone.rmdir()
        self.sb.run("task", "add", "-g", "fake", "will work")
        work = self.sb.run("task", "work")
        self.assertEqual(work.returncode, 1)  # one failure reported
        self.assertIn("echo: will work", work.stdout.decode())
        listing = self.sb.run("task", "list").stdout.decode()
        self.assertIn("failed", listing)
        self.assertIn("done", listing)
        self.assertNotIn("running", listing)

    def test_doctor_and_help_do_not_crash(self):
        doc = self.sb.run("doctor")
        self.assertIn("Claude Code", out(doc))
        self.assertIn("9.9.9", out(doc))
        self.assertEqual(self.sb.run("help").returncode, 0)
        self.assertEqual(self.sb.run().returncode, 0)  # non-interactive: prints help


if __name__ == "__main__":
    unittest.main()
