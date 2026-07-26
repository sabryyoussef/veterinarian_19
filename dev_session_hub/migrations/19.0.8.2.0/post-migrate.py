# -*- coding: utf-8 -*-
"""Link TOURZ Dev Hub project to Torz OpenProject map when present. Additive only."""


def migrate(cr, version):
    if not version:
        return
    cr.execute(
        """
        SELECT EXISTS (
            SELECT 1 FROM information_schema.tables
            WHERE table_name = 'dev_project_openproject_map_rel'
        )
        """
    )
    if not cr.fetchone()[0]:
        return
    # Prefer maps for Torz OP project 6 and/or Odoo project 25; fall back to map id 22.
    cr.execute(
        """
        INSERT INTO dev_project_openproject_map_rel (dev_project_id, openproject_map_id)
        SELECT p.id, m.id
        FROM dev_project p
        JOIN openproject_project_map m
          ON (
                m.op_project_id = 6
             OR m.odoo_project_id = 25
             OR m.id = 22
          )
        WHERE p.code = 'TOURZ'
          AND COALESCE(m.active, true) = true
          AND NOT EXISTS (
              SELECT 1 FROM dev_project_openproject_map_rel r
              WHERE r.dev_project_id = p.id AND r.openproject_map_id = m.id
          )
        """
    )
