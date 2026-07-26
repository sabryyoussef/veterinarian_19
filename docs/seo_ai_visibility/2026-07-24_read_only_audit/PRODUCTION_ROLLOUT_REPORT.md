# Production SEO / AI visibility rollout report

**Date:** 2026-07-24 (Africa/Cairo)  
**Status:** Controlled Production deploy **complete** through Phase 4 publication of 2 articles; Phase 5 Facebook **awaiting your schedule approval**; Phase 6 external **review only**  
**Dev Hub:** WI `#3343` · Analysis `#2697` (Test DB evidence attachments)

---

## 1) Production backup evidence

| Item | Value |
|------|--------|
| Backup dir | `/home/sabry/odoo_base/base_odoo_19/backups/pet_spot_elsahel_seo_prod_20260724T153032Z` |
| DB dump | `pet_spot_elsahel.dump` (~18M, custom format) — `pg_restore -l` TOC ~26354 |
| Filestore | `filestore.tgz` (~111M, ~6143 members) |
| Modules before | `modules_before.json` (346 installed) |
| Social #16 snapshot | `social_account_16.json` |
| Disk free at backup | ~247G |
| Preflight doc | `PRODUCTION_PREFLIGHT.md` |

## 2) Target / revision

| Item | Value |
|------|--------|
| DB | `pet_spot_elsahel` |
| Service | `pet_spot_elsahel.service` · `:8027` |
| Public | https://drpaws.ai |
| Repo | `…/projects/pet_spot_elsahel` |
| Branch | `feature/wa-work-inbox` |
| Commit at deploy | `4c1fc00555a3ede2ccf7582fdb87af6082a29195` |
| Deploy method | RPC website/content from validated Test scripts (**not** a full Dev Hub module push) |
| Website id | **1** (PetSpot El Sahel) — resume site untouched beyond already-unpublished `/` |

### Changed modules / files (operational)

| Change | Result |
|--------|--------|
| `website_blog` | **Installed** on Production → `19.0.1.1` |
| `res.company` / `website` NAP | Canonical name, phones, Amwaj 2 address, El Alamein, FB/IG |
| Homepage / contact / footer QWeb | Redeployed from `website/page_templates.py` + `schema_ld.py` |
| Service pages | Created `/emergency-vet-north-coast`, `/veterinary-clinic-near-amwaj`, `/veterinary-home-visits-sahel`, `/pet-vaccinations-north-coast`, `/grooming-boarding-sahel`, `/contact-directions-booking` |
| Placeholder `555` | Removed from website header/footer/contact/accordion/contact-info (+ newsletter SMS snippet) |
| Blog | PetSpot Pet Care Guide + 8 posts (2 published, 6 draft) |
| Social | 12 `social.post` drafts on account **#16** (0 scheduled) |

Key source files used: `website/implement_prod_seo.py`, `website/deploy.py`, `website/page_templates.py`, `website/schema_ld.py`, `website/site_config.py`, `website/business_data.json`.

## 3) Module upgrade result

| Module | Before | After |
|--------|--------|-------|
| website_blog | uninstalled | **installed** 19.0.1.1 |
| website | installed | installed |
| social / social_facebook | installed | installed (unchanged) |

## 4) Production UAT result

**Overall: PASS** (`prod_uat_evidence/uat_report.json`)

| Check | Result |
|-------|--------|
| Home / contact / 6 services / blog HTTP 200 | Pass |
| No `555` on key public pages | Pass |
| Primary / call-center / WA / Amwaj 2 / Maps shortlink | Pass |
| VeterinaryCare + LocalBusiness JSON-LD | Pass |
| Shop KG `/g/11w2b6j71t` absent | Pass |
| Draft articles not in sitemap before publish | Pass |
| `/appointment` + `/my/home` smoke | HTTP 200 |
| Social #16 still connected | Pass |
| Social drafts all `state=draft`, no `scheduled_date` | Pass |

Log notes: XML-RPC deprecation WARNINGs (expected). WebSocket bind 500 on `/websocket` (gevent port routing) — **pre-existing**, not introduced by this content deploy.

## 5) Live URLs

- https://drpaws.ai/
- https://drpaws.ai/contactus
- https://drpaws.ai/emergency-vet-north-coast
- https://drpaws.ai/veterinary-clinic-near-amwaj
- https://drpaws.ai/veterinary-home-visits-sahel
- https://drpaws.ai/pet-vaccinations-north-coast
- https://drpaws.ai/grooming-boarding-sahel
- https://drpaws.ai/contact-directions-booking
- https://drpaws.ai/blog
- https://drpaws.ai/blog/petspot-pet-care-guide-2/what-to-do-during-a-pet-emergency-in-north-coast-1
- https://drpaws.ai/blog/petspot-pet-care-guide-2/heatstroke-signs-in-dogs-and-cats-during-sahel-summer-2
- Maps: https://maps.app.goo.gl/AaHup6NEFodZEs7S7

## 6) Structured-data validation

Public HTML contains JSON-LD types including **VeterinaryCare**, **LocalBusiness**, Organization, FAQPage on home; service/contact pages include VeterinaryCare + LocalBusiness; published articles include injected **Article** JSON-LD with clinic `about`.

Coords in schema: `30.9909989`, `28.6840834`. Canonical KG used in messaging: `/g/11w2cv6pz0` only.

## 7) Sitemap result

After cache clear, sitemap includes service pages + both published article URLs. Draft articles **not** listed. (Default `our-blog-1` / some slides URLs remain from prior Odoo install — cleanup optional later.)

## 8) Screenshots

Under `prod_uat_evidence/screenshots/`: `home.jpg`, `contactus.jpg`, `emergency.jpg`, `blog.jpg`, `article1.jpg`, `article2.jpg`.

## 9) Rollback readiness

Restore from backup dir above (stop service → `pg_restore` dump → restore filestore tgz → start). Preflight documents steps.

## 10) First two articles (published)

| # | Title | URL |
|---|-------|-----|
| 1 | What to do during a pet emergency in North Coast / ماذا تفعل عند طوارئ… | [live](https://drpaws.ai/blog/petspot-pet-care-guide-2/what-to-do-during-a-pet-emergency-in-north-coast-1) |
| 2 | Heatstroke signs in dogs and cats during Sahel summer / علامات ضربة الحر… | [live](https://drpaws.ai/blog/petspot-pet-care-guide-2/heatstroke-signs-in-dogs-and-cats-during-sahel-summer-2) |

Full bilingual HTML + disclaimer: `prod_uat_evidence/article_previews_1_2.json`.  
Remaining six articles: **unpublished drafts**.

## 11) First three Facebook post previews (NOT scheduled)

Account **#16** only · Page https://www.facebook.com/animalcarecenterpetspots · full copy in `prod_uat_evidence/facebook_post_previews.json`

| Post id | Proposed schedule (Cairo) | Links to |
|---------|---------------------------|----------|
| 1 | Sun 2026-08-03 10:00 | Article 1 + Maps (UTM `emergency`) |
| 2 | Tue 2026-08-05 10:00 | Article 2 (UTM `heatstroke`) |
| 3 | Thu 2026-08-07 10:00 | Article 1 + Maps (UTM `directions`) |

**Awaiting your explicit approval to set `scheduled_date` / schedule.** Remaining nine posts stay drafts.

## 12) External correction review table

See `EXTERNAL_CORRECTION_REVIEW_TABLE.md`.

## 13) Unauthorized-change confirmation

Confirmed **not** performed:

- Google Business Profile edits  
- Merge/delete of shop KG `/g/11w2b6j71t`  
- Yellow Pages / Al-Makan / Buy Egypt / Bing / Apple edits  
- DNS or Cloudflare changes  
- Publishing articles 3–8  
- Scheduling/publishing any Facebook post  
- Creating or reconnecting any Facebook account/page  

## GBP screenshot

Binary PNG still **not located** in chat uploads/Downloads under place-card names. Please provide the file path or drop it under  
`docs/seo_ai_visibility/2026-07-24_read_only_audit/evidence/`  
and it will be linked to WI `#3343` / Analysis `#2697`.
