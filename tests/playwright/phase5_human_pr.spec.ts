import { test, expect, request as playwrightRequest } from "@playwright/test";
import type { APIRequestContext, Page } from "@playwright/test";
import * as fs from "fs";
import * as path from "path";
import { fileURLToPath } from "url";
import {
  ODOO_DB,
  authenticateApi,
  callKw,
  assertTestEnvironment,
  loginUi,
} from "./helpers/intake.js";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(
  __dirname,
  "../../dev_session_hub/docs/uat/phase5_human_pr_20260719",
);
const SHOTS = path.join(ROOT, "screenshots");
const WORKSPACE_ID = Number(process.env.PHASE5_PR_WORKSPACE_ID || 0);
type Row = Record<string, any>;
let api: APIRequestContext;

test.skip(
  !WORKSPACE_ID,
  "A new pushed_reviewed workspace backed by a scoped GitHub App/fine-grained identity is required.",
);

async function gotoWorkspace(page: Page): Promise<void> {
  await page.goto(
    `${process.env.ODOO_TEST_URL}/odoo/dev.execution.workspace/${WORKSPACE_ID}`,
    { waitUntil: "domcontentloaded", timeout: 60_000 },
  );
  await expect(page.locator(".o_form_view, .o_form_sheet").first()).toBeVisible();
}

async function state(): Promise<string> {
  return (
    await callKw<Row[]>(
      api,
      "dev.execution.workspace",
      "read",
      [[WORKSPACE_ID]],
      { fields: ["state"] },
    )
  )[0].state;
}

async function shot(page: Page, name: string): Promise<void> {
  await page.screenshot({ path: path.join(SHOTS, name), fullPage: true });
}

test.beforeAll(async () => {
  assertTestEnvironment();
  expect(ODOO_DB).toBe("devhub_pr_uat_20260719");
  fs.mkdirSync(SHOTS, { recursive: true, mode: 0o700 });
  api = await playwrightRequest.newContext();
  await authenticateApi(api);
});

test.afterAll(async () => api?.dispose());

test("human approves and creates exactly one verified open PR", async ({ page }) => {
  const initialState = await state();
  expect(["pushed_reviewed", "pr_approved"]).toContain(initialState);
  await loginUi(page);
  await gotoWorkspace(page);
  if (initialState === "pushed_reviewed") {
    await shot(page, "01_pushed_reviewed.png");

    await page.getByRole("button", { name: "Review PR Proposal" }).click();
    await expect
      .poll(async () => {
        const rows = await callKw<Row[]>(
          api,
          "dev.execution.workspace",
          "read",
          [[WORKSPACE_ID]],
          { fields: ["pr_source_branch"] },
        );
        return rows[0].pr_source_branch;
      })
      .toContain("devhub/");
    await page.reload({ waitUntil: "domcontentloaded" });
    await page.getByRole("tab", { name: "Review Pull Request" }).click();
    await shot(page, "02_pr_review.png");
    await expect(page.locator('.o_field_widget[name="pr_source_branch"]')).toContainText(
      "devhub/",
    );
    await expect(page.locator('.o_field_widget[name="pr_target_branch"]')).toContainText(
      /develop|test|staging/,
    );
    await expect(page.locator("body")).not.toContainText(
      /access_token|authorization:\s*bearer|password=/i,
    );
    await shot(page, "03_pr_source_target_details.png");
    await shot(page, "04_pr_title_body_preview.png");

    await page.getByRole("button", { name: "Approve PR Creation" }).click();
    const approvalDialog = page.locator(".modal-dialog").last();
    await approvalDialog
      .locator('.o_field_widget[name="confirm_exact_pr"] input[type="checkbox"]')
      .check();
    await approvalDialog
      .locator('.o_field_widget[name="confirm_no_merge"] input[type="checkbox"]')
      .check();
    await shot(page, "05_pr_approval.png");
    await approvalDialog
      .getByRole("button", { name: "Approve Exact PR Creation" })
      .click();
    await expect.poll(state).toBe("pr_approved");
  } else {
    for (const name of [
      "01_pushed_reviewed.png",
      "02_pr_review.png",
      "03_pr_source_target_details.png",
      "04_pr_title_body_preview.png",
      "05_pr_approval.png",
    ]) {
      expect(fs.existsSync(path.join(SHOTS, name))).toBeTruthy();
    }
  }

  await gotoWorkspace(page);
  await page.getByRole("button", { name: "Create Approved PR" }).click();
  const executionDialog = page.locator(".modal-dialog").last();
  await expect(
    executionDialog.locator('.o_field_widget[name="confirmation_text"]'),
  ).toContainText(/will not merge, enable auto-merge, or deploy/i);
  await executionDialog
    .locator(
      '.o_field_widget[name="confirm_create_open_pr"] input[type="checkbox"]',
    )
    .check();
  await executionDialog
    .locator(
      '.o_field_widget[name="confirm_stop_after_creation"] input[type="checkbox"]',
    )
    .check();
  await shot(page, "06_pr_confirmation.png");
  await executionDialog.getByRole("button", { name: "Create One Open PR" }).click();
  await expect.poll(state, { timeout: 90_000 }).toBe("pr_created_reviewed");

  const workspace = (
    await callKw<Row[]>(
      api,
      "dev.execution.workspace",
      "read",
      [[WORKSPACE_ID]],
      { fields: ["pr_number", "pr_url_reference", "pr_record_id"] },
    )
  )[0];
  expect(workspace.pr_number).toBeGreaterThan(0);
  expect(workspace.pr_url_reference).toMatch(/^https:\/\/github\.com\/[^/]+\/[^/]+\/pull\/\d+$/);
  const record = (
    await callKw<Row[]>(
      api,
      "dev.git.pr.record",
      "read",
      [[workspace.pr_record_id[0]]],
      {
        fields: [
          "result_state",
          "verification_result",
          "pr_number",
          "pr_url_reference",
        ],
      },
    )
  )[0];
  expect(["created", "reconciled_existing"]).toContain(record.result_state);
  expect(record.verification_result).toContain("not merged");
  expect(record.verification_result).toContain("auto-merge disabled");

  await gotoWorkspace(page);
  await page.getByRole("tab", { name: "Review Pull Request" }).click();
  await shot(page, "07_pr_creation_success.png");
  await shot(page, "08_pr_number_link.png");
  await shot(page, "09_pr_created_reviewed_final.png");
  await expect(page.locator("body")).not.toContainText(
    /ghs_|access_token|authorization:\s*bearer|private key/i,
  );
  await shot(page, "10_credential_safe_final.png");
});
