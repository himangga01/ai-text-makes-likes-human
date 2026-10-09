// Strength descriptions under the engine switch (DESIGN 3.4, 4.3): the v2 meaning is served only when v2 is
// selected; ids, labels, parsing and the legacy rewriteInstructions never change.
import { describe, expect, it } from 'vitest';
import {
  LEGACY_REWRITE_OPTIONS, parseRewriteOptions, REWRITE_OPTIONS, rewriteInstructions, rewriteOptionChoices, SEJONG_REWRITE_OPTIONS
} from '../../src/engine/rewrite-policy.js';

describe('rewrite option descriptions per engine', () => {
  it('serves the legacy list by default and the v2 list only for v2', () => {
    expect(rewriteOptionChoices('legacy')).toBe(LEGACY_REWRITE_OPTIONS);
    expect(rewriteOptionChoices('v2')).toBe(SEJONG_REWRITE_OPTIONS);
    // Without SUPER_SEJONG_ENGINE=v2 in the test process, the list chosen at start-up is the legacy one.
    if ((process.env.SUPER_SEJONG_ENGINE ?? '').trim().toLowerCase() !== 'v2') expect(REWRITE_OPTIONS).toBe(LEGACY_REWRITE_OPTIONS);
  });

  it('keeps ids and labels and changes only the descriptions', () => {
    const strip = (list: readonly { id: string; label: string }[]) => list.map(({ id, label }) => ({ id, label }));
    expect(strip(SEJONG_REWRITE_OPTIONS)).toEqual(strip(LEGACY_REWRITE_OPTIONS));
    SEJONG_REWRITE_OPTIONS.forEach((option, index) => expect(option.description).not.toBe(LEGACY_REWRITE_OPTIONS[index]!.description));
    // Strength never relaxes a guard in v2, so no description promises broad restructuring.
    for (const option of SEJONG_REWRITE_OPTIONS) expect(option.description).not.toMatch(/크게 바꿉니다|적극적으로 바꿉니다/u);
    for (const option of SEJONG_REWRITE_OPTIONS.slice(1, 4)) expect(option.description).toContain('말투와 뜻은 그대로');
    // rewrite (WP-19): broad rewriting by paragraph, the voice fitted per paragraph, meaning and CTAs kept
    const rewrite = SEJONG_REWRITE_OPTIONS.find(option => option.id === 'rewrite')!;
    expect(rewrite.label).toBe('매우 강하게(다시쓰기)');
    expect(rewrite.description).toMatch(/문단마다/u);
    expect(rewrite.description).toMatch(/뜻·행동 요청은 그대로/u);
  });

  it('leaves parsing and the legacy instructions untouched', () => {
    expect(parseRewriteOptions('direct-text', 'very-strong')).toEqual({ inputKind: 'direct-text', strength: 'very-strong' });
    expect(rewriteInstructions({ inputKind: 'direct-text', strength: 'very-strong' }, 1)).toContain('많은 문장을 실제로 재서술');
  });
});
