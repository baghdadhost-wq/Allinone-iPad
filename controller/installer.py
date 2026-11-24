"""Installing / updating the three components, and the `doctor` health report."""

from __future__ import annotations

import os
import platform
import sys
from typing import List, Sequence

from . import procs, ui
from .i18n import tr
from .nodejs import NodeError, supported


def git_hint() -> str:
    system = platform.system()
    if system == "Windows":
        return "winget install --id Git.Git -e"
    if system == "Darwin":
        return "xcode-select --install   (or: brew install git)"
    return "sudo apt install git   (or your distribution's package manager)"


def expand(ctx, components: Sequence[str]) -> List[str]:
    wanted = [c.lower() for c in components] or ["all"]
    gws = list(ctx.gateways())
    out: List[str] = []
    for c in wanted:
        if c == "all":
            out += ["node", *gws, "claude"]
        elif c in ("node", "claude", *gws):
            out.append(c)
        elif c in ("claude-code", "claudecode"):
            out.append("claude")
        else:
            raise SystemExit(tr("Unknown component '{c}'. Use: all, node, claude, {g}",
                                "مكوّن غير معروف '{c}'. استخدم: all, node, claude, {g}", c=c, g=", ".join(gws)))
    seen, ordered = set(), []
    for c in out:
        if c not in seen:
            seen.add(c)
            ordered.append(c)
    # Node.js first: everything else needs it.
    if any(c != "node" for c in ordered) and "node" not in ordered and ctx.node.mode == "portable" \
            and not ctx.node.ready():
        ordered.insert(0, "node")
    return ordered


def install(ctx, components: Sequence[str], force: bool = False, latest: bool = False, rebuild: bool = False,
            refresh: bool = False) -> bool:
    items = expand(ctx, components)
    needs_git = any(c in ctx.gateways() and ctx.gateway(c).install_mode() == "source" for c in items)
    if needs_git and not procs.which("git"):
        ui.error(tr("Git is required to download the gateways' source code. Install it with:\n    {h}",
                    "Git مطلوب لتنزيل الكود المصدري للبوابات. ثبّته بالأمر:\n    {h}", h=git_hint()))
        return False
    ok = True
    for comp in items:
        ui.heading(tr("Installing {c}", "تثبيت {c}", c=comp))
        try:
            if comp == "node":
                ctx.node.ensure(force=force, refresh=refresh)
            elif comp == "claude":
                ctx.claude().install(force=force or refresh, latest=latest)
            else:
                ctx.gateway(comp).install(force=force, latest=latest, rebuild=rebuild, refresh=refresh)
        except (NodeError, procs.CommandError, RuntimeError, OSError) as exc:
            ok = False
            ui.error(f"{comp}: {exc}")
            if comp == "node":
                ui.error(tr("Cannot continue without Node.js.", "لا يمكن المتابعة بدون Node.js."))
                break
    print()
    if ok:
        ui.ok(tr("Done. Start with:  allinone", "تم. ابدأ بالأمر:  allinone"))
    else:
        ui.warn(tr("Some steps failed — see the messages above, then run:  allinone doctor",
                   "فشلت بعض الخطوات — راجع الرسائل أعلاه ثم نفّذ:  allinone doctor"))
    return ok


def doctor(ctx) -> bool:
    rows = []
    healthy = True

    def add(name: str, good: bool, detail: str, required: bool = True):
        nonlocal healthy
        mark = ui.green("✔") if good else (ui.red("✘") if required else ui.yellow("!"))
        if required and not good:
            healthy = False
        rows.append([mark, name, detail])

    py = sys.version_info
    add("Python", py >= (3, 10), f"{platform.python_version()} ({sys.executable})")
    git = procs.which("git")
    add("Git", bool(git), git or tr("missing — {h}", "غير موجود — {h}", h=git_hint()))

    ver = ctx.node.version()
    node_detail = f"{'.'.join(map(str, ver)) if ver else tr('missing', 'غير موجود')}  ({ctx.node.mode}: {ctx.node.node_path() or '-'})"
    if ver and not supported(ver):
        node_detail += tr("  — needs 22.22.2+ or 24.x", "  — يلزم 22.22.2+ أو 24.x")
    if not ver and ctx.node.mode == "portable":
        node_detail += tr("  — run: allinone install node", "  — نفّذ: allinone install node")
    add("Node.js", supported(ver), node_detail)

    for gw in ctx.gateways().values():
        st = gw.status()
        detail = gw.base_url + "  "
        if not st["installed"]:
            detail += tr("not installed — allinone install {n}", "غير مثبت — allinone install {n}", n=gw.name)
        else:
            detail += (st["version"] or "") + "  " + (ui.green(tr("running", "يعمل")) if st["up"] else tr("stopped", "متوقف"))
        add(gw.title, st["installed"], detail, required=False)
        if st["up"] and gw.needs_token():
            add(f"{gw.title} key", bool(gw.token()),
                tr("found", "موجود") if gw.token() else tr("not found — open the dashboard, then: allinone key {n} <KEY>",
                                                          "غير موجود — افتح لوحة التحكم ثم: allinone key {n} <KEY>", n=gw.name),
                required=False)

    claude = ctx.claude()
    cver = claude.version() if claude.is_installed() else None
    add("Claude Code", bool(cver), cver or tr("not installed — allinone install claude",
                                              "غير مثبت — allinone install claude"))

    writable = os.access(ctx.data_dir, os.W_OK)
    add(tr("Data folder", "مجلد البيانات"), writable, str(ctx.data_dir))

    ui.heading("Allinone doctor")
    ui.table(rows)
    print()
    if healthy:
        ui.ok(tr("Everything needed is in place.", "كل ما يلزم جاهز."))
    else:
        ui.warn(tr("Fix the ✘ items, or run:  allinone install", "أصلح العناصر ✘ أو نفّذ:  allinone install"))
    return healthy
