import { readFile } from 'node:fs/promises';
import { runInNewContext } from 'node:vm';
import { describe, expect, it } from 'vitest';

describe('desktop text completion ordering', () => {
  it('keeps listening when the invoke response precedes result and done events', async () => {
    let listener: (event: unknown) => void = () => {};
    let unsubscribed = false;
    const source = await readFile('public/transport.js', 'utf8');
    const bridge = {
      onEvent(callback: typeof listener) { listener = callback; return () => { unsubscribed = true; }; },
      async transform() {}, async cancel() {}
    };
    const transform = runInNewContext(source.replaceAll('export ', '') + '\ntransform;', {
      window: { humanizeDesktop: bridge }, setTimeout, clearTimeout, DOMException
    });
    const events: unknown[] = [];
    let settled = false;
    const pending = transform('원문', 'claude', new AbortController().signal, (event: unknown) => events.push(event)).then(() => { settled = true; });
    await new Promise(resolve => setTimeout(resolve, 10));
    expect(settled).toBe(false);
    expect(unsubscribed).toBe(false);
    listener({type: 'result-delta', text: '결과'});
    listener({type: 'done'});
    await pending;
    expect(events).toHaveLength(2);
    expect(unsubscribed).toBe(true);
  });

  it('sends the captured direct-text strength as top-level desktop fields', async () => {
    let listener: (event: unknown) => void = () => {};
    let payload: unknown;
    const source = await readFile('public/transport.js', 'utf8');
    const bridge = {
      onEvent(callback: typeof listener) { listener = callback; return () => {}; },
      async transform(value: unknown) {
        payload = value;
        queueMicrotask(() => listener({ type: 'done' }));
      },
      async cancel() {}
    };
    const transform = runInNewContext(source.replaceAll('export ', '') + '\ntransform;', {
      window: { humanizeDesktop: bridge }, setTimeout, clearTimeout, DOMException, URLSearchParams
    });

    await transform(
      '원문',
      'codex',
      new AbortController().signal,
      () => {},
      { model: 'gpt-6-astra', effort: 'low' },
      { inputKind: 'direct-text', strength: 'strong' }
    );

    expect(payload).toEqual({
      text: '원문',
      engine: 'codex',
      settings: { model: 'gpt-6-astra', effort: 'low' },
      inputKind: 'direct-text',
      strength: 'strong'
    });
  });
});
