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
