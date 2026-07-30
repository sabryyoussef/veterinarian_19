import { test, expect } from "@playwright/test";
import * as path from "path";
import { LoginPage } from "./pages/login.page.js";
import { LandedCostPolicyPage } from "./pages/landed_cost.page.js";
import { ShadowAssessmentPage } from "./pages/shadow_assessment.page.js";
import { InquiryPage } from "./pages/inquiry.page.js";
import { OdooRpc, openModelForm } from "./helpers/odoo_rpc.js";
import { getEvidence } from "./helpers/evidence.js";
import { runShellWorkflow } from "./helpers/shell_runner.js";
import {
  TEST_DB,
  odooDb,
  odooPassword,
  requireCredentials,
} from "./helpers/env.js";

test.describe.configure({ mode: "serial" });

test.describe("@test-synthetic PetSpot TEST synthetic pickup", () => {
  test.beforeEach(() => {
    test.skip(
      !odooPassword(),
      "BLOCKED_MISSING_UI_CREDENTIALS: set ODOO_PASSWORD",
    );
    test.skip(
      odooDb() !== TEST_DB && process.env.PETSPOT_PW_ENV !== "test",
      `TEST suite requires ODOO_DB=${TEST_DB}`,
    );
  });

  test("pickup lifecycle with screenshots + cleanup", async ({
    page,
    request,
  }, testInfo) => {
    requireCredentials();
    const evidence = getEvidence(testInfo);
    const runId = evidence.runId;
    const outDir = path.join(evidence.root, "shell");
    const activateOut = path.join(outDir, "activate.json");
    const pickupOut = path.join(outDir, "pickup.json");
    const cleanupOut = path.join(outDir, "cleanup.json");

    let cleanupOk = false;
    try {
      const activated = runShellWorkflow("activate_synthetic", {
        runId,
        outPath: activateOut,
      });
      evidence.appendLog(`activated policy=${activated.policy_id}`);

      const rpc = new OdooRpc(request);
      await rpc.authenticate();
      const login = new LoginPage(page);
      await login.login();

      const policyPage = new LandedCostPolicyPage(page, rpc);
      const synthetic = await policyPage.findSynthetic();
      expect(synthetic?.active).toBeTruthy();
      if (synthetic) {
        await policyPage.open(synthetic.id as number);
        await evidence.shot(page, "20-test-synthetic-policy.png", {
          testId: "test-policy",
          environment: "test",
          scenario: "Synthetic policy active",
          result: "pass",
          recordId: String(synthetic.id),
        });
      }

      const pickup = runShellWorkflow("pickup_lifecycle", {
        runId,
        outPath: pickupOut,
      });
      evidence.writeJson("pickup-lifecycle.json", pickup);

      const inquiryPage = new InquiryPage(page, rpc);
      await inquiryPage.open(pickup.inquiry_id as number);
      await evidence.shot(page, "21-test-pickup-inquiry.png", {
        testId: "test-pickup-inquiry",
        environment: "test",
        scenario: "Pickup inquiry",
        result: "pass",
        recordId: String(pickup.inquiry_id),
      });

      const shadow = new ShadowAssessmentPage(page, rpc);
      await shadow.open(pickup.assessment_id as number);
      await evidence.shot(page, "22-test-pickup-assessment.png", {
        testId: "test-pickup-assessment",
        environment: "test",
        scenario: "Shadow assessment",
        result: "pass",
        recordId: String(pickup.assessment_id),
        notes: `state=${pickup.assessment_state}`,
      });

      await openModelForm(
        page,
        "petspot.vetution.quotation.ledger",
        pickup.ledger_id as number,
      );
      await evidence.shot(page, "23-test-pickup-quotation.png", {
        testId: "test-pickup-quote",
        environment: "test",
        scenario: "Auto quotation",
        result: "pass",
        recordId: String(pickup.ledger_id),
        notes: `product=${pickup.product_price} delivery=${pickup.delivery_charge}`,
      });
      expect(Number(pickup.delivery_charge || 0)).toBe(0);
      expect(Number(pickup.product_price || 0)).toBeGreaterThan(0);

      await openModelForm(
        page,
        "petspot.vetution.payment.trust",
        pickup.payment_id as number,
      );
      await evidence.shot(page, "24-test-pickup-payment-trust.png", {
        testId: "test-pickup-payment",
        environment: "test",
        scenario: "Payment trust",
        result: "pass",
        recordId: String(pickup.payment_id),
      });

      if (pickup.po_id) {
        await openModelForm(page, "purchase.order", pickup.po_id as number);
        await evidence.shot(page, "25-test-draft-rfq.png", {
          testId: "test-pickup-rfq",
          environment: "test",
          scenario: "Draft RFQ/PO",
          result: "pass",
          recordId: String(pickup.po_id),
          notes: `state=${pickup.po_state}`,
        });
      }

      await openModelForm(
        page,
        "petspot.fulfillment.case",
        pickup.case_id as number,
      );
      await evidence.shot(page, "26-test-giza-receipt.png", {
        testId: "test-pickup-receipt",
        environment: "test",
        scenario: "Case after Giza receipt",
        result: "pass",
        recordId: String(pickup.case_id),
      });
      await evidence.shot(page, "27-test-pickup-completed.png", {
        testId: "test-pickup-complete",
        environment: "test",
        scenario: "Pickup completed",
        result: "pass",
        recordId: String(pickup.case_id),
        notes: `case_state=${pickup.case_state} awb_count=${pickup.awb_count}`,
      });

      expect(pickup.message_transport).toBe("mock");
      expect(String(pickup.message_state)).toMatch(/sent/i);
      expect(Number(pickup.awb_count || 0)).toBe(0);
    } finally {
      try {
        const cleanup = runShellWorkflow("cleanup_synthetic", {
          runId,
          outPath: cleanupOut,
        });
        evidence.writeJson("test-cleanup.json", cleanup);
        cleanupOk = cleanup.synthetic_active === false;
        await evidence.shot(page, "29-test-cleanup-policy.png", {
          testId: "test-cleanup",
          environment: "test",
          scenario: "Deactivate synthetic policy",
          result: cleanupOk ? "pass" : "FAIL_TEST_CLEANUP",
          notes: JSON.stringify({
            synthetic_active: cleanup.synthetic_active,
            commercial_active_id: cleanup.commercial_active_id,
          }),
        });
      } catch (err) {
        evidence.writeJson("test-cleanup.json", {
          ok: false,
          error: String(err),
        });
        evidence.recordResult({
          testId: "test-cleanup",
          environment: "test",
          scenario: "Cleanup",
          result: "FAIL_TEST_CLEANUP",
          screenshot: "",
          recordId: "",
          notes: String(err),
        });
      }
    }
    expect(cleanupOk, "FAIL_TEST_CLEANUP").toBeTruthy();
  });
});
