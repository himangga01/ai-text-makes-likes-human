import { expect, test, type Page } from '@playwright/test';
import { MODEL_OPTIONS } from '../../src/engine/model-policy.js';

const providers={codex:{ready:true,installed:true,authenticated:true,message:'Codex 사용 가능'},claude:{ready:true,installed:true,authenticated:true,message:'Claude 사용 가능'}};
const healthy={status:'ready',modelOptions:MODEL_OPTIONS,modelDefaults:{codex:{model:'gpt-6.1-sol',effort:'xhigh'},claude:{model:'claude-opus-5-5',effort:'xhigh'}},providers,documentsAvailable:true};
const ndjson=(values:unknown[])=>values.map(x=>JSON.stringify(x)).join('\n')+'\n';
const completed=ndjson([{type:'accepted',jobId:'j',position:0},{type:'result-start'},{type:'result-delta',text:'다듬은 결과'},{type:'done',chunks:1,elapsedMs:1}]);
async function ready(page:Page){await page.goto('/');await expect(page.locator('#codex-connection')).toHaveAttribute('data-state','ready');}
async function openOffice(page:Page){
  await page.route('**/api/documents',r=>r.fulfill({status:201,json:{id:'doc',token:'t',name:'a.docx',format:'docx',preview:'원문',editableBlocks:1,preservedBlocks:0}}));
  await ready(page);
  await page.locator('#text-file-input').setInputFiles({name:'a.docx',mimeType:'application/octet-stream',buffer:Buffer.from('file')});
  await expect(page.locator('#source-text')).toHaveValue('원문');
}

test('R2-4.2: a second failed poll does not bring back a status the user already replaced',async({page})=>{
  let up=true;
  await page.route('**/api/health',r=>up?r.fulfill({json:healthy}):r.abort());
  await page.route('**/api/transform*',r=>r.fulfill({contentType:'application/x-ndjson',body:completed}));
  await ready(page);
  await page.locator('#source-text').fill('원문');await page.locator('#transform-button').click();
  await expect(page.locator('#status-chip')).toContainText('완료');
  up=false;await page.locator('#refresh-health').click();await expect(page.locator('#status-chip')).toHaveText('연결 오류');
  await page.locator('#reset-button').click();await expect(page.locator('#status-chip')).toHaveText('준비');
  await page.locator('#refresh-health').click();await expect(page.locator('#status-chip')).toHaveText('연결 오류');
  up=true;await page.locator('#refresh-health').click();
  await expect(page.locator('#codex-connection')).toHaveAttribute('data-state','ready');
  await expect(page.locator('#status-chip')).toHaveText('준비');
});

test('R2-4.3: a document rejected before the job starts stays usable and re-syncs models',async({page})=>{
  let healthCalls=0,deletes=0;
  await page.route('**/api/health',r=>{healthCalls++;return r.fulfill({json:healthy});});
  await page.route('**/api/documents/doc',r=>{if(r.request().method()==='DELETE')deletes++;return r.fulfill({json:{ok:true}});});
  await page.route('**/api/documents/doc/transform*',r=>r.fulfill({status:400,json:{code:'INVALID_MODEL_SETTINGS',message:'선택한 CLI에서 지원하는 모델과 추론 레벨을 선택해 주세요.'}}));
  await openOffice(page);const before=healthCalls;
  await page.locator('#transform-button').click();
  await expect(page.locator('#status-message')).toContainText('모델 목록');
  await expect(page.locator('#status-message')).not.toContainText('다시 선택');
  await expect.poll(()=>healthCalls).toBeGreaterThan(before);
  await expect(page.locator('#transform-button')).toBeEnabled();
  expect(deletes).toBe(0);
});

test('R2-4.3: a queue-full rejection keeps the document',async({page})=>{
  let deletes=0;
  await page.route('**/api/health',r=>r.fulfill({json:healthy}));
  await page.route('**/api/documents/doc',r=>{if(r.request().method()==='DELETE')deletes++;return r.fulfill({json:{ok:true}});});
  await page.route('**/api/documents/doc/transform*',r=>r.fulfill({status:429,json:{code:'QUEUE_FULL',message:'현재 3건이 처리 중입니다. 잠시 후 다시 시도해 주세요.'}}));
  await openOffice(page);
  await page.locator('#transform-button').click();
  await expect(page.locator('#status-message')).toContainText('3건');
  await expect(page.locator('#status-message')).not.toContainText('다시 선택');
  await expect(page.locator('#transform-button')).toBeEnabled();
  expect(deletes).toBe(0);
});

test('R2-4.4: server model defaults apply when nothing was saved, and only explicit choices persist',async({page})=>{
  await page.route('**/api/health',r=>r.fulfill({json:{...healthy,modelDefaults:{codex:{model:'gpt-6-sol',effort:'low'},claude:{model:'claude-opus-5-5',effort:'medium'}}}}));
  await ready(page);
  await expect(page.locator('#claude-model')).toHaveValue('claude-opus-5-5');await expect(page.locator('#claude-effort')).toHaveValue('medium');
  await expect(page.locator('#claude-effort option[value="medium"]')).toContainText('기본');
  await expect(page.locator('#codex-model')).toHaveValue('gpt-6-sol');await expect(page.locator('#codex-effort')).toHaveValue('low');
  await page.locator('#codex-effort').selectOption('high');
  const saved=JSON.parse(await page.evaluate(()=>localStorage.getItem('humanize-model-settings')!));
  expect(saved.codex).toEqual({model:'gpt-6-sol',effort:'high'});expect(saved.claude).toBeUndefined();
});

test('R2-4.5: a silent poll never switches the engine',async({page})=>{
  await page.clock.install();
  let calls=0;
  await page.route('**/api/health',r=>{calls++;return r.fulfill({json:calls===1?healthy:{...healthy,providers:{...providers,codex:{ready:false,installed:true,authenticated:false,message:'로그인 필요'}}}});});
  await ready(page);
  await expect(page.locator('input[name=engine][value=codex]')).toBeChecked();
  await page.clock.runFor(60_000);await expect.poll(()=>calls).toBe(2);
  await expect(page.locator('#codex-connection')).toHaveAttribute('data-state','auth');
  await expect(page.locator('input[name=engine][value=codex]')).toBeChecked();
  await expect(page.locator('#status-chip')).not.toHaveText('엔진 변경');
});

test('R2-4.6: a server shutdown error re-checks health',async({page})=>{
  let healthCalls=0;
  await page.route('**/api/health',r=>{healthCalls++;return r.fulfill({json:healthy});});
  await page.route('**/api/transform*',r=>r.fulfill({contentType:'application/x-ndjson',body:ndjson([{type:'accepted',jobId:'j',position:0},{type:'error',code:'SERVER_SHUTDOWN',message:'서버가 재시작되어 변환이 중단되었습니다. 잠시 후 다시 시도해 주세요.',retryable:true}])}));
  await ready(page);const before=healthCalls;
  await page.locator('#source-text').fill('원문');await page.locator('#transform-button').click();
  await expect(page.locator('#status-message')).toContainText('재시작');
  await expect.poll(()=>healthCalls).toBeGreaterThan(before);
});

test('R2-4.6: a network failure shows a Korean message',async({page})=>{
  await page.route('**/api/health',r=>r.fulfill({json:healthy}));
  await page.route('**/api/transform*',r=>r.abort('failed'));
  await ready(page);
  await page.locator('#source-text').fill('원문');await page.locator('#transform-button').click();
  await expect(page.locator('#status-message')).toContainText('서버에 연결하지 못했습니다');
});

test('R2-4.7: desktop IPC errors are shown without the Electron prefix',async({page})=>{
  await page.addInitScript(({health})=>{(window as any).humanizeDesktop={health:async()=>health,preferences:async()=>({selectedEngine:'codex',models:{},rewriteStrength:'normal'}),selectEngine:async()=>{},onEvent:()=>()=>{},cancel:async()=>{},
    transform:async()=>{throw new Error("Error invoking remote method 'humanize:transform': Error: 이미 변환 중입니다.");}};},{health:healthy});
  await page.goto('/');await expect(page.locator('#codex-connection')).toHaveAttribute('data-state','ready');
  await page.locator('#source-text').fill('원문');await page.locator('#transform-button').click();
  await expect(page.locator('#status-message')).toHaveText('이미 변환 중입니다.');
});
