# حل المشاكل

ابدأ دائماً بالأمر:

```bash
allinone doctor
```

يفحص هذا الأمر Python وGit وNode.js والبوابتين وClaude Code، ويقترح الحل لكل عنصر فيه ✘.

## الأمر `python` يفتح متجر Microsoft (Windows)

هذا اختصار وهمي من Windows. ثبّت Python من python.org أو عبر `install.cmd`، ثم عطّل الاختصار من: Settings → Apps → Advanced app settings → App execution aliases.

## فشل تنزيل Node.js

قد يحدث ذلك خلف جدار حماية أو proxy.

1. ثبّت Node.js 24 يدوياً من [nodejs.org](https://nodejs.org) (اختر إصدار 24، لا الأحدث).
2. في `config/local.jsonc` اكتب:

```jsonc
{ "node": { "mode": "system" } }
```

> الإصدارات المقبولة هي 22.22.2+ أو 24.x فقط. الإصدار 26 (أحدث LTS) لا يدعمه FreeLLMAPI.

## فشل `npm install` أثناء تثبيت بوابة

- **السبب الأشهر**: مكتبة `better-sqlite3`، وهي تحتاج ملفاً مبنياً مسبقاً يُنزَّل من GitHub. تأكد أن الاتصال بـ GitHub متاح.
- **على Windows**: إن احتاجت المكتبة البناء محلياً، ثبّت Visual Studio Build Tools مع خيار «Desktop development with C++».
- **أعد المحاولة**: `allinone install freellmapi --force`

## البوابة لا تبدأ

```bash
allinone gateway logs omniroute      # آخر سطور السجل
allinone gateway logs omniroute -f   # متابعة مباشرة
```

- **رسالة «المنفذ مستخدم»**: برنامج آخر يستخدم المنفذ. غيّر `port` في الإعدادات، أو أوقف البرنامج الآخر.
- **OmniRoute بطيء في أول تشغيل**: هذا طبيعي، والمهلة 240 ثانية. لتغييرها عدّل `start_timeout`.

## Claude Code يطلب تسجيل الدخول

معنى ذلك أن مفتاح البوابة لم يصل إليه.

- **FreeLLMAPI**: نفّذ `allinone key freellmapi` لترى هل وُجد المفتاح. إن لم يوجد، انسخه من صفحة Keys في لوحة التحكم ثم احفظه:

```bash
allinone key freellmapi freellmapi-xxxxxxxx
```

- **OmniRoute**: إن فعّلت `REQUIRE_API_KEY`، احفظ مفتاحاً من Dashboard → API Keys بالأمر `allinone key omniroute <KEY>`.

## أخطاء 400 من البوابة

### `Extra inputs are not permitted` أو حقول غير معروفة

أضف إلى `config/allinone.jsonc`:

```jsonc
"claude": { "env": { "CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS": "1" } }
```

### خطأ حدّ السياق (context / token limit)

النموذج المختار سياقه أصغر من 200K. ضع في `claude.env` الخاص بالبوابة قيمة أصغر من سياق النموذج، مثل:

```
CLAUDE_CODE_AUTO_COMPACT_WINDOW=100000
```

## النموذج لا يستخدم الأدوات جيداً

يعدّل الملفات بشكل خاطئ، أو يكرر نفسه، أو يتوقف. هذا شائع مع النماذج الصغيرة والمجانية.

- اختر نموذجاً أقوى في استدعاء الأدوات (tool calling).
- أو ضع النموذج القوي في `model`، والرخيص في `haiku_model` فقط.

## النص العربي يظهر مقلوباً في الطرفية

هذا قصور في بعض الطرفيات، مثل Windows Terminal وطرفية VS Code، لأنها لا تدعم الكتابة من اليمين لليسار. يمكنك:

- استخدام واجهة إنجليزية: `allinone lang en`
- أو الاكتفاء بالعربية في محادثتك مع Claude فقط.

## البدء من جديد

| ما تريد إعادة ضبطه | ماذا تحذف |
|---|---|
| البرامج المثبتة | المجلد `runtime/`، ثم `allinone install` |
| البيانات (مفاتيح المزودين، الذاكرة، المهام، كلمات المرور) | المجلد `data/` |

> لا تحذف `data/secrets.json` وحده، لأن مفاتيح FreeLLMAPI المحفوظة مشفرة بمفتاح موجود فيه.
