"""Editing a gateway's source and keeping the edits across reinstalls (patch workflow)."""

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from helpers import ROOT  # noqa: F401

from controller import sources


def git(cwd, *args):
    subprocess.run(["git", *args], cwd=str(cwd), check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


@unittest.skipUnless(shutil.which("git"), "git is required")
class PatchWorkflow(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="aio-src-"))
        self.upstream = self.tmp / "upstream"
        self.upstream.mkdir()
        git(self.upstream, "init", "-q", "-b", "main")
        (self.upstream / "server.js").write_text("const port = 3001;\nconsole.log('hello');\n")
        (self.upstream / ".gitignore").write_text("node_modules/\ndist/\n")
        git(self.upstream, "add", "-A")
        git(self.upstream, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "v1")
        git(self.upstream, "tag", "v1")
        self.root = self.tmp / "allinone"  # where customizations/ lives
        self.root.mkdir()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_save_and_reapply(self):
        dest = self.tmp / "runtime" / "gw"
        sources.checkout(str(self.upstream), "v1", dest)
        self.assertTrue(sources.is_checkout(dest))
        self.assertIsNone(sources.save_local(self.root, "gw", dest))  # nothing changed yet

        # user edits a file, adds a new one; build output is ignored
        (dest / "server.js").write_text("const port = 3001;\nconsole.log('customized');\n")
        (dest / "provider.js").write_text("export const extra = true;\n")
        (dest / "dist").mkdir()
        (dest / "dist" / "bundle.js").write_text("built")
        self.assertTrue(sources.has_unsaved_changes(self.root, "gw", dest))
        patch = sources.save_local(self.root, "gw", dest)
        self.assertEqual(patch.name, sources.LOCAL_PATCH)
        text = patch.read_text()
        self.assertIn("customized", text)
        self.assertIn("provider.js", text)
        self.assertNotIn("bundle.js", text)
        self.assertFalse(sources.has_unsaved_changes(self.root, "gw", dest))

        # a shared patch written by hand is applied too, before zz-local
        shared = sources.patch_dir(self.root, "gw") / "01-port.patch"
        upstream_copy = self.tmp / "u2"
        sources.checkout(str(self.upstream), "v1", upstream_copy)
        (upstream_copy / "README.md").write_text("custom readme\n")
        git(upstream_copy, "add", "-A")
        shared.write_text(subprocess.run(["git", "diff", "--cached"], cwd=str(upstream_copy),
                                         stdout=subprocess.PIPE, check=True).stdout.decode())

        # fresh install elsewhere: both patches come back
        dest2 = self.tmp / "runtime" / "gw2"
        sources.checkout(str(self.upstream), "v1", dest2)
        self.assertEqual(sources.apply_patches(self.root, "gw", dest2), 2)
        self.assertIn("customized", (dest2 / "server.js").read_text())
        self.assertTrue((dest2 / "provider.js").exists())
        self.assertEqual((dest2 / "README.md").read_text(), "custom readme\n")
        # the shared patch is committed, so saving again only contains the local edits
        self.assertFalse(sources.has_unsaved_changes(self.root, "gw", dest2))
        again = sources.save_local(self.root, "gw", dest2).read_text()
        self.assertNotIn("custom readme", again)
        self.assertIn("customized", again)

    def test_conflicting_patch_is_reported(self):
        dest = self.tmp / "runtime" / "gw"
        sources.checkout(str(self.upstream), "v1", dest)
        (dest / "server.js").write_text("const port = 9999;\nconsole.log('hello');\n")
        sources.save_local(self.root, "gw", dest)
        # upstream changes the same line
        (self.upstream / "server.js").write_text("const port = 4000;\nconsole.log('hello');\n")
        git(self.upstream, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-am", "v2")
        git(self.upstream, "tag", "v2")
        dest2 = self.tmp / "runtime" / "gw2"
        sources.checkout(str(self.upstream), "v2", dest2)
        with self.assertRaises(sources.SourceError):
            sources.apply_patches(self.root, "gw", dest2)


if __name__ == "__main__":
    unittest.main()
