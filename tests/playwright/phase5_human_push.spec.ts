import { test, expect, request as playwrightRequest } from "@playwright/test";
import type { APIRequestContext, Page } from "@playwright/test";
import { execFileSync } from "child_process";
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
  "../../dev_session_hub/docs/uat/phase5_human_push_20260719",
);
const SHOTS = path.join(ROOT, "screenshots");
const REMOTE_HOST = "sabry3@sabry3-precision-5540.tailcf9988.ts.net";
const REMOTE_REPO = "/srv/devhub-uat/remotes/petspot-human-push-uat.git";
const SSH = [
  "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
  "-o", "StrictHostKeyChecking=yes", REMOTE_HOST,
];
const WORKSPACE_ID = 11;
const MESSAGE =
  "[DW-7] Add human Push contract test\n\n" +
  "Work Item: DW-7\nApproved Plan revision: 1\nTests: targeted 2/2; regression 2/2.";
type Row = Record<string, any>;
let api: APIRequestContext;

function remote(command: string): string {
  return execFileSync("ssh", [...SSH, command], {
    encoding: "utf8",
    timeout: 120_000,
  }).trim();
}

function evidence(name: string, content: string): void {
  fs.writeFileSync(path.join(ROOT, name), content.trim() + "\n", {
    encoding: "utf8",
    mode: 0o600,
  });
}

async function gotoModel(page: Page, model: string, id: number): Promise<void> {
  await page.goto(`${process.env.ODOO_TEST_URL}/odoo/${model}/${id}`, {
    waitUntil: "domcontentloaded",
    timeout: 60_000,
  });
  await expect(page.locator(".o_form_view, .o_form_sheet").first()).toBeVisible({
    timeout: 45_000,
  });
}

async function shot(page: Page, name: string): Promise<void> {
  await page.screenshot({ path: path.join(SHOTS, name), fullPage: true });
}

async function confirmButton(page: Page, name: RegExp): Promise<void> {
  await page.getByRole("button", { name }).first().click();
  const dialog = page.locator(".modal-dialog").last();
  if (await dialog.isVisible({ timeout: 3000 }).catch(() => false)) {
    await dialog.getByRole("button", { name: /Confirm|Ok|Continue/i }).last().click();
  }
}

async function state(): Promise<string> {
  return (
    await callKw<Row[]>(api, "dev.execution.workspace", "read", [[WORKSPACE_ID]], {
      fields: ["state"],
    })
  )[0].state;
}

test.beforeAll(async () => {
  assertTestEnvironment();
  expect(ODOO_DB).toBe("devhub_isolation_uat");
  fs.mkdirSync(SHOTS, { recursive: true, mode: 0o700 });
  api = await playwrightRequest.newContext();
  await authenticateApi(api);
});

test.afterAll(async () => api?.dispose());

test("human approves one exact normal Push and execution stops", async ({ page }) => {
  const workspace = (
    await callKw<Row[]>(api, "dev.execution.workspace", "read", [[WORKSPACE_ID]], {
      fields: ["state", "execution_branch", "worktree_path", "base_head"],
    })
  )[0];
  expect(["review_required", "committed_reviewed"]).toContain(workspace.state);
  const remoteBefore = remote(
    `set -eu; sudo -u devworker git --git-dir=${REMOTE_REPO} for-each-ref --format='%(refname) %(objectname)' | sort`,
  );
  const mainBefore = remote(
    "set -eu; git -C /srv/devhub-uat/manual/petspot-uat rev-parse HEAD; " +
    "git -C /srv/devhub-uat/manual/petspot-uat status --porcelain=v1 -z | sha256sum | cut -d' ' -f1",
  );

  await loginUi(page);
  if (workspace.state === "review_required") {
    await gotoModel(page, "dev.execution.workspace", WORKSPACE_ID);
    await page.getByRole("button", { name: "Approve Git Commit" }).click();
    await page.getByRole("tab", { name: "Commit Message" }).click();
    await page
      .locator('.o_field_widget[name="commit_message"]:visible textarea')
      .fill(MESSAGE);
    await page
      .getByRole("button", { name: /Record Exact-State Commit Approval/i })
      .click();
    await expect.poll(state, { timeout: 30_000 }).toBe("commit_approved");
    await gotoModel(page, "dev.execution.workspace", WORKSPACE_ID);
    await page.getByRole("button", { name: "Create Approved Commit" }).click();
    await confirmButton(page, /Confirm and Create One Local Commit/i);
    await expect.poll(state, { timeout: 45_000 }).toBe("committed_reviewed");
  }

  await gotoModel(page, "dev.execution.workspace", WORKSPACE_ID);
  await page.getByRole("tab", { name: "Review Git Push" }).click();
  await shot(page, "01_committed_reviewed.png");
  await page.getByRole("button", { name: "Review Push Target" }).click();
  await gotoModel(page, "dev.execution.workspace", WORKSPACE_ID);
  await page.getByRole("tab", { name: "Review Git Push" }).click();
  await shot(page, "02_push_review.png");

  await page.getByRole("button", { name: "Approve Git Push" }).click();
  await expect(
    page.locator('.o_field_widget[name="confirmation_text"]:visible').first(),
  ).toContainText(/It will not create a PR, merge, or deploy/i);
  await page
    .locator('.o_field_widget[name="confirm_exact_push"]:visible input[type="checkbox"]')
    .check();
  await shot(page, "03_push_approval.png");
  await page.getByRole("button", { name: /Record Exact Push Approval/i }).click();
  await expect.poll(state, { timeout: 30_000 }).toBe("push_approved");

  const approved = (
    await callKw<Row[]>(api, "dev.execution.workspace", "read", [[WORKSPACE_ID]], {
      fields: ["push_approval_id", "committed_sha"],
    })
  )[0];
  const approval = (
    await callKw<Row[]>(
      api,
      "dev.git.push.approval",
      "read",
      [[approved.push_approval_id[0]]],
      {
        fields: [
          "remote_name", "remote_branch", "remote_head_before", "commit_sha",
          "approver_id", "binding_hash", "push_mode",
        ],
      },
    )
  )[0];
  expect(approval.commit_sha).toBe(approved.committed_sha);
  expect(approval.remote_branch).toBe(workspace.execution_branch);
  expect(approval.push_mode).toBe("normal");

  await gotoModel(page, "dev.execution.workspace", WORKSPACE_ID);
  await page.getByRole("button", { name: "Push Approved Commit" }).click();
  await expect(
    page.locator('.o_field_widget[name="confirmation_text"]:visible').first(),
  ).toContainText(/It will not create a PR, merge, or deploy/i);
  await page
    .locator('.o_field_widget[name="confirm_push_now"]:visible input[type="checkbox"]')
    .check();
  await shot(page, "04_push_confirmation.png");
  await confirmButton(page, /Confirm and Push One Branch/i);
  await expect.poll(state, { timeout: 60_000 }).toBe("pushed_reviewed");

  await gotoModel(page, "dev.execution.workspace", WORKSPACE_ID);
  await page.getByRole("tab", { name: "Review Git Push" }).click();
  await shot(page, "05_push_success.png");
  const final = (
    await callKw<Row[]>(api, "dev.execution.workspace", "read", [[WORKSPACE_ID]], {
      fields: ["push_record_id", "pushed_at", "current_head", "committed_sha"],
    })
  )[0];
  const record = (
    await callKw<Row[]>(
      api,
      "dev.git.push.record",
      "read",
      [[final.push_record_id[0]]],
      {
        fields: [
          "result", "verification_result", "remote_head_before",
          "remote_head_after", "commit_sha", "remote_branch",
        ],
      },
    )
  )[0];
  expect(record.result).toBe("success");
  expect(record.remote_head_after).toBe(final.committed_sha);
  expect(final.current_head).toBe(final.committed_sha);
  await gotoModel(page, "dev.git.push.record", final.push_record_id[0]);
  await shot(page, "06_remote_verification.png");
  await gotoModel(page, "dev.execution.workspace", WORKSPACE_ID);
  await shot(page, "07_pushed_reviewed_final.png");

  const remoteAfter = remote(
    `set -eu; sudo -u devworker git --git-dir=${REMOTE_REPO} for-each-ref --format='%(refname) %(objectname)' | sort`,
  );
  expect(remoteAfter).toContain(
    `refs/heads/${workspace.execution_branch} ${final.committed_sha}`,
  );
  expect(
    remote(
      "set -eu; git -C /srv/devhub-uat/manual/petspot-uat rev-parse HEAD; " +
      "git -C /srv/devhub-uat/manual/petspot-uat status --porcelain=v1 -z | sha256sum | cut -d' ' -f1",
    ),
  ).toBe(mainBefore);
  evidence(
    "sanitized_git_remote_before_after.txt",
    `BEFORE\n${remoteBefore || "(no refs)"}\nAFTER\n${remoteAfter}\n`,
  );
  evidence(
    "push_metadata.txt",
    JSON.stringify(
      {
        workspace_id: WORKSPACE_ID,
        branch: workspace.execution_branch,
        commit_sha: final.committed_sha,
        remote: approval.remote_name,
        remote_branch: approval.remote_branch,
        approval_id: approved.push_approval_id[0],
        approver: approval.approver_id[1],
        pre_push_remote_head: approval.remote_head_before || null,
        post_push_remote_head: record.remote_head_after,
        result: record.result,
        verification: record.verification_result,
        pr_created: false,
        merged: false,
        deployed: false,
      },
      null,
      2,
    ),
  );
});
