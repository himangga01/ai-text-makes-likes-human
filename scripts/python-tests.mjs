import { spawnSync } from 'node:child_process';
import { existsSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { resolvePythonCommand } from './python-command.mjs';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const suite = process.argv[2];
if (!suite) { console.error('Usage: node scripts/python-tests.mjs <tests/documents|tests/skills>'); process.exit(2); }

// Skill gateway tests exercise direct text through the Node bridge; build it once when missing.
if (path.resolve(suite) === path.join(root, 'tests', 'skills') && !existsSync(path.join(root, 'build-resources/skill-bridge/skill-bridge.cjs'))) {
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
