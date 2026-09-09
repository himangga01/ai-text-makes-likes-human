import {test,expect} from '@playwright/test';
import path from 'node:path';
test('Office upload previews text, sends selected CLI and downloads original format',async({page})=>{
  await page.route('**/api/health',r=>r.fulfill({json:{status:'ready',claudeAvailable:true,documentsAvailable:true}}));
  const token='a'.repeat(64);
  await page.route('**/api/documents',r=>r.fulfill({status:201,json:{id:'doc-1',token,name:'보고서-humanized.docx',format:'docx',preview:'[문단 1]\n테스트 원문',editableBlocks:1,preservedBlocks:0,slides:0,warnings:['각주 보존']}}));
  let selected='';
  await page.route('**/api/documents/doc-1/transform*',r=>{
    selected=new URL(r.request().url()).searchParams.get('engine')??'';
    expect(r.request().headers().authorization).toBe(`Bearer ${token}`);
    return r.fulfill({contentType:'application/x-ndjson',body:[
      {type:'accepted',jobId:'doc-1',position:0},
      {type:'document-result',artifactId:'doc-1',name:'보고서-humanized.docx',format:'docx',bytes:2,sha256:'test',preview:'[문단 1]\n검증된 결과'},
      {type:'done',sourceChars:6,outputChars:6,chunks:1,elapsedMs:50}
    ].map(x=>JSON.stringify(x)).join('\n')+'\n'});
  });
  await page.route('**/api/documents/doc-1/result',r=>r.fulfill({body:Buffer.from('PK'),contentType:'application/vnd.openxmlformats-officedocument.wordprocessingml.document'}));
  await page.goto('/');
  await page.locator('#text-file-input').setInputFiles(path.resolve('tests/fixtures/documents/mixed.docx'));
  await expect(page.locator('#source-text')).toHaveValue('[문단 1]\n테스트 원문');
  await expect(page.locator('#source-text')).toHaveJSProperty('readOnly',true);
  await page.locator('#engine-option-claude').click();
  await page.locator('#transform-button').click();
  await expect(page.locator('#status-chip')).toContainText('완료');expect(selected).toBe('claude');
  const download=page.waitForEvent('download');await page.locator('#download-button').click();
  expect((await download).suggestedFilename()).toBe('보고서-humanized.docx');
});
