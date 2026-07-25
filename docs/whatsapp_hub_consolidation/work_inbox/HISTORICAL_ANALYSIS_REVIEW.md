# WhatsApp Historical Analysis Review

**Environment:** `pet_spot_elsahel_test`  
**Module:** `devhub_whatsapp` ≥ `19.0.9.2.27`  
**Prompt:** `wa_project_aware_v2.2`  

---

## Scope (corrected)

Historical analysis review includes:

1. **Confirmed single-project whitelist groups** — lane `confirmed_single`
2. **Dev Needed** — explicitly approved **multi-project** review group — lane `multi_project`

### Dev Needed constraints (unchanged)

```text
project_mapping_state = ambiguous
ai_triage_enabled = false
mandatory_human_review = true
```

Do **not** remap Dev Needed to a single project. Do **not** enable unsupervised AI triage.

### Process for Dev Needed

- Segment messages by topic and project alias
- Retrieve validated project candidates for every segment
- Propose a project only under the current v2.2 relevance policy
- Require human confirmation for every selected project (questionnaire + conceptual confirmation; evaluation rows still block WI mutations)
- Leave mixed-project segments unresolved
- Create **no** Work Items
- Attach to **no** Work Items
- Change **no** inbox states

### Excluded

- **Alzaeem** (`unmapped`)
- Inactive or inaccessible groups
- Groups without historical-review approval / insufficient project candidates

---

## Dashboard sections

| Menu | Action | Domain |
|------|--------|--------|
| DH WhatsApp → Historical Review → **Confirmed Single-Project** | Confirmed lane evals | `is_evaluation_result` + `historical_review_lane=confirmed_single` |
| DH WhatsApp → Historical Review → **Multi-Project Historical Review** | Dev Needed evals | `is_evaluation_result` + `historical_review_lane=multi_project` |

Source flags (Sources → Historical review allowlist):

- `historical_review_enabled`
- `historical_review_lane` = `confirmed_single` | `multi_project` | `excluded`

---

## Reviewer questionnaire template

Use on each evaluation analysis (**Historical Review** tab). Header fields are filled from the AI result.

```text
# WhatsApp Historical Analysis Review

**Group:**                    <source_id>
**Mapped project:**           <dev_project_id baseline FK — not authoritative for Dev Needed>
**Proposed project:**         <resolved_project_id>
**Message date:**             <earliest batch message timestamp>
**Analysis ID:**              <id>
**Sample ID:**                <evaluation_sample_id>
**Proposed Work Item:**       <proposed_work_item_id>
**Review lane:**              confirmed_single | multi_project

## AI result

**Summary:**                  <summary>
**Classification:**           <classification>
**Recommended action:**       <recommended_action>
**Project relevance:**        <project_relevance JSON>
**Existing or new Work Item:** <work_item_decision>
**Technical evidence used:**  <evidence_used>
**Likely affected modules/models:** <analysis.likely_affected_*>
**Missing information:**      <missing_information>
**Acceptance criteria:**      <analysis.acceptance_criteria>

## Reviewer questionnaire

### 1. Is the AI summary correct?
* Yes / Partially correct / No
**Correction:**

### 2. Does this segment belong to the mapped / proposed project?
* Yes / No / Unclear / It belongs to another project
**Correct project, when known:**
(For Dev Needed: judge against the *proposed* project / candidates, not the PetSpot baseline FK.)

### 3. Is the classification correct?
* Yes / No
**Correct classification:** New task | Existing Work Item follow-up | Bug report |
Question | Decision required | Context update | Information | Completed work |
Noise | Unclear

### 4. Is this actionable work?
* Yes / No / More context is required
**What action is required?**

### 5. Is this new or existing work?
* Create a new Work Item | Attach to the proposed Work Item |
  Attach to a different Work Item | No Work Item is needed | Unclear
**Correct existing Work Item, when known:**

### 6. Is the proposed Work Item correct?
* Yes / No / No Work Item was proposed / More evidence is needed
**Reviewer notes:**

### 7. Is the technical analysis relevant?
* Fully relevant / Partially relevant / Generic / Incorrect / Insufficient evidence
**Incorrect or missing technical details:**

### 8. Are any claims unsupported?
* No / Yes / Unclear
**Unsupported claims:**

### 9. Are the acceptance criteria useful?
* Ready to use / Need minor correction / Need major correction / Not applicable
**Corrected acceptance criteria:**

### 10. Is more information required?
* No / Yes
**Questions to ask:**

### 11. Final review decision
* Approve as New Work | Approve as Existing Work Follow-up | Needs Clarification |
  Question or Decision | Information / Completed | Noise | Wrong Project or Group |
  Reject Analysis | Reanalyse

### 12. Overall usefulness
* 1 — Unusable
* 2 — Mostly incorrect
* 3 — Partially useful
* 4 — Useful with minor corrections
* 5 — Ready for operational review

**Final reviewer notes:**
```

Save via **Save Historical Review** (requires Q11 + Q12). This records the questionnaire only — it does **not** create/attach Work Items or change inbox states.

---

## Safety

| Check | Expected |
|-------|----------|
| Dev Needed mapping | `ambiguous` |
| Dev Needed AI triage | `false` |
| Alzaeem historical | excluded |
| Eval create/attach/ignore | blocked |
| Production / OpenProject | untouched |
