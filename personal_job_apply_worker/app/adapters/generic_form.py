# -*- coding: utf-8 -*-
"""Schema-driven generic HTML form adapter (inspect + fill, never invent)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional

from app.adapters.base import AdapterResult, BaseApplyAdapter
from app.models import ApplicantFixture, StopReason

_SENSITIVE_RE = re.compile(
    r"passport|national\s*id|ssn|social security|bank account|iban|credit card|payment",
    re.I,
)


@dataclass
class FormFieldSchema:
    field_id: str
    name: str
    label: str
    field_type: str
    required: bool
    options: list[str] = field(default_factory=list)
    multi: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "field_id": self.field_id,
            "name": self.name,
            "label": self.label,
            "field_type": self.field_type,
            "required": self.required,
            "options": list(self.options),
            "multi": self.multi,
        }


INSPECT_JS = """() => {
  const fields = [];
  const seen = new Set();
  const labelFor = (el) => {
    if (el.id) {
      const lab = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
      if (lab) return (lab.innerText || '').trim();
    }
    const wrap = el.closest('label');
    if (wrap) return (wrap.innerText || '').trim().slice(0, 200);
    const aria = el.getAttribute('aria-label');
    if (aria) return aria.trim();
    const ph = el.getAttribute('placeholder');
    if (ph) return ph.trim();
    return (el.name || el.id || el.type || 'field').toString();
  };
  const push = (el, type, multi=false) => {
    const name = el.name || el.id || '';
    const key = type + ':' + name + ':' + (el.id || '');
    if (seen.has(key)) return;
    seen.add(key);
    const required = !!(el.required || el.getAttribute('aria-required') === 'true');
    let options = [];
    if (el.tagName === 'SELECT') {
      options = Array.from(el.options || []).map(o => (o.text || o.value || '').trim()).filter(Boolean);
    }
    fields.push({
      field_id: el.id || name || key,
      name: name,
      label: labelFor(el).slice(0, 240),
      field_type: type,
      required,
      options,
      multi,
    });
  };
  document.querySelectorAll('input, textarea, select').forEach(el => {
    if (el.type === 'hidden' || el.disabled) return;
    const t = (el.type || el.tagName || '').toLowerCase();
    if (['submit','button','image','reset'].includes(t)) return;
    if (t === 'file') return push(el, 'file');
    if (t === 'checkbox') return push(el, 'checkbox', true);
    if (t === 'radio') {
      const name = el.name || '';
      if (!name) return;
      const key = 'radio:' + name;
      if (seen.has(key)) return;
      seen.add(key);
      const radios = Array.from(document.querySelectorAll(`input[type=radio][name="${CSS.escape(name)}"]`));
      const required = radios.some(r => r.required || r.getAttribute('aria-required') === 'true');
      const options = radios.map(r => {
        const lab = r.labels && r.labels[0] ? (r.labels[0].innerText || '').trim() : (r.value || '');
        return lab || r.value || '';
      }).filter(Boolean);
      const groupLabel = labelFor(el).replace(/Yes|No/gi, '').trim() || name;
      fields.push({
        field_id: name,
        name,
        label: groupLabel.slice(0, 240) || name,
        field_type: 'radio',
        required,
        options,
        multi: false,
      });
      return;
    }
    if (el.tagName === 'SELECT') return push(el, el.multiple ? 'multiselect' : 'select', !!el.multiple);
    if (el.tagName === 'TEXTAREA') return push(el, 'textarea');
    if (['email','tel','number','date','url','text','password'].includes(t) || !t) {
      return push(el, t === 'password' ? 'password' : (t || 'text'));
    }
    push(el, t || 'text');
  });
  return fields;
}"""


class GenericFormAdapter(BaseApplyAdapter):
    """Fallback DOM adapter for employer-hosted / unsupported ATS HTML forms."""

    name = "generic_form"

    async def can_handle(self, page) -> bool:
        try:
            n = await page.locator("form input, form textarea, form select, input[type='email']").count()
            return n > 0
        except Exception:
            return False

    async def inspect_schema(self, page) -> list[FormFieldSchema]:
        raw = await page.evaluate(INSPECT_JS)
        out: list[FormFieldSchema] = []
        for item in raw or []:
            out.append(
                FormFieldSchema(
                    field_id=str(item.get("field_id") or ""),
                    name=str(item.get("name") or ""),
                    label=str(item.get("label") or ""),
                    field_type=str(item.get("field_type") or "text"),
                    required=bool(item.get("required")),
                    options=list(item.get("options") or []),
                    multi=bool(item.get("multi")),
                )
            )
        return out

    async def fill_draft(
        self,
        page,
        applicant: ApplicantFixture,
        cv_path: str,
        answers: Optional[dict[str, Any]] = None,
    ) -> AdapterResult:
        schema = await self.inspect_schema(page)
        if answers is None:
            from app.answer_mapper import map_schema_to_answers

            answers, _missing = map_schema_to_answers(
                [f.to_dict() for f in schema],
                applicant=applicant,
            )
        filled: list[str] = []
        missing_required: list[str] = []

        for field in schema:
            blob = f"{field.label} {field.name}".lower()
            if field.field_type == "password" or _SENSITIVE_RE.search(blob):
                if field.required:
                    return AdapterResult(
                        filled_fields=filled,
                        stop_reason=StopReason.sensitive_docs,
                        message=f"sensitive_required:{field.label}",
                        adapter_name=self.name,
                    )
                continue

            value = self._resolve_value(field, applicant, answers)
            if value is None or value == "":
                if field.required and field.field_type != "file":
                    missing_required.append(field.label or field.name)
                continue

            try:
                ok = await self._fill_one(page, field, value, cv_path)
                if ok:
                    filled.append(field.label or field.name or field.field_id)
                elif field.required:
                    missing_required.append(field.label or field.name)
            except Exception as exc:  # noqa: BLE001
                if field.required:
                    return AdapterResult(
                        filled_fields=filled,
                        stop_reason=StopReason.unknown_question,
                        message=f"fill_failed:{field.label}:{exc}",
                        adapter_name=self.name,
                    )

        if missing_required:
            return AdapterResult(
                filled_fields=filled,
                stop_reason=StopReason.unknown_question,
                message="missing_fact:" + ";".join(missing_required[:8]),
                adapter_name=self.name,
            )
        return AdapterResult(filled_fields=filled, adapter_name=self.name)

    def _resolve_value(
        self,
        field: FormFieldSchema,
        applicant: ApplicantFixture,
        answers: dict[str, Any],
    ) -> Any:
        # Explicit mapped answers first (from answer library / Dify)
        for key in (field.field_id, field.name, field.label):
            if key and key in answers:
                return answers[key]
        # Heuristic verified-only mapping from applicant fixture
        blob = f"{field.label} {field.name}".lower()
        ftype = field.field_type
        if ftype == "email" or "email" in blob:
            return applicant.email
        if ftype == "tel" or "phone" in blob or "mobile" in blob:
            return applicant.phone
        if ftype == "file" or "resume" in blob or "cv" in blob or "curriculum" in blob:
            return "__CV__"
        if "cover" in blob and "letter" in blob:
            return applicant.cover_letter
        if ftype in ("text", "textarea") and (
            "name" in blob or "full name" in blob or field.name in ("name", "full_name", "partner_name")
        ):
            return applicant.full_name
        # Leave unknown requireds for missing_fact
        return answers.get(field.label) or answers.get(field.name)

    async def _fill_one(self, page, field: FormFieldSchema, value: Any, cv_path: str) -> bool:
        loc = None
        if field.name:
            loc = page.locator(f"[name='{field.name}']").first
        if (not loc or await loc.count() == 0) and field.field_id:
            loc = page.locator(f"#{field.field_id}").first
        if not loc or await loc.count() == 0:
            return False

        ftype = field.field_type
        if ftype == "file":
            if value != "__CV__":
                return False
            await loc.set_input_files(cv_path)
            return True
        if ftype == "checkbox":
            want = str(value).lower() in ("1", "true", "yes", "on")
            checked = await loc.is_checked()
            if want != checked:
                await loc.click()
            return True
        if ftype == "radio":
            # try value match among radios with same name
            radios = page.locator(f"input[type='radio'][name='{field.name}']")
            n = await radios.count()
            for i in range(n):
                r = radios.nth(i)
                rv = (await r.get_attribute("value")) or ""
                label = await r.evaluate(
                    "el => (el.labels && el.labels[0] ? el.labels[0].innerText : el.value) || ''"
                )
                if str(value).lower() in (rv.lower(), (label or "").lower()):
                    await r.check()
                    return True
            return False
        if ftype in ("select", "multiselect"):
            try:
                await loc.select_option(label=str(value))
                return True
            except Exception:
                try:
                    await loc.select_option(value=str(value))
                    return True
                except Exception:
                    return False
        await loc.fill(str(value))
        # post-fill visible validation
        current = await loc.input_value()
        return (current or "").strip() == str(value).strip() or ftype == "textarea"
