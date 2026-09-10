import { readFile, writeFile, mkdir } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { execFileSync } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
export async function prepareNode(pythonDirectory) {
  const lock = JSON.parse(await readFile(path.join(root, 'node-runtime.json'), 'utf8'));
  const archivePath = path.join(root, 'build-resources', lock.archive);
  let archive;
  try { archive = await readFile(archivePath); } catch {
    const response = await fetch(lock.url, { signal: AbortSignal.timeout(60_000) });
    if (!response.ok) throw new Error(`Node download failed (${response.status})`);
    archive = Buffer.from(await response.arrayBuffer());
  }
  if (createHash('sha256').update(archive).digest('hex') !== lock.sha256) throw new Error('Node archive checksum mismatch');
  await writeFile(archivePath, archive);
  const destination = path.join(root, 'build-resources/node');
  await mkdir(destination, { recursive: true });
  execFileSync(path.join(pythonDirectory, 'python.exe'), ['-c',
    'import pathlib,sys,zipfile; z=zipfile.ZipFile(sys.argv[1]); p=pathlib.Path(sys.argv[2]); [(p / n).write_bytes(z.read(sys.argv[3]+"/"+n)) for n in ("node.exe","LICENSE")]',
    archivePath, destination, lock.prefix], { windowsHide: true });
  await writeFile(path.join(destination, 'runtime-lock.json'), JSON.stringify(lock, null, 2));
  const version = execFileSync(path.join(destination, 'node.exe'), ['--version'], { encoding: 'utf8', windowsHide: true }).trim();
  if (version !== `v${lock.version}`) throw new Error('Node executable version mismatch');
  return destination;
}
