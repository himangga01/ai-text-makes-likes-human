import { DocumentEngine } from '../dist/documents/document-engine.js';
import { loadConfig } from '../dist/config.js';
import { SpawnCommandRunner } from '../dist/process/command-runner.js';
import { mkdir, writeFile, copyFile } from 'node:fs/promises';
import path from 'node:path';
const root=path.resolve('.');
const work=path.resolve('runtime/test-tmp/document-live');await mkdir(work,{recursive:true});
const engine=new DocumentEngine({...loadConfig(process.env,root),runtimeRoot:work},new SpawnCommandRunner());
const records=[];
for(const cli of ['codex','claude'])for(const format of ['docx','pptx']) {
  console.log(`START ${cli} ${format}`);
  const state=await engine.prepare(path.resolve(`tests/fixtures/documents/mixed.${format}`));
  const result=await engine.transform(state,cli,work,new AbortController().signal,event=>{
    if(event.type==='progress')console.log(`${cli}/${format}: ${event.message}`);
  });
  const file=path.join(work,`${cli}-humanized.${format}`);await copyFile(result.output,file);
  records.push({cli,format,file,sha256:result.sha256,bytes:result.bytes,elapsedMs:result.elapsedMs,warnings:result.state.warnings,preview:result.state.preview});
  await engine.cleanup(state.job);
  await writeFile(path.join(work,'results.json'),JSON.stringify(records,null,2));
  console.log(`DONE ${cli} ${format} ${result.bytes} bytes`);
}
