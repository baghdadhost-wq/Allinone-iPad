# دليل التخصيص

كل شيء في Allinone قابل للتعديل. هذا الدليل يشرح أين يكون كل نوع من التعديلات، مع أمثلة جاهزة.

> **قاعدة عامة:**
> - الملفات في `config/` و`claude/` و`customizations/` ملفاتك أنت، ومحفوظة في git.
> - المجلدان `runtime/` و`data/` يديرهما البرنامج، ولا يُرفعان إلى git.

---

## 1. النماذج

### نموذج افتراضي لكل بوابة

في `config/allinone.jsonc`:

```jsonc
"omniroute": {
  "claude": {
    "model": "auto",                 // OmniRoute يختار
    "haiku_model": "glm/glm-4.7-flash",  // نموذج سريع ورخيص للمهام الخلفية
    "subagent_model": "kimi/kimi-k2.6"   // الوكلاء الفرعيون
  }
}
```

- `model`: النموذج الرئيسي لـ Claude Code (`ANTHROPIC_MODEL`).
- `opus_model` و`sonnet_model` و`haiku_model`: النموذج الذي يُستخدم لكل فئة يطلبها Claude Code. إن تُركت فارغة تأخذ قيمة `model` (لأن `tiers_follow_model` مفعّل).
- إن تركت `model` فارغاً، ستقرر البوابة نفسها. في FreeLLMAPI يحدث ذلك من **Keys → Anthropic**، حيث تربط عائلات Claude بنماذج مجانية.

### نموذج عند التشغيل فقط

```bash
allinone start omniroute -m deepseek/deepseek-v4-flash
```

أو اكتبه عند سؤال «النموذج»، أو غيّره داخل Claude Code بالأمر `/model <id>`.

اعرض النماذج المتاحة بالأمر `allinone models omniroute`.

### إظهار نماذج غير Claude في قائمة `/model`

- **OmniRoute**: ضع `EXPOSE_CC_DISCOVERY_ALIASES=true` في `config/gateways/omniroute.env`.
- **FreeLLMAPI**: يعرض نماذجه تلقائياً.

---

## 2. أدوات Python جديدة لـ Claude Code

أنشئ ملفاً في `claude/mcp/tools/`، مثلاً `claude/mcp/tools/my_tools.py`:

```python
from mcp_kit import tool

@tool
def iraqi_dinar_to_usd(amount: float, rate: float = 1310.0) -> str:
    """تحويل مبلغ من الدينار العراقي إلى الدولار بسعر صرف معيّن."""
    return f"{amount / rate:.2f} USD"

@tool
def count_lines(path: str) -> int:
    """عدد أسطر ملف نصي."""
    with open(path, encoding="utf-8") as f:
        return sum(1 for _ in f)
```

أعد تشغيل Claude Code، وستظهر الأداتان باسم `mcp__allinone__iraqi_dinar_to_usd` و`mcp__allinone__count_lines`. يقرأ Claude نص الـ docstring ليعرف متى يستخدم كل أداة. التفاصيل في [`claude/mcp/tools/README.md`](../claude/mcp/tools/README.md).

الأدوات المدمجة، مثل الذاكرة و`ask_model` ومعلومات البوابة، موجودة في `claude/mcp/allinone_tools.py`، ويمكنك تعديلها أيضاً.

---

## 3. خوادم MCP إضافية (ومنها أدوات البوابتين)

الملف `config/mcp.jsonc` بصيغة `.mcp.json` نفسها في Claude Code، مع ثلاثة مفاتيح إضافية: `enabled` و`only_with_gateway` و`description`.

### أدوات FreeLLMAPI داخل Claude Code

تشمل الأدوات حالة المزودين والاستهلاك واستراتيجية التوجيه وغيرها.

1. فعّل MCP من لوحة تحكم FreeLLMAPI، من **Keys → Agent compatibility**.
2. في `config/mcp.jsonc` اجعل `"enabled": true` في الخادم `freellmapi`.

### أدوات OmniRoute داخل Claude Code

أكثر من 100 أداة لإدارة المزودين والـ combos والذاكرة وغيرها.

1. من لوحة تحكم OmniRoute فعّل MCP في `/dashboard/mcp` بنقل `streamable-http`.
2. أنشئ API Key بصلاحية **Management** من Dashboard → API Keys.
3. احفظه بالأمر `allinone key omniroute-manage <KEY>`.
4. اجعل `"enabled": true` في الخادم `omniroute`.

### أي خادم آخر

```jsonc
"github": {
  "type": "http",
  "url": "https://api.githubcopilot.com/mcp/",
  "headers": { "Authorization": "Bearer {{env:GITHUB_TOKEN}}" }
},
"sqlite": {
  "command": "npx",
  "args": ["-y", "mcp-server-sqlite", "--db-path", "{{project}}/app.db"]
}
```

المتغيرات المتاحة:
`{{python}}` `{{root}}` `{{data}}` `{{db}}` `{{project}}` `{{gateway}}` `{{gateway_url}}` `{{gateway_token}}` `{{model}}` `{{secret:قسم.مفتاح}}` `{{env:اسم}}`

---

## 4. Skills وأوامر ووكلاء (Plugins)

يحمّل Allinone كل مجلد داخل `claude/plugins/` يحتوي `.claude-plugin/plugin.json`.

### Skill جديد في plugin الموجود

أنشئ الملف `claude/plugins/allinone/skills/translate/SKILL.md`:

```markdown
---
name: translate
description: ترجمة ملف أو نص إلى العربية مع الحفاظ على المصطلحات التقنية.
argument-hint: <ملف أو نص>
---
ترجم ما يلي إلى العربية الفصحى، واترك أسماء الدوال والأوامر كما هي:

$ARGUMENTS
```

داخل Claude Code يصبح الأمر: `/allinone:translate README.md`

### وكيل جديد (subagent)

أنشئ `claude/plugins/allinone/agents/tester.md` بالبنية نفسها الموجودة في `reviewer.md` (الحقول `name` و`description` و`tools` و`model`).

### plugin مستقل

انسخ المجلد `claude/plugins/allinone` إلى `claude/plugins/mytools`، وغيّر `name` في `plugin.json`. سيُحمَّل تلقائياً، وأوامره تبدأ بـ `/mytools:`.

يمكن أيضاً تحميل plugins من مكان آخر بإضافتها إلى `"extra_plugin_dirs"` في `config/allinone.jsonc`.

---

## 5. Hooks والصلاحيات وإعدادات Claude Code

الملف `claude/settings.json` هو ملف إعدادات Claude Code العادي، ويُمرَّر بالخيار `--settings` في كل جلسة. يمكنك استخدام `{{python}}` و`{{root}}` و`{{project}}` داخله.

### مثال: تنسيق ملفات Python تلقائياً بعد كل تعديل

السكربت `format_python.py` في هذا المثال تكتبه أنت، ويقرأ من stdin بيانات الأداة التي استُخدمت.

```json
"PostToolUse": [
  {
    "matcher": "Write|Edit",
    "hooks": [
      { "type": "command", "command": "{{python}}", "args": ["{{root}}/claude/hooks/format_python.py"] }
    ]
  }
]
```

> استخدم دائماً الصيغة `command` + `args`، أي exec form. هكذا يعمل الـ hook على Windows وmacOS وLinux دون مشاكل في علامات الاقتباس.

### مثال: السماح بأوامر معيّنة دون سؤال

```json
"permissions": {
  "allow": ["mcp__allinone", "Bash(npm test *)", "Bash(git status)"]
}
```

### تعليمات بداية الجلسة

حرّر `claude/context.md`. يُرسل نصه إلى Claude في بداية كل جلسة، ومعه آخر 5 ملاحظات من الذاكرة. لتغيير عدد الملاحظات اضبط `ALLINONE_CONTEXT_NOTES` في `claude.env`.

### إعدادات Claude Code المستقلة

مع `"isolated_config": true` (الافتراضي)، يحفظ Claude Code داخل Allinone سجله وإعداداته في `data/claude-home`، فلا يتداخل مع Claude Code الذي تستخدمه بحسابك العادي.

---

## 6. تعديل الكود المصدري للبوابات

### FreeLLMAPI

FreeLLMAPI مثبت من المصدر دائماً.

1. عدّل ما تريد داخل `runtime/freellmapi/`، مثل إضافة مزوّد في `server/src/providers/`.
2. أعد البناء: `allinone install freellmapi --rebuild`
3. جرّب: `allinone freellmapi`
4. احفظ تعديلاتك: `allinone customize save freellmapi`
   - تُكتب في `customizations/freellmapi/patches/zz-local.patch`، فاحفظ هذا الملف في git.

- **بعد التحديث**: عند `allinone update freellmapi` يُنزَّل الكود من جديد، ثم تُطبَّق تعديلاتك تلقائياً.
- **عند التعارض**: إن غيّرت النسخة الأصلية الأسطر نفسها، يخبرك البرنامج بمكانها لتحلها ثم تحفظ من جديد.
- **حماية التعديلات**: لن يحذف التحديث تعديلات غير محفوظة. يطلب منك حفظها أولاً، أو تمرير `--force`.
- **ملفات تعديل إضافية**: يمكنك وضع ملفات `.patch` أخرى في `customizations/freellmapi/patches/`، وتُطبَّق بالترتيب الأبجدي قبل `zz-local.patch`.

### OmniRoute

OmniRoute مثبت افتراضياً من npm، وهي حزمة جاهزة. لتعديل الكود:

```jsonc
"omniroute": {
  "install": { "mode": "source", "ref": "v3.8.54" }
}
```

ثم نفّذ `allinone install omniroute --force`. بعد ذلك تعمل خطوات FreeLLMAPI نفسها: `customize save` ثم `--rebuild`.

> تنبيه: OmniRoute مشروع ضخم (حوالي 1 GB من الكود والتوثيق)، وبناؤه يحتاج ذاكرة 8 GB أو أكثر.

### استخدام نسختك المنسوخة (fork)

بدلاً من ملفات patch، يمكنك أن تعمل fork للبوابة على GitHub وتضع رابطه في `install.repo`، مع الفرع المناسب في `install.ref`.

### بدون تعديل الكود

أغلب التخصيص لا يحتاج تعديل الكود أصلاً:

- **OmniRoute**: مزودون مخصصون (OpenAI-compatible) من الواجهة، وcombos، واستراتيجيات توجيه، وضغط السياق.
- **FreeLLMAPI**: مزودون مخصصون، وسلاسل fallback، وضغط السياق، وإعدادات تعريفية عبر `FREEAPI_CONFIG_PATH`.
- **خيارات الإطلاق** لكل منهما في `config/gateways/<name>.env`.

---

## 7. إضافة بوابة ثالثة

أي خادم يتكلم Anthropic Messages API (`/v1/messages`) يمكن إضافته في `config/allinone.jsonc`.

**بوابة على جهاز آخر أو خدمة سحابية:**

```jsonc
"office-gateway": {
  "type": "custom",
  "title": "Office Gateway",
  "base_url": "http://192.168.1.50:20128",
  "claude": { "model": "auto" }
}
```

احفظ مفتاحها بالأمر `allinone key office-gateway <KEY>`.

**بوابة يشغّلها Allinone بنفسه**، مثل LiteLLM:

```jsonc
"litellm": {
  "type": "custom",
  "title": "LiteLLM",
  "port": 4000,
  "health_path": "/health/liveliness",
  "start": {
    "command": ["litellm", "--config", "{{root}}/config/litellm.yaml", "--port", "{{port}}"],
    "cwd": "{{data}}"
  },
  "claude": { "model": "my-model" }
}
```

ستظهر في القائمة كخيار ثالث تلقائياً.

---

## 8. المنافذ والشبكة

- **تغيير المنفذ**: عدّل `port` في `config/allinone.jsonc`.
- **الاستماع على الشبكة المحلية**: غيّر `host` إلى `0.0.0.0`.
  > تحذير: بذلك يستطيع أي جهاز في الشبكة استخدام حصصك. فعّل `REQUIRE_API_KEY=true` في OmniRoute قبل ذلك.

---

## 9. الإعدادات الشخصية

أنشئ `config/local.jsonc` بالبنية نفسها التي يستخدمها `allinone.jsonc`، واكتب فيه ما تريد تغييره فقط. يُدمج فوق الإعدادات الأصلية، وهو مستثنى من git. مثال:

```jsonc
{
  "language": "ar",
  "default_project": "D:/projects/shop",
  "keep_gateway_running": true
}
```
