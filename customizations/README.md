# تعديلاتك على كود البوابات

```
customizations/
  freellmapi/patches/   ← تُطبَّق على runtime/freellmapi بعد كل تثبيت أو تحديث
  omniroute/patches/    ← تُطبَّق على runtime/omniroute (إن كان install.mode = "source")
```

## طريقة العمل

1. عدّل الملفات داخل `runtime/<gateway>/`.
2. `allinone install <gateway> --rebuild` لإعادة البناء والتجربة.
3. `allinone customize save <gateway>` لكتابة تعديلاتك في `patches/zz-local.patch`.
4. احفظ الملف في git بالأمرين `git add customizations && git commit`.

يمكنك وضع ملفات `.patch` إضافية (مثل `01-my-provider.patch`)، وتُطبَّق بالترتيب الأبجدي قبل `zz-local.patch`.

أوامر مفيدة:

- `allinone customize status <gateway>`: ما الذي تغيّر، وهل كل التعديلات محفوظة.
- `allinone customize diff <gateway>`: عرض التعديلات الحالية.

التفاصيل في [docs/CUSTOMIZE.md](../docs/CUSTOMIZE.md#6-تعديل-الكود-المصدري-للبوابات).
