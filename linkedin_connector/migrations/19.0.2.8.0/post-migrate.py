# -*- coding: utf-8 -*-
"""Classify existing LinkedIn accounts and backfill post content_purpose."""


def migrate(cr, version):
    cr.execute(
        """
        UPDATE linkedin_account
           SET account_type = 'company',
               fallback_personal_post = false
         WHERE COALESCE(linkedin_organization_id, '') <> ''
           AND (account_type IS NULL OR account_type = '')
        """
    )
    cr.execute(
        """
        UPDATE linkedin_account
           SET account_type = 'personal',
               fallback_personal_post = false,
               linkedin_organization_id = NULL,
               profile_url = COALESCE(
                   NULLIF(profile_url, ''),
                   'https://www.linkedin.com/in/sabry-youssef-56a878185/'
               )
         WHERE COALESCE(linkedin_organization_id, '') = ''
           AND (account_type IS NULL OR account_type = '')
        """
    )
    cr.execute(
        """
        UPDATE linkedin_account
           SET fallback_personal_post = false
         WHERE fallback_personal_post IS DISTINCT FROM false
        """
    )
    # content_purpose column added by ORM before post-migrate
    cr.execute(
        """
        UPDATE linkedin_post AS p
           SET content_purpose = 'company_marketing'
          FROM linkedin_account AS a
         WHERE p.account_id = a.id
           AND a.account_type = 'company'
           AND (p.content_purpose IS NULL OR p.content_purpose = '')
        """
    )
    cr.execute(
        """
        UPDATE linkedin_post AS p
           SET content_purpose = 'job_branding'
          FROM linkedin_account AS a
         WHERE p.account_id = a.id
           AND a.account_type = 'personal'
           AND (p.content_purpose IS NULL OR p.content_purpose = '')
        """
    )
    cr.execute(
        """
        UPDATE linkedin_post
           SET content_purpose = 'job_branding'
         WHERE content_purpose IS NULL OR content_purpose = ''
        """
    )
