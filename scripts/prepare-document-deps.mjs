import { readFile, writeFile, mkdir } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { spawnSync } from 'node:child_process';
import path from 'node:path';
export async function prepareDocumentDeps(python) {
  const lock = JSON.parse(await readFile('python-document-deps.lock.json', 'utf8'));
  const cache = path.resolve('build-resources', lock.filename);
  let bytes;
  try { bytes = await readFile(cache); } catch {}
  if (!bytes || createHash('sha256').update(bytes).digest('hex') !== lock.sha256) {
    const response = await fetch(lock.url, { signal: AbortSignal.timeout(60000) });
    if (!response.ok) throw new Error('Document dependency download failed');
    bytes = Buffer.from(await response.arrayBuffer());
  }
  if (createHash('sha256').update(bytes).digest('hex') !== lock.sha256) throw new Error('Document dependency hash mismatch');
  await mkdir(path.dirname(cache), { recursive: true }); await writeFile(cache, bytes);
  const result = spawnSync(path.join(python, 'python.exe'), ['-c',
    "import zipfile,sys,pathlib; z=zipfile.ZipFile(sys.argv[1]); root=pathlib.Path(sys.argv[2]).resolve(); assert all((root/n).resolve().is_relative_to(root) for n in z.namelist()); z.extractall(root)", cache, path.join(python, 'Lib', 'site-packages')], { encoding: 'utf8', windowsHide: true });
  if (result.status !== 0) throw new Error('Document dependency extraction failed');
  await writeFile(path.join(python, 'python314._pth'), 'python314.zip\n.\nLib/site-packages\nimport site\n');
  await writeFile(path.join(python, 'document-deps-lock.json'), JSON.stringify(lock, null, 2));
  const smoke = spawnSync(path.join(python, 'python.exe'), ['-c', 'from lxml import etree; print(etree.LXML_VERSION)'], { encoding: 'utf8', windowsHide: true });
  if (smoke.status !== 0) throw new Error('Embedded document parser failed to load');
}
