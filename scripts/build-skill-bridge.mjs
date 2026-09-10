import { build } from 'esbuild';
import { mkdir } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
export async function buildSkillBridge() {
  const browser = await build({ entryPoints: [path.join(root, 'scripts/skill-comparison-browser.js')], bundle: true,
    write: false, platform: 'browser', format: 'iife', target: 'es2022', minify: true,
    define: { 'import.meta.url': '"file:///unused-worker"' } });
  const destination = path.join(root, 'build-resources/skill-bridge/skill-bridge.cjs');
  await mkdir(path.dirname(destination), { recursive: true });
  await build({ entryPoints: [path.join(root, 'scripts/skill-bridge.ts')], outfile: destination,
    bundle: true, platform: 'node', format: 'cjs', target: 'node24',
    // Worker code is tree-shaken out; the artifact uses only precomputed diff and copy.
    define: { COMPARISON_BROWSER: JSON.stringify(browser.outputFiles[0].text), 'import.meta.url': '"file:///unused-worker"' } });
  return destination;
}
if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) console.log(await buildSkillBridge());
