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
    "pricelists.create": "إضافة قوائم أسعار",
    "pricelists.manage": "تعديل قوائم الأسعار",
    "pricelists.delete": "حذف قوائم الأسعار",
    "workorders.read": "عرض أوامر التصنيع",
    "workorders.create": "إضافة أوامر تصنيع",
    "workorders.write": "تعديل أوامر التصنيع",
    "workorders.stage": "تغيير مرحلة أمر التصنيع",
    "workorders.delete": "حذف أوامر التصنيع",
    "invoices.create": "إضافة فواتير",
    "invoices.delete": "حذف الفواتير (المسودة) وإلغاء الصادرة",
    "inventory.read": "عرض المخزن",
    "inventory.create": "إضافة مخازن وحركات وتحويلات",
    "inventory.write": "تعديل حركات المخزن والتحويلات",
    "inventory.delete": "حذف المخازن والتحويلات (اللي لسه ماتبعتتش)",
    "purchasing.read": "عرض المشتريات",
    "purchasing.create": "إضافة موردين وأوامر شراء",
    "purchasing.write": "تعديل المشتريات",
    "purchasing.delete": "حذف الموردين وأوامر الشراء (المسودة)",
    "treasury.read": "عرض الخزينة",
    "treasury.create": "إضافة خزن وحركات خزينة",
    "treasury.write": "تعديل الخزينة والفواتير",
    "treasury.delete": "حذف الخزن وعكس حركات الخزينة",
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
        "library.read", "engine.calculate", "customers.read", "customers.create", "customers.write", "surveys.read",
        "surveys.create", "surveys.write", "quotes.read", "quotes.create", "quotes.write", "workorders.read",
        "inventory.read"]},
    "production": {"name": "إنتاج", "permissions": [
        "library.read", "engine.calculate", "workorders.read", "workorders.create", "workorders.write",
        "workorders.stage", "inventory.read", "surveys.read"]},
    "warehouse": {"name": "مخازن", "permissions": [
        "library.read", "inventory.read", "inventory.create", "inventory.write", "purchasing.read", "workorders.read"]},
    "accounts": {"name": "حسابات", "permissions": [
        "customers.read", "quotes.read", "workorders.read", "purchasing.read", "purchasing.create", "purchasing.write",
        "treasury.read", "treasury.create", "treasury.write", "invoices.create", "pricelists.create",
        "pricelists.manage"]},
}
