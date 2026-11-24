"""Interactive menu shown when `allinone` runs without arguments."""

from __future__ import annotations

import webbrowser
from pathlib import Path
from typing import List

from . import __version__, flows, installer, ui
from .claude import ClaudeError
from .gateways import GatewayError
from .i18n import set_language, tr


def run_menu(ctx) -> int:
    project = flows.resolve_project(ctx, None)
    started_here: List[str] = []
    try:
        while True:
            gws = list(ctx.gateways().values())
            ui.heading(f"Allinone {__version__} · Claude Code ⇄ {' / '.join(g.title for g in gws)}")
            ui.say(f"  {tr('Project', 'المشروع')}: {ui.bold(str(project))}")
            print()
            default_name = ctx.state.get("last_gateway") or ctx.cfg.get("default_gateway") or gws[0].name
            default_idx = "1"
            for i, gw in enumerate(gws, 1):
                st = gw.status()
                if gw.name == default_name:
                    default_idx = str(i)
                state = ui.green("● " + tr("running", "يعمل")) if st["up"] else ui.dim("○ " + tr("stopped", "متوقف"))
                extra = "" if st["installed"] else ui.yellow("  " + tr("(not installed)", "(غير مثبت)"))
                ui.say(f"  {ui.bold(str(i))}) {ui.pad(gw.title, 12)} {ui.pad(state, 12)} {ui.dim(gw.base_url)}{extra}")
            print()
            ui.say(ui.dim("  " + tr("p) project   d) dashboard   s) status   t) tasks   i) install/update   "
                                    "l) language   q) quit",
                                    "p) المشروع   d) لوحة التحكم   s) الحالة   t) المهام   i) تثبيت/تحديث   "
                                    "l) اللغة   q) خروج")))
            choice = ui.ask(tr("Choose a gateway for Claude Code", "اختر البوابة لـ Claude Code"), default_idx).lower()

            if choice in ("q", "quit", "exit", "0"):
                return 0
            if choice == "p":
                new = ui.ask(tr("Project folder", "مجلد المشروع"), str(project))
                p = Path(new).expanduser()
                if p.is_dir():
                    project = p.resolve()
                else:
                    ui.error(tr("Folder not found: {p}", "المجلد غير موجود: {p}", p=p))
                continue
            if choice == "s":
                installer.doctor(ctx)
                continue
            if choice == "t":
                _tasks(ctx)
                continue
            if choice == "i":
                if ui.confirm(tr("Install/update all components now?", "تثبيت/تحديث جميع المكونات الآن؟")):
                    installer.install(ctx, ["all"])
                continue
            if choice == "l":
                lang = ui.ask("1) العربية   2) English", "1")
                code = "en" if lang.strip() in ("2", "en") else "ar"
                ctx.state.set("language", code)
                set_language(code)
                continue
            if choice == "d":
                gw = _pick(gws, ui.ask(tr("Which gateway", "أي بوابة"), default_idx))
                if gw:
                    try:
                        flows.ensure_installed(ctx, gw, True)
                        if gw.start() == "started":
                            started_here.append(gw.name)
                        for note in gw.dashboard_notes():
                            ui.say("   " + note)
                        webbrowser.open(gw.dashboard_url())
                        ui.ok(gw.dashboard_url())
                    except (GatewayError, ClaudeError, RuntimeError) as exc:
                        ui.error(str(exc))
                continue

            gw = _pick(gws, choice)
            if not gw:
                ui.warn(tr("Unknown choice.", "اختيار غير معروف."))
                continue
            try:
                flows.ensure_claude(ctx, True)
                if flows.bring_up(ctx, gw, True):
                    started_here.append(gw.name)
                ctx.state.set("last_gateway", gw.name)
                model = flows.choose_model(gw, None)
                flows.banner(gw, model, project)
                code = ctx.claude().run_interactive(gw, model, project, [])
                if code not in (0, None):
                    ui.warn(tr("Claude Code exited with code {c}", "خرج Claude Code بالرمز {c}", c=code))
            except (GatewayError, ClaudeError, RuntimeError) as exc:
                ui.error(str(exc))
    except KeyboardInterrupt:
        print()
        return 130
    finally:
        if not ctx.cfg.get("keep_gateway_running", False):
            for name in dict.fromkeys(started_here):
                gw = ctx.gateway(name)
                if gw.managed_pid():
                    ui.step(tr("Stopping {t}", "إيقاف {t}", t=gw.title))
                    gw.stop()


def _pick(gws, choice: str):
    if choice.isdigit() and 1 <= int(choice) <= len(gws):
        return gws[int(choice) - 1]
    for gw in gws:
        if choice.lower() in (gw.name.lower(), gw.title.lower()):
            return gw
    return None


def _tasks(ctx) -> None:
    rows = ctx.store().list_tasks(15)
    if not rows:
        ui.say(tr("No tasks yet. Add one with:  allinone task add \"...\"",
                  "لا توجد مهام بعد. أضف مهمة بالأمر:  allinone task add \"...\""))
        return
    ui.table([[str(r["id"]), r["status"], r["gateway"] or "", (r["prompt"] or "")[:60].replace("\n", " ")]
              for r in rows], headers=["#", tr("status", "الحالة"), tr("gateway", "البوابة"), tr("prompt", "الطلب")])
