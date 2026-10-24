# إصدار نسخة جديدة وتوصيلها للعملاء

## الترقيم
Semantic Versioning في ملف `VERSION`:
- **PATCH** (1.2.**3**): إصلاح أخطاء.
- **MINOR** (1.**3**.0): خصائص جديدة متوافقة.
- **MAJOR** (**2**.0.0): تغيير مش متوافق (مثلًا الأجهزة القديمة مش هتشتغل).

وأي تغيير يتكتب في `CHANGELOG.md` تحت الإصدار.

## قبل الإصدار
1. كل الاختبارات لازم تعدّي: `cd backend && python -m pytest`. ودي بتشتغل أوتوماتيك قبل كل commit (`git config core.hooksPath .githooks`) وعلى GitHub Actions مع كل push.
2. **أي تغيير في قاعدة البيانات = migration جديد** (`alembic revision --autogenerate -m "..."`)، وتراجعه بإيدك:
   - ممنوع حذف عمود أو جدول فيه بيانات، أو تغيير نوعه، في نفس الإصدار. اعملها على مرحلتين:
     - **(expand)** ضيف الجديد وانقل البيانات بخطوة صريحة في الـ migration.
     - **(contract)** شيل القديم في إصدار لاحق.
   - أي جدول جديد فيه `company_id` لازم يتفعّل عليه RLS في نفس الـ migration (`rls.enable(op, "table")`). الاختبار `test_every_tenant_table_has_rls` بيفشل لو نسيت.
   - `tests/test_migrations.py` بيتأكد إن البيانات القديمة ماتغيرتش بعد الترقية. ضيف بيانات للجداول الجديدة لو الـ migration بيلمسها.
3. لو الإصدار مش متوافق مع الأجهزة القديمة، ارفع `MIN_CLIENT_VERSION` في الإعدادات الافتراضية.

## بناء ملف التحديث
```bash
python tools/release/build_update.py --key ~/.mytech/vendor_private.pem --out dist/ \
    --min-from 1.0.0 --min-client 1.2.0 --notes "..."
```
- بيطلع `dist/mytech-<version>.mtu`: الكود + الـ migrations + المكتبات (Windows wheels) + manifest موقّع بمفتاحك.
- `--no-deps` لو المكتبات ماتغيرتش، والملف هيبقى أصغر.
- المفتاح الخاص لو عليه باسورد، حطه في المتغير `MYTECH_KEY_PASSWORD`.

## التطبيق عند العميل (أوفلاين)
```powershell
powershell -ExecutionPolicy Bypass -File C:\MYTech\update.ps1 -Package D:\mytech-1.3.0.mtu
```
الـ updater بيعمل الخطوات دي بالترتيب:
1. **يتحقق** من توقيع الملف وسلامة كل ملف فيه، وإن الإصدار أحدث من الحالي، وإن الحالي مش أقدم من `min_from_version`.
2. **نسخة احتياطية إجبارية** (`backups\..._pre-update-<version>.dump`). لو فشلت، التحديث مابيبدأش.
3. يوقف الخدمة، ويفك الإصدار الجديد في `app\<version>` (القديم بيفضل زي ما هو).
4. يشغّل الـ migrations **بالكود الجديد**.
5. يحوّل `current.json` للإصدار الجديد، ويشغّل الخدمة، ويتأكد إن `/system/info` بيرجّع الإصدار الجديد وإن `/system/health` سليم.
6. **لو أي خطوة فشلت:** يوقف الخدمة، ويسترجع النسخة الاحتياطية، ويرجّع `current.json` للإصدار القديم، ويشغّل الخدمة. كل ده بيتسجل في `logs\updates.log`.

الرجوع لإصدار قديم يدويًا: رجّع `current.json` للإصدار القديم واسترجع نسخة `pre-update` (شوف INSTALL.md).

## الأونلاين
نفس الأمر على السيرفر السحابي، ومرة واحدة بس لكل الشركات (`python -m app.ops.updater file.mtu --root /opt/mytech`)، مع service controller لـ systemd بدل Windows (شوف ONLINE.md).

## تحديثات المكتبة (القطاعات)
دي **منفصلة** عن تحديث البرنامج: انشر من حساب MYTech، وصدّر حزمة ووقّعها وابعتها. التفاصيل في `docs/LIBRARY.md` §8.

## المفاتيح
`python -m tools.vendor_admin keygen` بيعمل المفتاح الخاص (احتفظ بيه وخد منه نسخة؛ **عمره ما يدخل الريبو**) ويحط المفتاح العام في `backend/app/licensing/vendor_public_key.pem`. اعمل commit للمفتاح العام **قبل أول إصدار**. المفتاح العام اللي في الريبو دلوقتي **مفتاح تطوير**، والمفتاح الخاص بتاعه اتمسح.
