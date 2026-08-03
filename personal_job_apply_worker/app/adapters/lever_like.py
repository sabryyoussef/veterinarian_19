"""Lever-like offline fixture adapter (draft fill only)."""

from __future__ import annotations

from app.adapters.base import AdapterResult, BaseApplyAdapter
from app.models import ApplicantFixture


class LeverLikeAdapter(BaseApplyAdapter):
    name = "lever_like"

    async def can_handle(self, page) -> bool:
        marker = page.locator("[data-adapter='lever_like'], #lever-like-form")
        return await marker.count() > 0

    async def fill_draft(self, page, applicant: ApplicantFixture, cv_path: str) -> AdapterResult:
        filled: list[str] = []
        mapping = [
            ("input[name='name'], #name", applicant.full_name, "full_name"),
            ("input[name='email'], #email", applicant.email, "email"),
            ("input[name='phone'], #phone", applicant.phone, "phone"),
            ("textarea[name='comments'], #comments", applicant.cover_letter, "comments"),
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
            message="lever_like draft filled (dry-run; submit not clicked)",
            adapter_name=self.name,
        )
