# pet.spot public-location correction — status (stop before Production)

**Date:** 2026-07-24 (Africa/Cairo)  
**Public location only:** `pet.spot` · `30.9909056, 28.6842417` · https://www.google.com/maps?q=30.9909056,28.6842417  
**Internal:** Legacy Google listing — disputed primary ownership — no action authorized (silent; not on website/JSON-LD/sameAs).

---

## 1. Facebook (Production account #16)

| Post | Action |
|------|--------|
| #1 Emergency | **Returned to draft** (Amwaj 2 + old Maps shortlink) |
| #2 Heatstroke | **Left scheduled** 2026-08-05 07:00 UTC — no location conflict |
| #3 Directions | **Draft / unscheduled**; copy replaced with neutral `pet.spot` + S1 exterior image (att #1412). **Not scheduled.** |

Preview JSON: `prod_uat_evidence/facebook_directions_draft_petspot.json`

---

## 2. Old-reference inventory

| Surface | Result |
|---------|--------|
| **Production website** | Still promotes Amwaj 2 / Wahat / old Maps / old coords / Pet Spot Clinic KG in JSON-LD — **awaiting approved Prod deploy** |
| **Test website (after correction)** | Homepage UAT: pet.spot ✓ · Gate 1 ✓ · new coords ✓ · no Amwaj 2 / old shortlink / move language / legacy KG / Pet Spot Clinic |
| Inventory files | `prod_uat_evidence/OLD_LOCATION_REFERENCE_INVENTORY.md`, `test_uat_evidence/test_location_inventory_after.json` |

---

## 3. WhatsApp photo shortlist

See `prod_uat_evidence/wa_clinic_photos/WHATSAPP_PHOTO_SHORTLIST.md`  
Preferred: **S1 / S2 / S3** night exterior + PET SPOT signage.  
Gaps: Gate 1 landmark clip, reception, treatment (non-patient), daytime clean crop.

---

## 4. pet.spot Google verification

`prod_uat_evidence/PETSPOT_GBP_VERIFICATION_PREP.md`  
**Blocker:** GBP console not inspected this session — Place/KG ID, verification status, and methods unknown.  
**Blocker:** Exterior signage reads **PET SPOT**, strategy name is **`pet.spot`** — confirm match before video submit.

---

## 5. Test implementation diff (source)

| Area | Change |
|------|--------|
| `website/business_data.json` | Public brand `pet.spot`; new coords/maps; Gate 1 / Sidi Abdel Rahman; legacy IDs internal-only |
| `website/schema_ld.py` | VeterinaryCare/LocalBusiness for `pet.spot`; **no** disputed KG in `sameAs` |
| `website/site_config.py` | Empty public `kg_id`; company name from brand |
| `website/page_templates.py` | Neutral location banner + FAQ/pages (no move / previous location) |
| `website/implement_test_seo.py` | Env + articles + UAT detectors |
| `evolution_whatsapp_chat/data/whatsapp_templates.xml` | Maps → new direct pin (module data; Test DB templates not all mirrored) |

**Not deployed to Production.**

Evidence: `test_uat_evidence/relocation_petspot_final_checks.json`, screenshots `home_desktop.png` / `contact_desktop.png`.

---

## 6. Social-post preview (draft only)

Arabic-first Directions on Production **social.post #3** (draft):

> موقع Pet.spot بجوار بوابة أمواج 1 على الطريق الرئيسي. اضغط للوصول مباشرة عبر Google Maps.  
> https://www.google.com/maps?q=30.9909056,28.6842417  
> عيادة: 01280833332 · واتساب: 01000059085 · 24/7  

Image: S1 exterior. **Do not schedule until Sabry approves.**

---

## 7. Dev Hub

Work Item **#3343** updated with note + attachments (inventory, shortlist, GBP prep, FB draft, Test checks, S1 photo).  
Analysis **#2697**: attach if model access available (partial — WI done).

---

## Remaining blockers

1. **Sabry approval** for Production website deploy of pet.spot NAP.  
2. **GBP console inspect** for `pet.spot` (ID, verification status/methods, pin/category/phone/hours).  
3. **Signage vs name** `PET SPOT` vs `pet.spot`.  
4. Missing **Gate 1 / reception / interior** media for verification video.  
5. **Post #1** still has old Amwaj 2 copy in draft — rewrite or leave unused.  
6. Production **WhatsApp live templates** may still carry old Maps until module upgrade on Prod (deferred).  
7. Analysis #2697 attachment if model ACL blocks.  

**Stopped:** no Production website change, no GBP verification submit, no FB schedule of Directions.
