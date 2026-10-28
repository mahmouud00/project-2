"""Permission codes and the built-in roles.

A user gets roles per branch (UserBranchRole). branch_id NULL = all branches.
"""
from __future__ import annotations

# module.action
PERMISSIONS: dict[str, str] = {
    "org.manage": "إدارة الشركة والفروع",
    "users.manage": "إدارة المستخدمين والصلاحيات",
    "library.read": "عرض مكتبة القطاعات",
    "library.manage": "تعديل قطاعات الشركة الخاصة والمعايرة",
    "library.delete": "حذف قطاعات وخامات ونماذج الشركة الخاصة",
    "library.import": "استيراد حزم تحديث المكتبة",
    "engine.calculate": "حساب المقاسات والتخصيمات",
    "customers.read": "عرض العملاء",
    "customers.create": "إضافة عملاء",
    "customers.write": "تعديل العملاء",
    "customers.delete": "حذف العملاء",
    "surveys.read": "عرض المعاينات",
    "surveys.create": "إضافة معاينات",
    "surveys.write": "تعديل المعاينات",
    "surveys.delete": "حذف المعاينات",
    "quotes.read": "عرض عروض الأسعار",
    "quotes.create": "إضافة عروض أسعار",
    "quotes.write": "تعديل عروض الأسعار",
    "quotes.delete": "حذف عروض الأسعار",
    "quotes.approve_price": "الموافقة على سعر أقل من السعر العادل (مدير المبيعات)",
    "workorders.read": "عرض أوامر التصنيع",
    "workorders.create": "إضافة أوامر تصنيع",
    "workorders.write": "تعديل أوامر التصنيع",
    "workorders.stage": "تغيير مرحلة أمر التصنيع",
    "workorders.delete": "حذف أوامر التصنيع",
    "sales.approve": "تأكيد البيعة (الحسابات) قبل ما أمر التصنيع يتوافق عليه ويدخل تصنيع",
    "invoices.create": "إضافة فواتير",
    "invoices.delete": "حذف الفواتير (المسودة) وإلغاء الصادرة",
    "purchasing.read": "عرض المشتريات",
    "purchasing.create": "إضافة موردين وأوامر شراء",
    "purchasing.write": "تعديل المشتريات",
    "purchasing.delete": "حذف الموردين وأوامر الشراء (المسودة)",
    "purchasing.approve": "تأكيد المشتريات (الحسابات) قبل ما تتطلب من المورد",
    "treasury.read": "عرض الخزينة",
    "treasury.create": "إضافة خزن وحركات خزينة",
    "treasury.write": "تعديل الخزينة والفواتير",
    "treasury.delete": "حذف الخزن وعكس حركات الخزينة",
    "finance.read": "عرض ربحية الشركة ورأس المال والأصول",
    "hr.read": "عرض الموظفين ومرتباتهم",
    "hr.create": "إضافة موظفين وحوافز وخصومات وسلف وإجازات",
    "hr.write": "تعديل بيانات الموظفين",
    "hr.delete": "حذف الموظفين والحركات اللي لسه ماتصرفتش",
    "hr.payroll": "عمل كشف المرتبات وصرفه من الخزينة",
    "maintenance.read": "عرض طلبات الصيانة",
    "maintenance.create": "إضافة طلبات صيانة",
    "maintenance.write": "تعديل طلبات الصيانة",
    "maintenance.delete": "حذف طلبات الصيانة",
    "field.read": "متابعة الفنيين: مهامهم ومكانهم على الخريطة",
    "field.manage": "توزيع مهام المعاينة والتركيب والصيانة على الفنيين",
    "field.delete": "حذف مهام الفنيين",
    "field.self": "فني: يشوف مهامه من الموبايل ويبعت مكانه وهو في المهمة",
    "notify.accounts": "إشعارات الحسابات: بيعة أو أمر شراء مستني تأكيد",
    "notify.sales": "إشعارات المبيعات: أي تحديث على العملاء وعروض الأسعار والتحصيل",
    "notify.production": "إشعارات التصنيع: بيعة اتأكدت وكل نقل مرحلة في أوامر التصنيع",
    "notify.field": "إشعارات التركيبات: مهام الفنيين وحالتها وطلبات الصيانة",
    "privacy.manage": "طلبات البيانات الشخصية (تصدير/مسح)",
    "audit.read": "عرض سجل التعديلات",
    "delete.permanent": "الحذف النهائي فورًا من غير ما يستنى ٣٠ يوم، والتراجع عن حذف أي حد",
    "system.manage": "النسخ الاحتياطي والتحديثات والأجهزة",
}

# Platform (vendor) only — granted to users of PLATFORM_COMPANY_ID.
PLATFORM_PERMISSIONS: dict[str, str] = {
    "platform.library.author": "تأليف المكتبة العامة ونشرها",
    "platform.companies.manage": "إدارة الشركات والاشتراكات",
}

_ALL = list(PERMISSIONS)

DEFAULT_ROLES: dict[str, dict] = {
    # the administrator manages technicians but is not one (field.self puts a user on the technicians map)
    "admin": {"name": "مدير", "permissions": [p for p in _ALL if p != "field.self"]},
    "sales": {"name": "مبيعات", "permissions": [
        "library.read", "engine.calculate", "customers.read", "customers.create", "customers.write", "surveys.read",
        "surveys.create", "surveys.write", "quotes.read", "quotes.create", "quotes.write", "workorders.read",
        "maintenance.read", "maintenance.create", "maintenance.write", "field.read"]},
    "production": {"name": "إنتاج", "permissions": [
        "library.read", "engine.calculate", "workorders.read", "workorders.create", "workorders.write",
        "workorders.stage", "surveys.read"]},
    "accounts": {"name": "حسابات", "permissions": [
        "customers.read", "quotes.read", "workorders.read", "purchasing.read", "purchasing.create", "purchasing.write",
        "treasury.read", "treasury.create", "treasury.write", "invoices.create", "purchasing.approve", "finance.read", "hr.read", "hr.payroll", "sales.approve",
        "notify.accounts"]},
    "sales_manager": {"name": "مدير مبيعات", "permissions": [
        "library.read", "engine.calculate", "customers.read", "customers.create", "customers.write", "surveys.read",
        "surveys.create", "surveys.write", "quotes.read", "quotes.create", "quotes.write", "quotes.approve_price",
        "workorders.read", "workorders.create", "invoices.create", "treasury.read", "maintenance.read", "maintenance.create",
        "maintenance.write", "field.read", "notify.sales"]},
    "production_manager": {"name": "مدير تصنيع", "permissions": [
        "library.read", "engine.calculate", "workorders.read", "workorders.create", "workorders.write",
        "workorders.stage", "surveys.read", "purchasing.read", "purchasing.create", "notify.production"]},
    "field_manager": {"name": "مدير تركيبات", "permissions": [
        "customers.read", "surveys.read", "workorders.read", "maintenance.read", "maintenance.create",
        "maintenance.write", "field.read", "field.manage", "notify.field"]},
    "hr": {"name": "موارد بشرية", "permissions": ["hr.read", "hr.create", "hr.write", "hr.delete"]},
    "technician": {"name": "فني", "permissions": ["field.self"]},
}
