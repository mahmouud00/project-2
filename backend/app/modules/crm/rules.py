"""What a customer record must have (every company):

- the full name: three names at least;
- a mobile number (Egyptian, 11 digits) and a WhatsApp number;
- the governorate (the rest of the address is optional);
- how the customer reached us, how the conversation started, and at least two questions the customer asked;
- the national ID is optional here, but a quotation cannot be accepted without it (sales/router.py).

A new customer needs all of it; an edit checks every field it sends (the program sends them all, so an old customer
is completed the first time it is edited).
"""
from __future__ import annotations

import re

from app.core.errors import ValidationFailed

GOVERNORATES = (
    "القاهرة", "الجيزة", "الإسكندرية", "القليوبية", "الشرقية", "الدقهلية", "الغربية", "المنوفية", "البحيرة",
    "كفر الشيخ", "دمياط", "بورسعيد", "الإسماعيلية", "السويس", "الفيوم", "بني سويف", "المنيا", "أسيوط", "سوهاج",
    "قنا", "الأقصر", "أسوان", "البحر الأحمر", "الوادي الجديد", "مطروح", "شمال سيناء", "جنوب سيناء",
)
CONTACT_METHODS = ("مكالمة", "واتساب", "فيسبوك", "زيارة المعرض", "ترشيح من عميل", "أخرى")
MIN_QUESTIONS = 2

_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
_MOBILE = re.compile(r"^01[0125]\d{8}$")


def _digits(value: str) -> str:
    """'+20 100-123 4567' / '٠١٠٠١٢٣٤٥٦٧' -> '01001234567' (Egypt); other countries keep their + and digits."""
    v = re.sub(r"[\s\-().]", "", value.translate(_DIGITS))
    if v.startswith("00"):
        v = "+" + v[2:]
    if v.startswith("+20"):
        v = "0" + v[3:]
    return v


def mobile(value: str) -> str | None:
    v = _digits(value)
    return v if _MOBILE.match(v) else None


def whatsapp(value: str) -> str | None:
    v = _digits(value)
    if _MOBILE.match(v):
        return v
    return v if re.fullmatch(r"\+\d{8,15}", v) else None


def national_id(value: str) -> str | None:
    v = _digits(value)
    return v if re.fullmatch(r"[23]\d{13}", v) else None


def questions(text: str) -> list[str]:
    return [q.strip(" -•*.") for q in (text or "").splitlines() if q.strip(" -•*.")]


def check(data: dict, *, new: bool) -> dict:
    """Validate (and tidy) the customer fields in `data`; for a new customer every required field must be there.
    Returns the tidied values; raises CUSTOMER_INCOMPLETE naming every problem."""
    problems: dict[str, str] = {}

    def given(key: str) -> bool:
        return key in data if not new else True

    def blank(key: str) -> bool:
        v = data.get(key)
        return v is None or not str(v).strip()

    if given("name"):
        if len((data.get("name") or "").split()) < 3:
            problems["name"] = "الاسم لازم يبقى ثلاثي"
        else:
            data["name"] = " ".join(data["name"].split())
    if given("phone"):
        if blank("phone"):
            problems["phone"] = "رقم الموبايل إجباري"
        elif (m := mobile(data["phone"])) is None:
            problems["phone"] = "رقم الموبايل لازم يبقى 11 رقم ويبدأ بـ 010 أو 011 أو 012 أو 015"
        else:
            data["phone"] = m
    if given("whatsapp"):
        if blank("whatsapp"):
            problems["whatsapp"] = "رقم الواتساب إجباري"
        elif (w := whatsapp(data["whatsapp"])) is None:
            problems["whatsapp"] = "رقم الواتساب غلط"
        else:
            data["whatsapp"] = w
    if given("governorate"):
        if data.get("governorate") not in GOVERNORATES:
            problems["governorate"] = "اختار المحافظة"
    if given("contact_method"):
        if data.get("contact_method") not in CONTACT_METHODS:
            problems["contact_method"] = "اختار طريقة التواصل"
    if given("first_contact"):
        if blank("first_contact"):
            problems["first_contact"] = "اكتب بداية الكلام مع العميل"
        else:
            data["first_contact"] = data["first_contact"].strip()
    if given("customer_questions"):
        qs = questions(data.get("customer_questions") or "")
        if len(qs) < MIN_QUESTIONS:
            problems["customer_questions"] = f"اكتب {MIN_QUESTIONS} أسئلة على الأقل سألها العميل (كل سؤال في سطر)"
        else:
            data["customer_questions"] = "\n".join(qs)
    if data.get("national_id") not in (None, ""):
        if (n := national_id(data["national_id"])) is None:
            problems["national_id"] = "الرقم القومي لازم يبقى 14 رقم"
        else:
            data["national_id"] = n
    elif "national_id" in data:
        data["national_id"] = None
    if problems:
        raise ValidationFailed("بيانات العميل ناقصة: " + "، ".join(problems.values()),
                               code="CUSTOMER_INCOMPLETE", details=problems)
    return data
