import { afterAll, beforeAll, expect, it } from 'vitest';
import { chromium, type Browser } from '@playwright/test';
import { mkdtemp, readFile, writeFile, rm } from 'node:fs/promises';
import { execFileSync } from 'node:child_process';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
let browser: Browser;
let temporary: string;
beforeAll(async () => {
  temporary = await mkdtemp(path.resolve('runtime/test-tmp/skill-comparison-'));
  browser = await chromium.launch({ headless: true });
});
afterAll(async () => { await browser?.close(); if (temporary) await rm(temporary, {recursive:true}); });
async function artifact(source: string, candidate: string) {
  const request = path.join(temporary, 'request.json'), result = path.join(temporary, 'result.json');
  await writeFile(request, JSON.stringify({operation:'comparison', source, candidate}));
  execFileSync(process.execPath, ['build-resources/skill-bridge/skill-bridge.cjs',request,result]);
  const data = JSON.parse(await readFile(result,'utf8'));
  const file = path.join(temporary,'compare.html'); await writeFile(file,data.html);
  const page = await browser.newPage();
  await page.goto(pathToFileURL(file).href);
  return {page,data};
}
it.each([
  ['\n자료 자료 👩‍💻😀\n둘째 줄\n','\n자료 검토 👩‍💻😀\n둘째 줄\n'],
  ['<script>window.injected=1</script> & "인용"\n','<img src=x onerror="window.injected=1"> & 새 표현\n'],
  ['바뀌지 않은 글 😀\n','바뀌지 않은 글 😀\n'],
  ['가'.repeat(130000),'나'.repeat(130000)]
])('reconstructs escaped source and final under file:// including coarse and unchanged cases', async (source,candidate) => {
  const {page,data} = await artifact(source,candidate);
  const values = await page.evaluate(() => {
    const changes = document.querySelector('#changes')!;
    const source = changes.cloneNode(true) as Element; source.querySelectorAll('ins').forEach(node=>node.remove());
    const final = changes.cloneNode(true) as Element; final.querySelectorAll('del').forEach(node=>node.remove());
    return {source:source.textContent, final:final.textContent, pure:document.querySelector('#final')!.textContent,
      injected:(window as any).injected, images:document.querySelectorAll('img').length};
  });
  expect(values).toEqual({source,final:candidate,pure:candidate,injected:undefined,images:0});
  if (source.length>100000) expect(data.coarse).toBe(true);
  await page.getByRole('button',{name:'최종문 보기'}).click();
  await expect.poll(()=>page.locator('#final').isVisible()).toBe(true);
  await page.close();
}, 15000);
it('copies pure final text from full and partial diff selections and final-copy button', async () => {
  const {page} = await artifact('첫째 낡은 표현 마지막\n','첫째 새로운 표현 마지막\n');
  const copy = await page.evaluate(async () => {
    const changes = document.querySelector('#changes')!;
    function selected(node:Node, start?:number, end?:number) {
      const range = document.createRange(); range.selectNodeContents(node);
      if(start!==undefined) { range.setStart(node,start); range.setEnd(node,end!); }
      const selection = document.getSelection()!; selection.removeAllRanges(); selection.addRange(range);
      const data = new DataTransfer(); data.setData('text/html','old');
      document.dispatchEvent(new ClipboardEvent('copy',{bubbles:true,cancelable:true,clipboardData:data}));
      return {text:data.getData('text/plain'),html:data.getData('text/html')};
    }
    const full=selected(changes);
    const inserted=changes.querySelector('ins')!;
    const partial=selected(inserted.firstChild!,0,1);
    const deleted=selected(changes.querySelector('del')!);
    let buttonText='';
    Object.defineProperty(navigator,'clipboard',{value:{writeText:async(text:string)=>{buttonText=text;}}});
    (document.querySelector('#copy') as HTMLButtonElement).click(); await Promise.resolve();
    return {full,partial,deleted,buttonText};
  });
  expect(copy.full).toEqual({text:'첫째 새로운 표현 마지막\n',html:''});
  expect(copy.partial.text).toBe('새');
  expect(copy.deleted.text).toBe('');
  expect(copy.buttonText).toBe('첫째 새로운 표현 마지막\n');
  await page.close();
});
