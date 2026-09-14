import {test,expect} from '@playwright/test';
test('text import locks editing and transformation until file reading completes',async({page})=>{
  await page.route('**/api/health',r=>r.fulfill({json:{status:'ready',claudeAvailable:true}}));
  await page.addInitScript(()=>{
    const original=File.prototype.arrayBuffer;
    File.prototype.arrayBuffer=async function(){
      await new Promise<void>(resolve=>{(window as any).finishFileRead=resolve;});
      return original.call(this);
    };
  });
  await page.goto('/');
  await page.locator('#source-text').fill('previous text');
  await page.locator('#text-file-input').setInputFiles({name:'input.md',mimeType:'text/markdown',buffer:Buffer.from('# loaded text')});
  await expect(page.locator('#source-text')).toHaveJSProperty('readOnly',true);
  await expect(page.locator('#transform-button')).toBeDisabled();
  await expect(page.locator('#text-file-button')).toBeDisabled();
  await page.evaluate(()=>(window as any).finishFileRead());
  await expect(page.locator('#source-text')).toHaveValue('# loaded text');
  await expect(page.locator('#source-text')).toHaveJSProperty('readOnly',false);
  await page.locator('#source-text').fill('user edit');
  await expect(page.locator('#source-text')).toHaveValue('user edit');
  await expect(page.locator('#source-file-name')).toBeHidden();
});
