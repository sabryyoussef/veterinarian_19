# -*- coding: utf-8 -*-
"""Mark historical assessments that used the pre-separation combined cost model."""


def migrate(cr, version):
    cr.execute(
        """
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'petspot_vetution_shadow_assessment'
          AND column_name = 'legacy_combined_cost_model'
        """
    )
    if not cr.fetchone():
        return
    # Rows assessed before this module version lack the new economics fields
    # being populated at create time with legacy_combined_cost_model=False.
    # Mark pre-existing rows as legacy when recommended_product_price is null
    # and they already have a landed_cost (old combined worksheet).
    cr.execute(
        """
        UPDATE petspot_vetution_shadow_assessment
           SET legacy_combined_cost_model = TRUE
         WHERE COALESCE(legacy_combined_cost_model, FALSE) = FALSE
           AND recommended_product_price IS NULL
           AND landed_cost IS NOT NULL
           AND create_date < NOW()
        """
    )
