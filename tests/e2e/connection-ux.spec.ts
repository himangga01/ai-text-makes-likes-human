import { test,expect } from '@playwright/test';
import { MODEL_OPTIONS } from '../../src/engine/model-policy.js';

const healthy={status:'ready',modelOptions:MODEL_OPTIONS,checkedAt:'2026-09-09T07:00:00Z',providers:{
  codex:{ready:true,installed:true,authenticated:true,message:'Codex 사용 가능'},
  claude:{ready:true,installed:true,authenticated:true,message:'Claude 사용 가능'}}};
test('model selection survives reload and uses selected CLI settings; stopwatch freezes on completion',async({page})=>{
 await page.route('**/api/health',r=>r.fulfill({json:healthy}));
 let finish:(()=>void)|undefined;let requested:URL|undefined;
 await page.route('**/api/transform*',async r=>{
   requested=new URL(r.request().url());await new Promise<void>(resolve=>{finish=resolve;});
   await r.fulfill({contentType:'application/x-ndjson',body:[{type:'result-start'},{type:'result-delta',text:'검증된 결과'},
     {type:'done',sourceChars:5,outputChars:5,chunks:1,elapsedMs:1}].map(x=>JSON.stringify(x)).join('\n')+'\n'});
 });
 await page.goto('/');await expect(page.locator('#codex-connection')).toHaveAttribute('data-state','ready');
 await page.locator('#codex-model').selectOption('gpt-6-astra');await page.locator('#codex-effort').selectOption('low');
 await page.locator('#claude-model').selectOption('claude-sonnet-5');await page.locator('#claude-effort').selectOption('xhigh');
 await page.reload();await expect(page.locator('#codex-model')).toHaveValue('gpt-6-astra');await expect(page.locator('#codex-effort')).toHaveValue('low');
 await expect(page.locator('#claude-model')).toHaveValue('claude-sonnet-5');
 await page.clock.install();
 await page.locator('#source-text').fill('원본을 다듬는다.');
 const a=await page.locator('#source-text').boundingBox(),b=await page.locator('#result-text').boundingBox();
 expect(a!.height).toBe(b!.height);expect(a!.y).toBe(b!.y);
 await page.locator('#transform-button').click();await expect.poll(()=>Boolean(finish)).toBe(true);
 expect(requested!.searchParams.get('model')).toBe('gpt-6-astra');expect(requested!.searchParams.get('effort')).toBe('low');
 await expect(page.locator('#codex-model')).toBeDisabled();
 await page.clock.runFor(65000);await expect(page.locator('#elapsed-time')).toHaveText('01:05');
 finish!();await expect(page.locator('#status-chip')).toContainText('완료');
 const elapsed=await page.locator('#elapsed-time').innerText();await page.clock.runFor(10000);await expect(page.locator('#elapsed-time')).toHaveText(elapsed);
 await page.locator('#reset-button').click();await expect(page.locator('#elapsed-time')).toHaveText('00:00');
});
test('refresh distinguishes auth and missing CLI and enables a newly authenticated provider',async({page})=>{
 let ready=false;
 await page.route('**/api/health',r=>r.fulfill({json:ready?healthy:{...healthy,status:'degraded',providers:{
   codex:{ready:false,installed:false,authenticated:false,message:'Codex 없음'},claude:{ready:false,installed:true,authenticated:false,message:'Claude 로그인 필요'}}}}));
 await page.goto('/');await expect(page.locator('#codex-connection')).toHaveAttribute('data-state','error');
 await expect(page.locator('#claude-connection')).toHaveAttribute('data-state','auth');
 await page.locator('#source-text').fill('원본 문장');await expect(page.locator('#transform-button')).toBeDisabled();
 ready=true;await page.locator('#refresh-health').click();await expect(page.locator('#claude-connection')).toHaveAttribute('data-state','ready');
 await expect(page.locator('#transform-button')).toBeEnabled();
});
