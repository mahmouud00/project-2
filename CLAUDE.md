# CLAUDE.md — MYTech Solutions

## وصف المشروع
سيستم لإدارة مصانع الشبابيك والأبواب (UPVC، شاتر، ألومنيوم)، بيتباع تحت اسم **MYTech Solutions**.
المرحلة الحالية: **Backend بس** (مفيش Frontend ولا موبايل). الـ API لازم يفضل صالح لتطبيق موبايل بعدين من غير تعديل.

كود واحد بوضعين حسب `APP_MODE`:
- `offline`: شركة واحدة، جهاز سيرفر في المصنع (PostgreSQL + API كـ Windows Service)، الأجهزة على الشبكة الداخلية، من غير إنترنت.
- `online`: سيرفر سحابي واحد لشركات كتير بفروع، عزل كامل بين الشركات.

**ممنوع** أي "offline sync" (تخزين محلي يزامن بعدين). مش مطلوب.

## الحالة
شوف `docs/PROGRESS.md`. **مهم:** القطاعات والتخصيمات مش متكتوبة من ملف الإكسيل؛ صاحب المشروع بيدخّلها بنفسه في "المكتبة"
(سيستم ← ثوابت ← خامات بألوانها ← نماذج بصورها وتعريف كامل: متغيرات، معادلات، قطع لكل خامة بمعادلة طولها وعددها وزواياها،
زجاج، إكسسوار، تحقق، رسمة ← اختبارات مرجعية ← نشر). النشر بيعمل نسخة مجمّدة، وهي اللي الحسابات بتستخدمها.

## المستندات
- `docs/BOM_ANALYSIS.md` — تحليل `data/bom.xlsx` + كل المعادلات + التناقضات والأسئلة المفتوحة.
- `docs/ARCHITECTURE.md` — تصميم الداتابيز والـ API والوضعين.
- `docs/PROGRESS.md` — اللي خلص واللي فاضل (يتحدث بعد كل مرحلة).
- `docs/LIBRARY.md` — إزاي MYTech بتضيف القطاعات والخامات والنماذج والتخصيمات وتنشرها وتوصّلها.
- `docs/API.md` · `docs/INSTALL.md` · `docs/UPDATE.md` · `docs/ONLINE.md` · `CHANGELOG.md`.

## التقنيات
Python 3.12 · FastAPI · SQLAlchemy 2.0 + psycopg 3 · Alembic · PostgreSQL 16 (مع Row-Level Security) · Pydantic v2 · Argon2id · JWT (PyJWT) · Ed25519 (`cryptography`) · pytest · LibreOffice headless (لتوليد القيم المرجعية من الإكسيل) · WinSW (خدمة ويندوز، اقتراح).

## هيكل الفولدرات (المخطط)
```
backend/app/{core,db,tenancy,auth,licensing,modules/*}   # الـ API والمنطق
backend/migrations/                                      # Alembic
backend/tests/ (golden/ للاختبارات المرجعية)
tools/{vendor_admin,bom_import,updater,backup,golden_gen}
deploy/windows/
data/bom.xlsx                                            # ملف القطاعات المرجعي (ماتعدلوش)
docs/
```

## التشغيل والاختبارات
```
python -m venv .venv && .venv/bin/pip install -e "backend[dev]"
cp .env.example backend/.env                       # وعدّل القيم (الأسرار)
cd backend
python -m app.cli init-db --admin-url postgresql+psycopg://postgres:***@localhost/postgres   # الأدوار والداتابيز
python -m app.cli migrate                          # alembic upgrade head
python -m app.cli create-platform-admin --username vendor        # حساب MYTech لتأليف المكتبة
python -m app.cli create-company --code ACME --name "..."        # شركة عميل
uvicorn app.main:app --port 8000                   # التوثيق: /api/docs
python -m pytest                                   # لازم كله يعدّي (بيعمل داتابيز mytech_test بأدوار mytech_test_*)
```
الاختبارات محتاجة PostgreSQL شغالة و`pg_dump`/`pg_restore` و`TEST_ADMIN_URL` (افتراضي `postgresql+psycopg://postgres:postgres@localhost:5432/postgres`).
فعّل الـ hook مرة واحدة: `git config core.hooksPath .githooks` (بيشغّل كل الاختبارات قبل أي commit). وGitHub Actions بيشغّلها مع كل push.

## خريطة الكود
- `app/core` إعدادات، أخطاء، لوجات بتحجب البيانات الشخصية، audit + optimistic locking
- `app/db` Base/mixins، الجلسات (app بـ RLS / system بـ BYPASSRLS)، RLS DDL
- `app/tenancy/context.py` سياق الطلب (الشركة، المستخدم، الصلاحيات لكل فرع)، بوابة الترخيص
- `app/auth` الدخول/التوكنز/الصلاحيات · `app/licensing` الترخيص بالوضعين + التوقيع Ed25519
- `app/engine` لغة المعادلات (`expr.py`) والحساب (`compute.py`) — عام، مفيهوش أي تخصيم
- `app/modules/library` المكتبة، النشر، الحساب، الحزم · `app/modules/org` · `app/modules/system`
- `app/modules/{crm,sales,production,inventory,purchasing,treasury,privacy}` النواة الإدارية
- `app/engine/cutting.py` تحسين التقطيع · `app/modules/production/manufacturing.py` مخرجات التصنيع
- `app/ops` النسخ الاحتياطي، الأحداث اللحظية، الاكتشاف، الجدولة، التحديثات (`updater.py`)
- `deploy/windows` خدمة ويندوز وسكريبتات التسطيب والتحديث · `tools/release` بناء ملفات التحديث
- `migrations/versions` — كل migration بيفعّل RLS على جداوله الجديدة (`rls.enable`)
- `tools/vendor_admin` أداة MYTech: مفاتيح، تراخيص، اشتراكات، توقيع الحزم

## قواعد ممنوع تتكسر
1. **ممنوع أي معادلة أو ثابت تخصيم جوه الكود.** كل المعادلات والثوابت بيانات في الداتابيز. الكود فيه الـ parser والـ evaluator والقواعد العامة بس.
2. **ممنوع `eval` / `exec`** أو أي تقييم لنص من المستخدم. المعادلات بتتقيّم بالـ parser الخاص بس.
3. **كل جدول بيانات فيه `company_id`**، وكل استعلام معزول على مستوى الشركة (فلتر في الكود + RLS في PostgreSQL). `company_id` بييجي من التوكن، عمره ما ييجي من body أو query الطلب. مكتبة القطاعات العامة ملك "شركة النظام" `PLATFORM_COMPANY_ID`.
4. **لازم كل الاختبارات تعدّي قبل أي commit**، وخصوصًا الاختبارات المرجعية للتخصيمات (`tests/golden`). أي فرق أكبر من 0.1 مم = فشل.
5. **أي تغيير في الداتابيز = migration بـ Alembic يحافظ على البيانات القديمة.** ممنوع حذف أو تغيير نوع عمود فيه بيانات من غير خطوة نقل صريحة ومختبرة. كل migration ليه اختبار upgrade على بيانات.
6. **أي حاجة مش واضحة في التخصيمات أو منطق التصنيع: اسأل ومتخمنش.** الغلط في التخصيمات أخطر حاجة في السيستم. سجّل السؤال في `docs/BOM_ANALYSIS.md` §5.
7. الحسابات بـ `Decimal`، والأطوال في الداتابيز بالمليمتر. ممنوع `float` في التخصيمات أو الفلوس.
8. كل سجل فيه `version` (optimistic locking). التعديل بنسخة قديمة = `409 Conflict`، عمره ما يمسح تعديل حد تاني.
9. أوامر الشغل بتتسجل بنسخة المعادلات (`formula_set_version_id`) والمعايرة اللي اتحسبت بيها، والأوامر القديمة ماتتغيرش لما المعادلات تتحدث.
10. تعديلات الشركة ومعايرتها منفصلة عن صفوف المكتبة، وتحديث المكتبة عمره ما يمسحها أو يغيرها.
11. **ممنوع تطبع بيانات شخصية** (أسماء، تليفونات، عناوين، رقم قومي) أو توكنز أو باسوردات في اللوجات. أي وصول لبيانات شخصية يتسجل في `pii_access_log`.
12. الأسرار في `.env` بس. `.env` عمره ما يترفع على GitHub (موجود في `.gitignore`)، وأي إعداد جديد يتضاف لـ `.env.example`.
13. المفتاح الخاص بتوقيع التراخيص والحزم عمره ما يدخل الريبو.
14. الفرق بين الأوفلاين والأونلاين يفضل ورا واجهات (`LicenseProvider`، مصدر المكتبة). باقي الكود مايسألش "أنا في أنهي وضع".
15. أي جدول جديد فيه `company_id` لازم يتفعّل عليه RLS في نفس الـ migration (`rls.enable(op, table)` أو `rls.enable(op, table, "library")`).
16. الحركات المالية والمخزنية مابتتعدلش ولا بتتمسح؛ التصحيح بحركة عكسية.
17. بعد كل مرحلة: commit واضح + تحديث `docs/PROGRESS.md` + `CHANGELOG.md`. وحدّث الملف ده كل ما حاجة أساسية تتغير.

## مصطلحات
فتحة (opening) · حلق (frame) · ضلفة (sash) · باكتة (glazing bead) · بار/برور (frame extension) · قاطوع (mullion) · سقاس · طبة وسكينة (interlock) · بندة/بانل (panel) · سلك (insect screen) · بليسيه (pleated screen) · شفاط (exhaust fan opening) · خلوص التركيب (installation clearance) · سماحية اللحام (weld allowance) · بوكس/خد/طمبورة/شريحة/علاقة/حباسة (shutter box/end cap/tube/slat/hanger/stopper).
