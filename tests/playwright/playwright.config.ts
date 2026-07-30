import { defineConfig } from "@playwright/test";
import path from "path";
import fs from "fs";
import { fileURLToPath } from "url";
import os from "os";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

function resolveChromePath(): string | undefined {
  if (process.env.PLAYWRIGHT_CHROME_PATH) {
    return process.env.PLAYWRIGHT_CHROME_PATH;
  }
  const browsersRoot = path.join(__dirname, "browsers", "chrome");
  if (!fs.existsSync(browsersRoot)) {
    return undefined;
  }
  const versions = fs.readdirSync(browsersRoot);
  for (const ver of versions) {
    const candidate = path.join(browsersRoot, ver, "chrome-linux64", "chrome");
    if (fs.existsSync(candidate)) {
      return candidate;
    }
  }
  return undefined;
}

function evidenceRoot(): string {
  if (process.env.PETSPOT_PW_EVIDENCE_DIR) {
    return process.env.PETSPOT_PW_EVIDENCE_DIR;
  }
  const stamp = new Date()
    .toISOString()
    .replace(/[-:]/g, "")
    .replace(/\.\d+Z$/, "Z");
  const dir = path.join(
    os.homedir(),
    ".cursor",
    "evidence",
    `petspot-playwright-uat-${stamp}`,
  );
  fs.mkdirSync(dir, { recursive: true });
  process.env.PETSPOT_PW_EVIDENCE_DIR = dir;
  return dir;
}

const chromePath = resolveChromePath();
const evidenceDir = evidenceRoot();

export default defineConfig({
  testDir: ".",
  testMatch: "**/*.spec.ts",
  timeout: 600_000,
  expect: { timeout: 45_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [
    ["list"],
    [
      "html",
      {
        open: "never",
        outputFolder: path.join(evidenceDir, "playwright-report"),
      },
    ],
    ["json", { outputFile: path.join(evidenceDir, "results.json") }],
  ],
  use: {
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
    headless: process.env.PW_HEADED === "1" ? false : true,
    ignoreHTTPSErrors: true,
    ...(chromePath
      ? {
          launchOptions: {
            executablePath: chromePath,
            args: ["--no-sandbox", "--disable-dev-shm-usage"],
          },
        }
      : {}),
  },
  projects: [
    {
      name: "chromium",
      testIgnore: ["**/petspot_fulfillment_vetution/**"],
      use: { browserName: "chromium" },
    },
    {
      name: "production-shadow",
      testMatch: [
        "**/petspot_fulfillment_vetution/production-shadow.spec.ts",
        "**/petspot_fulfillment_vetution/my-work.spec.ts",
      ],
      grep: /@production-shadow/,
      use: {
        browserName: "chromium",
        baseURL: process.env.ODOO_URL || "http://127.0.0.1:8027",
      },
    },
    {
      name: "test-synthetic",
      testMatch: [
        "**/petspot_fulfillment_vetution/test-synthetic-*.spec.ts",
        "**/petspot_fulfillment_vetution/exception-matrix.spec.ts",
        "**/petspot_fulfillment_vetution/my-work.spec.ts",
      ],
      grep: /@test-synthetic/,
      use: {
        browserName: "chromium",
        baseURL: process.env.ODOO_URL || "http://127.0.0.1:8028",
      },
    },
  ],
  outputDir: path.join(evidenceDir, "test-results"),
});
