import { defineConfig } from "@playwright/test";
import path from "path";
import fs from "fs";
import { fileURLToPath } from "url";

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

const chromePath = resolveChromePath();

export default defineConfig({
  testDir: ".",
  testMatch: "**/*.spec.ts",
  timeout: 600_000,
  expect: { timeout: 45_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [["list"], ["html", { open: "never", outputFolder: "report" }]],
  use: {
    trace: "retain-on-failure",
    screenshot: "off",
    video: "off",
    headless: true,
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
      use: {
        browserName: "chromium",
      },
    },
  ],
  outputDir: path.join(__dirname, "test-results"),
});
