# Production deploy — pet.spot location correction

**Timestamp:** 2026-07-24T16:49:14.743769+00:00  
**Backup:** `/home/sabry/odoo_base/base_odoo_19/backups/pet_spot_elsahel_petspot_loc_prod_20260724T164244Z`  
**Rollback:** not needed (deploy succeeded). Restore procedure in backup README.

## Canonical public location
- **Name:** pet.spot  
- **Coords:** 30.9909056, 28.6842417  
- **Maps:** https://www.google.com/maps?q=30.9909056,28.6842417  
- **Address:** Main Road, beside Amwaj Gate 1, Sidi Abdel Rahman, North Coast  
- **Phones:** 01280833332 · 01201568888 · WA 01000059085 · 24/7  

## Deployed
- Homepage + location banner, contact, footer, Gate 1 / emergency / service pages  
- JSON-LD VeterinaryCare/LocalBusiness for `pet.spot` (no disputed KG in sameAs)  
- Company/street/city; campaign maps URL system parameter  
- Articles 1–2 remain published; CTAs aligned  
- WhatsApp `evo.wa.template` IDs **11, 14, 16, 20** → new Maps URL  

## Facebook (unchanged schedule policy)
| ID | State |
|----|-------|
| 1 | draft |
| 2 | **scheduled** 2026-08-05 07:00:00 UTC |
| 3 | draft (Directions preview; **not scheduled**) |

## Public old-reference scan
**Customer-facing pages:** **0** hits for Amwaj 2 / Wahat / old Maps / old coords / disputed KG / move language / Pet Spot Clinic.

Remaining Amwaj 2 / old Maps only on **unpublished social drafts** (#1,#4,#6,#11,#12) — not website.

## Live URLs
- https://drpaws.ai/  
- https://drpaws.ai/contact-directions-booking  
- https://drpaws.ai/veterinary-clinic-near-amwaj  
- https://drpaws.ai/emergency-vet-north-coast  

Screenshots: `prod_uat_evidence/screenshots_petspot_prod/`

## Untouched
GBP · FB scheduling · external listings · DNS/Cloudflare · ownership dispute disclosure  

## Signage/GBP blocker
Permanent sign reads **PET SPOT**; profile name **pet.spot**. No verification submit until Sabry chooses A (visible dot → PET.SPOT) or B (rename profile to match sign). Do not edit disputed legacy listing.
