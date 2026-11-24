"""A customer the API accepts (every required field filled); a test overrides what it is about."""


def cust(name: str = "أحمد محمد علي", **over) -> dict:
    return {"name": name, "phone": "01012345678", "whatsapp": "01012345678", "governorate": "القاهرة",
            "contact_method": "مكالمة", "first_contact": "سأل عن سعر شباك",
            "customer_questions": "سعر المتر كام؟\nالتركيب بياخد قد إيه؟", **over}
