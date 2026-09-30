import { readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { expect, it } from 'vitest';
import { makeTestRoot, removeTestRoot } from '../helpers/test-root.js';
import * as preferences from '../../desktop/preferences.js';
it('loads legacy/malformed saved strength as normal and round-trips a validated preference',async()=>{
 const root=await makeTestRoot();const file=path.join(root,'settings.json');
 try {
  expect((await preferences.loadPreferences(file)).rewriteStrength).toBe('normal');
  for(const saved of [{selectedEngine:'claude'},null,{rewriteStrength:'maximum'},{rewriteStrength:['strong']}]) {
   await writeFile(file,JSON.stringify(saved));
   expect((await preferences.loadPreferences(file)).rewriteStrength).toBe('normal');
  }
  const current=await preferences.loadPreferences(file);
  await preferences.selectRewriteStrength(current,'very-strong',()=>preferences.savePreferences(file,current));
  expect((await preferences.loadPreferences(file)).rewriteStrength).toBe('very-strong');
  await expect(preferences.selectRewriteStrength(current,'maximum',()=>preferences.savePreferences(file,current))).rejects.toThrow();
  expect(current.rewriteStrength).toBe('very-strong');
  expect(JSON.parse(await readFile(file,'utf8')).rewriteStrength).toBe('very-strong');
 } finally {await removeTestRoot(root);}
});
it('does not pin the current model defaults as a user choice when nothing was saved',async()=>{
 const root=await makeTestRoot();const file=path.join(root,'settings.json');
 try {
  await writeFile(file,JSON.stringify({selectedEngine:'claude',models:{codex:{model:'gpt-6-sol',effort:'low'}}}));
  const loaded=await preferences.loadPreferences(file);
  expect(loaded.models).toEqual({codex:{model:'gpt-6-sol',effort:'low'}});
  await preferences.selectRewriteStrength(loaded,'strong',()=>preferences.savePreferences(file,loaded));
  expect(JSON.parse(await readFile(file,'utf8')).models).toEqual({codex:{model:'gpt-6-sol',effort:'low'}});
  await writeFile(file,JSON.stringify({models:{claude:{model:'claude-opus-5-5'}}}));
  expect((await preferences.loadPreferences(file)).models).toEqual({claude:{model:'claude-opus-5-5',effort:'high'}});
 } finally {await removeTestRoot(root);}
});
