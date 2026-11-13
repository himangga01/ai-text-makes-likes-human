import { mkdtemp, rm, writeFile } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { afterEach, expect, it } from 'vitest';
import { loadConfig } from '../../src/config.js';
import { isLoopbackAddress, publicHostOf, readPublicHosts } from '../../src/network/public-hosts.js';

const dirs: string[] = [];
afterEach(async () => { await Promise.all(dirs.splice(0).map(dir => rm(dir, { recursive: true, force: true }))); });
const tempDir = async () => { const dir = await mkdtemp(path.join(os.tmpdir(), 'public-hosts-')); dirs.push(dir); return dir; };

it('reads one lower-cased name per line, skipping comments, IPs, ports and junk', async () => {
  const dir = await tempDir(), file = path.join(dir, 'public-hosts.txt');
  await writeFile(file, '# tunnel names\nSejong.Example.com  # main\n\nsejong.example.com\n192.168.0.22\nlocalhost\nbad name.example.com\nport.example.com:443\nhttps://x.example.com\n-lead.example.com\nb.example.co.kr\r\n');
  expect(readPublicHosts(file)).toEqual(['sejong.example.com', 'b.example.co.kr']);
  expect(readPublicHosts(path.join(dir, 'missing.txt'))).toEqual([]);
});

it('loads the file beside the runtime jobs directory', async () => {
  const root = await tempDir();
  expect(loadConfig({ HUMANIZE_RUNTIME_ROOT: root }, process.cwd()).publicHosts).toEqual([]);
  await writeFile(path.join(root, 'public-hosts.txt'), 'sejong.example.com\n');
  expect(loadConfig({ HUMANIZE_RUNTIME_ROOT: root }, process.cwd()).publicHosts).toEqual(['sejong.example.com']);
});

it('only a loopback connector can present a listed name', () => {
  for (const address of ['127.0.0.1', '127.0.0.53', '::1', '::ffff:127.0.0.1']) expect(isLoopbackAddress(address)).toBe(true);
  for (const address of ['192.168.0.22', '10.0.0.1', '::ffff:192.168.0.5', 'fe80::1', undefined]) expect(isLoopbackAddress(address)).toBe(false);
  const hosts = ['sejong.example.com'];
  expect(publicHostOf('Sejong.Example.com', '127.0.0.1', hosts)).toBe('sejong.example.com');
  expect(publicHostOf('sejong.example.com', '192.168.0.30', hosts)).toBeUndefined();
  expect(publicHostOf('evil.example.com', '127.0.0.1', hosts)).toBeUndefined();
  expect(publicHostOf('sejong.example.com:7882', '127.0.0.1', hosts)).toBeUndefined();
  expect(publicHostOf('sejong.example.com', '127.0.0.1', [])).toBeUndefined();
});
