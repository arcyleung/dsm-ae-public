import { firefox } from "playwright";
import path from "node:path";
import { fileURLToPath } from "node:url";
import fs from "node:fs";

const outDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../tmp-layout");
fs.mkdirSync(outDir, { recursive: true });
const base = process.env.BLOG_URL || "http://127.0.0.1:5174";

const browser = await firefox.launch();
const page = await browser.newPage({ viewport: { width: 1400, height: 900 } });
const errors = [];
page.on("pageerror", (e) => errors.push(String(e)));

async function shot(url, name) {
  await page.goto(url, { waitUntil: "networkidle", timeout: 30000 });
  await page.waitForTimeout(800);
  const file = path.join(outDir, name);
  await page.screenshot({ path: file, fullPage: false });
  const title = await page.title();
  const body = await page.locator("body").innerText();
  console.log(name, "title=", title, "chars=", body.length, "file=", file);
  return body;
}

const blog = await shot(base + "/", "blog.png");
const matrix = await shot(base + "/?tab=matrix", "matrix.png");
const traj = await shot(base + "/?tab=traj", "traj.png");

const checks = {
  blogHasHeading: /Diagnosing Agentic Behaviour/i.test(blog),
  matrixHasSyndrome: /Syndrome matrix/i.test(matrix),
  matrixHasMetrics: /Metric results/i.test(matrix),
  matrixHasTrees: /Decision trees/i.test(matrix),
  matrixNoIframe: !(await page.locator("iframe").count()),
  trajHasSessions: /sessions|featured|f4ac2beb/i.test(traj),
};
console.log("checks", checks);
console.log("pageerrors", errors);
await browser.close();
if (Object.values(checks).some((v) => !v) || errors.length) process.exit(1);
