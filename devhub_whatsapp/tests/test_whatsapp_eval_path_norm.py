# -*- coding: utf-8 -*-
"""Path equivalence helpers for evaluation scoring."""
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install", "devhub_whatsapp")
class TestWhatsappEvalPathNorm(TransactionCase):
    def test_basename_and_absolute_equivalent(self):
        Eval = self.env["dev.whatsapp.analysis.eval"]
        self.assertTrue(
            Eval._paths_equivalent(
                "index.html",
                "/opt/localaddons/edafaa_student_profile/static/description/index.html",
            )
        )
        self.assertTrue(Eval._paths_equivalent("html4css1.css", "html4css1.css"))
        self.assertTrue(
            Eval._paths_equivalent(
                "static/description/index.html",
                "/x/y/static/description/index.html",
            )
        )

    def test_different_module_paths_not_equivalent(self):
        Eval = self.env["dev.whatsapp.analysis.eval"]
        self.assertFalse(
            Eval._paths_equivalent(
                "/opt/localaddons/edafaa_student_profile/static/description/index.html",
                "/opt/localaddons/batch_intake/static/description/index.html",
            )
        )
