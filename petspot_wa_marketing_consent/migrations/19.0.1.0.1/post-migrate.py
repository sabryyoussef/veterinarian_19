# -*- coding: utf-8 -*-
def migrate(cr, version):
    """Archive historical v1 + candidate draft v1.1; keep approved v1.1 active."""
    cr.execute(
        """
        UPDATE petspot_wa_consent_wording
           SET active = CASE
                WHEN version IN ('clinic_v1_1_approved', 'staff_v1_1_approved') THEN TRUE
                WHEN version IN ('clinic_v1', 'staff_v1', 'clinic_v1_1', 'staff_v1_1') THEN FALSE
                ELSE active
           END
        """
    )
