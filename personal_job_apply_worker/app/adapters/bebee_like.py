"""BeBee-like offline fixture adapter (draft fill only)."""

from __future__ import annotations

from app.adapters.base import AdapterResult, BaseApplyAdapter
from app.models import ApplicantFixture


class BebeeLikeAdapter(BaseApplyAdapter):
    name = "bebee_like"

    async def can_handle(self, page) -> bool:
        marker = page.locator("[data-adapter='bebee_like'], #bebee-like-form")
        return await marker.count() > 0

    async def fill_draft(self, page, applicant: ApplicantFixture, cv_path: str) -> AdapterResult:
        filled: list[str] = []
        mapping = [
            ("input[name='full_name'], #full_name", applicant.full_name, "full_name"),
            ("input[name='email'], #email", applicant.email, "email"),
            ("textarea[name='cover_letter'], #cover_letter", applicant.cover_letter, "cover_letter"),
        ]
        for selector, value, label in mapping:
            loc = page.locator(selector)
            if await loc.count() == 0:
                continue
            await loc.first.fill(value)
            filled.append(label)

        file_input = page.locator("input[type='file'][name='cv'], #cv")
        if await file_input.count() > 0:
            await file_input.first.set_input_files(cv_path)
            filled.append("cv")

        return AdapterResult(
            filled_fields=filled,
            message="bebee_like draft filled (dry-run; submit not clicked)",
            adapter_name=self.name,
        )
