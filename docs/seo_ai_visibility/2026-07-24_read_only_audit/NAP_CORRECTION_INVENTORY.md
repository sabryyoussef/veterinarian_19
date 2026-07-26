# NAP / hours / brand correction inventory (pre-implementation)

Confirmed hierarchy (Sabry 2026-07-24):

| Role | Value |
|------|--------|
| Official name | PetSpot El Sahel Veterinary Clinic |
| Primary phone | 01280833332 (+201280833332) |
| Call-center | 01201568888 (+201201568888) |
| WhatsApp | 01000059085 (wa.me/201000059085) |
| Hours | 24/7 |
| Emergency | 24/7 |
| Facebook sameAs | https://www.facebook.com/animalcarecenterpetspots |
| Address | Canonical — see CANONICAL_NAP.md |

## Live Production HTML (drpaws.ai) — observed wrong values

| Occurrence | Current | Proposed |
|------------|---------|----------|
| Header/footer `tel:+1 555-555-5556` | Placeholder US | Remove; use +201280833332 |
| Primary WA CTAs | wa.me/201201568888 | wa.me/201000059085 |
| Display phone 012 01568888 as main | Call-center used as CTA | Primary clinic 01280833332; call-center labeled separately |
| Second phone 012 80833332 | Present but secondary | Promote to primary |
| Hours | Summer season · Open daily | Open 24 hours, 7 days / مفتوح 24 ساعة |
| Brand strings | PetSpot El Sahel / Pet Spot Veterinary Clinic mix | PetSpot El Sahel Veterinary Clinic (+ AR equivalent) |
| Address lines | Beside Amwaj 1 gate… | **Hold** until GBP |

## Code / config files to change (after address unlock)

| File | Issue | Proposed |
|------|-------|----------|
| `website/business_data.json` | WA=201201568888; call_center mislabeled; hours seasonal; emails mixed | Align phones/WA/hours/name; address from GBP |
| `website/.env` / `.env.example` | CLINIC_PHONE=+201201568888; WA same; MARASSI naming | CLINIC_PHONE=+201280833332; CLINIC_CALL_CENTER=+201201568888; CLINIC_WHATSAPP=201000059085 |
| `website/site_config.py` | Defaults/env mapping; phone_marassi alias | Rename roles; schema helpers |
| `website/page_templates.py` | Marassi label; Amwaj copy; WA links | 24/7; primary/call-center/WA buttons; remove 555 |
| `website/content_brief.md` | Stale Marassi coords/phones | Rewrite from canonical |
| `website/assets/gallery/facebook/manifest.json` | Many captions: WA/phones/Sky Court/km | Do not republish; archive or rewrite later |
| `petspot_campaign_rewards/.../survey_user_input.py` | Phone role line | Align hierarchy |
| Odoo `website.homepage` / footer views | Deployed QWeb with 555 + old WA | Redeploy via deploy.py on **Test** first |
| Odoo `res.company` / partner | phone +201201568888; street Amwaj text | Update after GBP |

## Social (Production)

- `social.account` id **16**: بيت الدواء البيطري -pet spot / handle `animalcarecenterpetspots` / facebook_account_id `1378190768902001` / **connected** (`is_media_disconnected=False`)
- Test DB has **no** Facebook social.account — drafts/scheduling for review should use Production Social Marketing connection **only after approval**; do not create duplicate page
- `website_blog`: **uninstalled** on Test and Production — install on Test first after unblock

## Checklist (Dev Hub)

- [x] GBP address confirmed (Plus Code/Place ID nice-to-have)
- [x] Code NAP cleanup (Test)
- [x] website_blog install + bilingual blog config (Test)
- [x] Landing + service pages (Test)
- [x] JSON-LD on key pages (Test; Cloudflare/hreflang later)
- [x] 8 draft articles (unpublished)
- [x] 4-week social calendar drafts (no publish)
- [x] External correction pack (no edits)
- [x] Test evidence + approval gate (this package)
- [ ] Production deploy (denied until approval)
