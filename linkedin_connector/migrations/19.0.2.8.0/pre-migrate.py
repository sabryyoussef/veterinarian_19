# -*- coding: utf-8 -*-
"""Pre-create account_type so required column upgrade does not fail on existing rows."""


def migrate(cr, version):
    cr.execute(
        """
        SELECT 1 FROM information_schema.tables
         WHERE table_name = 'linkedin_account'
        """
    )
    if not cr.fetchone():
        return
    cr.execute(
        """
        SELECT 1 FROM information_schema.columns
         WHERE table_name = 'linkedin_account' AND column_name = 'account_type'
        """
    )
    if not cr.fetchone():
        cr.execute(
            "ALTER TABLE linkedin_account ADD COLUMN account_type VARCHAR"
        )
    cr.execute(
        """
        UPDATE linkedin_account
           SET account_type = 'company'
         WHERE COALESCE(linkedin_organization_id, '') <> ''
           AND (account_type IS NULL OR account_type = '')
        """
    )
    cr.execute(
        """
        UPDATE linkedin_account
           SET account_type = 'personal'
         WHERE COALESCE(linkedin_organization_id, '') = ''
           AND (account_type IS NULL OR account_type = '')
        """
    )
    # Remaining unknowns → company if any org-like name else personal
    cr.execute(
        """
        UPDATE linkedin_account
           SET account_type = 'personal'
         WHERE account_type IS NULL OR account_type = ''
        """
    )
