import { statSync } from 'node:fs';
import { copyFile } from 'node:fs/promises';
import path from 'node:path';

// Saving over the opened source would destroy the original. Existing files are
// compared by identity (symlinks, NFD/NFC names, junctions); otherwise by path,
// case-insensitively on Windows and the default macOS volume.
export function sameFile(a: string, b: string, platform: NodeJS.Platform = process.platform): boolean {
  try {
    const left = statSync(a, { bigint: true }), right = statSync(b, { bigint: true });
    return left.dev === right.dev && left.ino === right.ino;
  } catch { /* A missing target is compared by path. */ }
  const left = path.resolve(a), right = path.resolve(b);
  return platform === 'win32' || platform === 'darwin' ? left.toLowerCase() === right.toLowerCase() : left === right;
}

// The save dialog already confirmed overwriting another file; only the source is refused.
export async function saveDocumentCopy(output: string, target: string, original: string | undefined, format: string): Promise<void> {
  if ((original && sameFile(target, original)) || path.extname(target).toLowerCase() !== '.' + format) throw new Error('원본과 다른 새 파일 이름을 지정해 주세요.');
  try { await copyFile(output, target); }
  catch { throw new Error('문서를 저장하지 못했습니다. 다른 위치나 이름을 지정해 주세요.'); }
}
