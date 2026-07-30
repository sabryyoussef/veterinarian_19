# -*- coding: utf-8 -*-
import base64
import csv
import io
from datetime import datetime

from odoo import _, fields, models
from odoo.exceptions import UserError


class ShipBluCoverageImportWizard(models.TransientModel):
    _name = "shipblu.coverage.import.wizard"
    _description = "Import ShipBlu Coverage CSV/XLSX"

    backend_id = fields.Many2one("shipblu.backend", required=True)
    data_file = fields.Binary(required=True)
    filename = fields.Char()
    dry_run = fields.Boolean(default=True)
    result_log = fields.Text(readonly=True)

    def action_import(self):
        self.ensure_one()
        if not self.data_file:
            raise UserError(_("Upload a CSV or XLSX file."))
        raw = base64.b64decode(self.data_file)
        name = (self.filename or "").lower()
        rows = []
        if name.endswith(".xlsx"):
            try:
                from openpyxl import load_workbook
            except ImportError as exc:
                raise UserError(_("openpyxl is required for XLSX import.")) from exc
            wb = load_workbook(io.BytesIO(raw), read_only=True)
            ws = wb.active
            headers = [str(c.value or "").strip().lower() for c in next(ws.iter_rows(max_row=1))]
            for row in ws.iter_rows(min_row=2, values_only=True):
                rows.append({headers[i]: row[i] for i in range(len(headers))})
        else:
            text = raw.decode("utf-8-sig")
            reader = csv.DictReader(io.StringIO(text))
            for row in reader:
                rows.append({(k or "").strip().lower(): v for k, v in row.items()})

        created = updated = skipped = unmatched = 0
        duplicates = 0
        messages = []
        Zone = self.env["shipblu.zone"].sudo()
        City = self.env["shipblu.city"].sudo()
        Gov = self.env["shipblu.governorate"].sudo()
        seen = set()
        ts = datetime.utcnow().isoformat()

        for row in rows:
            shipblu_id = row.get("shipblu_id") or row.get("zone_id") or row.get("id")
            name_val = row.get("name") or row.get("zone") or row.get("district")
            if not shipblu_id and not name_val:
                unmatched += 1
                continue
            key = str(shipblu_id or name_val)
            if key in seen:
                duplicates += 1
                continue
            seen.add(key)

            vals = {
                "name": str(name_val or key),
                "backend_id": self.backend_id.id,
                "company_id": self.backend_id.company_id.id,
            }
            if shipblu_id and str(shipblu_id).isdigit():
                vals["shipblu_id"] = int(shipblu_id)

            # Optional coverage flags if columns present — stored only if fields exist
            domain = [("backend_id", "=", self.backend_id.id)]
            if vals.get("shipblu_id"):
                domain.append(("shipblu_id", "=", vals["shipblu_id"]))
            else:
                domain.append(("name", "=", vals["name"]))

            existing = Zone.search(domain, limit=1)
            if self.dry_run:
                if existing:
                    updated += 1
                else:
                    created += 1
                continue

            if existing:
                existing.write({"name": vals["name"]})
                updated += 1
            else:
                if not vals.get("shipblu_id"):
                    unmatched += 1
                    messages.append(f"Skip (no shipblu_id): {vals['name']}")
                    continue
                # city/gov optional
                Zone.create(vals)
                created += 1

        summary = (
            f"dry_run={self.dry_run} created={created} updated={updated} "
            f"skipped={skipped} unmatched={unmatched} duplicates={duplicates} "
            f"source={self.filename} ts={ts}"
        )
        messages.insert(0, summary)
        self.result_log = "\n".join(messages)
        # Non-destructive: never delete coverage rows
        return {
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
        }
