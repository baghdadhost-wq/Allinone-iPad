"""Source checkouts of the gateways and your saved modifications to them.

Workflow for changing a gateway's code (source install mode):

1. `allinone install freellmapi` clones the upstream repo at the configured ref
   into runtime/freellmapi and applies every patch from
   customizations/freellmapi/patches/ (in name order).
2. Edit any file under runtime/freellmapi/, rebuild with
   `allinone install freellmapi --rebuild`, try it.
3. `allinone customize save freellmapi` writes your edits to
   customizations/freellmapi/patches/zz-local.patch — commit that file.
4. Updating to a newer upstream version re-clones and re-applies the patches,
   so your changes survive updates (git reports conflicts if upstream changed
   the same lines).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import List, Optional

from . import procs, ui
from .i18n import tr

LOCAL_PATCH = "zz-local.patch"
GIT_ID = ["-c", "user.name=Allinone", "-c", "user.email=allinone@localhost", "-c", "commit.gpgsign=false"]


class SourceError(RuntimeError):
    pass


def git(args: List[str], cwd: Path, capture: bool = True, check: bool = True):
    exe = procs.which("git")
    if not exe:
        raise SourceError(tr("Git is required. Install it from https://git-scm.com and try again.",
                             "Git مطلوب. ثبّته من https://git-scm.com ثم أعد المحاولة."))
    env = dict(os.environ)
    env["GIT_TERMINAL_PROMPT"] = "0"
    return procs.run([exe, *args], cwd=cwd, env=env, capture=capture, check=check)


def is_checkout(path: Path) -> bool:
    return (path / ".git").exists()


def checkout(repo: str, ref: str, dest: Path) -> str:
    """Fresh shallow checkout of repo@ref into dest. Returns the commit id."""
    dest.mkdir(parents=True, exist_ok=True)
    git(["init", "-q"], dest)
    git(["remote", "add", "origin", repo], dest)
    ui.step(tr("Downloading {r} ({ref})", "تنزيل {r} ({ref})", r=repo, ref=ref))
    try:
        git(["fetch", "--depth", "1", "origin", ref], dest, capture=False)
    except procs.CommandError:
        # A branch name that is also ambiguous, or a server that refuses shallow fetch by sha.
        git(["fetch", "origin", ref], dest, capture=False)
    git(["checkout", "-q", "--detach", "FETCH_HEAD"], dest)
    git(["tag", "-f", "allinone-upstream"], dest)
    return current_commit(dest)


def current_commit(path: Path) -> str:
    return git(["rev-parse", "HEAD"], path).stdout.decode().strip()


def patch_dir(root: Path, name: str) -> Path:
    return root / "customizations" / name / "patches"


def patch_files(root: Path, name: str) -> List[Path]:
    d = patch_dir(root, name)
    return sorted(p for p in d.glob("*.patch") if p.is_file()) if d.exists() else []


def apply_patches(root: Path, name: str, dest: Path) -> int:
    """Apply saved patches. Shared patches get committed; zz-local.patch stays as working-tree edits."""
    files = patch_files(root, name)
    shared = [p for p in files if p.name != LOCAL_PATCH]
    local = [p for p in files if p.name == LOCAL_PATCH]
    for patch in shared:
        _apply(patch, dest)
    if shared:
        git(["add", "-A"], dest)
        git([*GIT_ID, "commit", "-q", "--no-verify", "-m", "allinone: shared customizations"], dest)
    for patch in local:
        _apply(patch, dest)
    if files:
        ui.ok(tr("Applied {n} customization patch(es)", "تم تطبيق {n} من ملفات التخصيص", n=len(files)))
    return len(files)


def _apply(patch: Path, dest: Path) -> None:
    if patch.stat().st_size == 0:
        return
    ui.step(tr("Applying {p}", "تطبيق {p}", p=patch.name))
    try:
        git(["apply", "--3way", "--whitespace=nowarn", str(patch)], dest)
    except procs.CommandError as exc:
        raise SourceError(tr(
            "Patch {p} no longer applies cleanly (upstream changed the same lines).\n{e}\n"
            "Fix the conflict markers in {d}, then run: allinone customize save <gateway>",
            "ملف التعديل {p} لم يعد ينطبق بسلاسة (النسخة الأصلية غيّرت الأسطر نفسها).\n{e}\n"
            "أصلح علامات التعارض في {d} ثم نفّذ: allinone customize save <gateway>",
            p=patch.name, e=exc, d=dest)) from exc


def local_diff(dest: Path) -> str:
    """Diff of everything changed in the checkout since the shared patches (includes new files)."""
    git(["add", "-A", "-N", "."], dest)
    try:
        out = git(["diff", "--binary", "HEAD"], dest).stdout.decode("utf-8", errors="surrogateescape")
    finally:
        git(["reset", "-q"], dest, check=False)
    return out


def save_local(root: Path, name: str, dest: Path) -> Optional[Path]:
    if not is_checkout(dest):
        raise SourceError(tr("{n} is not installed from source (set install.mode to \"source\").",
                             "{n} ليس مثبتاً من الكود المصدري (اضبط install.mode على \"source\").", n=name))
    diff = local_diff(dest)
    target = patch_dir(root, name) / LOCAL_PATCH
    if not diff.strip():
        if target.exists():
            target.unlink()
        return None
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(diff, encoding="utf-8", errors="surrogateescape", newline="\n")
    return target


def has_unsaved_changes(root: Path, name: str, dest: Path) -> bool:
    if not is_checkout(dest):
        return False
    try:
        diff = local_diff(dest)
    except (procs.CommandError, SourceError):
        return False
    target = patch_dir(root, name) / LOCAL_PATCH
    saved = target.read_text(encoding="utf-8", errors="surrogateescape") if target.exists() else ""
    return _norm(diff) != _norm(saved)


def _norm(text: str) -> str:
    return "\n".join(line.rstrip() for line in text.replace("\r\n", "\n").strip().splitlines()
                     if not line.startswith("index "))
