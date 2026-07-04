# -*- coding: utf-8 -*-
"""Egyptian phone normalization shared by portal, lookup, and intake."""
import re


def normalize_eg_phone(value):
    """Return digits-only phone, preferring 20XXXXXXXXXX when possible."""
    if not value:
        return ''
    text = str(value).split('@', 1)[0]
    digits = re.sub(r'\D', '', text)
    if not digits:
        return ''
    if digits.startswith('01') and len(digits) == 11:
        return '20' + digits[1:]
    if digits.startswith('1') and len(digits) == 10:
        return '20' + digits
    if digits.startswith('20') and len(digits) >= 12:
        return digits
    return digits


def phone_match_variants(value):
    """Variants useful for partner search."""
    phone = normalize_eg_phone(value)
    if not phone:
        return set()
    variants = {phone}
    last10 = phone[-10:] if len(phone) >= 10 else phone
    variants.add(last10)
    if phone.startswith('20') and len(phone) > 2:
        variants.add('0' + phone[2:])
        variants.add(phone[2:])
    return {v for v in variants if v}


def phones_match(a, b):
    """True if two phone-like values refer to the same EG number."""
    na = normalize_eg_phone(a)
    nb = normalize_eg_phone(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    return na[-10:] == nb[-10:] and len(na) >= 10 and len(nb) >= 10


def normalize_pet_name(name):
    """Case-insensitive name key for pet matching."""
    if not name:
        return ''
    text = str(name).strip().lower()
    return re.sub(r'\s+', ' ', text)
