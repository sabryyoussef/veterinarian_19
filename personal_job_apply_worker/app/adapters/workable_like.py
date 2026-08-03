"""Workable-like offline fixture adapter (draft fill only)."""

from __future__ import annotations

from app.adapters.base import AdapterResult, BaseApplyAdapter
from app.models import ApplicantFixture


class WorkableLikeAdapter(BaseApplyAdapter):
    name = "workable_like"

    async def can_handle(self, page) -> bool:
        marker = page.locator("[data-adapter='workable_like'], #workable-like-form")
        return await marker.count() > 0

    async def fill_draft(self, page, applicant: ApplicantFixture, cv_path: str) -> AdapterResult:
        filled: list[str] = []
        mapping = [
            ("input[name='firstname'], #firstname", applicant.full_name.split()[0], "firstname"),
            (
                "input[name='lastname'], #lastname",
                applicant.full_name.split()[-1] if " " in applicant.full_name else "Example",
                "lastname",
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
            message="workable_like draft filled (dry-run; submit not clicked)",
            adapter_name=self.name,
        )
