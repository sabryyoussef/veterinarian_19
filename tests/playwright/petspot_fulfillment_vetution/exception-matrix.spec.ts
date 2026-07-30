import { test, expect } from "@playwright/test";
import * as path from "path";
import { LoginPage } from "./pages/login.page.js";
import { OdooRpc, openAction } from "./helpers/odoo_rpc.js";
import { getEvidence } from "./helpers/evidence.js";
import { runShellWorkflow } from "./helpers/shell_runner.js";
import {
  ACTION_XML,
  TEST_DB,
  odooDb,
  odooPassword,
  requireCredentials,
} from "./helpers/env.js";

test.describe.configure({ mode: "serial" });

test.describe("@test-synthetic PetSpot exception matrix", () => {
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

  test("exception matrix scenarios", async ({ page, request }, testInfo) => {
    requireCredentials();
    const evidence = getEvidence(testInfo);
    const runId = `${evidence.runId}-EX`;
    const outDir = path.join(evidence.root, "shell");
    const activateOut = path.join(outDir, "activate-ex.json");
    const matrixOut = path.join(outDir, "exception-matrix.json");
    const cleanupOut = path.join(outDir, "cleanup-ex.json");

    let cleanupOk = false;
    try {
      runShellWorkflow("activate_synthetic", { runId, outPath: activateOut });
      const matrix = runShellWorkflow("exception_matrix", {
        runId,
        outPath: matrixOut,
      });
      evidence.writeJson("exception-matrix.json", matrix);

      const rows = (matrix.matrix as Array<Record<string, string>>) || [];
      const failed = rows.filter((r) => r.result === "fail");
      const notAuto = rows.filter((r) =>
        String(r.result).startsWith("NOT_AUTOMATED"),
      );

      const rpc = new OdooRpc(request);
      await rpc.authenticate();
      const login = new LoginPage(page);
      await login.login();
      try {
        const actionId = await rpc.actionXmlIdToId(ACTION_XML.shadow_assessments);
        await openAction(page, actionId, {
          model: "petspot.vetution.shadow.assessment",
        });
      } catch (err) {
        evidence.appendLog(`shadow_list_nav_failed ${String(err)}`);
        // Still capture whatever is on screen for evidence
      }

      // Representative evidence shots for blocked scenarios
      await evidence.shot(page, "40-test-stale-supplier-blocked.png", {
        testId: "ex-3.4.2",
        environment: "test",
        scenario: "Stale supplier (matrix)",
        result: rows.find((r) => r.id === "3.4.2")?.result || "missing",
        notes: rows.find((r) => r.id === "3.4.2")?.notes || "",
      });
      await evidence.shot(page, "41-test-missing-mapping-blocked.png", {
        testId: "ex-3.4.3",
        environment: "test",
        scenario: "Missing mapping",
        result: rows.find((r) => r.id === "3.4.3")?.result || "missing",
        notes: rows.find((r) => r.id === "3.4.3")?.notes || "",
      });
      await evidence.shot(page, "42-test-price-review-required.png", {
        testId: "ex-3.4.7",
        environment: "test",
        scenario: "Price review ~11%",
        result: rows.find((r) => r.id === "3.4.7")?.result || "missing",
        notes: rows.find((r) => r.id === "3.4.7")?.notes || "",
      });
      await evidence.shot(page, "43-test-unsigned-payment-rejected.png", {
        testId: "ex-3.4.16",
        environment: "test",
        scenario: "Unsigned Paymob rejected",
        result: rows.find((r) => r.id === "3.4.16")?.result || "missing",
        notes: rows.find((r) => r.id === "3.4.16")?.notes || "",
      });
      await evidence.shot(page, "44-test-wrong-payment-amount-rejected.png", {
        testId: "ex-3.4.17",
        environment: "test",
        scenario: "Wrong payment amount",
        result: rows.find((r) => r.id === "3.4.17")?.result || "missing",
        notes: rows.find((r) => r.id === "3.4.17")?.notes || "",
      });

      for (const row of rows) {
        evidence.recordResult({
          testId: row.id,
          environment: "test",
          scenario: `Exception ${row.id}`,
          result: row.result,
          screenshot: "",
          recordId: "",
          notes: row.notes || "",
        });
      }

      expect(failed, JSON.stringify(failed)).toEqual([]);
      evidence.appendLog(
        `exception_matrix not_automated=${notAuto.map((r) => r.id).join(",")}`,
      );
    } finally {
      try {
        const cleanup = runShellWorkflow("cleanup_synthetic", {
          runId,
          outPath: cleanupOut,
        });
        evidence.writeJson("test-cleanup-exception.json", cleanup);
        cleanupOk = cleanup.synthetic_active === false;
      } catch (err) {
        evidence.writeJson("test-cleanup-exception.json", {
          ok: false,
          error: String(err),
        });
      }
    }
    expect(cleanupOk, "FAIL_TEST_CLEANUP").toBeTruthy();
  });
});
