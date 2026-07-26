# PetSpot El Sahel — AI Visibility & Local SEO Read-Only Audit

**Date:** 2026-07-24 (Africa/Cairo)  
**Brand target:** PetSpot El Sahel Veterinary Clinic  
**Scope:** Phases 1–3 evidence + Phases 4–7 **proposal only**  
**Production / public changes:** **None** (stopped for Sabry approval)

---

## Methodology (visibility tests)

| Dimension | Method | Limitation |
|-----------|--------|------------|
| Organic web | Web search APIs + live `curl` of public URLs | Not a logged-in Google SERP from Amwaj; **do not treat as Maps rank** |
| Maps | Resolve `maps.app.goo.gl` redirects to lat/lng; public FB/Maps links | No GPS-at-Amwaj Maps pack scrape; **no exact Maps rank claimed** |
| Directories | Fetch Al-Makan, FB pages; YP URL known but Cloudflare-blocked from this host | YP values from prior marketing profile + URL only |
| Website tech | HTTPS fetch of `drpaws.ai`, robots, sitemap, HTML parse, bot UAs | Rich Results UI not fully automated (0 JSON-LD confirmed by parse) |
| Odoo | Read-only XML-RPC to Production `:8027` `pet_spot_elsahel` | MCP Odoo points at **Test** `:8028` (empty company) — not used as NAP source |

**Test location for future Maps benchmarks (proposed):** Amwaj 1 gate area ≈ `30.9910 N, 28.6841 E` (from live Maps shortlink).

---

## 1. Current-state audit (summary)

### Public web surface

| Asset | Status |
|-------|--------|
| Canonical site | `https://drpaws.ai/` — HTTPS 200, SSR bilingual landing |
| `www.drpaws.ai` | HTTPS 200 **same content**, **no redirect** to apex |
| `http://drpaws.ai` | **200 without redirect to HTTPS** (no HSTS observed) |
| `petspot.drpaws.ai` | Backend login (not a marketing landing) |
| `petspot.odoo.com` | Redirects to Odoo upgrade page — **stale remote target** |
| Legacy Wix | `https://vetdrughouse.wixsite.com/pets` — network brand still indexed |

### Brand visibility (organic, web-search tool — 2026-07-24)

| Query class | PetSpot observable? | Notes |
|-------------|---------------------|-------|
| Exact brand EN (`PetSpot El Sahel`, Amwaj clinic) | **Strong** — `drpaws.ai` often #1 | Also Al-Makan, Wix, FB |
| Exact brand AR (`بت سبوت` أمواج) | **Present** — Al-Makan + site | Address/hours on Al-Makan conflict with site |
| Generic EN (`veterinary clinic Amwaj`) | **Present** — site + Al-Makan + EgyptDoc competitors | Happy Pets / Vet Specialty Center also appear |
| Generic AR best/emergency Sahel | **Weak / absent as #1** | **The 30 Vet Center** content pages dominate “أفضل / طوارئ / زيارة منزلية” SERPs |
| Emergency EN North Coast | Mixed | Al-Makan (PetSpot) + Cairo emergency brands; not a clean local pack test |

### AI crawler / robots

- Cloudflare managed `robots.txt`: `GPTBot`, `ClaudeBot`, `Google-Extended`, `Applebot-Extended`, etc. **Disallow: /**
- `User-agent: *` **Allow: /** + `Content-Signal: search=yes,ai-train=no,use=reference`
- **`OAI-SearchBot` not listed** → falls under `*` → HTTP 200 on homepage (verified)
- **Training vs AI-search policy not explicitly separated** for `ai-input` (only `ai-train=no`)

### Structured data

- **No** `application/ld+json` on homepage
- **No** Microdata `itemscope`
- Manual conclusion: **VeterinaryCare / LocalBusiness schema missing** (Rich Results would fail for local entity)

---

## 2. Canonical-data discrepancy table

Values below are **observed**, not asserted as correct.

| Field | Source | Observed value |
|-------|--------|----------------|
| Business name | Live site title / Odoo company | PetSpot El Sahel |
| Business name | `business_data.json` legal | Pet Spot Veterinary Clinic |
| Business name | FB sister page | بيت الدواء البيطري -pet spot |
| Business name | FB profile `61591968621292` | pet spot clinic \| Marsa Matruh |
| Business name | Al-Makan | بت سبوت - امواج |
| Business name | Official ask | PetSpot El Sahel Veterinary Clinic |
| Branch / area | Live site / Odoo street | Beside Amwaj 1 gate, Main Road, Sidi Abdel Rahman |
| Branch / area | Al-Makan | سكاى كورت مول … امام امواج، **الكيلو 139** |
| Branch / area | Yellow Pages (prior profile) | **Km 136** Sky Court Mall, Sidi Abdel Rahman |
| Branch / area | Older FB snippet (marketing profile) | **Km 128** / Agora / Marassi |
| Branch / area | `content_brief.md` (stale) | **Marassi**, Alexandria |
| Amwaj gate ref | Live site | Amwaj **1** gate |
| Amwaj gate ref | Al-Makan | امام امواج (no gate number) |
| GPS | Maps shortlink on site `AaHup6NEFodZEs7S7` | ≈ **30.9909989, 28.6840834** |
| GPS | Maps shortlink on FB Haram page `aC7CBQkFyzz6fVt68` | ≈ **30.991027, 28.684183** (near-identical pin; labeled Haram in JSON) |
| Phone CTA / WhatsApp | Live site | **01201568888** / `wa.me/201201568888` |
| Phone “Amwaj branch” in JSON | `business_data.json` branch amwaj | **01280833332** |
| Phone “Matruh” on FB intro | animalcarecenterpetspots | **01280833332** |
| Call center | FB intro / Al-Makan | **01000059085** |
| Phone | FB profile Marsa Matruh HTML scrape | **01008657085** (additional) |
| Phone | Placeholder on live HTML | **`tel:+1 555-555-5556`** (header/footer) |
| Email | Odoo company / `.env` | **vetelsahel@gmail.com** |
| Email | `business_data.json` / FB | **vetdrughouse@gmail.com** |
| Hours | Live site | Summer season · Open daily / موسم الصيف · مفتوح يومياً |
| Hours | Al-Makan | **مفتوح ٢٤ ساعة** / open all day every day |
| Hours | FB animalcarecenterpetspots | **Always open** + address **451 Haram St, Giza** |
| Hours | `content_brief.md` | Jun–Sep **10:00–22:00** |
| 24/7 emergency | Site copy | Mentions Emergency / home visit — **no explicit verified 24/7 claim on homepage hours** |
| 24/7 emergency | Al-Makan / competitors SERP | Al-Makan implies 24h; The 30 Vet markets 24/7 heavily |
| Website | Odoo / live | https://drpaws.ai |
| Website | Legacy | Wix vetdrughouse; petspot.odoo.com broken for public |
| Booking | Live | `/appointment`, WhatsApp CTAs |
| Booking | Legacy | Wix “احجز موعد طوارىء” forms |

---

## 3. Competitor comparison (North Coast / Amwaj area)

| Competitor | Strength vs PetSpot | Evidence |
|------------|---------------------|----------|
| **The 30 Vet Center** | Owns Arabic informational SERPs for أفضل / طوارئ / زيارة منزلية / عيادة متنقلة | Dedicated SEO articles on `the30vetcenter.com` |
| **Happy Pets** | Multi-branch brand; Marina + Hacienda listings; hotline **15891**; bilingual site | `happypetseg.com`, Al-Makan, EgyptDoc |
| **Veterinary Speciality Center** | EgyptDoc North Coast listing (Marina 5) | `egyptdoc.com` |
| **Network / sister brand noise** | بيت الدواء / Animal Care Center / Wix compete for brand queries | Shared FB page Giza NAP |
| Dubai “Amwaj” vets | Irrelevant geo pollution for “Amwaj” queries | Pawbulance JBR etc. |

**Takeaway:** Brand queries work; **generic Arabic intent is owned by content-led competitors**. PetSpot needs dedicated bilingual service pages + clean NAP + GBP — not more homepage paragraphs alone.

---

## 4. Prioritized issues

### Critical

1. **NAP inconsistency** across site, Al-Makan, FB (Giza / Always open), km markers (128/136/139), phone role confusion.
2. **Placeholder US phone** `+1 555-555-5556` on production HTML.
3. **No VeterinaryCare JSON-LD**; weak entity signals for Google + AI citation.
4. **Unsupported / conflicting 24/7 claims** on Al-Makan (and FB Always open) vs seasonal site hours — risk of policy/trust issues.

### High

5. **`www` and apex both indexable** without redirect; HTTP without HTTPS redirect.
6. **Cloudflare blocks GPTBot/ClaudeBot**; OAI-SearchBot allowed but AI-train/ai-input policy not explicit — needs Sabry decision.
7. **Generic keyword gap** vs The 30 Vet / Happy Pets.
8. **Dual Facebook identities** (Giza sister page vs Matruh profile) dilute El Sahel entity.
9. **Email inconsistency** (`vetelsahel@` vs `vetdrughouse@`).
10. **Analytics / GSC / Bing Webmaster** not evident on public HTML; no `utm_source=chatgpt.com` tracking plan live.
11. Sitemap includes low-value URLs (`/website/info`, `/profile/users`) and **no service landing URLs**.

### Medium

12. Arabic is inline SSR but `html lang="en-US"` only; no `hreflang`.
13. Stale `content_brief.md` (Marassi) can mislead future deploys.
14. Gallery/real photos still incomplete per prior website report.
15. Yellow Pages / Buy Egypt / Bing Places / Apple Business Connect — weak or unverified presence from this host.
16. `business_data.json` maps Haram branch to Amwaj-area coordinates shortlink — data model bug.

### Low

17. Legacy Wix still ranks for brand/booking queries.
18. Slides/quiz URLs in sitemap — fine later, not primary local SEO.

---

## 5. Proposed implementation plan (awaiting approval)

### Phase A — Canonical facts lock (Sabry)

Confirm every field in §9. Freeze into `website/business_data.json` + single “source of truth” doc. No public edits until then.

### Phase B — Website (code → Test → Production)

1. Fix placeholder phone; unify phones/emails/hours/maps.
2. Add bilingual landing refinements: **PetSpot El Sahel Veterinary Clinic — Amwaj**.
3. New pages (AR+EN): emergency North Coast; near Amwaj; home visits Sahel; vaccinations; grooming & boarding.
4. Valid `VeterinaryCare` + `Organization` JSON-LD (`sameAs`, geo, hours, telephone, areaServed).
5. Canonical www→apex + HTTP→HTTPS (Cloudflare / Odoo).
6. robots: keep search allow; **explicit Sabry decision** on GPTBot / training vs OAI-SearchBot.
7. Sitemap hygiene + GSC/Bing submit readiness.
8. Analytics with `utm_source=chatgpt.com` (and Maps/GBP UTMs).

### Phase C — External profiles package (manual by Sabry / owners)

GBP, FB, IG, YP, Buy Egypt, Al-Makan, Bing Places, Apple Business Connect — see Phase 5 package in canvas / § below.

### Phase D — Reviews & content ops

Review link/QR, Arabic WhatsApp request (post-visit only), 4-week calendar, 4 draft articles, photo checklist — **no incentivized reviews**.

### Phase E — Monthly measurement

Benchmark template in § deliverable #9.

---

## 6. Exact files / systems that would change (after approval)

| System | Paths / objects |
|--------|-----------------|
| Website content source | `projects/pet_spot_elsahel/website/business_data.json`, `page_templates.py`, `site_config.py`, `deploy.py`, `.env` |
| Odoo Production website | `website.page` Home/Contact + **new pages**; `ir.ui.view` homepage/footer (`website.homepage`, `gen_key… PetSpot Footer`); `res.company` / `res.partner` NAP |
| Cloudflare | `drpaws.ai` / `www` redirect rules; optional robots managed content; HSTS |
| Analytics | GA4/GTM or Plausible — **not present today** |
| External | GBP, FB×2, IG, Al-Makan, YP `…/pet-spot/671305`, Bing Places, Apple Business Connect, optional Wix deindex/redirect |
| Docs / Dev Hub | This folder; optional Dev Hub work item + analysis attachment |

**Not to touch without separate approval:** DNS tunnel hostnames, Production DB schema, WhatsApp Hub, Evolution.

---

## 7. Test and rollback plan

1. Deploy to **Test** `test.drpaws.ai` first; Playwright smoke (homepage NAP, JSON-LD, no 555 phone).
2. Validate JSON-LD with [Google Rich Results Test](https://search.google.com/test/rich-results) + Schema Markup Validator.
3. Production deploy via existing `website/deploy.py` only after Sabry sign-off checklist.
4. Rollback: redeploy previous QWeb arch from git / Odoo view backup; Cloudflare rule disable; sitemap previous version.
5. External listings: keep a before-screenshot pack; revert text fields manually if wrong.

---

## 8. Items requiring Sabry’s confirmation

1. **Official English name** exactly as: `PetSpot El Sahel Veterinary Clinic`? Arabic canonical?
2. **Primary public phone** for Amwaj + which number is WhatsApp CTA.
3. Roles for **01201568888 / 01280833332 / 01000059085 / 01008657085**.
4. **Call center** number and whether it may appear on Sahel pages.
5. **Canonical address line** (gate Amwaj 1 vs Sky Court Mall) and **kilometer number** if any.
6. Confirm **GPS pin** `https://maps.app.goo.gl/AaHup6NEFodZEs7S7` is the only Sahel pin.
7. **Opening hours** (seasonal dates + daily clock times) and whether **24/7 emergency** is allowed to claim.
8. **Primary email** for public schema (`vetelsahel@` vs `vetdrughouse@`).
9. Which Facebook is **sameAs** for El Sahel (profile vs animalcarecenterpetspots).
10. Instagram bio/NAP ownership confirmation.
11. Prices that may be published; doctor names/qualifications allowed.
12. **robots policy:** allow OAI-SearchBot (yes today) — keep GPTBot blocked? Allow `ai-input`?
13. Approve creating a **Dev Hub work item** and attaching this audit (internal only).

---

## 9. Before/after ranking benchmark template

Record monthly. **Always document test location.**

| Metric | Method | Baseline 2026-07-24 | Month+1 | Month+2 |
|--------|--------|---------------------|---------|---------|
| Brand EN organic | Search from documented browser/VPN; note top 5 URLs | drpaws.ai strong | | |
| Brand AR organic | Same | Al-Makan + site | | |
| Generic AR “عيادة بيطرية أمواج” | Same + screenshot | Competitors + PetSpot mixed | | |
| Generic AR emergency/best | Same | The 30 Vet dominant | | |
| Maps pack (Amwaj pin) | Phone/browser at ≈30.991,28.684; query + screenshot | **Not ranked this audit** | | |
| GBP calls / directions / site clicks | GBP Insights | TBD after access | | |
| GSC impressions/clicks | Search Console | TBD | | |
| ChatGPT citation test | Fixed prompt set; note if cites drpaws.ai | Not run (needs human) | | |
| Gemini / Copilot / Perplexity | Fixed prompts | Not run | | |
| WhatsApp / booking conversions | Odoo / WA metrics | TBD | | |
| `utm_source=chatgpt.com` sessions | Analytics | 0 (no tag) | | |
| Reviews count / rating / response % | GBP + FB | FB ~11 recommends on sister page | | |

---

## Phase 5 — External profile correction package (draft — do not publish)

| Profile | URL | Current (observed) | Proposed (after Sabry confirm) | Manual? |
|---------|-----|--------------------|--------------------------------|---------|
| Google Business Profile | TBD — need Sabry login / Place ID | Maps pin exists via shortlink; full GBP fields not audited logged-in | Match canonical NAP + hours + categories Veterinary care | **Yes** |
| Facebook (sister) | https://www.facebook.com/animalcarecenterpetspots/ | Giza address, Always open, mixed phones in intro | Either Sahel location page or clear “network HQ” labeling; hours truthful | **Yes** |
| Facebook (profile) | https://www.facebook.com/profile.php?id=61591968621292 | Marsa Matruh; phone 01008657085 seen | Align name/NAP or unlink from Sahel sameAs | **Yes** |
| Instagram | https://www.instagram.com/pet_spot_clinic/ | Login-walled in fetch | Bio + link in bio → drpaws.ai + WA | **Yes** |
| Al-Makan | https://www.al-makan.com/veterinary/بت-سبوت-امواج/ | Sky Court km 139, 24h, 0100+0120 | Canonical address/hours/phones | **Yes** |
| Yellow Pages | https://yellowpages.com.eg/en/profile/pet-spot/671305 | Prior: Km 136 Sky Court + other branches | Canonical Sahel + branch list | **Yes** |
| Buy Egypt | Not found this audit | — | Create or claim if exists | **Yes** |
| Bing Places | Not verified | — | Create from GBP sync if possible | **Yes** |
| Apple Business Connect | Not verified | — | Create/claim | **Yes** |

---

## Phase 6–7 drafts (prepared, not executed)

- Review workflow: only after completed appointment in Odoo; WhatsApp template in Arabic; Google review short link once Place ID confirmed.
- Content calendar + 4 article outlines: heat safety; vaccination before travel; boarding checklist; when to seek emergency care (no unsubstantiated “best/24/7” claims).
- Photo checklist: exterior+Amwaj gate context, reception, consult room, grooming, boarding, doctors (with consent), equipment, team.

---

## Evidence archive

Local copies under this folder: `robots`, `sitemap`, `homepage_text`, `bot_access`, `fetch_log`.

**Status:** Read-only audit complete. **Awaiting explicit approval** before any Production, DNS, Cloudflare, or third-party listing changes.
