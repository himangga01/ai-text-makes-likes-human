import {test,expect} from '@playwright/test';
import {MODEL_OPTIONS} from '../../src/engine/model-policy.js';
test('fresh browser preserves the local Claude default and distinct model labels',async({page})=>{
  await page.route('**/api/health',r=>r.fulfill({json:{status:'ready',claudeAvailable:true,modelOptions:MODEL_OPTIONS}}));
  await page.goto('/');
  await expect(page.locator('#claude-model')).toHaveValue('claude-opus-5-5');
  await expect(page.locator('#claude-effort')).toHaveValue('xhigh');
  await expect(page.locator('#claude-model option')).toHaveText(['Claude Opus 5.5','Claude Fable 5.1','Claude Sonnet 5.5','Claude Haiku 5.5','Claude Sonnet 5','Claude Opus 5']);
});
