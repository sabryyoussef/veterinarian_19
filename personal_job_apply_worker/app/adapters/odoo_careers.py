"""Odoo.com website recruitment apply form adapter (draft fill only)."""

from __future__ import annotations

from app.adapters.base import AdapterResult, BaseApplyAdapter
from app.models import ApplicantFixture


class OdooCareersAdapter(BaseApplyAdapter):
    name = "odoo_careers"

    async def can_handle(self, page) -> bool:
        form = page.locator("#hr_recruitment_form, form[action*='website/form']")
        name = page.locator("input[name='partner_name']")
        return (await form.count() > 0) and (await name.count() > 0)

    async def fill_draft(self, page, applicant: ApplicantFixture, cv_path: str) -> AdapterResult:
        """Fill Odoo careers fields. Never click Send/Apply. Never fill LinkedIn URL (resume path)."""
        filled: list[str] = []

        mapping = [
            ("input[name='partner_name']", applicant.full_name, "partner_name"),
            ("input[name='email_from']", applicant.email, "email_from"),
            ("input[name='partner_phone']", applicant.phone, "partner_phone"),
        ]
        for selector, value, label in mapping:
            if not value:
                continue
            loc = page.locator(selector)
            if await loc.count() == 0:
                continue
            await loc.first.fill(value)
            filled.append(label)

        # Resume path: set file input only; leave linkedin_profile empty.
        linkedin = page.locator("input[name='linkedin_profile']")
        if await linkedin.count() > 0:
            # Explicitly clear if anything present — resume-only path.
            try:
                await linkedin.first.fill("")
            except Exception:
                pass
            filled.append("linkedin_profile_left_empty")

        file_input = page.locator("input[type='file'][name='Resume'], input[type='file']#recruitment6")
        if await file_input.count() > 0 and cv_path:
            await file_input.first.set_input_files(cv_path)
            filled.append("Resume")

        if applicant.cover_letter:
            intro = page.locator("textarea[name='short_introduction']")
            if await intro.count() > 0:
                # Keep intro generic / non-salary unless required (it is optional).
                await intro.first.fill(applicant.cover_letter[:500])
                filled.append("short_introduction")

        return AdapterResult(
            filled_fields=filled,
            message="odoo_careers draft filled (dry-run; submit not clicked; LinkedIn left empty)",
            adapter_name=self.name,
        )
