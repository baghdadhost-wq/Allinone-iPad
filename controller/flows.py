"""High-level flows shared by the command line and the interactive menu."""

from __future__ import annotations

import webbrowser
from pathlib import Path
from typing import List, Optional

from . import installer, ui
from .claude import ClaudeError
from .gateways import Gateway, GatewayError
from .i18n import tr


def resolve_project(ctx, project: Optional[str]) -> Path:
    raw = project or ctx.cfg.get("default_project") or ""
    path = ctx.cfg.abs_path(raw) if raw else Path.cwd()
    path = path.resolve()
    if not path.is_dir():
        raise GatewayError(tr("Project folder does not exist: {p}", "مجلد المشروع غير موجود: {p}", p=path))
    return path


def ensure_installed(ctx, gw: Gateway, interactive: bool) -> None:
    need_node = gw.install_mode() in ("npm", "source")
    if need_node and not ctx.node.node_path():
        if interactive and ui.confirm(tr("Node.js (needed by {t}) is not installed. Install it now?",
                                         "Node.js (يحتاجه {t}) غير مثبت. هل تريد تثبيته الآن؟", t=gw.title)):
            if not installer.install(ctx, ["node"]):
                raise GatewayError(tr("Node.js installation failed.", "فشل تثبيت Node.js."))
        else:
            raise GatewayError(tr("Node.js is missing. Run: allinone install", "Node.js غير موجود. نفّذ: allinone install"))
    if not gw.is_installed():
        if interactive and ui.confirm(tr("{t} is not installed yet. Install it now?",
                                         "{t} غير مثبت بعد. هل تريد تثبيته الآن؟", t=gw.title)):
            if not installer.install(ctx, [gw.name]):
                raise GatewayError(tr("Installation of {t} failed.", "فشل تثبيت {t}.", t=gw.title))
        else:
            raise GatewayError(tr("{t} is not installed. Run: allinone install {n}",
                                  "{t} غير مثبت. نفّذ: allinone install {n}", t=gw.title, n=gw.name))


def ensure_claude(ctx, interactive: bool) -> None:
    claude = ctx.claude()
    if claude.is_installed():
        return
    if interactive and ui.confirm(tr("Claude Code is not installed yet. Install it now?",
                                     "Claude Code غير مثبت بعد. هل تريد تثبيته الآن؟")):
        if installer.install(ctx, ["claude"]):
            return
    raise ClaudeError(tr("Claude Code is not installed. Run: allinone install claude",
                         "Claude Code غير مثبت. نفّذ: allinone install claude"))


def bring_up(ctx, gw: Gateway, interactive: bool) -> bool:
    """Make sure the gateway is installed, running and has a usable key. Returns True if we started it."""
    if gw.can_start() or gw.install_mode() != "none":
        if not gw.is_up():
            ensure_installed(ctx, gw, interactive)
    started = gw.start() == "started"
    try:
        if started:
            for note in gw.dashboard_notes():
                ui.say(ui.dim("   " + note))
        check_key(ctx, gw, interactive)
        check_providers(ctx, gw, interactive)
    except BaseException:
        # Do not leave behind a gateway we started if setup is abandoned (missing key, Ctrl+C...).
        if started and not ctx.cfg.get("keep_gateway_running", False):
            gw.stop()
        raise
    return started


def check_key(ctx, gw: Gateway, interactive: bool) -> None:
    if not gw.needs_token() or gw.token():
        return
    ui.warn(tr("{t} needs its API key, and it was not found yet.", "{t} يحتاج مفتاح API ولم يتم العثور عليه بعد.",
               t=gw.title))
    for note in gw.dashboard_notes():
        ui.say("   " + note)
    if not interactive:
        raise GatewayError(tr("Set it with:  allinone key {n} <KEY>", "اضبطه بالأمر:  allinone key {n} <KEY>", n=gw.name))
    if ui.confirm(tr("Open the {t} dashboard in your browser?", "هل تريد فتح لوحة تحكم {t} في المتصفح؟", t=gw.title)):
        webbrowser.open(gw.dashboard_url())
    key = ui.ask(tr("Paste the key here (Enter to retry automatic detection)",
                    "الصق المفتاح هنا (Enter لإعادة المحاولة تلقائياً)"))
    if key:
        ctx.secrets.set(gw.name, "api_key", key.strip())
    if not gw.token():
        raise GatewayError(tr("No key for {t}. Set it with:  allinone key {n} <KEY>",
                              "لا يوجد مفتاح لـ {t}. اضبطه بالأمر:  allinone key {n} <KEY>", t=gw.title, n=gw.name))


def check_providers(ctx, gw: Gateway, interactive: bool) -> None:
    models = gw.models()
    if models is None:
        return  # the gateway does not list models without extra auth; nothing to check
    useful = [m for m in models if not m.lower().startswith("auto")]
    if useful:
        return
    ui.warn(tr("{t} has no usable model yet — add at least one provider key in its dashboard.",
               "لا يوجد في {t} نموذج صالح بعد — أضف مفتاح مزوّد واحد على الأقل من لوحة التحكم.", t=gw.title))
    for note in gw.dashboard_notes():
        ui.say("   " + note)
    if interactive and ui.confirm(tr("Open the dashboard now?", "فتح لوحة التحكم الآن؟")):
        webbrowser.open(gw.dashboard_url())
        ui.ask(tr("Press Enter when you have added a provider", "اضغط Enter بعد إضافة مزوّد"))


def choose_model(gw: Gateway, preset: Optional[str]) -> Optional[str]:
    if preset is not None:
        return preset
    default = gw.default_model()
    if not ui.interactive():
        return None
    label = default or tr("gateway default", "افتراضي البوابة")
    while True:
        value = ui.ask(tr("Model (Enter = {d}, ? = list)", "النموذج (Enter = {d}، ? = عرض القائمة)", d=label))
        if value in ("", label):
            return None
        if value != "?":
            return value
        models = gw.models()
        if not models:
            ui.warn(tr("The gateway did not return a model list.", "لم تُرجع البوابة قائمة نماذج."))
            continue
        for i, m in enumerate(models[:60], 1):
            ui.say(f"  {i:>2}. {m}")
        if len(models) > 60:
            ui.say(ui.dim(tr("  … and {n} more (type the exact id)", "  … و{n} غيرها (اكتب المعرّف كاملاً)",
                             n=len(models) - 60)))
        pick = ui.ask(tr("Number or model id", "رقم أو معرّف النموذج"))
        if pick.isdigit() and 1 <= int(pick) <= min(60, len(models)):
            return models[int(pick) - 1]
        if pick:
            return pick


def banner(gw: Gateway, model: Optional[str], project: Path) -> None:
    shown = model or gw.default_model() or tr("gateway default", "افتراضي البوابة")
    ui.heading(tr("Claude Code ⇄ {t}", "Claude Code ⇄ {t}", t=gw.title))
    ui.say(f"  {tr('Gateway', 'البوابة')}:  {gw.base_url}")
    ui.say(f"  {tr('Model', 'النموذج')}:   {shown}")
    ui.say(f"  {tr('Project', 'المشروع')}: {project}")
    ui.say(ui.dim("  " + tr("Inside Claude Code: /allinone:remember, /allinone:recall, /allinone:gateway, /model",
                            "داخل Claude Code: ‎/allinone:remember و ‎/allinone:recall و ‎/allinone:gateway و ‎/model")))
    print()


def launch(ctx, gw_name: Optional[str], project: Optional[str], model: Optional[str],
           extra_args: List[str], keep: bool = False, interactive: bool = True) -> int:
    gw = ctx.gateway(gw_name)
    proj = resolve_project(ctx, project)
    ensure_claude(ctx, interactive)
    started = bring_up(ctx, gw, interactive)
    try:
        ctx.state.set("last_gateway", gw.name)
        chosen = choose_model(gw, model)
        banner(gw, chosen, proj)
        return ctx.claude().run_interactive(gw, chosen, proj, extra_args)
    finally:
        if started and not keep and not ctx.cfg.get("keep_gateway_running", False):
            ui.step(tr("Stopping {t}", "إيقاف {t}", t=gw.title))
            gw.stop()


def run_task(ctx, gw: Gateway, task_id: int, prompt: str, model: Optional[str], project: Path,
             resume: Optional[str] = None) -> dict:
    tcfg = ctx.cfg.get("tasks") or {}
    store = ctx.store()
    store.mark_running(task_id)
    ui.step(tr("Task #{i} → {t}", "المهمة #{i} ← {t}", i=task_id, t=gw.title))
    try:
        res = ctx.claude().run_headless(
            gw, model, project, prompt, resume=resume,
            permission_mode=tcfg.get("permission_mode") or None,
            allowed_tools=list(tcfg.get("allowed_tools") or []),
            max_turns=int(tcfg.get("max_turns") or 0),
            timeout=float(tcfg.get("timeout_seconds") or 0) or None)
    except KeyboardInterrupt:
        store.fail_task(task_id, "interrupted")
        raise
    except Exception as exc:  # keep the queue going, record why
        store.fail_task(task_id, str(exc))
        raise
    store.finish_task(task_id, res)
    return res
