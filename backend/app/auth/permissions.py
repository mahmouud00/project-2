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
    "library.import": "استيراد حزم تحديث المكتبة",
    "engine.calculate": "حساب المقاسات والتخصيمات",
    "customers.read": "عرض العملاء",
    "customers.write": "تعديل العملاء",
    "surveys.read": "عرض المعاينات",
    "surveys.write": "تعديل المعاينات",
    "quotes.read": "عرض عروض الأسعار",
    "quotes.write": "تعديل عروض الأسعار",
    "pricelists.manage": "إدارة قوائم الأسعار",
    "workorders.read": "عرض أوامر التصنيع",
    "workorders.write": "تعديل أوامر التصنيع",
    "workorders.stage": "تغيير مرحلة أمر التصنيع",
    "inventory.read": "عرض المخزن",
    "inventory.write": "حركات المخزن والتحويلات",
    "purchasing.read": "عرض المشتريات",
    "purchasing.write": "تعديل المشتريات",
    "treasury.read": "عرض الخزينة",
    "treasury.write": "حركات الخزينة",
    "privacy.manage": "طلبات البيانات الشخصية (تصدير/مسح)",
    "audit.read": "عرض سجل التعديلات",
    "system.manage": "النسخ الاحتياطي والتحديثات والأجهزة",
}

# Platform (vendor) only — granted to users of PLATFORM_COMPANY_ID.
PLATFORM_PERMISSIONS: dict[str, str] = {
    "platform.library.author": "تأليف المكتبة العامة ونشرها",
    "platform.companies.manage": "إدارة الشركات والاشتراكات",
}

_ALL = list(PERMISSIONS)

DEFAULT_ROLES: dict[str, dict] = {
    "admin": {"name": "مدير", "permissions": _ALL},
    "sales": {"name": "مبيعات", "permissions": [
        "library.read", "engine.calculate", "customers.read", "customers.write", "surveys.read", "surveys.write",
        "quotes.read", "quotes.write", "workorders.read", "inventory.read"]},
    "production": {"name": "إنتاج", "permissions": [
        "library.read", "engine.calculate", "workorders.read", "workorders.write", "workorders.stage",
        "inventory.read", "surveys.read"]},
    "warehouse": {"name": "مخازن", "permissions": [
        "library.read", "inventory.read", "inventory.write", "purchasing.read", "workorders.read"]},
    "accounts": {"name": "حسابات", "permissions": [
        "customers.read", "quotes.read", "workorders.read", "purchasing.read", "purchasing.write",
        "treasury.read", "treasury.write", "pricelists.manage"]},
}
