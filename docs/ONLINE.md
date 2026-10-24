# تشغيل النسخة الأونلاين على سيرفر سحابي

الكود هو هو. الفرق كله في الإعدادات والنشر.

## الإعدادات
```
APP_MODE=online
DATABASE_URL / DATABASE_SYSTEM_URL / DATABASE_OWNER_URL   (سيرفر PostgreSQL 16 مُدار أو على نفس الجهاز)
JWT_SECRET=<64+ حرف عشوائي>
CORS_ORIGINS=["https://app.example.com"]
BACKUP_DIR=/var/backups/mytech
DISCOVERY_ENABLED=false
MEDIA_DIR=/var/lib/mytech/media      (أو storage مشترك لو فيه أكتر من سيرفر)
```
اللي بيتغير في الأونلاين أوتوماتيك:
- **الترخيص:** اشتراكات في قاعدة البيانات بدل ملف (`OnlineSubscriptionProvider`).
- **الدخول:** `company_code` بقى مطلوب.
- **المكتبة:** مشتركة بين كل الشركات وMYTech بس اللي بتحدّثها، والعملاء مايقدروش يستوردوا حزم.
- **النسخ الاحتياطي:** إدارته لـ MYTech بس، لأن الداتابيز فيها كل الشركات.
- **اكتشاف الشبكة:** مقفول.

## العزل بين الشركات
- **RLS في PostgreSQL** على كل الجداول، ويوزر الـ API (`mytech_app`) مش owner ومش BYPASSRLS. يعني حتى لو حصل غلط في الكود، الداتابيز نفسها بترفض ترجّع بيانات شركة تانية.
- `company_id` بييجي من التوكن بس.
- اختبارات `tests/test_isolation.py` و`test_business_flow.py` بتغطي ده.

## المطلوب للنشر (لسه مش معمول)
1. **سيرفر في مصر** (أو أقرب region)، Ubuntu 24.04، و4 vCPU / 8GB كبداية.
2. **PostgreSQL 16**:
   - `python -m app.cli init-db --admin-url ...` ثم `migrate`.
   - يفضل backup على storage خارجي (pg_dump يومي + WAL archiving لو محتاج point-in-time).
3. **الـ API**:
   - خدمة systemd بتشغّل `python -m app.server`، أو uvicorn بـ `--workers 4`.
   - كل الـ workers بيستقبلوا الأحداث اللحظية عن طريق PostgreSQL LISTEN/NOTIFY، ومفيش داعي لـ Redis.
   - الـ scheduler بيستخدم advisory lock، فالنسخة الاحتياطية بتتعمل مرة واحدة بس.
4. **Reverse proxy** (Caddy أو Nginx):
   - HTTPS إجباري بشهادة Let's Encrypt، و`X-Forwarded-*`.
   - دعم WebSocket على `/api/v1/system/events`.
   - حد أقصى لحجم الرفع 500MB (عشان حزم المكتبة).
   - rate limiting على `/api/v1/auth/*`.
5. **الشركات والاشتراكات** من أداة MYTech على السيرفر:
   ```
   python -m tools.vendor_admin create-company --code ACME --name "..." --admin admin
   python -m tools.vendor_admin set-subscription --company ACME --modules core,manufacturing,mfg.upvc --max-users 20 --max-branches 3 --max-devices 30 --expires 2027-12-31
   python -m tools.vendor_admin list-subscriptions
   ```
6. **المراقبة:** `/api/v1/system/health`، ومساحة الديسك، وآخر backup (`/api/v1/system/backups` بحساب MYTech).
7. **التحديثات:** نفس ملف `.mtu` و`app.ops.updater` مع `ServiceController` لـ systemd (`systemctl stop/start mytech`) بدل Windows. لسه محتاج سكريبت صغير.
8. **قانون حماية البيانات:**
   - استضافة البيانات في مصر، أو موافقة المركز لو برّه.
   - سياسة خصوصية للعملاء.
   - تعيين مسؤول حماية بيانات.
   - endpoints التصدير والمسح وسجل الوصول جاهزة.
