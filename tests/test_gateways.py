"""OmniRoute / FreeLLMAPI specifics: environment, credentials, Claude Code variables."""

import json
import os
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

from helpers import ROOT  # noqa: F401  (puts the repo on sys.path)

from controller.config import Config
from controller.context import Context
from controller.gateways import parse_env_file, render


class GatewayTypes(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="aio-gw-"))
        os.environ["ALLINONE_DATA_DIR"] = str(self.tmp / "data")
        os.environ["ALLINONE_RUNTIME_DIR"] = str(self.tmp / "runtime")
        os.environ["ALLINONE_LOCAL_CONFIG"] = str(self.tmp / "none.jsonc")
        self.ctx = Context(Config())

    def tearDown(self):
        for key in ("ALLINONE_DATA_DIR", "ALLINONE_RUNTIME_DIR", "ALLINONE_LOCAL_CONFIG"):
            os.environ.pop(key, None)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_shipped_config_lists_both_gateways(self):
        gws = self.ctx.gateways()
        self.assertEqual(list(gws), ["omniroute", "freellmapi"])
        self.assertEqual(gws["omniroute"].base_url, "http://127.0.0.1:20128")
        self.assertEqual(gws["freellmapi"].base_url, "http://127.0.0.1:3001")
        self.assertEqual(gws["omniroute"].install_mode(), "npm")
        self.assertEqual(gws["freellmapi"].install_mode(), "source")

    def test_omniroute_environment(self):
        gw = self.ctx.gateway("omniroute")
        env = gw.required_env()
        self.assertEqual(env["PORT"], "20128")
        self.assertEqual(env["OMNIROUTE_SERVER_HOST"], "127.0.0.1")
        self.assertEqual(env["DATA_DIR"], str(self.tmp / "data" / "omniroute"))
        self.assertNotEqual(env["INITIAL_PASSWORD"], "CHANGEME")
        self.assertGreaterEqual(len(env["INITIAL_PASSWORD"]), 12)
        # stable across calls (stored in data/secrets.json)
        self.assertEqual(env["INITIAL_PASSWORD"], gw.required_env()["INITIAL_PASSWORD"])
        self.assertIn(env["INITIAL_PASSWORD"], " ".join(gw.dashboard_notes()))
        cenv = gw.claude_env()
        self.assertEqual(cenv["ANTHROPIC_BASE_URL"], "http://127.0.0.1:20128")
        self.assertEqual(cenv["ANTHROPIC_AUTH_TOKEN"], "omniroute-no-auth")
        self.assertEqual(cenv["ANTHROPIC_MODEL"], "auto")
        self.assertEqual(cenv["ANTHROPIC_DEFAULT_SONNET_MODEL"], "auto")
        self.assertEqual(cenv["CLAUDE_CODE_AUTO_COMPACT_WINDOW"], "190000")
        # a model chosen at launch wins
        self.assertEqual(gw.claude_env("kimi/kimi-k2.6")["ANTHROPIC_DEFAULT_HAIKU_MODEL"], "kimi/kimi-k2.6")

    def test_omniroute_start_command_uses_package_bin(self):
        gw = self.ctx.gateway("omniroute")
        pkg = gw.install_dir / "node_modules" / "omniroute"
        (pkg / "bin").mkdir(parents=True)
        (pkg / "package.json").write_text(json.dumps({"version": "3.8.54", "bin": {"omniroute": "bin/omniroute.mjs"}}))
        (pkg / "bin" / "omniroute.mjs").write_text("// stub")
        self.assertTrue(gw.is_installed())
        node = self.tmp / "runtime" / "node" / ("node.exe" if os.name == "nt" else "bin/node")
        node.parent.mkdir(parents=True)
        node.write_text("")
        spec = gw.start_spec()
        self.assertEqual(spec.cmd[1:], [str(pkg / "bin" / "omniroute.mjs"), "serve", "--port", "20128", "--no-open", "--no-tray"])
        self.assertEqual(spec.cmd[0], str(node))
        self.assertTrue(spec.env["PATH"].startswith(str(node.parent)))
        self.assertNotIn("ANTHROPIC_API_KEY", spec.env)

    def test_freellmapi_environment_and_unified_key(self):
        gw = self.ctx.gateway("freellmapi")
        env = gw.required_env()
        self.assertEqual(env["NODE_ENV"], "production")
        self.assertEqual(env["HOST"], "127.0.0.1")
        self.assertEqual(len(env["ENCRYPTION_KEY"]), 64)
        self.assertEqual(env["FREEAPI_DB_PATH"], str(self.tmp / "data" / "freellmapi" / "freellmapi.db"))
        self.assertTrue(gw.needs_token())
        self.assertEqual(gw.token(), "")

        db = gw.db_path()
        db.parent.mkdir(parents=True)
        conn = sqlite3.connect(str(db))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT)")
        conn.execute("INSERT INTO settings VALUES ('unified_api_key', 'freellmapi-abc123')")
        conn.commit()
        try:
            self.assertEqual(gw.token(), "freellmapi-abc123")  # read while the writer keeps it open
        finally:
            conn.close()
        cenv = gw.claude_env()
        self.assertEqual(cenv["ANTHROPIC_AUTH_TOKEN"], "freellmapi-abc123")
        self.assertEqual(cenv["CLAUDE_CODE_AUTO_MODE_SERVER"], "0")
        # a key saved by the user takes precedence
        self.ctx.secrets.set("freellmapi", "api_key", "freellmapi-manual")
        self.assertEqual(gw.token(), "freellmapi-manual")

    def test_empty_model_lets_the_gateway_decide(self):
        gw = self.ctx.gateway("freellmapi")
        env = gw.claude_env("")
        self.assertNotIn("ANTHROPIC_MODEL", env)
        self.assertNotIn("ANTHROPIC_DEFAULT_OPUS_MODEL", env)

    def test_base_url_never_ends_with_v1(self):
        from controller.gateways import Gateway

        gw = Gateway("x", {"base_url": "https://gw.example.com/v1/"}, self.ctx)
        self.assertEqual(gw.base_url, "https://gw.example.com")

    def test_render_and_env_file(self):
        self.ctx.secrets.set("svc", "api_key", "S3CRET")
        value = render({"a": ["{{port}}", "{{secret:svc.api_key}}", "{{ unknown }}"]}, {"port": "1"}, self.ctx.secrets)
        self.assertEqual(value, {"a": ["1", "S3CRET", "{{ unknown }}"]})
        f = self.tmp / "x.env"
        f.write_text("# c\nexport A=1\nB=\"two words\"\nC=3 # note\n\nbad line\n", encoding="utf-8")
        self.assertEqual(parse_env_file(f), {"A": "1", "B": "two words", "C": "3"})

    def test_shipped_env_files_parse(self):
        for name in ("omniroute", "freellmapi"):
            parsed = parse_env_file(ROOT / "config" / "gateways" / f"{name}.env")
            self.assertEqual(parsed, {}, f"{name}.env should ship with everything commented out")


if __name__ == "__main__":
    unittest.main()


class ClaudeResolver(unittest.TestCase):
    """Finding the executable that the @anthropic-ai/claude-code npm package installed."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="aio-cc-"))
        os.environ["ALLINONE_DATA_DIR"] = str(self.tmp / "data")
        os.environ["ALLINONE_RUNTIME_DIR"] = str(self.tmp / "runtime")
        os.environ["ALLINONE_LOCAL_CONFIG"] = str(self.tmp / "none.jsonc")
        self.ctx = Context(Config())
        self.cc = self.ctx.claude()
        self.pkg = self.cc.prefix / "node_modules" / "@anthropic-ai" / "claude-code"
        (self.pkg / "bin").mkdir(parents=True)
        self.bin_dir = self.cc.prefix / "node_modules" / ".bin"
        self.bin_dir.mkdir(parents=True)

    def tearDown(self):
        import controller.claude as cmod

        cmod.IS_WINDOWS = os.name == "nt"
        for key in ("ALLINONE_DATA_DIR", "ALLINONE_RUNTIME_DIR", "ALLINONE_LOCAL_CONFIG"):
            os.environ.pop(key, None)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _package(self, bin_rel, content):
        (self.pkg / "package.json").write_text(json.dumps({"version": "2.9.0", "bin": {"claude": bin_rel}}))
        (self.pkg / bin_rel).write_bytes(content)

    def test_native_binary(self):
        self._package("bin/claude", b"\x7fELF\x02\x01\x01binary")
        if os.name != "nt":
            self.assertEqual(self.cc.command(), [str(self.pkg / "bin" / "claude")])
        self.assertEqual(self.cc.installed_version(), "2.9.0")

    def test_js_launcher_runs_with_node(self):
        import shutil as sh

        if not sh.which("node"):
            self.skipTest("node not on PATH")
        self._package("cli.js", b"#!/usr/bin/env node\nconsole.log(1)\n")
        cmd = self.cc.command()
        self.assertEqual(cmd[1], str(self.pkg / "cli.js"))
        self.assertIn("node", Path(cmd[0]).name)

    def test_windows_prefers_exe_then_npm_shim(self):
        import controller.claude as cmod

        cmod.IS_WINDOWS = True
        self._package("bin/claude", b"MZ native without extension")
        (self.bin_dir / "claude.cmd").write_text("@echo off")
        self.assertEqual(self.cc.command(), [str(self.bin_dir / "claude.cmd")])
        (self.pkg / "bin" / "claude.exe").write_bytes(b"MZ native")
        self.assertEqual(self.cc.command(), [str(self.pkg / "bin" / "claude.exe")])
