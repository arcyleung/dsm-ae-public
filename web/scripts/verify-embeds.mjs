import { firefox } from "playwright";

const browser = await firefox.launch();
const page = await browser.newPage({ viewport: { width: 1400, height: 900 } });
const errors = [];
page.on("pageerror", (e) => errors.push(String(e)));
await page.goto("http://127.0.0.1:5174/", { waitUntil: "networkidle", timeout: 30000 });
await page.waitForTimeout(1200);
const text = await page.locator("body").innerText();
const checks = {
  hasMetrics: /Metric results/i.test(text),
  hasSyndrome: /Syndrome matrix/i.test(text),
  hasTraj: /185 permission refusals|f4ac2beb/i.test(text),
  trajText: "",
  iframe: await page.locator("iframe").count(),
  section3: /layered measurement approach/i.test(text),
  errors,
};
const trajEl = page.locator(".traj").first();
if (await trajEl.count()) {
  checks.trajText = await trajEl.innerText();
}
checks.has603 = /60306e4e/.test(checks.trajText);
checks.has796 = /796e0492/.test(checks.trajText);
console.log(checks);
const m = page.getByRole("heading", { name: /Metric results/i });
if (await m.count()) {
  await m.first().scrollIntoViewIfNeeded();
  await page.screenshot({ path: "/tmp/dsm-blog-verify/s12-metrics.png" });
}
const s = page.getByRole("heading", { name: /Syndrome matrix/i });
if (await s.count()) {
  await s.first().scrollIntoViewIfNeeded();
  await page.screenshot({ path: "/tmp/dsm-blog-verify/s12-syndromes.png" });
}
const t = page.locator(".traj").first();
if (await t.count()) {
  await t.scrollIntoViewIfNeeded();
  await page.screenshot({ path: "/tmp/dsm-blog-verify/s15-traj.png" });
}
await browser.close();
if (
  !checks.hasMetrics ||
  !checks.hasSyndrome ||
  !checks.hasTraj ||
  checks.has603 ||
  checks.has796 ||
  checks.iframe ||
  checks.section3 ||
  errors.length
) {
  process.exit(1);
}
