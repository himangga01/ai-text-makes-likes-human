import {expect,test} from '@playwright/test';

test('a failed replacement preserves completed direct and Office output',async({page})=>{
  const events=(values:unknown[])=>values.map(x=>JSON.stringify(x)).join('\n')+'\n';
  await page.route('**/api/health',r=>r.fulfill({json:{status:'ready',claudeAvailable:true}}));
  await page.route('**/api/transform*',r=>r.fulfill({contentType:'application/x-ndjson',body:events([{type:'result-start'},{type:'result-delta',text:'completed direct'},{type:'done',chunks:1,elapsedMs:1}])}));
  await page.goto('/');await page.locator('#source-text').fill('source');await page.locator('#transform-button').click();
  await expect(page.locator('#result-text')).toHaveValue('completed direct');
  await page.locator('#text-file-input').setInputFiles({name:'bad.txt',mimeType:'text/plain',buffer:Buffer.from([0xff,0xfe,0])});
  await expect(page.locator('#status-chip')).toHaveText('파일 오류');
  await expect(page.locator('#result-text')).toHaveValue('completed direct');await expect(page.locator('#copy-button')).toBeEnabled();
  let imports=0;
  await page.route('**/api/documents',r=>++imports===1?r.fulfill({status:201,json:{id:'doc',token:'token',name:'old.docx',format:'docx',preview:'old document',editableBlocks:1,preservedBlocks:0}}):r.fulfill({status:400,json:{message:'bad document'}}));
  await page.route('**/api/documents/doc/transform*',r=>r.fulfill({contentType:'application/x-ndjson',body:events([{type:'document-result',artifactId:'doc',name:'old.docx',format:'docx',preview:'completed Office'},{type:'done',chunks:1,elapsedMs:1}])}));
  await page.locator('#text-file-input').setInputFiles({name:'old.docx',mimeType:'application/octet-stream',buffer:Buffer.from('file')});
  await expect(page.locator('#source-text')).toHaveValue('old document');await page.locator('#transform-button').click();
  await expect(page.locator('#result-text')).toHaveValue('completed Office');
  await page.locator('#text-file-input').setInputFiles({name:'bad.docx',mimeType:'application/octet-stream',buffer:Buffer.from('bad')});
  await expect(page.locator('#status-chip')).toHaveText('파일 오류');await expect(page.locator('#result-text')).toHaveValue('completed Office');
  await expect(page.locator('#download-button')).toBeVisible();await expect(page.locator('#download-button')).toBeEnabled();
});

test('desktop import is available only through the native picker',async({page})=>{
  await page.addInitScript(()=>{(window as any).nativeCalls=0;(window as any).humanizeDesktop={
    health:async()=>({status:'ready',claudeAvailable:true}),preferences:async()=>({}),
    openText:async()=>{(window as any).nativeCalls++;return null;}};});
  let webImports=0;page.on('request',request=>{if(request.url().includes('/api/documents'))webImports++;});
  await page.goto('/');await expect(page.locator('#text-file-input')).toBeDisabled();
  await expect(page.locator('#text-file-input')).toHaveAttribute('tabindex','-1');
  await page.locator('#text-file-input').setInputFiles({name:'office.docx',mimeType:'application/octet-stream',buffer:Buffer.from('file')});
  await page.locator('#text-file-button').click();
  await expect.poll(()=>page.evaluate(()=>(window as any).nativeCalls)).toBe(1);expect(webImports).toBe(0);
});

test('native document selection owns the editor until parsing resolves',async({page})=>{
  await page.addInitScript(()=>{
    (window as any).humanizeDesktop={health:async()=>({status:'ready',claudeAvailable:true}),preferences:async()=>({}),
      openText:()=>new Promise(resolve=>(window as any).finishImport=resolve),closeDocument:async()=>{}};
  });
  await page.goto('/');await page.locator('#source-text').fill('old source');await page.locator('#text-file-button').click();
  for(const selector of ['#transform-button','#reset-button','#text-file-button','#text-file-input'])await expect(page.locator(selector)).toBeDisabled();
  await expect(page.locator('#source-text')).toHaveAttribute('readonly','');
  await page.evaluate(()=>(window as any).finishImport({document:{id:'new-doc',token:'token',name:'new.docx',format:'docx',preview:'new document',editableBlocks:1,preservedBlocks:0}}));
  await expect(page.locator('#source-text')).toHaveValue('new document');await expect(page.locator('#text-file-button')).toBeEnabled();
});

test('hidden file input cannot replace a running text job',async({page})=>{
  await page.route('**/api/health',r=>r.fulfill({json:{status:'ready',claudeAvailable:true}}));
  let finish!:()=>void;const gate=new Promise<void>(r=>finish=r);
  await page.route('**/api/transform*',async r=>{await gate;await r.fulfill({contentType:'application/x-ndjson',body:[{type:'result-start'},{type:'result-delta',text:'finished'},{type:'done',chunks:1,elapsedMs:1}].map(x=>JSON.stringify(x)).join('\n')+'\n'});});
  await page.goto('/');await page.locator('#source-text').fill('old source');await page.locator('#transform-button').click();
  try {
    await expect(page.locator('#text-file-input')).toBeDisabled();
    await page.locator('#text-file-input').setInputFiles({name:'replacement.txt',mimeType:'text/plain',buffer:Buffer.from('replacement')});
    await expect(page.locator('#source-text')).toHaveValue('old source');
  } finally {finish();}
  await expect(page.locator('#result-text')).toHaveValue('finished');
});
