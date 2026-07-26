import { defineConfig } from "@playwright/test";
import path from "path";
import fs from "fs";
import { fileURLToPath } from "url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

function resolveChromePath() {
  if (process.env.PLAYWRIGHT_CHROME_PATH) {
    return process.env.PLAYWRIGHT_CHROME_PATH;
  }
  const browsersRoot = path.join(
    "/home/sabry/odoo_base/base_odoo_19/projects/tours-trading/tests/playwright/browsers/chrome",
  );
  if (!fs.existsSync(browsersRoot)) {
    return undefined;
  }
  for (const ver of fs.readdirSync(browsersRoot)) {
    const candidate = path.join(browsersRoot, ver, "chrome-linux64", "chrome");
    if (fs.existsSync(candidate)) {
      return candidate;
    }
  }
  return undefined;
}

const chromePath = resolveChromePath();

export default defineConfig({
  testDir: ".",
  testMatch: "**/*uat.spec.ts",
  timeout: 300_000,
  expect: { timeout: 45_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  use: {
    headless: true,
    trace: "retain-on-failure",
    screenshot: "off",
    video: "off",
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
  projects: [{ name: "chromium", use: { browserName: "chromium" } }],
  outputDir: path.join(__dirname, "test-results"),
});
