import { spawnSync } from 'node:child_process';
import { readdirSync, readFileSync } from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import {
  familyMode, openReviewEnabled, OVERRIDABLE_FAMILIES, sejongFlags, selectEngine, suggestRequestsEnabled,
  type SejongFlags
} from '../../src/engine/sejong/config.js';
import {
  CHECK_SCHEMA, isSejongCode, PLAN_SCHEMA, SEJONG_FAMILIES, SEJONG_GENRES,
  type CheckReport, type Plan, type SejongResponse
} from '../../src/engine/sejong/types.js';
import type { RewriteStrength } from '../../src/engine/rewrite-policy.js';
import { pythonCommand } from '../helpers/python-command.js';

const root = path.resolve('.');
const fixtureDir = path.join(root, 'tests/fixtures/sejong');
const schemaDir = path.join(root, 'engine_runtime/sejong/schemas');
const json = (file: string): unknown => JSON.parse(readFileSync(file, 'utf8'));
const schemas = {
  plan: json(path.join(schemaDir, 'plan.schema.json')) as Schema,
  check: json(path.join(schemaDir, 'check.schema.json')) as Schema,
  response: json(path.join(root, 'src/engine/sejong/response-schema.json')) as Schema
};
function fixtures(kind: keyof typeof schemas): Array<[string, unknown]> {
  const names = readdirSync(fixtureDir).filter(name => name.startsWith(`${kind}-`) && name.endsWith('.json')).sort();
  expect(names.length).toBeGreaterThan(0);
  return names.map(name => [name, json(path.join(fixtureDir, name))]);
}
const clone = <T>(value: T): T => structuredClone(value);
const STRENGTHS: RewriteStrength[] = ['normal', 'medium', 'strong', 'very-strong', 'rewrite'];

/* ---------- the same JSON Schema subset as engine_runtime/sejong/io.py ---------- */

type Schema = { [key: string]: unknown };
const KEYWORDS = new Set(['$schema', '$id', '$comment', '$defs', 'title', 'description', 'default', 'examples',
  'type', 'enum', 'const', 'pattern', 'minLength', 'maxLength', 'minimum', 'maximum', 'minItems', 'maxItems',
  'uniqueItems', 'items', 'properties', 'required', 'additionalProperties', 'propertyNames', 'anyOf', '$ref']);

function kindOf(value: unknown): string {
  if (value === null) return 'null';
  if (Array.isArray(value)) return 'array';
  if (typeof value === 'number') return Number.isInteger(value) ? 'integer' : 'number';
  return typeof value;
}
function same(a: unknown, b: unknown): boolean {
  if (kindOf(a) === 'array' && kindOf(b) === 'array') {
    const x = a as unknown[], y = b as unknown[];
    return x.length === y.length && x.every((item, i) => same(item, y[i]));
  }
  if (kindOf(a) === 'object' && kindOf(b) === 'object') {
    const x = a as Record<string, unknown>, y = b as Record<string, unknown>;
    const keys = Object.keys(x);
    return keys.length === Object.keys(y).length && keys.every(key => key in y && same(x[key], y[key]));
  }
  return a === b;
}
function validate(value: unknown, schema: Schema, rootSchema: Schema = schema, at = '$'): string[] {
  const unknown = Object.keys(schema).filter(key => !KEYWORDS.has(key));
  if (unknown.length) throw new Error(`unsupported keywords ${unknown.join(',')} at ${at}`);
  const problems: string[] = [];
  if (typeof schema.$ref === 'string') {
    const target = schema.$ref.slice(2).split('/').reduce<unknown>((node, part) => (node as Schema)[part], rootSchema);
    problems.push(...validate(value, target as Schema, rootSchema, at));
  }
  const kind = kindOf(value);
  if (schema.type !== undefined) {
    const allowed = (Array.isArray(schema.type) ? schema.type : [schema.type]) as string[];
    if (!allowed.includes(kind) && !(kind === 'integer' && allowed.includes('number'))) return [...problems, `${at}: type`];
  }
  if ('const' in schema && !same(value, schema.const)) problems.push(`${at}: const`);
  if (Array.isArray(schema.enum) && !schema.enum.some(option => same(value, option))) problems.push(`${at}: enum`);
  if (Array.isArray(schema.anyOf) && !schema.anyOf.some(option => validate(value, option as Schema, rootSchema, at).length === 0))
    problems.push(`${at}: anyOf`);
  if (kind === 'string') {
    const length = [...(value as string)].length;
    if (typeof schema.minLength === 'number' && length < schema.minLength) problems.push(`${at}: minLength`);
    if (typeof schema.maxLength === 'number' && length > schema.maxLength) problems.push(`${at}: maxLength`);
    if (typeof schema.pattern === 'string' && !new RegExp(schema.pattern, 'u').test(value as string)) problems.push(`${at}: pattern`);
  }
  if (kind === 'integer' || kind === 'number') {
    if (typeof schema.minimum === 'number' && (value as number) < schema.minimum) problems.push(`${at}: minimum`);
    if (typeof schema.maximum === 'number' && (value as number) > schema.maximum) problems.push(`${at}: maximum`);
  }
  if (kind === 'array') {
    const items = value as unknown[];
    if (typeof schema.minItems === 'number' && items.length < schema.minItems) problems.push(`${at}: minItems`);
    if (typeof schema.maxItems === 'number' && items.length > schema.maxItems) problems.push(`${at}: maxItems`);
    if (schema.uniqueItems === true && items.some((item, i) => items.slice(0, i).some(other => same(item, other))))
      problems.push(`${at}: uniqueItems`);
    if (schema.items) items.forEach((item, i) => problems.push(...validate(item, schema.items as Schema, rootSchema, `${at}[${i}]`)));
  }
  if (kind === 'object') {
    const object = value as Record<string, unknown>;
    const properties = (schema.properties ?? {}) as Record<string, Schema>;
    for (const key of (schema.required ?? []) as string[]) if (!(key in object)) problems.push(`${at}: missing ${key}`);
    for (const [key, item] of Object.entries(object)) {
      if (schema.propertyNames && validate(key, schema.propertyNames as Schema, rootSchema, at).length) {
        problems.push(`${at}: propertyNames`);
        continue;
      }
      if (key in properties) problems.push(...validate(item, properties[key]!, rootSchema, `${at}.${key}`));
      else if (schema.additionalProperties === false) problems.push(`${at}: unknown ${key}`);
      else if (typeof schema.additionalProperties === 'object')
        problems.push(...validate(item, schema.additionalProperties as Schema, rootSchema, `${at}.${key}`));
    }
  }
  return problems;
}

describe('Super Sejong v2 fixtures', () => {
  it('validate against the plan, check and response schemas', () => {
    for (const kind of ['plan', 'check', 'response'] as const)
      for (const [name, data] of fixtures(kind)) expect([name, validate(data, schemas[kind])]).toEqual([name, []]);
  });

  it('carry the schema ids and the legacy gate keys first', () => {
    for (const [, data] of fixtures('plan')) expect((data as Plan).schema).toBe(PLAN_SCHEMA);
    for (const [, data] of fixtures('check')) {
      const report = data as CheckReport;
      expect(report.schema).toBe(CHECK_SCHEMA);
      expect(Object.keys(report).slice(0, 5)).toEqual(['gate', 'hardFailures', 'warningReasons', 'policy', 'shadowFailures']);
    }
  });

  it('keep needsModel equal to (requests non-empty or open review)', () => {
    for (const [, data] of fixtures('plan')) {
      const plan = data as Plan;
      expect(plan.needsModel).toBe(plan.requests.length > 0 || plan.openReview.enabled);
    }
  });

  it('use only lowercase codes, which the legacy gate parser keeps', () => {
    for (const [name, data] of fixtures('check')) {
      const report = data as CheckReport;
      const codes = [...report.hardFailures, ...report.shadowFailures,
        ...report.sentences.flatMap(s => [...s.codes, ...s.repairs]),
        ...report.retry.flatMap(r => r.violations.map(v => v.code))];
      expect(codes.length).toBeGreaterThan(0);
      for (const code of codes) expect([name, code, isSejongCode(code)]).toEqual([name, code, true]);
    }
  });

  it('map the emoji sentence to UTF-16 offsets that slice the JS string', () => {
    const source = '오늘은 세미나 후기를 정리합니다. 왜냐하면 일정이 바뀌었습니다. 참가비는 3만 원이 됬습니다.\n\n' +
      '현장 분위기가 좋았어요😀 ㅎㅎ 궁금한 점이 있으시면 댓글로 문의해 주세요.\n';
    const plan = json(path.join(fixtureDir, 'plan-blog-medium.json')) as Plan;
    const points = [...source];
    for (const s of plan.sentences) expect(source.slice(s.startU16, s.endU16)).toBe(points.slice(s.start, s.end).join(''));
    expect(source.slice(plan.sentences[3]!.startU16, plan.sentences[3]!.endU16)).toBe('현장 분위기가 좋았어요😀 ㅎㅎ');
  });
});

describe('Super Sejong v2 schemas', () => {
  it('reject the mutations the Python contract tests reject', () => {
    const plan = json(path.join(fixtureDir, 'plan-blog-medium.json')) as Plan;
    const planCases: Array<(p: Plan) => void> = [
      p => { (p as unknown as Record<string, unknown>).extra = 1; },
      p => { p.sentences[0]!.id = 's1'; },
      p => { (p.sentences[0]!.voice as { level: string }).level = 'haeyo'; },
      p => { (p.sentences[0] as unknown as { start: unknown }).start = true; },
      p => { p.sentences[0]!.end = 18.5; },
      p => { (p.options as { deterministicFix: unknown }).deterministicFix = true; },
      p => { p.ctaLedger[0]!.force = 6; },
      p => { p.findings[0]!.rule = 'ssj-a01'; },
      p => { p.requests[0]!.rules = ['SSJ-A01', 'SSJ-A01']; },
      p => { (p.seam as { prev: number[] }).prev = [0, 0, 0]; },
      p => { (p.stats.findingsByTier as Record<string, number>).fix = 1; }
    ];
    for (const mutate of planCases) {
      const broken = clone(plan);
      mutate(broken);
      expect(validate(broken, schemas.plan).length).toBeGreaterThan(0);
    }
    const report = json(path.join(fixtureDir, 'check-retry.json')) as CheckReport;
    const checkCases: Array<(r: CheckReport) => void> = [
      r => { r.shadowFailures.push('VOICE_LEVEL'); },
      r => { r.hardFailures.push('quote-altered'); },
      r => { r.retry[0]!.violations[0]!.code = 'voice level'; },
      r => { r.retry[0]!.violations = []; },
      r => { (r as { attempt: number }).attempt = 3; },
      r => { (r.counts.revertedByFamily as Record<string, number>).style = 1; },
      r => { (r.warningReasons.codes as string[]).push('P9_NEW'); }
    ];
    for (const mutate of checkCases) {
      const broken = clone(report);
      mutate(broken);
      expect(validate(broken, schemas.check).length).toBeGreaterThan(0);
    }
  });

  it('accept the writer reply shape of DESIGN 3.5 and nothing else', () => {
    const reply: SejongResponse = { replacements: [{ id: 'R1', text: '문장.', reason: 'SSJ-A01' }], rewrittenText: '', warnings: [] };
    expect(validate(reply, schemas.response)).toEqual([]);
    for (const bad of [
      { ...reply, edits: [] },
      { replacements: [], rewrittenText: '' },
      { ...reply, replacements: [{ id: 'X1', text: '문장.', reason: '' }] },
      { ...reply, replacements: [{ id: 'R12345', text: '문장.', reason: '' }] },
      { ...reply, replacements: [{ id: 'R1', text: '', reason: '' }] },
      { ...reply, replacements: [{ id: 'R1', text: '문장.', reason: 'x'.repeat(61) }] },
      { ...reply, warnings: Array.from({ length: 21 }, () => 'w') }
    ]) expect(validate(bad, schemas.response).length).toBeGreaterThan(0);
  });

  it('keeps one response schema for Python and TypeScript', () => {
    expect(json(path.join(schemaDir, 'response.schema.json'))).toEqual(schemas.response);
  });

  it('use only keywords both hand-written validators implement', () => {
    expect(() => validate('x', { type: 'string', format: 'email' })).toThrow('unsupported');
    expect(validate('abc\n', { pattern: '^[a-z]+$' }).length).toBeGreaterThan(0);
    expect(validate(true, { enum: [0, 1] }).length).toBeGreaterThan(0);
    expect(validate('😀', { maxLength: 1 })).toEqual([]);
  });

  it('match the lowercase code regex of the legacy gate parser', () => {
    const parser = readFileSync(path.join(root, 'src/engine/python-engine.ts'), 'utf8');
    expect(parser).toContain('/^[a-z_]{1,60}$/');
    for (const good of ['voice_level', 'a', '_', 'x'.repeat(60)]) expect(isSejongCode(good)).toBe(true);
    for (const bad of ['', 'Voice', 'voice-level', 'voice level', 'voice1', 'x'.repeat(61), 'voice_level\n', '보이스', 3, null])
      expect(isSejongCode(bad)).toBe(false);
  });
});

describe('ENGINE_VERSION', () => {
  it('names the engine, a semantic version and the contract schema the fixtures use', () => {
    const raw = readFileSync(path.join(root, 'engine_runtime/sejong/ENGINE_VERSION'), 'utf8');
    const match = /^id=super-sejong\nversion=((?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)(?:-[0-9A-Za-z.-]+)?)\nschema=([1-9]\d*)\n$/.exec(raw);
    expect(match).not.toBeNull();
    expect(PLAN_SCHEMA).toBe(`sejong-plan/${match![2]}`);
    expect(CHECK_SCHEMA).toBe(`sejong-check/${match![2]}`);
    for (const [, data] of fixtures('plan')) expect((data as Plan).engine).toEqual({ id: 'super-sejong', version: match![1] });
  });
});

describe('sejongFlags', () => {
  it('defaults to the legacy engine and the documented values', () => {
    expect(selectEngine({})).toBe('legacy');
    expect(sejongFlags({})).toEqual({
      engine: 'legacy', mode: 'enforce', gates: {}, v2Shadow: false, fixColloquial: false, deterministicFix: 'all',
      openReview: 'medium', genreDefault: 'general', worker: false, kiwi: 'off', rejected: []
    } satisfies SejongFlags);
  });

  it('accepts exactly the documented values of each variable', () => {
    const table: Array<[string, keyof SejongFlags, Record<string, unknown>, unknown]> = [
      ['SUPER_SEJONG_ENGINE', 'engine', { legacy: 'legacy', v2: 'v2', ' V2 ': 'v2' }, 'legacy'],
      ['SUPER_SEJONG_MODE', 'mode', { enforce: 'enforce', shadow: 'shadow', OFF: 'off' }, 'enforce'],
      ['SUPER_SEJONG_V2_SHADOW', 'v2Shadow', { 0: false, 1: true }, false],
      ['SUPER_SEJONG_FIX_COLLOQUIAL', 'fixColloquial', { 0: false, 1: true }, false],
      ['SUPER_SEJONG_DETERMINISTIC_FIX', 'deterministicFix', { all: 'all', 'edited-only': 'edited-only', off: 'off' }, 'all'],
      ['SUPER_SEJONG_OPEN_REVIEW', 'openReview', { medium: 'medium', strong: 'strong', always: 'always', off: 'off' }, 'medium'],
      ['SUPER_SEJONG_GENRE_DEFAULT', 'genreDefault', Object.fromEntries(SEJONG_GENRES.map(g => [g, g])), 'general'],
      ['SUPER_SEJONG_WORKER', 'worker', { off: false, on: true }, false]
    ];
    for (const [name, key, valid, fallback] of table) {
      for (const [raw, expected] of Object.entries(valid)) {
        const flags = sejongFlags({ [name]: raw });
        expect([name, raw, flags[key], flags.rejected]).toEqual([name, raw, expected, []]);
      }
      for (const raw of ['', '  ']) expect(sejongFlags({ [name]: raw })[key]).toEqual(fallback);
      for (const raw of ['true', 'yes', '2', 'v3', 'edited_only', 'legacy2']) {
        const flags = sejongFlags({ [name]: raw });
        expect([name, raw, flags[key], flags.rejected]).toEqual([name, raw, fallback, [name]]);
      }
    }
  });

  it('sets each family per mode, with floor and runaway always enforced', () => {
    const expected = {
      enforce: { floor: 'enforce', runaway: 'enforce', meaning: 'enforce', voice: 'enforce', cta: 'enforce', flow: 'enforce', clarity: 'shadow', norms: 'enforce', nli: 'off' },
      shadow: { floor: 'enforce', runaway: 'enforce', meaning: 'enforce', voice: 'shadow', cta: 'shadow', flow: 'shadow', clarity: 'shadow', norms: 'shadow', nli: 'off' },
      off: { floor: 'enforce', runaway: 'enforce', meaning: 'off', voice: 'off', cta: 'off', flow: 'off', clarity: 'off', norms: 'off', nli: 'off' }
    } as const;
    for (const [mode, families] of Object.entries(expected)) {
      const flags = sejongFlags({ SUPER_SEJONG_ENGINE: 'v2', SUPER_SEJONG_MODE: mode, SUPER_SEJONG_GATE_FLOOR: 'off' });
      expect(Object.keys(families).sort()).toEqual([...SEJONG_FAMILIES].sort());
      for (const family of SEJONG_FAMILIES) expect([mode, family, familyMode(flags, family)]).toEqual([mode, family, families[family]]);
    }
  });

  it('applies per-family overrides in every mode', () => {
    for (const family of OVERRIDABLE_FAMILIES)
      for (const value of ['enforce', 'shadow', 'off'] as const)
        for (const mode of ['enforce', 'shadow', 'off']) {
          const name = `SUPER_SEJONG_GATE_${family.toUpperCase()}`;
          const flags = sejongFlags({ SUPER_SEJONG_MODE: mode, [name]: value });
          const downgraded = family === 'nli' && value === 'enforce';
          expect(familyMode(flags, family)).toBe(downgraded ? 'shadow' : value);
          expect(flags.rejected).toEqual(downgraded ? [name] : []);
        }
    const typo = sejongFlags({ SUPER_SEJONG_GATE_VOICE: 'loud' });
    expect([familyMode(typo, 'voice'), typo.rejected]).toEqual(['enforce', ['SUPER_SEJONG_GATE_VOICE']]);
  });

  it('never lets NLI enforce', () => {
    for (const mode of ['enforce', 'shadow', 'off'])
      for (const raw of [undefined, 'enforce', 'ENFORCE', 'shadow', 'off', 'bogus'])
        expect(familyMode(sejongFlags({ SUPER_SEJONG_MODE: mode, SUPER_SEJONG_GATE_NLI: raw }), 'nli')).not.toBe('enforce');
    expect(familyMode(sejongFlags({ SUPER_SEJONG_GATE_NLI: 'enforce' }), 'nli')).toBe('shadow');
  });

  it('runs Kiwi only inside the worker', () => {
    expect(sejongFlags({ SUPER_SEJONG_KIWI: 'worker', SUPER_SEJONG_WORKER: 'on' }).kiwi).toBe('worker');
    const flags = sejongFlags({ SUPER_SEJONG_KIWI: 'worker' });
    expect([flags.kiwi, flags.rejected]).toEqual(['off', ['SUPER_SEJONG_KIWI']]);
  });

  it('enables the open review by strength, and never in mode off', () => {
    const expected = {
      // rewrite (WP-19) rewrites whole paragraphs: the open review never applies to it
      medium: [false, true, true, true, false], strong: [false, false, true, true, false],
      always: [true, true, true, true, false], off: [false, false, false, false, false]
    };
    for (const [setting, row] of Object.entries(expected)) {
      const flags = sejongFlags({ SUPER_SEJONG_OPEN_REVIEW: setting });
      const off = sejongFlags({ SUPER_SEJONG_OPEN_REVIEW: setting, SUPER_SEJONG_MODE: 'off' });
      expect(STRENGTHS.map(strength => openReviewEnabled(flags, strength))).toEqual(row);
      expect(STRENGTHS.map(strength => openReviewEnabled(off, strength))).toEqual([false, false, false, false, false]);
    }
    expect(suggestRequestsEnabled(sejongFlags({ SUPER_SEJONG_MODE: 'off' }))).toBe(false);
  });

  it('reads process.env by default', () => {
    const previous = process.env.SUPER_SEJONG_ENGINE;
    process.env.SUPER_SEJONG_ENGINE = 'v2';
    try {
      expect(selectEngine()).toBe('v2');
      expect(sejongFlags().engine).toBe('v2');
    } finally {
      if (previous === undefined) delete process.env.SUPER_SEJONG_ENGINE;
      else process.env.SUPER_SEJONG_ENGINE = previous;
    }
  });

  it('agrees with Flags.from_env in Python on every case', () => {
    const variables: Record<string, string[]> = {
      SUPER_SEJONG_ENGINE: ['legacy', 'v2', ' V2 ', 'bogus'],
      SUPER_SEJONG_MODE: ['enforce', 'shadow', 'off', 'Shadow', 'bogus', ''],
      SUPER_SEJONG_V2_SHADOW: ['0', '1', 'true'],
      SUPER_SEJONG_FIX_COLLOQUIAL: ['0', '1', 'on'],
      SUPER_SEJONG_DETERMINISTIC_FIX: ['all', 'edited-only', 'off', 'edited_only'],
      SUPER_SEJONG_OPEN_REVIEW: ['medium', 'strong', 'always', 'off', 'never'],
      SUPER_SEJONG_GENRE_DEFAULT: [...SEJONG_GENRES, 'news'],
      SUPER_SEJONG_WORKER: ['off', 'on', '1'],
      SUPER_SEJONG_KIWI: ['off', 'worker', 'spawn'],
      ...Object.fromEntries(OVERRIDABLE_FAMILIES.map(f => [`SUPER_SEJONG_GATE_${f.toUpperCase()}`, ['enforce', 'shadow', 'off', 'x']]))
    };
    const cases: Array<Record<string, string>> = [{}];
    for (const [name, values] of Object.entries(variables)) for (const value of values) cases.push({ [name]: value });
    for (const mode of ['enforce', 'shadow', 'off'])
      for (const nli of ['enforce', 'shadow']) cases.push({ SUPER_SEJONG_MODE: mode, SUPER_SEJONG_GATE_NLI: nli, SUPER_SEJONG_GATE_VOICE: 'off' });
    cases.push({ SUPER_SEJONG_WORKER: 'on', SUPER_SEJONG_KIWI: 'worker', SUPER_SEJONG_ENGINE: 'v2', SUPER_SEJONG_OPEN_REVIEW: 'strong' });
    cases.push({ SUPER_SEJONG_KIWI: 'worker', SUPER_SEJONG_GATE_CTA: 'x', SUPER_SEJONG_ENGINE: 'x', SUPER_SEJONG_GATE_NLI: 'enforce' });

    const view = (flags: SejongFlags) => ({
      ...flags,
      families: Object.fromEntries(SEJONG_FAMILIES.map(f => [f, familyMode(flags, f)])),
      openReviewBy: Object.fromEntries(STRENGTHS.map(s => [s, openReviewEnabled(flags, s)]))
    });
    const script = [
      'import json, sys',
      'sys.path.insert(0, ".")',
      'from engine_runtime.sejong.config import Flags, family_mode, open_review_enabled',
      'from engine_runtime.sejong.types import FAMILIES, STRENGTHS',
      'out = []',
      'for env in json.load(sys.stdin):',
      '    f = Flags.from_env(env)',
      '    out.append({"engine": f.engine, "mode": f.mode, "gates": f.gates, "v2Shadow": f.v2_shadow,',
      '                "fixColloquial": f.fix_colloquial, "deterministicFix": f.deterministic_fix,',
      '                "openReview": f.open_review, "genreDefault": f.genre_default, "worker": f.worker,',
      '                "kiwi": f.kiwi, "rejected": list(f.rejected),',
      '                "families": {x: family_mode(f, x) for x in FAMILIES},',
      '                "openReviewBy": {s: open_review_enabled(f, s) for s in STRENGTHS}})',
      'print(json.dumps(out))'
    ].join('\n');
    const result = spawnSync(pythonCommand, ['-c', script], {
      cwd: root, input: JSON.stringify(cases), encoding: 'utf8', windowsHide: true,
      env: { ...process.env, PYTHONUTF8: '1', PYTHONDONTWRITEBYTECODE: '1' }
    });
    expect(result.stderr).toBe('');
    expect(result.status).toBe(0);
    const python = JSON.parse(result.stdout) as unknown[];
    expect(cases.length).toBeGreaterThan(50);
    expect(python).toEqual(cases.map(env => view(sejongFlags(env))));
  });
});
