# External-profile correction pack (NO EDITS YET)

**Date:** 2026-07-24  
**Policy:** Prepare corrections only. Do **not** modify Google, Facebook, directories, Apple, Bing, or any third-party listing until Sabry approves each change.  
**Dev Hub:** Work Item `#3343` · Analysis `#2697`

## Canonical record (apply everywhere after approval)

| Field | Value |
|-------|--------|
| Marketing name | PetSpot El Sahel Veterinary Clinic |
| Google listing name | Pet Spot Clinic |
| Arabic | عيادة بيت سبوت الساحل البيطرية |
| Authoritative KG | `/g/11w2cv6pz0` (Veterinary clinic) |
| Primary phone | 01280833332 (+201280833332) |
| Call-center | 01201568888 (+201201568888) |
| WhatsApp | 01000059085 |
| Hours | Open 24 hours, 7 days / مفتوح 24 ساعة |
| Address AR | الساحل الشمالي، بجوار واحة خطاب، أمام أمواج 2، العلمين، مصر |
| Address EN | North Coast, beside Wahat Khattab, in front of Amwaj 2, El Alamein, Egypt |
| Lat / Lng | 30.9909989, 28.6840834 |
| Directions | https://maps.app.goo.gl/AaHup6NEFodZEs7S7 |
| Website | https://drpaws.ai/ (Production after deploy approval; Test: https://test.drpaws.ai/) |
| Facebook | https://www.facebook.com/animalcarecenterpetspots |
| Instagram | https://www.instagram.com/pet_spot_clinic/ |
| Email | vetelsahel@gmail.com |

**Hard rules:** No km 128/136/139. Amwaj **2** only. No Facebook Giza address. Prefer Google-formatted address if later extractable.

---

## 1) Google Business Profile / Knowledge Graph

### Authoritative

- **Use:** Pet Spot Clinic · `/g/11w2cv6pz0` · Veterinary clinic  
- Confirm NAP, hours 24/7, website, phones hierarchy, Maps pin = canonical coords.  
- Directions shortlink already used on website: `AaHup6NEFodZEs7S7`.

### Potential duplicate / incorrect (investigation only)

| Field | Value |
|-------|--------|
| Label observed | `(pet spot (shop` |
| KG | `/g/11w2b6j71t` |
| Action now | **Document only** |
| Forbidden without separate approval | Merge, delete, edit, claim, or suppress |
| Next step | Ownership verification + Google support / GBP duplicate flow if Sabry owns both |

Sister shortlink `aC7CBQkFyzz6fVt68` (~15 m) must **not** be treated as a second location.

### Nice-to-have (not blockers)

- Plus Code confirmation on place card  
- `ChIJ…` Place ID extraction once browser/GBP console available  

Evidence: Sabry GBP place-card screenshot (binary to be filed under `evidence/` when available) recorded on Analysis `#2697`.

---

## 2) Facebook Page

| Item | Current risk | Proposed (after approval) |
|------|--------------|---------------------------|
| Page | animalcarecenterpetspots | Keep; align About NAP |
| Address | Historical Giza / non-Amwaj copy risk | Replace with canonical EN/AR Coast address; Amwaj 2 |
| Phone | May not match hierarchy | Primary 01280833332; optional call-center note |
| Hours | Seasonal / unclear | 24/7 |
| Odoo Social | Production account `#16` connected | Do not create a second Page connection |

**Do not** schedule/publish posts until approved.

---

## 3) Instagram

| Item | Proposed |
|------|----------|
| Profile | pet_spot_clinic |
| Bio / contact | Match phones + link to drpaws.ai / Maps shortlink |
| Location sticker | Amwaj 2 / El Alamein — not Giza |

---

## 4) Yellow Pages / Egyptian directories

| Source | Observed conflict (audit) | Proposed |
|--------|---------------------------|----------|
| Yellow Pages / similar | Wrong km / phones | Submit canonical NAP; remove obsolete km |
| Al-Makan | Sky Court / conflicting pin text | Update to Wahat Khattab / Amwaj 2 / El Alamein |
| Buy Egypt / others | Stale branch copy | Same canonical pack |

Exact listing URLs from audit folder should be re-opened at edit time; no live edits in this phase.

---

## 5) Bing Places / Apple Business Connect

| Platform | Action after approval |
|----------|------------------------|
| Bing Places | Create or claim with canonical NAP + lat/lng |
| Apple Business Connect | Same; category Veterinary Clinic |

---

## 6) Website / Odoo (Test done; Production gated)

Already prepared on **Test** (`test.drpaws.ai`): NAP cleanup, service pages, VeterinaryCare JSON-LD, blog drafts, contactus fixed.  
Production `drpaws.ai` / `:8027` — **await Sabry approval**.

---

## Approval checklist (external)

- [ ] Confirm GBP screenshot filed as binary attachment  
- [ ] Approve any GBP edit on `/g/11w2cv6pz0` only  
- [ ] Separate ticket for `/g/11w2b6j71t` ownership investigation  
- [ ] Approve Facebook About NAP edit  
- [ ] Approve each directory submission  
- [ ] Approve Bing / Apple claim  
- [ ] Approve Production website deploy  
