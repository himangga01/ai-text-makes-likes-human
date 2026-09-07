import { chromium } from "@playwright/test";
import { readFile, writeFile, access } from "node:fs/promises";
import { createHash } from "node:crypto";
export async function prepareIcon() {
  const svg = await readFile("assets/icon.svg", "utf8");
  const hash = createHash("sha256").update(svg).digest("hex");
  try { if ((await readFile("build-resources/icon.sha256", "utf8")) === hash) { await access("build-resources/icon.ico"); return; } } catch { /* build below */ }
  const browser = await chromium.launch({ headless: true });
  try {
    const page = await browser.newPage({ viewport: { width: 256, height: 256 }, deviceScaleFactor: 1 });
    await page.setContent(`<style>body{margin:0}</style>${svg}`);
    const png = await page.screenshot({ omitBackground: true });
    const header = Buffer.alloc(22); header.writeUInt16LE(1, 2); header.writeUInt16LE(1, 4);
    header.writeUInt16LE(1, 10); header.writeUInt16LE(32, 12); header.writeUInt32LE(png.length, 14); header.writeUInt32LE(22, 18);
    await writeFile("build-resources/icon.ico", Buffer.concat([header, png]));
    await writeFile("build-resources/icon.png", png); await writeFile("build-resources/icon.sha256", hash);
  } finally { await browser.close(); }
}
