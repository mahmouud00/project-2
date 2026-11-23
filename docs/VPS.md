# رفع السيرفر على VPS (أونلاين، شركات كتير)

الملفات في `deploy/vps`: `install.sh` (التسطيب)، `update.sh` (التحديث)، `manage.sh` (الشركات والاشتراكات)،
و`docker-compose.yml` (PostgreSQL + السيرفر + Caddy بيعمل HTTPS لوحده).

## ١. الـVPS
- نظام التشغيل: **Ubuntu 24.04** (OS نضيف، من غير لوحة تحكم). على الأقل 2 vCPU و4GB رام.
- احفظ **IP** السيرفر و**باسورد root**، وماتبعتهمش لحد.

## ٢. الدومين
في لوحة الدومين (هوستنجر ← Domains ← DNS): سجل **A**، الاسم `app`، القيمة = IP الـVPS.
الموقع الرئيسي للشركة بيفضل على الدومين نفسه، والبرنامج على `app.<الدومين>`.

## ٣. التسطيب
من الكمبيوتر: `ssh root@<IP>` (أو Terminal الـVPS في هوستنجر)، وبعدين:
```bash
curl -fsSL https://raw.githubusercontent.com/mahmouud00/project-2/claude/youthful-maxwell-n6mca9/deploy/vps/install.sh -o install.sh
bash install.sh
```
بيسأل عن الدومين (`app.<الدومين>`) والإيميل، وبعدين اسم وكلمة سر حساب MYTech.
الأسرار بتتكتب في `/opt/mytech/deploy/vps/.env`: خد منه نسخة واحفظها في مكان آمن.

## ٤. الشركات
```bash
cd /opt/mytech/deploy/vps
bash manage.sh create-company --code WINTAG --name "وينتاج" --admin admin
bash manage.sh set-subscription --company WINTAG --modules core,manufacturing,mfg.upvc --max-users 20 --max-branches 3 --max-devices 30 --expires 2027-12-31
```
الدخول من البرنامج: السيرفر `https://app.<الدومين>` + كود الشركة + المستخدم.
نقل داتا المصنع لشركة على السيرفر ده: شوف `docs/MOVE.md`.

## ٥. التحديث
`bash /opt/mytech/deploy/vps/update.sh` (بياخد نسخة احتياطية الأول).
