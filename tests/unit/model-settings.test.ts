import { afterEach, describe, it, expect } from 'vitest';
import { writeFile } from 'node:fs/promises';
import path from 'node:path';
import { FALLBACK_MODEL_OPTIONS, HUMANIZE_MODEL as HUMANIZE, getModelDefaults, getModelOptions, parseModelSelection, parseModelSettings, resetModelCatalog,
  setLiveModels } from '../../src/engine/model-policy.js';
import { CodexRunner } from '../../src/engine/codex-runner.js';
import { ClaudeRunner } from '../../src/engine/claude-runner.js';
import { makeTestRoot, removeTestRoot } from '../helpers/test-root.js';
import type { CommandRequest } from '../../src/process/command-runner.js';

it('defaults remain unchanged and provider/model effort combinations are validated',()=>{
  expect(parseModelSettings('codex')).toEqual({model:'gpt-6.1-sol',effort:'high'});
  expect(parseModelSettings('claude')).toEqual({model:'claude-opus-5-5',effort:'xhigh'});
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
  expect(parseModelSettings('codex','gpt-6.1-sol','ultra')).toEqual({model:'gpt-6.1-sol',effort:'ultra'});
  expect(parseModelSettings('claude','claude-haiku-5-5','max')).toEqual({model:'claude-haiku-5-5',effort:'max'});
  expect(()=>parseModelSettings('claude','claude-haiku-5-5','ultra')).toThrow();
  expect(()=>parseModelSettings('codex','claude-haiku-5-5','low')).toThrow();
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

afterEach(()=>resetModelCatalog());

it('retains distinct, correctly labelled fallback model choices in CLI order',()=>{
  expect(getModelOptions()).toEqual(FALLBACK_MODEL_OPTIONS);
  expect(FALLBACK_MODEL_OPTIONS.codex.map(x=>x.id)).toEqual(['gpt-6.1-sol','gpt-6-astra','gpt-6.1-terra','gpt-6-sol','gpt-6-luna',
    'gpt-5.6-sol','gpt-5.6-terra','gpt-5.6-luna']);
  expect(FALLBACK_MODEL_OPTIONS.claude.map(x=>[x.id,x.label])).toEqual([
    ['claude-opus-5-5','Claude Opus 5.5'],
    ['claude-fable-5-2','Claude Fable 5.2'],
    ['claude-sonnet-5-5','Claude Sonnet 5.5'],
    ['claude-haiku-5-5','Claude Haiku 5.5'],
    ['claude-fable-5-1','Claude Fable 5.1'],
    ['claude-sonnet-5','Claude Sonnet 5'],
    ['claude-opus-5','Claude Opus 5'],
    ['claude-fable-5','Claude Fable 5'],
    ['claude-opus-4-8','Claude Opus 4.8'],
    ['claude-opus-4-7','Claude Opus 4.7'],
    ['claude-opus-4-6','Claude Opus 4.6'],
    ['claude-sonnet-4-6','Claude Sonnet 4.6']
  ]);
  // Haiku 4.5 has no effort levels and the portal always sends one.
  expect(FALLBACK_MODEL_OPTIONS.claude.some(x=>x.id.includes('haiku-4'))).toBe(false);
  expect(parseModelSettings('codex','gpt-6.1-terra','ultra')).toEqual({model:'gpt-6.1-terra',effort:'ultra'});
  expect(parseModelSettings('claude','claude-fable-5-2','xhigh')).toEqual({model:'claude-fable-5-2',effort:'xhigh'});
  expect(()=>parseModelSettings('claude','claude-sonnet-4-6','xhigh')).toThrow();
  // An omitted effort follows the defaults rule for that model instead of failing on the engine default level.
  expect(parseModelSettings('claude','claude-opus-4-6')).toEqual({model:'claude-opus-4-6',effort:'high'});
  expect(parseModelSettings('codex','gpt-6-luna')).toEqual({model:'gpt-6-luna',effort:'high'});
});

describe('live model list',()=>{
  const nova={id:'gpt-7-nova',label:'GPT-7 Nova',efforts:['low','medium','high','xhigh']};
  it('validates against the live list and falls back again on reset',()=>{
    expect(setLiveModels('codex',[nova,{id:HUMANIZE,label:'GPT-6.1 Sol',efforts:['low','high']}])).toBe(true);
    expect(parseModelSettings('codex','gpt-7-nova','xhigh')).toEqual({model:'gpt-7-nova',effort:'xhigh'});
    expect(()=>parseModelSettings('codex','gpt-6-astra','low')).toThrow('선택한 CLI에서 지원하는 모델과 추론 레벨을 선택해 주세요.');
    expect(()=>parseModelSettings('codex',HUMANIZE,'ultra')).toThrow();
    expect(parseModelSettings('codex')).toEqual({model:HUMANIZE,effort:'high'});
    expect(getModelOptions().claude).toBe(FALLBACK_MODEL_OPTIONS.claude);
    resetModelCatalog();
    expect(getModelOptions()).toEqual(FALLBACK_MODEL_OPTIONS);
    expect(()=>parseModelSettings('codex','gpt-7-nova','low')).toThrow();
  });
  it('picks the configured default, then the CLI default, then the first model',()=>{
    setLiveModels('codex',[nova,{id:HUMANIZE,label:'GPT-6.1 Sol',efforts:['low','medium','high']}],{model:'gpt-7-nova',effort:'xhigh'});
    expect(getModelDefaults().codex).toEqual({model:HUMANIZE,effort:'high'});
    // The configured default left the CLI: the CLI default takes over, at the configured level it supports.
    setLiveModels('codex',[{id:'gpt-6-luna',label:'GPT-6 Luna',efforts:['low']},nova],{model:'gpt-7-nova',effort:'xhigh'});
    expect(getModelDefaults().codex).toEqual({model:'gpt-7-nova',effort:'high'});
    expect(parseModelSettings('codex')).toEqual({model:'gpt-7-nova',effort:'high'});
    setLiveModels('codex',[{id:'gpt-6-luna',label:'GPT-6 Luna',efforts:['low','medium']},nova]);
    expect(getModelDefaults().codex).toEqual({model:'gpt-6-luna',effort:'low'});
    expect(getModelDefaults().claude).toEqual({model:'claude-opus-5-5',effort:'xhigh'});
  });
  it('takes the effort from the configured level, the CLI default, high, then the first level',()=>{
    const only=(efforts:string[],cliEffort?:string)=>{setLiveModels('claude',[{id:'claude-fable-6',label:'Claude Fable 6',efforts}],{model:'claude-fable-6',effort:cliEffort});return getModelDefaults().claude;};
    expect(only(['low','high','xhigh'],'low')).toEqual({model:'claude-fable-6',effort:'xhigh'});
    expect(only(['low','medium','max'],'medium')).toEqual({model:'claude-fable-6',effort:'medium'});
    expect(only(['low','high','max'],'ultra')).toEqual({model:'claude-fable-6',effort:'high'});
    expect(only(['medium','max'])).toEqual({model:'claude-fable-6',effort:'medium'});
    // The CLI default effort belongs to the CLI default model only.
    setLiveModels('claude',[{id:'claude-fable-6',label:'Claude Fable 6',efforts:['low','medium']},{id:'claude-opus-6',label:'Claude Opus 6',efforts:['low','medium']}],{model:'claude-opus-6',effort:'medium'});
    expect(getModelDefaults().claude).toEqual({model:'claude-opus-6',effort:'medium'});
    expect(parseModelSettings('claude','claude-fable-6')).toEqual({model:'claude-fable-6',effort:'low'});
  });
  it('takes only usable entries and keeps the current list when none is left',()=>{
    expect(setLiveModels('codex',[])).toBe(false);
    expect(setLiveModels('codex',[{id:'bad id',label:'x',efforts:['low']},{id:'gpt-7',label:'x',efforts:[]},{id:'gpt-8',label:'x',efforts:['low" --x']}])).toBe(false);
    expect(getModelOptions().codex).toBe(FALLBACK_MODEL_OPTIONS.codex);
    expect(setLiveModels('codex',[{...nova,efforts:['low','low','bad level']},{...nova,label:'duplicate'},{id:'gpt-7-luna',label:' ',efforts:['high']}])).toBe(true);
    expect(getModelOptions().codex).toEqual([{id:'gpt-7-nova',label:'GPT-7 Nova',efforts:['low']},{id:'gpt-7-luna',label:'gpt-7-luna',efforts:['high']}]);
  });
});

it('checks only the shape of a selection for a process without the live list',()=>{
  expect(parseModelSelection('gpt-7-nova','turbo')).toEqual({model:'gpt-7-nova',effort:'turbo'});
  for(const [model,effort] of [['','low'],['gpt-7-nova',''],[undefined,'low'],['gpt-7-nova',undefined],[['gpt'],'low']])
    expect(()=>parseModelSelection(model,effort)).toThrow('선택한 CLI에서 지원하는 모델과 추론 레벨을 선택해 주세요.');
});
