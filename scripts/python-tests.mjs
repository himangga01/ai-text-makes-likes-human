import { spawnSync } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { resolvePythonCommand } from './python-command.mjs';
import { readSejongEngineVersion } from './engine-runtime.mjs';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const suite = process.argv[2];
if (!suite) { console.error('Usage: node scripts/python-tests.mjs <tests/documents|tests/skills>'); process.exit(2); }

// The v2 engine package reads engine_runtime/sejong/ENGINE_VERSION when it is imported, so a missing or malformed
// file would surface as an import traceback in every test module that touches it. Say it once, up front.
try { await readSejongEngineVersion(root); }
catch (error) { console.error(`engine_runtime/sejong/ENGINE_VERSION is unusable: ${error.message}`); process.exit(1); }

// Skill gateway tests exercise the Node bridge, which bundles the shared TypeScript policy.
// Rebuild it on every run (esbuild takes milliseconds) so tests never use a stale bundle.
if (path.resolve(suite) === path.join(root, 'tests', 'skills')) {
  const { buildSkillBridge } = await import('./build-skill-bridge.mjs');
  await buildSkillBridge();
}
const modules = path.resolve(suite) === path.join(root, 'tests', 'documents') ? ['lxml'] : [];
let python;
try { python = resolvePythonCommand({ modules }); }
catch (error) { console.error(error.message); process.exit(1); }
const result = spawnSync(python, ['-m', 'unittest', 'discover', '-s', suite, '-p', 'test_*.py'],
  { cwd: root, stdio: 'inherit', windowsHide: true, env: { ...process.env, PYTHONUTF8: '1', PYTHONDONTWRITEBYTECODE: '1', NODE_COMMAND: process.env.NODE_COMMAND ?? process.execPath } });
process.exit(result.status ?? 1);
