import { mkdtemp, readFile, rm, symlink, writeFile } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { expect, it } from 'vitest';
import { sameFile, saveDocumentCopy } from '../../desktop/save-target.js';

it('recognizes the opened source file as a save target on case-insensitive platforms', () => {
  expect(sameFile('/docs/memo.txt', '/docs/./memo.txt', 'linux')).toBe(true);
  expect(sameFile('/docs/Memo.txt', '/docs/memo.txt', 'win32')).toBe(true);
  expect(sameFile('/docs/Memo.txt', '/docs/memo.txt', 'darwin')).toBe(true);
  expect(sameFile('/docs/Memo.txt', '/docs/memo.txt', 'linux')).toBe(false);
  expect(sameFile('/docs/memo.txt', '/docs/memo-humanized.txt', 'win32')).toBe(false);
});

it.skipIf(process.platform === 'win32')('recognizes the source through a symlinked directory', async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), 'save-target-'));
  try {
    await writeFile(path.join(root, 'memo.txt'), 'x');
    await symlink(root, path.join(root, 'link'));
    expect(sameFile(path.join(root, 'link', 'memo.txt'), path.join(root, 'memo.txt'), 'linux')).toBe(true);
  } finally { await rm(root, { recursive: true, force: true }); }
});

it.skipIf(process.platform !== 'darwin')('recognizes an NFD spelling of an NFC source name', async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), 'save-target-'));
  try {
    await writeFile(path.join(root, '회의록.txt'.normalize('NFC')), 'x');
    expect(sameFile(path.join(root, '회의록.txt'.normalize('NFD')), path.join(root, '회의록.txt'.normalize('NFC')), 'linux')).toBe(true);
  } finally { await rm(root, { recursive: true, force: true }); }
});

it('copies an Office result over a confirmed existing file but never over the source', async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), 'save-target-'));
  try {
    const output = path.join(root, 'output.docx'), original = path.join(root, 'a.docx'), target = path.join(root, 'a-humanized.docx');
    await writeFile(output, 'result'); await writeFile(original, 'source'); await writeFile(target, 'old');
    await saveDocumentCopy(output, target, original, 'docx');
    expect(await readFile(target, 'utf8')).toBe('result');
    await expect(saveDocumentCopy(output, original, original, 'docx')).rejects.toThrow('원본과 다른 새 파일 이름');
    await expect(saveDocumentCopy(output, path.join(root, 'a.pptx'), original, 'docx')).rejects.toThrow('원본과 다른 새 파일 이름');
    expect(await readFile(original, 'utf8')).toBe('source');
    await expect(saveDocumentCopy(path.join(root, 'missing.docx'), path.join(root, 'b.docx'), original, 'docx')).rejects.toThrow(/^문서를 저장하지 못했습니다/);
  } finally { await rm(root, { recursive: true, force: true }); }
});
