# Architecture — Personal Job Application Orchestrator (UAT P1–P3)

```mermaid
flowchart LR
  subgraph TEST["Odoo TEST :8028"]
    Jobs[linkedin.job]
    App[linkedin.job.application]
    Profile[linkedin.candidate.profile]
    Policy[linkedin.apply.policy]
    Attempt[linkedin.apply.attempt]
    API["Signed Orchestrator API\nHMAC X-Orchestrator-*"]
    Jobs --> App
    Profile --> API
    Policy --> API
    App --> API
    API --> Attempt
  end

  subgraph Draft["Draft / Inactive"]
    Dify["Dify: Job Application Pack Generator\nUNPUBLISHED"]
    N8N["n8n: Personal Job Application Orchestrator — UAT\nactive=false"]
  end

  subgraph Worker["personal-job-apply-worker :8095"]
    DraftAPI["POST /v1/apply/draft\ndry_run=true"]
    SubmitAPI["POST /v1/apply/submit\nalways 403"]
    Fixtures["Offline HTML fixtures\nBeBee / Greenhouse / CAPTCHA / OTP"]
    Artifacts["/home/sabry/private/job_apply_worker/artifacts\nmode 0700"]
  end

  API -->|"GET payload / POST pack / POST attempt"| N8N
  N8N -->|"structured JSON only"| Dify
  N8N -->|"dry_run draft only"| DraftAPI
  DraftAPI --> Fixtures
  DraftAPI --> Artifacts
  N8N --> API
  SubmitAPI -.->|"hard disabled"| X[Blocked]
```

## Trust boundaries
- n8n never opens PostgreSQL; only signed HTTP to Odoo TEST.
- Dify has no Odoo / email / WhatsApp / browser write tools.
- Worker never receives real credentials or Production CV; LinkedIn URLs rejected.
- Company LinkedIn account id=1 cannot own applications/attempts.
