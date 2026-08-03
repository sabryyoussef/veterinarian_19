"""Greenhouse-like offline fixture adapter (draft fill only)."""

from __future__ import annotations

from app.adapters.base import AdapterResult, BaseApplyAdapter
from app.models import ApplicantFixture


class GreenhouseLikeAdapter(BaseApplyAdapter):
    name = "greenhouse_like"

    async def can_handle(self, page) -> bool:
        marker = page.locator("[data-adapter='greenhouse_like'], #greenhouse-like-form")
        return await marker.count() > 0

    async def fill_draft(self, page, applicant: ApplicantFixture, cv_path: str) -> AdapterResult:
        filled: list[str] = []
        mapping = [
            ("input[name='first_name'], #first_name", applicant.full_name.split()[0], "first_name"),
            (
                "input[name='last_name'], #last_name",
                applicant.full_name.split()[-1] if " " in applicant.full_name else "Example",
                "last_name",
            ),
            ("input[name='email'], #email", applicant.email, "email"),
            ("input[name='phone'], #phone", applicant.phone, "phone"),
            ("textarea[name='cover_letter'], #cover_letter", applicant.cover_letter, "cover_letter"),
        ]
        for selector, value, label in mapping:
            loc = page.locator(selector)
            if await loc.count() == 0:
                continue
            await loc.first.fill(value)
            filled.append(label)

        file_input = page.locator("input[type='file'][name='resume'], #resume")
        if await file_input.count() > 0:
            await file_input.first.set_input_files(cv_path)
            filled.append("resume")

        return AdapterResult(
            filled_fields=filled,
            message="greenhouse_like draft filled (dry-run; submit not clicked)",
            adapter_name=self.name,
        )
