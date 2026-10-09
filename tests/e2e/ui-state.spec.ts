import { expect, test, type Page } from '@playwright/test';
import { MODEL_OPTIONS } from '../../src/engine/model-policy.js';

const providers={codex:{ready:true,installed:true,authenticated:true,message:'Codex 사용 가능'},claude:{ready:true,installed:true,authenticated:true,message:'Claude 사용 가능'}};
const healthy={status:'ready',modelOptions:MODEL_OPTIONS,modelDefaults:{codex:{model:'gpt-6.1-sol',effort:'high'},claude:{model:'claude-opus-5-5',effort:'xhigh'}},providers};
const ndjson=(values:unknown[])=>values.map(x=>JSON.stringify(x)).join('\n')+'\n';
const completed=ndjson([{type:'result-start'},{type:'result-delta',text:'다듬은 결과'},{type:'done',chunks:1,elapsedMs:1}]);
async function ready(page:Page){await page.goto('/');await expect(page.locator('#codex-connection')).toHaveAttribute('data-state','ready');}

test('E1: blocked site storage still leaves a working portal',async({page})=>{
  await page.addInitScript(()=>{Object.defineProperty(window,'localStorage',{configurable:true,get(){throw new DOMException('blocked','SecurityError');}});});
  await page.route('**/api/health',r=>r.fulfill({json:healthy}));
  await ready(page);
  await page.locator('#source-text').fill('원문');await expect(page.locator('#transform-button')).toBeEnabled();
  await page.locator('#rewrite-option-list input[value="strong"]').check();
  await expect(page.locator('#status-chip')).not.toHaveText('설정 저장 오류');
  await expect(page.locator('#rewrite-option-list input[value="strong"]')).toBeChecked();
});

test('A6: pre-health fallback matches current defaults and only the engine default effort is labelled default',async({page})=>{
  let release!:()=>void;const held=new Promise<void>(resolve=>{release=resolve;});
  await page.route('**/api/health',async r=>{await held;await r.fulfill({json:healthy});});
  await page.goto('/');
  await expect(page.locator('#claude-model')).toHaveValue('claude-opus-5-5');await expect(page.locator('#claude-effort')).toHaveValue('xhigh');
  await expect(page.locator('#codex-model')).toHaveValue('gpt-6.1-sol');await expect(page.locator('#codex-effort')).toHaveValue('high');
  release();await expect(page.locator('#codex-connection')).toHaveAttribute('data-state','ready');
  await expect(page.locator('#claude-effort option[value="xhigh"]')).toContainText('기본');
  await expect(page.locator('#claude-effort option[value="high"]')).not.toContainText('기본');
  await expect(page.locator('#codex-effort option[value="high"]')).toContainText('기본');
  await expect(page.locator('#codex-effort option')).toHaveCount(6);
});

test('A4/E9: removed saved models fall back to engine defaults, persist, and are announced',async({page})=>{
  await page.addInitScript(()=>{if(!sessionStorage.getItem('seeded')){sessionStorage.setItem('seeded','1');localStorage.setItem('humanize-model-settings',JSON.stringify({codex:{model:'gpt-5.5',effort:'xhigh'},claude:{model:'claude-fable-5-1',effort:'ultra'}}));}});
  await page.route('**/api/health',r=>r.fulfill({json:healthy}));
  await ready(page);
  await expect(page.locator('#codex-model')).toHaveValue('gpt-6.1-sol');await expect(page.locator('#codex-effort')).toHaveValue('high');
  await expect(page.locator('#claude-model')).toHaveValue('claude-fable-5-1');await expect(page.locator('#claude-effort')).toHaveValue('xhigh');
  await expect(page.locator('#status-message')).toContainText('gpt-5.5');
  // The removed choice is dropped rather than pinned, so later server defaults still apply.
  const saved=JSON.parse(await page.evaluate(()=>localStorage.getItem('humanize-model-settings')!));
  expect(saved.codex).toBeUndefined();expect(saved.claude).toMatchObject({model:'claude-fable-5-1'});
});

test('E9: a stale model rejection refreshes the model list and tells the user',async({page})=>{
  let healthCalls=0;
  await page.route('**/api/health',r=>{healthCalls++;return r.fulfill({json:healthy});});
  await page.route('**/api/transform*',r=>r.fulfill({status:400,json:{code:'INVALID_MODEL_SETTINGS',message:'선택한 CLI에서 지원하는 모델과 추론 레벨을 선택해 주세요.'}}));
  await ready(page);const before=healthCalls;
  await page.locator('#source-text').fill('원문');await page.locator('#transform-button').click();
  await expect(page.locator('#status-message')).toContainText('모델 목록');
  await expect.poll(()=>healthCalls).toBeGreaterThan(before);
});

test('E2: a stream failure after done keeps the finished result',async({page})=>{
  await page.route('**/api/health',r=>r.fulfill({json:healthy}));
  await page.route('**/api/transform*',r=>r.fulfill({contentType:'application/x-ndjson',body:completed+'{broken\n'}));
  await ready(page);
  await page.locator('#source-text').fill('원문');await page.locator('#transform-button').click();
  await expect(page.locator('#status-chip')).toContainText('완료');
  await expect(page.locator('#result-text')).toHaveValue('다듬은 결과');await expect(page.locator('#copy-button')).toBeEnabled();
});

test('E3/E7: background polls do not lock the editor, and an explicit refresh during a poll runs again',async({page})=>{
  await page.clock.install();
  let calls=0;let release:(()=>void)|undefined;
  await page.route('**/api/health',async r=>{calls++;if(calls===2)await new Promise<void>(resolve=>{release=resolve;});await r.fulfill({json:healthy});});
  await ready(page);
  await page.locator('#source-text').fill('원문');await expect(page.locator('#transform-button')).toBeEnabled();
  await page.clock.runFor(60_000);await expect.poll(()=>Boolean(release)).toBe(true);
  await expect(page.locator('#transform-button')).toBeEnabled();
  await expect(page.locator('#codex-connection')).toHaveAttribute('data-state','ready');
  await expect(page.locator('#codex-model')).toBeEnabled();
  await page.locator('#refresh-health').click();
  release!();
  await expect.poll(()=>calls).toBe(3);
});

test('E5: repeated copy clicks restore the original copy label',async({page})=>{
  await page.addInitScript(()=>{Object.defineProperty(navigator,'clipboard',{configurable:true,value:{writeText:async()=>{}}});});
  await page.route('**/api/health',r=>r.fulfill({json:healthy}));
  await page.route('**/api/transform*',r=>r.fulfill({contentType:'application/x-ndjson',body:completed}));
  await ready(page);
  const label=await page.locator('#copy-button').innerText();
  await page.locator('#source-text').fill('원문');await page.locator('#transform-button').click();
  await expect(page.locator('#copy-button')).toBeEnabled();
  await page.locator('#copy-button').dblclick();await expect(page.locator('#copy-button')).toHaveText('복사됨');
  await expect(page.locator('#copy-button')).toHaveText(label);
});

test('E6: recovered health clears the connection error status',async({page})=>{
  let ok=false;
  await page.route('**/api/health',r=>ok?r.fulfill({json:healthy}):r.abort());
  await page.goto('/');await expect(page.locator('#status-chip')).toHaveText('연결 오류');
  ok=true;await page.locator('#refresh-health').click();
  await expect(page.locator('#codex-connection')).toHaveAttribute('data-state','ready');
  await expect(page.locator('#status-chip')).not.toHaveText('연결 오류');
});

test('E10: the action zone stays reachable on phone width',async({page})=>{
  await page.setViewportSize({width:390,height:844});
  await page.route('**/api/health',r=>r.fulfill({json:healthy}));
  await ready(page);await page.locator('#source-text').fill('원문');
  await page.locator('#source-text').scrollIntoViewIfNeeded();
  const box=await page.locator('#transform-button').boundingBox();
  expect(box!.y+box!.height).toBeLessThanOrEqual(844);
});

test('E10: the coarse diff notice is not covered by the copy hint',async({page})=>{
  await page.route('**/api/health',r=>r.fulfill({json:healthy}));
  await page.goto('/');
  const overlap=await page.evaluate(async()=>{
    const {createResultDiff}=await import('/result-diff.js');
    const container=document.createElement('div');document.body.replaceChildren(container);
    await createResultDiff({container}).setResult('가'.repeat(25_000),'나'.repeat(25_000));
    const a=document.querySelector('.result-diff__copy-hint')!.getBoundingClientRect(),b=document.querySelector('.result-diff__notice')!.getBoundingClientRect();
    return b.height>0&&a.bottom>b.top&&b.bottom>a.top;
  });
  expect(overlap).toBe(false);
});

test('E12: an unavailable restored desktop engine switches to the available one and says why',async({page})=>{
  await page.addInitScript(({health})=>{(window as any).humanizeDesktop={health:async()=>health,preferences:async()=>({selectedEngine:'claude',models:{},rewriteStrength:'normal'}),selectEngine:async()=>{}};},
    {health:{...healthy,providers:{...providers,claude:{ready:false,installed:false,authenticated:false,message:'Claude 없음'}}}});
  await page.goto('/');
  await expect(page.locator('input[name=engine][value=codex]')).toBeChecked();
  await expect(page.locator('#status-message')).toContainText('Codex');
  await page.locator('#source-text').fill('원문');await expect(page.locator('#transform-button')).toBeEnabled();
});

test('E12: a failed Office run says the document must be selected again',async({page})=>{
  await page.route('**/api/health',r=>r.fulfill({json:{...healthy,documentsAvailable:true}}));
  await page.route('**/api/documents',r=>r.fulfill({status:201,json:{id:'doc',token:'t',name:'a.docx',format:'docx',preview:'원문',editableBlocks:1,preservedBlocks:0}}));
  await page.route('**/api/documents/doc/transform*',r=>r.fulfill({contentType:'application/x-ndjson',body:ndjson([{type:'accepted',jobId:'doc',position:0},{type:'error',code:'VALIDATION_FAILED',message:'검증 실패'}])}));
  await page.route('**/api/documents/doc',r=>r.fulfill({json:{ok:true}}));
  await ready(page);
  await page.locator('#text-file-input').setInputFiles({name:'a.docx',mimeType:'application/octet-stream',buffer:Buffer.from('file')});
  await expect(page.locator('#source-text')).toHaveValue('원문');await page.locator('#transform-button').click();
  await expect(page.locator('#status-message')).toContainText('다시 선택');
  await expect(page.locator('#transform-button')).toBeDisabled();
});
