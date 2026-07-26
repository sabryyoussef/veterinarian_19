# Test implementation — approval package

**Date:** 2026-07-24  
**Status:** Test complete — **awaiting Sabry approval** before any Production / external / publish steps  
**Dev Hub:** Work Item `#3343` (uuid `65b7b88e-52a9-49be-bca0-303a0f962910`) · Analysis `#2697`

## What was done (Test only)

| Item | Status |
|------|--------|
| Canonical NAP cleanup | Done on Test source + live Test site |
| Placeholder US `555` phone removed | Verified absent on key pages |
| Official `website_blog` installed | Blog **PetSpot Pet Care Guide** |
| Landing + 6 service pages | Live on `test.drpaws.ai` |
| VeterinaryCare / LocalBusiness JSON-LD | Present on home, services, contact |
| 8 bilingual articles | **Unpublished** drafts |
| 12 Social Marketing posts | **Draft** on Test (no FB account → cannot publish) |
| External correction pack | Prepared; shop KG `/g/11w2b6j71t` flagged |
| SEO / regression UAT | **Pass** (`implementation_report.json`) |
| `/contactus` 500 | **Fixed** (restored `contactus_form_values` for `website_crm`) |
| Evidence on WI `#3343` / Analysis `#2697` | Attached |

## Canonical NAP (locked)

- **GBP:** Pet Spot Clinic · KG `/g/11w2cv6pz0`
- **Do not use:** `(pet spot (shop` · `/g/11w2b6j71t` (pack only)
- **Coords:** 30.9909989, 28.6840834
- **AR:** الساحل الشمالي، بجوار واحة خطاب، أمام أمواج 2، العلمين، مصر
- **EN:** North Coast, beside Wahat Khattab, in front of Amwaj 2, El Alamein, Egypt
- **Directions:** https://maps.app.goo.gl/AaHup6NEFodZEs7S7
- **Phones:** primary 01280833332 · call-center 01201568888 · WA 01000059085 · 24/7

## Test URLs to review

- https://test.drpaws.ai/
- https://test.drpaws.ai/contactus
- https://test.drpaws.ai/emergency-vet-north-coast
- https://test.drpaws.ai/veterinary-clinic-near-amwaj
- https://test.drpaws.ai/veterinary-home-visits-sahel
- https://test.drpaws.ai/pet-vaccinations-north-coast
- https://test.drpaws.ai/grooming-boarding-sahel
- https://test.drpaws.ai/contact-directions-booking
- https://test.drpaws.ai/blog (articles remain unpublished)

## Evidence paths

`docs/seo_ai_visibility/2026-07-24_read_only_audit/`

- `CANONICAL_NAP.md`
- `EXTERNAL_PROFILE_CORRECTION_PACK.md`
- `SOCIAL_CALENDAR_DRAFTS.md`
- `test_uat_evidence/UAT_SUMMARY.md`
- `test_uat_evidence/implementation_report.json`
- HTML snapshots under `test_uat_evidence/page_*.html`

**GBP screenshot binary:** not present in chat uploads; text evidence recorded on Analysis `#2697`. Please attach PNG under `evidence/` when available.

## Explicitly NOT done (need your approval)

1. Production deploy (`drpaws.ai` / `:8027`)
2. Cloudflare / DNS (www→apex, force HTTPS)
3. Any Google / FB / directory / Bing / Apple listing edits
4. Publishing the 8 articles
5. Scheduling or publishing Facebook posts (Production account `#16`)
6. Merge/delete of shop KG `/g/11w2b6j71t`

## Rollback (Test)

Redeploy prior website arches from git/backup or restore Test DB snapshot if one exists; social drafts can be unlinked; blog posts remain unpublished so public risk is low.

## Decisions needed from you

1. Approve Production website deploy of this NAP/pages/schema package?  
2. Approve publishing articles (which first)?  
3. Approve copying social drafts to Production account `#16` and scheduling?  
4. Approve any external listing edits from the correction pack?  
5. Attach GBP screenshot binary to WI/analysis?
