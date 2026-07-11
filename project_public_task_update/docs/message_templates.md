# WhatsApp / Chatwoot message templates

Use `{odoo_public_link}` as placeholder — replace with the task's **Public Update URL**
from the task form (Public Update Link tab) after generating a token.

**URL pattern:** `https://test.drpaws.ai/task/update/<token>` (test) or your production Odoo domain.

**Link purpose:** Choose **Client update** or **Team planning** on the task form. The URL shape is the same; content differs.

---

## Client update — Full Arabic

```
برجاء استكمال بيانات الطلب من الرابط التالي:
{odoo_public_link}

لا تحتاج إلى حساب OpenProject.
الرابط مخصص لهذا الطلب فقط.
```

---

## Client update — Full English

```
Please complete the missing task details using this link:
{odoo_public_link}

No OpenProject login is required.
This link is only for this request.
```

---

## Client update — Short WhatsApp Arabic

```
من فضلك كمّل بيانات الطلب من هنا:
{odoo_public_link}
```

---

## Client update — Short WhatsApp English

```
Please complete the task details here:
{odoo_public_link}
```

---

## Team planning — Full Arabic

```
من فضلك راجع خطة تنفيذ التاسك وأضف أي بيانات ناقصة أو مهام فرعية مقترحة من الرابط:
{odoo_public_link}

لا تحتاج إلى حساب OpenProject.
الرابط مخصص لهذا التاسك فقط.
```

---

## Team planning — Full English

```
Please review the task implementation plan and add any missing details or suggested subtasks here:
{odoo_public_link}

No OpenProject login is required.
This link is only for this task.
```

---

## Notes

- Always send the **Odoo** link, never an OpenProject URL.
- Regenerate the link if it was disabled or expired.
- Regenerating or disabling the **parent** token controls access to the entire public page
  (including the read-only sub-task list).
- Internal users can use **WhatsApp AR/EN (client)** or **WhatsApp AR/EN (team)** buttons on the task form
  to preview the message with the link already filled in.
- **Team planning** links show implementation plan and missing-data questions; suggested subtasks are saved in chatter only (no auto task creation).

## Public sub-task list

- The public page shows a **read-only** list of **direct** children (`child_ids`) of the tokenized parent only.
- Displayed fields: task title, stage name, and open/done state (`is_closed`).
- Grandchildren, unrelated project tasks, assignees, descriptions, chatter, attachments,
  OpenProject IDs/URLs, and backend links are **not** exposed.
- Child titles are not clickable.
- If the parent has no children, an empty-state message is shown.
