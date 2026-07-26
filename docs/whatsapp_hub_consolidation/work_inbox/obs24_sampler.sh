#!/usr/bin/env bash
# Real 24h Test observation sampler for Dev Needed (#9) review-only auto-analysis.
# Appends one JSON snapshot per invocation to obs24_samples.ndjson.
# Schedule hourly (cron/systemd timer) for a full wall-clock day, then aggregate.
set -euo pipefail
PGPW='65b56f3782b16677a5c5724e86a5f212'
DB='pet_spot_elsahel_test'
OUT="/home/sabry/odoo_base/base_odoo_19/projects/pet_spot_elsahel/docs/whatsapp_hub_consolidation/work_inbox/obs24_samples.ndjson"
TS=$(date -u +%Y-%m-%dT%H:%M:%SZ)

read -r NEW_MSG CONV ANALYSES PENDING OLDJOBS DEADJOBS NEEDS_REVIEW WI_AI TASKS_NEW HEALTH_DELAYED HEALTH_GAP HEALTH_FAILED PENDING_SRC9 <<SQLOUT
$(PGPASSWORD="$PGPW" psql -h localhost -U odoo -d "$DB" -tAF' ' <<'SQL'
SELECT
 (SELECT COUNT(*) FROM whatsapp_message WHERE create_date >= now() - interval '1 hour'),
 (SELECT COUNT(DISTINCT group_jid) FROM whatsapp_message WHERE create_date >= now() - interval '1 hour'),
 (SELECT COUNT(*) FROM dev_whatsapp_analysis WHERE create_date >= now() - interval '1 hour'),
 (SELECT COUNT(*) FROM dev_whatsapp_analysis WHERE state='pending'),
 (SELECT COUNT(*) FROM dev_whatsapp_analysis_job WHERE state='pending' AND create_date < now() - interval '15 minutes'),
 (SELECT COUNT(*) FROM dev_whatsapp_analysis_job WHERE state='dead_letter'),
 (SELECT COUNT(*) FROM dev_whatsapp_analysis WHERE validation_state='needs_review'),
 (SELECT COUNT(*) FROM dev_work_item WHERE origin_ai_whatsapp=true AND create_date >= now() - interval '1 hour'),
 (SELECT COUNT(*) FROM project_task WHERE create_date >= now() - interval '1 hour'),
 (SELECT COUNT(*) FROM whatsapp_ingestion_health WHERE health_status='delayed'),
 (SELECT COUNT(*) FROM whatsapp_ingestion_health WHERE gap_detected=true),
 (SELECT COUNT(*) FROM whatsapp_ingestion_health WHERE health_status='failed'),
 (SELECT pending_analysis_after IS NOT NULL FROM dev_whatsapp_source WHERE id=9);
SQL
)
SQLOUT

printf '{"ts":"%s","new_msgs_1h":%s,"conversations_1h":%s,"analyses_1h":%s,"pending_analyses":%s,"jobs_older_15m":%s,"dead_letter_jobs":%s,"needs_review":%s,"wi_ai_1h":%s,"tasks_new_1h":%s,"health_delayed":%s,"health_gap":%s,"health_failed":%s,"src9_pending_scheduled":"%s"}\n' \
  "$TS" "$NEW_MSG" "$CONV" "$ANALYSES" "$PENDING" "$OLDJOBS" "$DEADJOBS" "$NEEDS_REVIEW" "$WI_AI" "$TASKS_NEW" "$HEALTH_DELAYED" "$HEALTH_GAP" "$HEALTH_FAILED" "$PENDING_SRC9" >> "$OUT"
echo "sample appended $TS -> $OUT"
