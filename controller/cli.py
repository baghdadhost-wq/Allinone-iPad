"""Command-line entry point:  allinone [command] ...

Run `allinone` with no arguments for the interactive menu, or `allinone help`.
"""

from __future__ import annotations

import argparse
import sys
import time
import webbrowser
from typing import List, Optional

from . import __version__, flows, i18n, installer, sources, ui
from .claude import ClaudeError
from .config import Config
from .context import Context
from .gateways import GatewayError
from .i18n import tr
from .nodejs import NodeError
from .procs import CommandError


# --------------------------------------------------------------- language
def init_language(ctx: Context) -> None:
    configured = str(ctx.cfg.get("language") or "auto").lower()
    if configured in i18n.SUPPORTED:
        i18n.set_language(configured)
        return
    saved = ctx.state.get("language")
    if saved in i18n.SUPPORTED:
        i18n.set_language(saved)
        return
    if ui.interactive():
        ui.say("Allinone — choose the interface language / اختر لغة الواجهة")
        answer = ui.ask("1) العربية   2) English", "1")
        code = "en" if answer.strip().lower() in ("2", "en", "english") else "ar"
    else:
        code = "ar"
    ctx.state.set("language", code)
    i18n.set_language(code)


# ---------------------------------------------------------------- parser
def build_parser(gateway_names: List[str]) -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="allinone",
        description=tr("Run Claude Code through OmniRoute or FreeLLMAPI.",
                       "تشغيل Claude Code عبر OmniRoute أو FreeLLMAPI."))
    p.add_argument("--version", action="version", version=f"Allinone {__version__}")
    sub = p.add_subparsers(dest="command")

    s = sub.add_parser("start", help=tr("start Claude Code through a gateway", "تشغيل Claude Code عبر بوابة"))
    s.add_argument("gateway", nargs="?", help=", ".join(gateway_names))
    s.add_argument("-p", "--project", help=tr("project folder (default: current folder)", "مجلد المشروع (الافتراضي: المجلد الحالي)"))
    s.add_argument("-m", "--model", help=tr("model id sent by Claude Code", "معرّف النموذج الذي يرسله Claude Code"))
    s.add_argument("--keep", action="store_true", help=tr("leave the gateway running afterwards", "إبقاء البوابة تعمل بعد الخروج"))
    s.epilog = tr("Arguments after -- go to Claude Code, e.g.:  allinone start omniroute -- --continue",
                  "ما يأتي بعد -- يُمرَّر إلى Claude Code، مثل:  allinone start omniroute -- --continue")

    r = sub.add_parser("run", help=tr("run one task without the interactive UI", "تنفيذ مهمة واحدة بدون واجهة تفاعلية"))
    r.add_argument("prompt", nargs="+")
    r.add_argument("-g", "--gateway")
    r.add_argument("-p", "--project")
    r.add_argument("-m", "--model")
    r.add_argument("--resume", help=tr("task number or Claude session id to continue", "رقم مهمة أو معرّف جلسة للمتابعة"))
    r.add_argument("--keep", action="store_true")

    t = sub.add_parser("task", help=tr("task queue: add, list, show, work", "طابور المهام: add, list, show, work"))
    tsub = t.add_subparsers(dest="task_cmd")
    ta = tsub.add_parser("add")
    ta.add_argument("prompt", nargs="+")
    ta.add_argument("-g", "--gateway")
    ta.add_argument("-p", "--project")
    ta.add_argument("-m", "--model")
    tl = tsub.add_parser("list")
    tl.add_argument("-n", type=int, default=20)
    ts = tsub.add_parser("show")
    ts.add_argument("id", type=int)
    tw = tsub.add_parser("work")
    tw.add_argument("--keep", action="store_true")

    g = sub.add_parser("gateway", help=tr("start, stop, status, logs", "start, stop, status, logs"))
    g.add_argument("action", choices=["start", "stop", "status", "logs"])
    g.add_argument("name", nargs="?")
    g.add_argument("-n", type=int, default=40, help="logs: number of lines")
    g.add_argument("-f", "--follow", action="store_true", help="logs: keep printing new lines")

    d = sub.add_parser("dashboard", help=tr("open a gateway dashboard", "فتح لوحة تحكم بوابة"))
    d.add_argument("name", nargs="?")

    m = sub.add_parser("models", help=tr("list a gateway's models", "عرض نماذج البوابة"))
    m.add_argument("name", nargs="?")

    k = sub.add_parser("key", help=tr("show or set a gateway API key", "عرض أو ضبط مفتاح API لبوابة"))
    k.add_argument("name")
    k.add_argument("value", nargs="?")
    k.add_argument("--clear", action="store_true")

    mem = sub.add_parser("memory", help=tr("shared memory: add, search, list, forget", "الذاكرة المشتركة: add, search, list, forget"))
    msub = mem.add_subparsers(dest="mem_cmd")
    ma = msub.add_parser("add")
    ma.add_argument("text", nargs="+")
    ma.add_argument("--tags", default="")
    ms = msub.add_parser("search")
    ms.add_argument("query", nargs="+")
    ml = msub.add_parser("list")
    ml.add_argument("-n", type=int, default=20)
    mf = msub.add_parser("forget")
    mf.add_argument("id", type=int)

    for name, helptext in (("install", tr("install components", "تثبيت المكونات")),
                           ("update", tr("update components", "تحديث المكونات"))):
        i = sub.add_parser(name, help=helptext)
        i.add_argument("components", nargs="*", help="all | node | claude | " + " | ".join(gateway_names))
        i.add_argument("--force", action="store_true", help=tr("reinstall even if present", "إعادة التثبيت حتى لو كان موجوداً"))
        i.add_argument("--latest", action="store_true", help=tr("use the newest published version", "استخدام أحدث إصدار منشور"))
        i.add_argument("--rebuild", action="store_true", help=tr("rebuild a source install after editing it",
                                                                 "إعادة بناء نسخة المصدر بعد تعديلها"))

    c = sub.add_parser("customize", help=tr("save/inspect your edits to a gateway's source", "حفظ/عرض تعديلاتك على كود البوابة"))
    c.add_argument("action", choices=["save", "status", "diff"])
    c.add_argument("name")

    sub.add_parser("doctor", help=tr("check the installation", "فحص التثبيت"))
    lg = sub.add_parser("lang", help="ar | en")
    lg.add_argument("code", choices=list(i18n.SUPPORTED))
    sub.add_parser("menu", help=tr("interactive menu (default)", "القائمة التفاعلية (الافتراضي)"))
    sub.add_parser("help")
    return p


# -------------------------------------------------------------- commands
def cmd_run(ctx: Context, a) -> int:
    gw = ctx.gateway(a.gateway)
    project = flows.resolve_project(ctx, a.project)
    flows.ensure_claude(ctx, False)
    started = flows.bring_up(ctx, gw, ui.interactive())
    resume = a.resume
    if resume and resume.isdigit():
        row = ctx.store().get_task(int(resume))
        resume = row["session_id"] if row and row["session_id"] else None
        if not resume:
            raise GatewayError(tr("Task {i} has no session to resume.", "المهمة {i} ليس لها جلسة للمتابعة.", i=a.resume))
    prompt = " ".join(a.prompt)
    store = ctx.store()
    task_id = store.add_task(prompt, gw.name, a.model or gw.default_model(), str(project), status="pending")
    try:
        res = flows.run_task(ctx, gw, task_id, prompt, a.model, project, resume=resume)
    finally:
        if started and not a.keep and not ctx.cfg.get("keep_gateway_running", False):
            gw.stop()
    _print_result(task_id, res)
    return 0 if not res.get("is_error") else 1


def _print_result(task_id: int, res: dict) -> None:
    print()
    print(res.get("result") or "")
    print()
    meta = [f"#{task_id}"]
    if res.get("session_id"):
        meta.append(f"session {res['session_id']}")
    if res.get("num_turns") is not None:
        meta.append(tr("{n} turns", "{n} دورة", n=res["num_turns"]))
    if res.get("duration_ms"):
        meta.append(f"{int(res['duration_ms']) / 1000:.1f}s")
    (ui.warn if res.get("is_error") else ui.ok)(" · ".join(meta))


def cmd_task(ctx: Context, a) -> int:
    store = ctx.store()
    if a.task_cmd == "add":
        gw = ctx.gateway(a.gateway)
        project = flows.resolve_project(ctx, a.project)
        tid = store.add_task(" ".join(a.prompt), gw.name, a.model or "", str(project))
        ui.ok(tr("Task #{i} queued for {t}. Run them with: allinone task work",
                 "أضيفت المهمة #{i} لـ {t}. نفّذ المهام بالأمر: allinone task work", i=tid, t=gw.title))
        return 0
    if a.task_cmd == "show":
        row = store.get_task(a.id)
        if not row:
            ui.error(tr("No task #{i}", "لا توجد مهمة #{i}", i=a.id))
            return 1
        for key in ("id", "status", "gateway", "model", "project", "session_id", "num_turns", "cost_usd"):
            ui.say(f"{key:>11}: {row[key] if row[key] is not None else ''}")
        ui.say(f"{'prompt':>11}: {row['prompt']}")
        print()
        print(row["result"] or "")
        return 0
    if a.task_cmd == "work":
        return _work(ctx, a.keep)
    rows = store.list_tasks(getattr(a, "n", 20))
    ui.table([[str(r["id"]), r["status"], r["gateway"] or "", time.strftime("%m-%d %H:%M", time.localtime(r["created"])),
               (r["prompt"] or "")[:70].replace("\n", " ")] for r in rows],
             headers=["#", tr("status", "الحالة"), tr("gateway", "البوابة"), tr("created", "أُنشئت"), tr("prompt", "الطلب")])
    return 0


def _work(ctx: Context, keep: bool) -> int:
    store = ctx.store()
    store.reset_stuck()
    started = {}
    failures = 0
    try:
        while True:
            row = store.next_pending()
            if not row:
                break
            try:
                gw = ctx.gateway(row["gateway"])
                project = flows.resolve_project(ctx, row["project"])
                if gw.name not in started:
                    flows.ensure_claude(ctx, False)
                    started[gw.name] = flows.bring_up(ctx, gw, False)
            except Exception as exc:  # record why this task cannot run, then go on with the next one
                store.fail_task(row["id"], str(exc))
                failures += 1
                ui.error(f"#{row['id']}: {exc}")
                continue
            try:
                res = flows.run_task(ctx, gw, row["id"], row["prompt"], row["model"] or None, project)
                _print_result(row["id"], res)
                failures += 1 if res.get("is_error") else 0
            except KeyboardInterrupt:
                raise
            except Exception as exc:  # run_task already marked the task failed
                failures += 1
                ui.error(f"#{row['id']}: {exc}")
    finally:
        if not keep and not ctx.cfg.get("keep_gateway_running", False):
            for name, was_started in started.items():
                if was_started:
                    ctx.gateway(name).stop()
    ui.ok(tr("Queue finished.", "اكتمل الطابور."))
    return 1 if failures else 0


def cmd_gateway(ctx: Context, a) -> int:
    if a.action == "status":
        rows = []
        for gw in ctx.gateways().values():
            st = gw.status()
            rows.append([gw.name, gw.title, ui.green(tr("running", "يعمل")) if st["up"] else tr("stopped", "متوقف"),
                         gw.base_url, (st["version"] or "") if st["installed"] else tr("not installed", "غير مثبت")])
        ui.table(rows, headers=[tr("name", "الاسم"), "", tr("state", "الحالة"), "URL", tr("version", "الإصدار")])
        return 0
    gw = ctx.gateway(a.name)
    if a.action == "start":
        flows.ensure_installed(ctx, gw, ui.interactive())
        state = gw.start()
        if state == "already":
            ui.ok(tr("{t} is already running at {u}", "{t} يعمل مسبقاً على {u}", t=gw.title, u=gw.base_url))
        for note in gw.dashboard_notes():
            ui.say("   " + note)
        ui.say(ui.dim(tr("Stop it with: allinone gateway stop {n}", "أوقفه بالأمر: allinone gateway stop {n}", n=gw.name)))
        return 0
    if a.action == "stop":
        if gw.stop():
            ui.ok(tr("{t} stopped", "تم إيقاف {t}", t=gw.title))
        elif gw.is_up():
            ui.warn(tr("{t} is running but was not started by Allinone; stop it where it was started.",
                       "{t} يعمل لكنه لم يُشغَّل من Allinone؛ أوقفه من حيث تم تشغيله.", t=gw.title))
        else:
            ui.say(tr("{t} is not running.", "{t} لا يعمل.", t=gw.title))
        return 0
    # logs
    lines = ui.tail_lines(gw.log_path, a.n)
    for line in lines:
        print(line)
    if a.follow:
        try:
            with open(gw.log_path, "r", encoding="utf-8", errors="replace") as fh:
                fh.seek(0, 2)
                while True:
                    line = fh.readline()
                    if line:
                        sys.stdout.write(line)
                        sys.stdout.flush()
                    else:
                        time.sleep(0.5)
        except (OSError, KeyboardInterrupt):
            pass
    return 0


def cmd_dashboard(ctx: Context, a) -> int:
    gw = ctx.gateway(a.name)
    flows.ensure_installed(ctx, gw, ui.interactive())
    gw.start()
    for note in gw.dashboard_notes():
        ui.say("   " + note)
    webbrowser.open(gw.dashboard_url())
    ui.ok(gw.dashboard_url())
    ui.say(ui.dim(tr("The gateway keeps running. Stop it with: allinone gateway stop {n}",
                     "البوابة تبقى تعمل. أوقفها بالأمر: allinone gateway stop {n}", n=gw.name)))
    return 0


def cmd_models(ctx: Context, a) -> int:
    gw = ctx.gateway(a.name)
    if not gw.is_up():
        ui.error(tr("{t} is not running. Start it with: allinone gateway start {n}",
                    "{t} لا يعمل. شغّله بالأمر: allinone gateway start {n}", t=gw.title, n=gw.name))
        return 1
    models = gw.models()
    if models is None:
        ui.error(tr("The gateway did not return a model list (it may need an API key: allinone key {n} <KEY>).",
                    "لم تُرجع البوابة قائمة النماذج (قد تحتاج مفتاحاً: allinone key {n} <KEY>).", n=gw.name))
        return 1
    for mid in models:
        print(mid)
    ui.say(ui.dim(tr("{n} models", "{n} نموذج", n=len(models))))
    return 0


def cmd_key(ctx: Context, a) -> int:
    try:
        gw = ctx.gateway(a.name)
        section, title = gw.name, gw.title
    except GatewayError:
        # Not a gateway: store it anyway, e.g. for {{secret:omniroute-manage.api_key}} in config/mcp.jsonc.
        if not (a.value or a.clear):
            raise
        gw, section, title = None, a.name, a.name
    if a.clear:
        ctx.secrets.set(section, "api_key", "")
        ui.ok(tr("Stored key removed.", "تم حذف المفتاح المحفوظ."))
        return 0
    if a.value:
        ctx.secrets.set(section, "api_key", a.value.strip())
        ui.ok(tr("Key saved for {t} (data/secrets.json).", "تم حفظ المفتاح لـ {t} (data/secrets.json).", t=title))
        return 0
    tok = gw.token()
    if not tok:
        ui.warn(tr("No key found for {t}.", "لا يوجد مفتاح لـ {t}.", t=gw.title))
        return 1
    ui.say(f"{gw.title}: {tok[:12]}…{tok[-4:]}" if len(tok) > 20 else f"{gw.title}: {tok}")
    return 0


def cmd_memory(ctx: Context, a) -> int:
    store = ctx.store()
    if a.mem_cmd == "add":
        mid = store.remember(" ".join(a.text), tags=a.tags, source="cli")
        ui.ok(tr("Saved as #{i}", "حُفظت برقم #{i}", i=mid))
        return 0
    if a.mem_cmd == "forget":
        ok = store.forget(a.id)
        (ui.ok if ok else ui.warn)(tr("Deleted.", "حُذفت.") if ok else tr("Not found.", "غير موجودة."))
        return 0 if ok else 1
    rows = store.search_memory(" ".join(a.query)) if a.mem_cmd == "search" else store.recent_memory(getattr(a, "n", 20))
    for r in rows:
        when = time.strftime("%Y-%m-%d", time.localtime(r["created"]))
        tags = f" [{r['tags']}]" if r["tags"] else ""
        ui.say(f"#{r['id']} {ui.dim(when)}{tags}  {r['text']}")
    if not rows:
        ui.say(tr("Nothing found.", "لا توجد نتائج."))
    return 0


def cmd_customize(ctx: Context, a) -> int:
    gw = ctx.gateway(a.name)
    dest = gw.install_dir
    if not sources.is_checkout(dest):
        ui.error(tr("{t} is not a source install. Set gateways.{n}.install.mode to \"source\" and run: "
                    "allinone install {n} --force",
                    "{t} ليس مثبتاً من المصدر. اضبط gateways.{n}.install.mode على \"source\" ثم نفّذ: "
                    "allinone install {n} --force", t=gw.title, n=gw.name))
        return 1
    if a.action == "save":
        path = sources.save_local(ctx.cfg.root, gw.name, dest)
        if path:
            ui.ok(tr("Your edits were saved to {p} — commit this file to keep them.",
                     "تم حفظ تعديلاتك في {p} — احفظ هذا الملف في git للاحتفاظ بها.", p=path))
        else:
            ui.say(tr("No edits to save.", "لا توجد تعديلات للحفظ."))
        return 0
    if a.action == "status":
        out = sources.git(["status", "--short"], dest).stdout.decode("utf-8", "replace")
        print(out or tr("No edits.", "لا توجد تعديلات."))
        unsaved = sources.has_unsaved_changes(ctx.cfg.root, gw.name, dest)
        (ui.warn if unsaved else ui.ok)(tr("Unsaved edits: run allinone customize save {n}",
                                           "تعديلات غير محفوظة: نفّذ allinone customize save {n}", n=gw.name)
                                        if unsaved else tr("Everything is saved.", "كل شيء محفوظ."))
        return 0
    print(sources.local_diff(dest))
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    ui.setup_streams()
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        ctx = Context(Config())
    except (OSError, ValueError) as exc:
        ui.error(f"config: {exc}")
        return 2
    init_language(ctx)
    gateway_names = list(ctx.gateways())

    # Everything after "--" is handed to Claude Code untouched.
    claude_args: List[str] = []
    if "--" in argv:
        cut = argv.index("--")
        argv, claude_args = argv[:cut], argv[cut + 1:]
    # Shortcut:  allinone omniroute [options] [-- claude args]  ==  allinone start omniroute ...
    if argv and argv[0].lower() in [g.lower() for g in gateway_names]:
        argv = ["start", *argv]
    parser = build_parser(gateway_names)
    a = parser.parse_args(argv)
    if claude_args and a.command not in ("start",):
        parser.error(tr("arguments after -- are only accepted by: start", "الوسائط بعد -- مقبولة فقط مع الأمر start"))

    try:
        if a.command in (None, "menu"):
            if not ui.interactive():
                parser.print_help()
                return 0
            from .menu import run_menu

            return run_menu(ctx)
        if a.command == "help":
            parser.print_help()
            return 0
        if a.command == "start":
            return flows.launch(ctx, a.gateway, a.project, a.model, claude_args, keep=a.keep,
                                interactive=ui.interactive()) or 0
        if a.command == "run":
            return cmd_run(ctx, a)
        if a.command == "task":
            return cmd_task(ctx, a)
        if a.command == "gateway":
            return cmd_gateway(ctx, a)
        if a.command == "dashboard":
            return cmd_dashboard(ctx, a)
        if a.command == "models":
            return cmd_models(ctx, a)
        if a.command == "key":
            return cmd_key(ctx, a)
        if a.command == "memory":
            return cmd_memory(ctx, a)
        if a.command in ("install", "update"):
            refresh = a.command == "update" and not a.rebuild
            return 0 if installer.install(ctx, a.components or ["all"], force=a.force, latest=a.latest,
                                          rebuild=a.rebuild, refresh=refresh) else 1
        if a.command == "customize":
            return cmd_customize(ctx, a)
        if a.command == "doctor":
            return 0 if installer.doctor(ctx) else 1
        if a.command == "lang":
            ctx.state.set("language", a.code)
            i18n.set_language(a.code)
            ui.ok(tr("Language set to English.", "تم ضبط اللغة على العربية."))
            return 0
    except KeyboardInterrupt:
        print()
        return 130
    except (GatewayError, ClaudeError, NodeError, CommandError, sources.SourceError) as exc:
        ui.error(str(exc))
        return 1
    parser.print_help()
    return 0
