import { execFileSync } from 'node:child_process';
import { existsSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const MINIMUM = [3, 11];
const CANDIDATES = ['python3.14', 'python3.13', 'python3.12', 'python3.11', 'python3', 'python'];

/** The engine scripts need Python 3.11 or newer; macOS still ships 3.9 as python3.
 * `modules` additionally requires importable packages, e.g. lxml for Office documents. */
function supported(command, modules) {
  try {
    const script = `import sys${modules.map(name => `,${name}`).join('')};print("%d.%d" % sys.version_info[:2])`;
    const output = execFileSync(command, ['-c', script],
      { encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'], windowsHide: true }).trim();
    const [major, minor] = output.split('.').map(Number);
    return major > MINIMUM[0] || (major === MINIMUM[0] && minor >= MINIMUM[1]);
  } catch { return false; }
}

/** Python for development scripts and tests.
 * Order: PYTHON_COMMAND, the bundled runtime, then the newest supported interpreter on PATH.
 * The server keeps using AppConfig.pythonCommand; this only removes Windows-only paths from tooling.
 * Returns undefined instead of throwing when `optional` is set, so suites can skip with a clear reason. */
export function resolvePythonCommand({ env = process.env, modules = [], optional = false } = {}) {
  const configured = env.PYTHON_COMMAND;
  if (configured && supported(configured, modules)) return configured;
  const bundled = process.platform === 'win32'
    ? path.join(root, 'build-resources', 'python', 'python.exe')
    : path.join(root, 'build-resources', 'python', 'bin', 'python3');
  if (existsSync(bundled) && supported(bundled, modules)) return bundled;
  for (const candidate of CANDIDATES) if (supported(candidate, modules)) return candidate;
  if (configured) return configured;
  if (optional) return undefined;
  throw new Error(`Python ${MINIMUM.join('.')}+${modules.length ? ` with ${modules.join(', ')}` : ''} was not found. Install it or set PYTHON_COMMAND.`);
}
