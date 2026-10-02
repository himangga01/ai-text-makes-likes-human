import { expect, test, type Page } from '@playwright/test';
import { MODEL_OPTIONS } from '../../src/engine/model-policy.js';

const providers={codex:{ready:true,installed:true,authenticated:true,message:'Codex 사용 가능'},claude:{ready:true,installed:true,authenticated:true,message:'Claude 사용 가능'}};
// Small server limits keep the test fast; the UI must follow the health payload, not its defaults.
const healthy={status:'ready',modelOptions:MODEL_OPTIONS,providers,documentsAvailable:true,inputLimits:{maxInputChars:10,maxTextFileBytes:64}};
async function ready(page:Page){
  await page.route('**/api/health',r=>r.fulfill({json:healthy}));
  await page.goto('/');await expect(page.locator('#codex-connection')).toHaveAttribute('data-state','ready');
}

test('text above the server limit disables Transform and explains why',async({page})=>{
  let requested=false;
  await page.route('**/api/transform*',r=>{requested=true;return r.abort();});
  await ready(page);
  await page.locator('#source-text').fill('가'.repeat(11));
  await expect(page.locator('#source-count')).toHaveText('11 / 10자');
  await expect(page.locator('#source-count')).toHaveClass(/is-over/);
  await expect(page.locator('#transform-button')).toBeDisabled();
  await expect(page.locator('#status-chip')).toHaveText('글자 수 초과');
  await expect(page.locator('#status-message')).toHaveText('원문은 10자 이하만 변환할 수 있습니다. 나눠서 변환해 주세요.');
  await page.locator('#source-text').fill('가'.repeat(10));
  await expect(page.locator('#source-count')).toHaveText('10자');
  await expect(page.locator('#transform-button')).toBeEnabled();
  expect(requested).toBe(false);
});

test('a TXT file above the size limit is refused and the editor keeps its text',async({page})=>{
  await ready(page);
  await page.locator('#source-text').fill('기존 원문');
  await page.locator('#text-file-input').setInputFiles({name:'big.txt',mimeType:'text/plain',buffer:Buffer.from('a'.repeat(65))});
  await expect(page.locator('#status-chip')).toHaveText('파일 오류');
  await expect(page.locator('#status-message')).toContainText('MiB 이하만 불러올 수 있습니다');
  await expect(page.locator('#source-text')).toHaveValue('기존 원문');
});

test('a TXT file within the size limit but over the character limit is refused',async({page})=>{
  await ready(page);
  await page.locator('#text-file-input').setInputFiles({name:'long.md',mimeType:'text/markdown',buffer:Buffer.from('a'.repeat(11))});
  await expect(page.locator('#status-message')).toHaveText('원문은 10자 이하만 변환할 수 있습니다. 나눠서 변환해 주세요.');
  await expect(page.locator('#source-text')).toHaveValue('');
});
