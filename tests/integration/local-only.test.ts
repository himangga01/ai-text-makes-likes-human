import type { AddressInfo } from 'node:net';
import { networkInterfaces } from 'node:os';
import { expect, it } from 'vitest';
import { createApp } from '../../src/app.js';
import { loadConfig } from '../../src/config.js';
import { TransformQueue } from '../../src/queue/transform-queue.js';
import { close } from '../helpers/http-app.js';
import { makeTestRoot, removeTestRoot } from '../helpers/test-root.js';

// This machine's own non-loopback address: connecting to it gives the server a non-loopback socket address.
const lanAddress = Object.values(networkInterfaces()).flat()
  .find(info => info && info.family === 'IPv4' && !info.internal && !info.address.startsWith('169.254.'))?.address;

it('the default listener is loopback only', () => {
  expect(loadConfig({}, process.cwd()).host).toBe('127.0.0.1');
});

it.skipIf(!lanAddress)('refuses a non-loopback socket even when HOST opens the listener to the network', async () => {
  const root = await makeTestRoot(), queue = new TransformQueue({ maxActive: 1, maxAccepted: 3 });
  let calls = 0;
  const app = createApp({ config: { ...loadConfig({ HOST: '0.0.0.0' }, process.cwd()), runtimeRoot: root, minFreeBytes: 1 }, queue,
    preflight: { ready: true, nodeVersion: process.version }, logger: { info() {}, error() {} },
    engine: { async transform() { calls++; throw new Error('must not run'); } } });
  const server = app.listen(0, '0.0.0.0');
  await new Promise<void>((resolve, reject) => { server.once('listening', resolve); server.once('error', reject); });
  const port = (server.address() as AddressInfo).port;
  try {
    for (const host of [`${lanAddress}:${port}`, `localhost:${port}`]) {
      const response = await fetch(`http://${lanAddress}:${port}/api/health`, { headers: { host } });
      expect(response.status).toBe(403);
      expect(await response.json()).toMatchObject({ code: 'LOCAL_ONLY', message: expect.stringContaining('이 PC에서만') });
    }
    const transform = await fetch(`http://${lanAddress}:${port}/api/transform`, { method: 'POST', headers: { 'content-type': 'text/plain' }, body: 'source' });
    expect(transform.status).toBe(403);
    expect(calls).toBe(0);
    expect((await fetch(`http://127.0.0.1:${port}/api/status`)).status).toBe(200);
  } finally {
    await queue.shutdown();
    await close(server);
    await removeTestRoot(root);
  }
});
