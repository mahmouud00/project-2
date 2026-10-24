# تسطيب سيرفر الأوفلاين وربط الأجهزة

## المطلوب
- **جهاز السيرفر:** Windows 10/11 أو Windows Server، رام 8GB أو أكتر، SSD، وIP ثابت على الشبكة الداخلية (يتظبط من الراوتر بـ DHCP reservation أو يدوي). يفضل يبقى عليه UPS.
- **PostgreSQL 16 for Windows** (من postgresql.org): وانت بتسطّبه احفظ باسورد `postgres`، وسيب الخدمة `postgresql-x64-16` تشتغل أوتوماتيك.
- **فولدر التسطيب من MYTech** (مثلًا `MYTech-0.1.0.zip`)، وجواه:
  `python\` (Python 3.12 embeddable) · `app\0.1.0\` (السيرفر + site-packages) · `service\` (`launcher.py` و`MYTechServer.xml` و`MYTechServer.exe` = WinSW) · `current.json` · `install.ps1` · `update.ps1`

## تجهيز فولدر التسطيب (عند MYTech، مرة لكل إصدار)
> مفيش سكريبت بيعمل الفولدر ده أوتوماتيك لسه، وماتجربش على ويندوز حقيقي. ده أول حاجة لازم تتعمل وتتجرب قبل أول تسطيب عند عميل.
1. `python\`: نزّل **Python 3.12 embeddable (Windows x86-64)** من python.org، وفي ملف `python312._pth` ضيف سطر `import site`.
2. `app\<version>\`: نفس محتوى الـ payload اللي `tools/release/build_update.py` بيعمله: `app\` و`migrations\` و`alembic.ini` و`VERSION` و`site-packages\`.
3. `service\`: انسخ `deploy\windows\launcher.py` و`MYTechServer.xml`، وحط WinSW-x64.exe (من github.com/winsw/winsw) باسم `MYTechServer.exe`.
4. `current.json`: `{"version": "<version>", "path": "app/<version>"}`.
5. `install.ps1` و`update.ps1` من `deploy\windows\`.

## الخطوات
1. فك الملف في `C:\MYTech`.
2. افتح PowerShell **كمسؤول (Run as Administrator)**:
   ```powershell
   cd C:\MYTech
   powershell -ExecutionPolicy Bypass -File install.ps1 -CompanyCode ACME -CompanyName "مصنع أكمي"
   ```
   السكريبت هيعمل الآتي:
   - يعمل `config\.env` بباسوردات عشوائية قوية لأدوار الداتابيز التلاتة وسر الـ JWT، ويقفل الملف على Administrators وSYSTEM بس.
   - يسألك عن باسورد `postgres`، ويعمل الأدوار والداتابيز `mytech`، ويطبق الـ migrations.
   - يعمل الشركة والفرع الرئيسي والمستخدم `admin`، ويسألك على باسورده (وهيتطلب تغييره أول دخول).
   - يسطّب خدمة **MYTechServer**: بتبدأ أوتوماتيك مع الجهاز وبعد PostgreSQL، وبتعيد التشغيل لوحدها لو وقعت.
   - يفتح الفايروول للشبكة الداخلية بس (Private/Domain): TCP 8000 للـ API وUDP 47800 للاكتشاف.
   - في الآخر يطبع **بصمة الجهاز**.
3. **الترخيص:**
   - ابعت البصمة لـ MYTech.
   - MYTech تصدر الملف:
     ```
     python -m tools.vendor_admin issue-license --company-code ACME --company-name "..." --fingerprint <البصمة> --modules core,manufacturing,mfg.upvc,mfg.shutter --max-devices 10 --expires 2027-12-31 --out acme.json
     ```
   - المدير يرفع الملف من الواجهة (`POST /api/v1/system/license`). قبل ما الترخيص يترفع، الدخول بيتمنع.
4. **المكتبة:** استورد حزمة المكتبة الموقّعة اللي MYTech بعتتها (`/library/packages/preview` ← `/apply`). التفاصيل في `docs/LIBRARY.md` §8.
5. **الإعدادات الأولى من حساب admin:**
   - إعدادات الشركة: الضريبة، والعربون، وسلاح المنشار، وأطراف العود، وأقل باقي يرجع المخزن.
   - الفروع، والمخازن، والخزن، وقوائم الأسعار.
   - المستخدمين وأدوارهم لكل فرع.
   - الأرصدة الافتتاحية للمخزن (`/inventory/adjustments`).

## HTTPS (اختياري في الأوفلاين)
حط مسار الشهادة والمفتاح في `config\.env`:
```
SSL_CERTFILE=C:\MYTech\config\server.crt
SSL_KEYFILE=C:\MYTech\config\server.key
```
وبعدين اعمل restart للخدمة. الشهادة ممكن تكون من CA داخلية، أو self-signed وتتسطّب في الأجهزة.

## ربط الأجهزة
- الأجهزة على نفس الشبكة (واي فاي أو كابل).
- **أوتوماتيك:** برنامج الجهاز بيبعت UDP broadcast على بورت 47800 (`MYTECH_DISCOVER`)، والسيرفر بيرد بعنوانه وبورته وإصداره. وكمان السيرفر بيعلن عن نفسه بـ mDNS باسم `_mytech._tcp.local`. للتجربة: `python tools/find_server.py`.
- **يدوي:** اكتب `http://<IP السيرفر>:8000`. ده الحل الوحيد لو الواجهة بتفتح من المتصفح، لأن المتصفح مايقدرش يعمل UDP ولا mDNS.
- كل جهاز بيتسجل أول ما يدخل وبيتعد في الترخيص. المدير يقدر يعطّل أي جهاز من `/devices`.
- **لو الشبكة قطعت:** الجهاز بيعيد الاتصال لوحده، وبيجدد التوكن بالـ refresh، وبيرجع يفتح قناة التحديث اللحظي. ولو جهاز فرعي اتقفل، مالوش أي تأثير على السيرفر ولا على باقي الأجهزة.

## النسخ الاحتياطي
- **أوتوماتيك:** كل يوم الساعة 2 بالليل في `C:\MYTech\backups`، ويحتفظ بآخر 14 نسخة. التغيير من `BACKUP_DIR` و`BACKUP_HOUR` و`BACKUP_KEEP`. يُفضّل يكون `BACKUP_DIR` على هارد تاني أو مسار شبكة.
- **نسخة فورية:** `POST /api/v1/system/backups`. وآخر حالة بتبان في `GET /api/v1/system/backups`.
- **الاسترجاع** (بيوقف الخدمة ويعمل نسخة من الوضع الحالي الأول):
  ```powershell
  C:\MYTech\service\MYTechServer.exe stop
  $env:PYTHONPATH="C:\MYTech\app\<الإصدار>;C:\MYTech\app\<الإصدار>\site-packages"; cd C:\MYTech\config
  C:\MYTech\python\python.exe -c "from app.ops.backup import restore; restore(r'C:\MYTech\backups\<الملف>.dump')"
  C:\MYTech\service\MYTechServer.exe start
  ```

## لو حاجة مش شغالة
- **اللوجات:** `C:\MYTech\logs` (خدمة WinSW)، و`logs\updates.log` للتحديثات. اللوجات مافيهاش أي بيانات شخصية.
- **السيرفر شغال؟** افتح `http://localhost:8000/api/v1/system/health`.
- **حالة الترخيص:** `GET /api/v1/system/license`.
