# Lead Engine — Getting Started Guide
### For Hospital Groups (and any multi-source lead operation)

---

## What this module does in one sentence

**Lead Engine captures every inquiry that reaches your hospital group — website forms, Google Ads, health camps, phone calls, referrals — scores each one, routes it to the right team, and automatically starts a follow-up sequence so no patient inquiry is ever forgotten.**

---

## Before you start — understand the four building blocks

```
LEAD SOURCE   →   SCORE RULES   →   ASSIGNMENT RULES   →   PLAYBOOK
(where it         (how valuable      (who handles it)       (what happens
 comes from)       is this lead?)                            automatically)
```

Think of it like a hospital triage system:
1. A patient arrives through a specific door (**Source**)
2. A nurse quickly assesses urgency (**Score**)
3. They are sent to the right department (**Assignment**)
4. A care protocol starts automatically (**Playbook**)

---

## Step 1 — Map your hospital group's lead sources

Before touching the system, answer this question on paper:

> **"Where do patient/client inquiries reach us today?"**

| Real-world channel | Lead Engine channel | Who typically sends |
|--------------------|---------------------|---------------------|
| Website "Book Consultation" form | `form` | Patients, families |
| Google / Facebook Ads campaign | `ads` | High-intent patients |
| Health camp / medical fair booth | `other` (manual entry) | Corporate HR, individuals |
| WhatsApp / phone call logged by front desk | `other` (manual entry) | Referrals, walk-ins |
| Insurance company partnership portal | `api` / `webhook` | B2B clients |
| Doctor referral from another hospital | `other` (manual entry) | Professional network |
| Medical tourism inquiry email | `email` | International patients |

Write down **each source with a short code** (no spaces, uppercase).
Example codes: `WEB_CONSULT`, `ADS_CARDIO`, `CAMP_DHAKA_2026`, `INSURER_DELTA`.

---

## Step 2 — Create your Lead Sources

**Where to go:** Lead Engine → Configuration → Sources

For each source you identified:

| Field | What to enter | Example |
|-------|--------------|---------|
| **Name** | Human label shown on every lead | `Website Consultation Form` |
| **Code** | Your short code (unique) | `WEB_CONSULT` |
| **Channel** | Pick from the dropdown | `Form` |
| **Auto-score** | Leave ON | ✓ |
| **Auto-assign** | Leave ON | ✓ |
| **Inbound API Token** | Only if connecting a website/app | `hosp-web-abc123` |
| **Description** | Who sends leads through this source | *"General public booking a specialist consultation via the hospital website"* |

> **Trade show / health camp sources:** leave the API token blank. You will create leads manually in CRM and pick this source from the dropdown.

---

## Step 3 — Decide what makes a lead valuable (Score Rules)

**Where to go:** Lead Engine → Configuration → Score Rules

Score rules add or subtract points when a lead arrives. Points have no fixed meaning — you define the scale. A typical hospital setup:

| Rule | Points | Why |
|------|--------|-----|
| Any lead from our Cardiology Ads campaign | +60 | Paid channel, high intent |
| Any lead from the website form | +10 | Baseline engagement |
| Lead provided an email address | +15 | Can follow up asynchronously |
| Lead provided a phone number | +20 | Can call immediately |
| Lead came from a corporate HR contact | +30 | B2B, higher value |
| Lead title contains "Manager" or "Director" | +25 | Decision-maker |
| Lead is from a known insurance company | +40 | Already a partner |

**Practical tip — bind rules to their source:**

When creating a score rule, always set the **Source** field to the specific source it belongs to (e.g., "Cardiology Ads: +60" is tied only to `ADS_CARDIO`). This prevents score inflation when you add more sources later.

**Example setup for a hospital group:**

```
Score Rule Name                         | +/- | Source
----------------------------------------|-----|-------------------
Cardiology Ads: baseline intent         | +60 | ADS_CARDIO
Cardiology Ads: email provided          | +15 | ADS_CARDIO
Website form: baseline                  | +10 | WEB_CONSULT
Website form: email provided            | +15 | WEB_CONSULT
Website form: phone provided            | +20 | WEB_CONSULT
Website form: senior title              | +25 | WEB_CONSULT
Health camp: attendance                 | +20 | CAMP_DHAKA_2026
Health camp: business card scanned      | +30 | CAMP_DHAKA_2026
```

---

## Step 4 — Route leads to the right team (Assignment Rules)

**Where to go:** Lead Engine → Configuration → Assignment Rules

You have two routing strategies — use both together:

### Strategy 1: Route by Source (who sent it)
```
Source = WEB_CONSULT     →  Team: Online Enquiries Team
Source = CAMP_DHAKA_2026 →  Team: Field Sales Team
Source = ADS_CARDIO      →  Team: Cardiology Sales
```

### Strategy 2: Route by Score (how hot is the lead)
```
Score >= 70  →  Team: Senior Account Managers  (high-value B2B or ads)
Score 40–69  →  Team: Inside Sales             (qualified, needs nurturing)
Score < 40   →  Team: Nurture / Marketing      (early stage, not ready)
```

**How to create an assignment rule:**

| Field | Description |
|-------|-------------|
| **Name** | Clear label: `"Cardiology Ads → Cardiology Team"` |
| **Sequence** | Lower number = runs first. Source-specific rules should run before score-band rules |
| **Source** | (Optional) Filter to a specific source |
| **Min Score / Max Score** | (Optional) Score band |
| **Sales Team** | The CRM team that owns this lead type |
| **Salesperson** | (Optional) Assign directly to a person |

**Recommended sequence order:**

```
Seq 10: Source = WEB_CONSULT          → Online Team
Seq 20: Source = ADS_CARDIO           → Cardiology Team
Seq 30: Source = CAMP_DHAKA_2026      → Field Sales Team
Seq 40: Score >= 70  (any source)     → Senior Managers
Seq 50: Score 40-69  (any source)     → Inside Sales
Seq 60: Score < 40   (catch-all)      → Marketing / Nurture
```

---

## Step 5 — Create follow-up Playbooks

**Where to go:** Lead Engine → Playbooks

A playbook is a sequence of automatic steps that runs on a lead after it is created and qualified. You define the steps once; the system executes them.

### Available step types

| Step Type | What it does |
|-----------|-------------|
| **Create Activity** | Creates a "Phone Call" or "Email" task for the assigned salesperson with a deadline |
| **Assign Owner** | Changes the sales team or salesperson on the lead |
| **Send Email Template** | Sends an automatic email to the lead's email address |
| **Execute Server Action** | Runs any Odoo server action (advanced) |

### Suggested playbooks for a hospital group

---

#### Playbook A — Website Enquiry (3 steps)
*For general website consultation requests*

| Step | Type | Timing | Action |
|------|------|--------|--------|
| 1 | Create Activity | Immediate | Phone call: "Qualify — understand what department they need, confirm insurance" |
| 2 | Assign Owner | Immediate | Assign to Online Enquiries Team |
| 3 | Create Activity | +2 days | Phone call: "Follow up — did they book? Any questions?" |

---

#### Playbook B — Health Camp Contact (2 steps)
*For leads scanned or collected at a health fair*

| Step | Type | Timing | Action |
|------|------|--------|--------|
| 1 | Create Activity | Immediate | Phone call: "Call while the event is fresh — confirm interest and offer a free health screening" |
| 2 | Assign Owner | Immediate | Assign to Field Sales Team |

---

#### Playbook C — Paid Ads / Cardiology Campaign (1 step, fast)
*For high-intent leads from paid advertising*

| Step | Type | Timing | Action |
|------|------|--------|--------|
| 1 | Create Activity | Immediate | Phone call: "HIGH PRIORITY — call within 1 hour. Confirm appointment interest and offer slot today" |

---

#### Playbook D — Organic / Blog Visitor (2 steps, low pressure)
*For curious visitors not yet ready to commit*

| Step | Type | Timing | Action |
|------|------|--------|--------|
| 1 | Send Email | Immediate | "Thanks for reaching out — here is what to expect at your first visit" |
| 2 | Create Activity | +1 day | Phone call: "Low-pressure follow-up — answer questions, offer a free screening if hesitant" |

---

### How to create a playbook

1. Go to **Lead Engine → Playbooks → New**
2. Give it a name and code (e.g., `HOSP_WEB_PB`)
3. Click **Add a line** in the Steps tab
4. For each step, choose the step type and timing
5. Save

---

## Step 6 — Link Playbooks to Sources

**Where to go:** Lead Engine → Configuration → Sources → (open a source)

On each source record:
- Set **Playbook** → select the playbook for this source
- Set **Auto-start after qualification** → **ON** for sources that use the HTTP intake (website, ads)
- Leave **Auto-start** → **OFF** for manual sources (health camps, phone calls) — the sales rep will start the playbook manually after reviewing the lead

| Source | Playbook | Auto-start |
|--------|----------|-----------|
| Website Consultation Form | Website Enquiry (A) | ON |
| Cardiology Ads | Paid Ads / Fast (C) | ON |
| Organic Blog | Low-Pressure Nurture (D) | ON |
| Health Camp 2026 | Health Camp (B) | OFF (manual) |

---

## Step 7 — Connect your website / CRM form (only for HTTP sources)

For sources with an API token (website forms, ad landing pages), you need to send leads to the intake endpoint:

```
POST  https://your-odoo.com/lead_engine/v1/intake
Authorization: Bearer YOUR_SOURCE_TOKEN
Content-Type: application/json

{
  "external_ref":  "unique-id-from-your-form",
  "name":          "Enquiry about Cardiology Consultation",
  "contact_name":  "Karim Rahman",
  "email_from":    "karim@example.com",
  "phone":         "+880-1711-000000",
  "partner_name":  "Rahman Group",
  "le_channel":    "form",
  "description":   "Patient interested in stress test + ECG package"
}
```

**Fields the intake accepts:**

| Field | Required | Description |
|-------|----------|-------------|
| `external_ref` | Yes | Your form's unique submission ID (prevents duplicates) |
| `name` | Yes | Opportunity/enquiry title |
| `contact_name` | No | Full name of the person |
| `email_from` | No | Email address |
| `phone` | No | Phone number |
| `partner_name` | No | Company or organisation name |
| `le_channel` | No | `form`, `ads`, `webhook`, `email`, `api` |
| `description` | No | Free text notes |

**What the intake returns:**

```json
{
  "ok": true,
  "result": {
    "lead_id": 1234,
    "created": true,
    "state": "success",
    "lead_score": 50
  }
}
```

If `created: false` and `state: "success"`, the lead already existed (same `external_ref`) — the system returned the existing record. This is the **duplicate detection** working correctly.

---

## Step 8 — For manual sources (health camps, phone calls)

When a sales rep collects a contact at a health fair or takes a phone enquiry:

1. Go to **CRM → New** (or use the Leads menu)
2. Fill in contact details
3. Set **Lead Engine Source** → select the relevant source (e.g., "Health Camp 2026")
4. Set **Capture Channel** → `Other`
5. Set **External Reference** → any unique ID you use (e.g., badge number, call log ID)
6. Save the lead
7. Click **Start Playbook** button on the lead form → select the playbook → confirm

The playbook will create the first activity (call task) immediately on the sales rep's to-do list.

---

## Day-to-day operations

### For a salesperson

Your daily workflow:
1. Open **CRM → My Pipeline** — leads assigned to you appear here
2. Check **Activities** (the clock icon) — these are your due tasks from playbooks
3. After each call, log the outcome as a note on the lead and mark the activity done
4. Move the lead through stages (New → Qualified → Proposal → Won/Lost)
5. When a lead is ready for a specialist, use the **Assign Owner** button or change the team

### For a sales manager

1. **Lead Engine → Dashboard → Intake Logs** — see every enquiry that came in, its status, and whether it was created or was a duplicate
2. **Lead Engine → Dashboard → Playbook Runs** — see which playbooks are running, which are done, and which have errors
3. **CRM → Reporting → Pipeline** — standard Odoo funnel analysis
4. Watch the **Lead Score** column — high-score leads that are not yet called are a gap

---

## Monitoring and troubleshooting

### "I submitted a form but no lead appeared"
→ Go to **Lead Engine → Intake Logs** and search for the `external_ref` you sent. Check the **Status** column — if it shows `error`, the **Processing Stage** column tells you where it failed.

### "A lead has a duplicate status"
→ Normal. This means the same `external_ref` was submitted twice (common with form retry buttons). Open the lead — the original lead is the master. You can merge or archive the duplicate from CRM.

### "Playbook did not start automatically"
→ Check the source record: is **Auto-start after qualification** turned ON? Also check the Intake Log for the lead — if the state is `success` but there is no playbook run, check that the source has a playbook assigned.

### "Lead score is much higher than expected"
→ You may have score rules without a Source filter that are applying to all leads. Go to **Lead Engine → Score Rules**, filter by `Source = not set`, and review those global rules. It is best practice to bind every rule to a specific source.

### "Wrong team is assigned to a lead"
→ Check the **Assignment Rules** sequence numbers. Lower sequence = runs first. A source-specific rule should have a lower sequence than a score-band rule. If a source rule matches, subsequent rules do not run.

---

## Quick reference — hospital group example configuration

```
SOURCES
───────
HOSP_WEB      Website "Book a Consultation" form       form    token: rotate-me
HOSP_ADS_CRD  Google Ads — Cardiology Campaign         ads     token: rotate-me
HOSP_CAMP_26  Health & Wellness Fair 2026               other   (no token, manual)
HOSP_ORG      Blog / Organic "Contact Us" form          form    token: rotate-me
HOSP_REF      Doctor Referral (logged by front desk)   other   (no token, manual)

SCORE RULES (all source-bound)
──────────────────────────────
+60  any lead from HOSP_ADS_CRD (high-intent paid channel)
+20  any lead from HOSP_CAMP_26 (attended an event)
+10  any lead from HOSP_WEB     (basic website interest)
+20  any lead from HOSP_WEB     (baseline)
+20  phone number provided       (any source)
+15  email address provided      (any source — one rule per source)
+30  partner_name set            (company = B2B potential)
+25  contact_name contains "Manager" or "Director" (decision maker)

ASSIGNMENT RULES
────────────────
Seq 10  Source=HOSP_WEB        → Online Enquiries Team
Seq 20  Source=HOSP_ADS_CRD   → Cardiology Business Team
Seq 30  Source=HOSP_CAMP_26   → Field Sales Team
Seq 40  Source=HOSP_REF       → Medical Liaison Team
Seq 50  Score >= 70            → Senior Account Managers
Seq 60  Score 40-69            → Inside Sales
Seq 70  Score < 40             → Marketing / Nurture

PLAYBOOKS
─────────
HOSP_WEB_PB    Website Consultation  3 steps: call → assign → 2-day follow-up
HOSP_CAMP_PB   Health Camp           2 steps: call → assign team
HOSP_ADS_PB    Cardiology Ads        1 step:  HIGH PRIORITY call within 1 hour
HOSP_ORG_PB    Organic Blog          2 steps: welcome email → next-day call
HOSP_REF_PB    Doctor Referral       2 steps: call referring doctor → assign specialist team
```

---

## Frequently asked questions

**Q: Do I need a developer to connect my website?**
A: No. You give your web developer the API token and the JSON format above. It is a standard HTTP POST — any website platform (WordPress, custom PHP, React, etc.) can send it. Your developer needs about 30 minutes to wire it up.

**Q: Can we have different configurations per hospital branch?**
A: Yes. Odoo's company system means each branch (configured as a separate company in Odoo) has its own sources, score rules, assignment rules, and playbooks. Use the **Company** field on each record.

**Q: What if the same patient submits the form twice?**
A: The system detects duplicates using `external_ref` (the form's unique submission ID). The second submission is logged in Intake Logs but no new lead is created. Your form must send a unique ID per submission (most form builders do this automatically).

**Q: Can a lead go through more than one playbook?**
A: Yes. You can manually start additional playbooks on a lead at any time using the **Start Playbook** button. Only one automatic playbook starts on intake; subsequent ones are manual.

**Q: How do we track which hospital department closed which lead?**
A: Use CRM Stages (New → Qualified → Proposal → Won) with each stage tagged to the relevant team. The standard Odoo reporting then shows pipeline by team, which maps to your departments.

**Q: The playbook ran but the salesperson did not do the call. What happens?**
A: The activity stays overdue on their task list. It does not automatically cancel or escalate in the MVP version. You as a manager can see overdue activities in CRM → Activities and reassign them.

---

## What to do on day one (checklist)

- [ ] List all the channels where your hospital receives patient enquiries (Step 1)
- [ ] Create one Lead Source per channel in Lead Engine → Configuration → Sources (Step 2)
- [ ] Create score rules for each source — at minimum a "baseline always" rule per source (Step 3)
- [ ] Create one assignment rule per source pointing to the right team (Step 4)
- [ ] Create one playbook per source with at least one "Phone Call" activity step (Step 5)
- [ ] Link each playbook to its source; turn Auto-start ON for API sources (Step 6)
- [ ] Give your web developer the API token and JSON format for website/ads forms (Step 7)
- [ ] Brief your front-desk staff on how to create manual leads for walk-ins and phone calls (Step 8)
- [ ] Submit one test lead through each channel and verify it appears in CRM with the correct score, team, and activity
