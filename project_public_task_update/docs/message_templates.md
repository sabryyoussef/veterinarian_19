# WhatsApp / Chatwoot message templates

Use `{odoo_public_link}` as placeholder — replace with the task's **Public Update URL**
from the task form (Public Update Link tab) after generating a token.

**URL pattern:** `https://test.drpaws.ai/task/update/<token>` (test) or your production Odoo domain.

---

## Full Arabic

```
برجاء استكمال بيانات الطلب من الرابط التالي:
{odoo_public_link}

لا تحتاج إلى حساب OpenProject.
الرابط مخصص لهذا الطلب فقط.
```

---

## Full English

```
Please complete the missing task details using this link:
{odoo_public_link}

No OpenProject login is required.
This link is only for this request.
```

---

## Short WhatsApp — Arabic

```
من فضلك كمّل بيانات الطلب من هنا:
{odoo_public_link}
```

---

## Short WhatsApp — English

```
Please complete the task details here:
{odoo_public_link}
```

---

## Notes

- Always send the **Odoo** link, never an OpenProject URL.
- Regenerate the link if it was disabled or expired.
- Internal users can use **WhatsApp AR** / **WhatsApp EN** buttons on the task form
  to preview the message with the link already filled in.
