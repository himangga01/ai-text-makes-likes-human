import {access,mkdir,writeFile,readdir} from 'node:fs/promises';
import path from 'node:path';
import {expect,it} from 'vitest';
import {DocumentEngine} from '../../src/documents/document-engine.js';
import {ArtifactStore} from '../../src/documents/artifact-store.js';
import {loadConfig} from '../../src/config.js';
import {SpawnCommandRunner} from '../../src/process/command-runner.js';
import {makeTestRoot,removeTestRoot} from '../helpers/test-root.js';

it('cleans its own completed Python job despite an abandoned transaction marker',async()=>{
  const root=await makeTestRoot();
  const engine=new DocumentEngine({...loadConfig({},process.cwd()),runtimeRoot:root},new SpawnCommandRunner());
  try {
    const state=await engine.prepare(path.resolve('tests/fixtures/documents/mixed.docx'));
    await writeFile(path.join(engine.root,state.job,'operation.lock'),'interrupted');
    await engine.cleanup(state.job);
    await expect(access(path.join(engine.root,state.job))).rejects.toThrow();
  } finally {await removeTestRoot(root);}
});

it('knows the job to clean when prepare is interrupted before it returns state',async()=>{
  const root=await makeTestRoot();const config={...loadConfig({},process.cwd()),runtimeRoot:root};
  const engine=new DocumentEngine(config,{async run(request){
    const at=request.args.indexOf('--job-id');const job=at>=0?request.args[at+1]!:'job-'+ 'a'.repeat(32);
    const dir=path.join(root,'documents',job);await mkdir(dir,{recursive:true});await writeFile(path.join(dir,'original.docx'),'partial private data');
    return {exitCode:1,termination:'aborted' as const,stdout:'',stderr:''};
  }});
  try {
    await expect(engine.prepare('source.docx')).rejects.toThrow();
    expect(await readdir(engine.root)).toEqual([]);
  } finally {await removeTestRoot(root);}
});

it('retains a record for retry when cleanup fails',async()=>{
  const root=await makeTestRoot();let fail=true;
  const engine={root:path.join(root,'jobs'),async cleanup(){if(fail)throw new Error('temporary cleanup failure');}} as any;
  const store=new ArtifactStore(path.join(root,'artifacts'),engine);
  try {
    const record=await store.create('source.docx');record.busy=false;record.state={job:'job-'+'a'.repeat(32)} as any;
    await expect(store.remove(record)).rejects.toThrow('temporary cleanup failure');expect(store.records.has(record.id)).toBe(true);
    fail=false;await store.sweep();expect(store.records.size).toBe(0);
  } finally {fail=false;await store.close();await removeTestRoot(root);}
});

it('keeps output during a save lease and expires it only after release',async()=>{
  const root=await makeTestRoot();const store=new ArtifactStore(path.join(root,'artifacts'),{root:path.join(root,'jobs'),async cleanup(){}} as any);
  try {
    const record=await store.create('source.docx');record.busy=false;record.output=path.join(record.dir,'result.docx');await writeFile(record.output,'result');
    const lease=store.readResult(record.id,record.token);record.expires=0;await store.sweep();
    await expect(access(record.output)).resolves.toBeUndefined();
    await lease.release();await lease.release();expect(store.records.size).toBe(0);
  } finally {await store.close();await removeTestRoot(root);}
});
