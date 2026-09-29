import { describe, it, expect } from 'vitest';
import { writeFile } from 'node:fs/promises';
import path from 'node:path';
import { parseModelSettings, MODEL_OPTIONS } from '../../src/engine/model-policy.js';
import { CodexRunner } from '../../src/engine/codex-runner.js';
import { ClaudeRunner } from '../../src/engine/claude-runner.js';
import { makeTestRoot, removeTestRoot } from '../helpers/test-root.js';
import type { CommandRequest } from '../../src/process/command-runner.js';

it('defaults remain unchanged and provider/model effort combinations are validated',()=>{
  expect(parseModelSettings('codex')).toEqual({model:'gpt-5.6-sol',effort:'medium'});
  expect(parseModelSettings('claude')).toEqual({model:'claude-fable-5-1',effort:'high'});
  expect(()=>parseModelSettings('codex','claude-opus-5','high')).toThrow();
  expect(()=>parseModelSettings('codex','gpt-5.6-luna','ultra')).toThrow();
  expect(()=>parseModelSettings('claude','claude-sonnet-5','ultra')).toThrow();
  expect(parseModelSettings('claude','claude-opus-5-5','max')).toEqual({model:'claude-opus-5-5',effort:'max'});
  expect(()=>parseModelSettings('claude','claude-opus-5-5','ultra')).toThrow();
  expect(()=>parseModelSettings('codex','claude-opus-5-5','high')).toThrow();
  expect(parseModelSettings('claude','claude-sonnet-5-5','max')).toEqual({model:'claude-sonnet-5-5',effort:'max'});
  expect(()=>parseModelSettings('claude','claude-sonnet-5-5','ultra')).toThrow();
  expect(parseModelSettings('codex','gpt-6-sol','ultra')).toEqual({model:'gpt-6-sol',effort:'ultra'});
  expect(()=>parseModelSettings('codex','gpt-6-luna','ultra')).toThrow();
  expect(()=>parseModelSettings('codex','gpt-5.2','low')).toThrow();
  expect(()=>parseModelSettings('codex','gpt-5.5','low')).toThrow();
  expect(()=>parseModelSettings('codex',['gpt-6-astra'],'low')).toThrow();
});
for(const kind of ['codex','claude'] as const)it(`${kind} receives per-request selection without changing the next request default`,async()=>{
  const root=await makeTestRoot();const calls:CommandRequest[]=[];
  try {
    const source=path.join(root,'source.txt'),rules=path.join(root,'rules.md'),schema=path.join(root,'schema.json');
    await writeFile(source,'문장을 보존한다.');await writeFile(rules,'규칙');await writeFile(schema,'{}');
    const runner={async run(r:CommandRequest){calls.push(r);const payload={rewrittenText:'문장을 보존한다.',warnings:[]};
      if(kind==='codex')await writeFile(r.args[r.args.indexOf('--output-last-message')+1]!,JSON.stringify(payload));
      return {exitCode:0,termination:'exit' as const,stdout:JSON.stringify({is_error:false,subtype:'success',structured_output:payload}),stderr:''};}};
    const options={schemaPath:schema,quickRulesPath:rules,timeoutMs:1000,runner,permitPool:{maxObserved:1,run:async<T>(_s:AbortSignal,task:()=>Promise<T>)=>task()}};
    const model=kind==='codex'?new CodexRunner({...options,codexCommand:'codex.exe'}):new ClaudeRunner({...options,claudeCommand:'claude.exe'});
    const selection=parseModelSettings(kind,kind==='codex'?'gpt-6-astra':'claude-sonnet-5','low');
    await model.transform(source,path.join(root,'result.json'),1,new AbortController().signal,selection);
    await model.transform(source,path.join(root,'default.json'),1,new AbortController().signal);
    expect(calls[0]!.args[calls[0]!.args.indexOf('--model')+1]).toBe(selection.model);
    expect(calls[1]!.args[calls[1]!.args.indexOf('--model')+1]).toBe(parseModelSettings(kind).model);
    expect(calls[0]!.args).toContain(kind==='codex'?'model_reasoning_effort="low"':'low');
  } finally {await removeTestRoot(root);}
});

it('retains distinct, correctly labelled Claude model choices',()=>{
  expect(MODEL_OPTIONS.claude.map(x=>[x.id,x.label])).toEqual([
    ['claude-fable-5-1','Claude Fable 5.1'],
    ['claude-opus-5-5','Claude Opus 5.5'],
    ['claude-sonnet-5-5','Claude Sonnet 5.5'],
    ['claude-sonnet-5','Claude Sonnet 5'],
    ['claude-opus-5','Claude Opus 5']
  ]);
});
