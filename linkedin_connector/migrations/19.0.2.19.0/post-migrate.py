# -*- coding: utf-8 -*-
def migrate(cr, version):
    """Backfill normalized tokens / discovery schedule on existing ATS sources."""
    cr.execute(
        """
        UPDATE linkedin_ats_source
           SET board_token_normalized = lower(trim(board_token))
         WHERE board_token IS NOT NULL
           AND board_token <> ''
           AND (board_token_normalized IS NULL OR board_token_normalized = '')
           AND ats_type IN ('greenhouse', 'lever', 'ashby', 'workable')
        """
    )
    cr.execute(
        """
        UPDATE linkedin_ats_source
           SET careers_url_normalized = trim(trailing '/' from board_token),
               board_token_normalized = trim(trailing '/' from board_token)
         WHERE ats_type = 'company_ats'
           AND board_token IS NOT NULL
           AND board_token <> ''
           AND (careers_url_normalized IS NULL OR careers_url_normalized = '')
        """
    )
    cr.execute(
        """
        UPDATE linkedin_ats_source
           SET next_discovery_at = NOW() AT TIME ZONE 'UTC'
         WHERE next_discovery_at IS NULL
        """
    )
    cr.execute(
        """
        UPDATE linkedin_ats_source
           SET discovery_interval_minutes = 360
         WHERE discovery_interval_minutes IS NULL OR discovery_interval_minutes <= 0
        """
    )
    cr.execute(
        """
        UPDATE linkedin_ats_source
           SET discovery_priority = 100
         WHERE discovery_priority IS NULL
        """
    )
