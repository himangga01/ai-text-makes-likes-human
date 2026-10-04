import { afterEach, expect, it, vi } from 'vitest';
import { readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { DocumentEngine } from '../../src/documents/document-engine.js';
import { SpawnCommandRunner, type CommandRequest } from '../../src/process/command-runner.js';
import { loadConfig } from '../../src/config.js';
import { createApp } from '../../src/app.js';
import { TransformQueue } from '../../src/queue/transform-queue.js';
import { listen, close } from '../helpers/http-app.js';
import { makeTestRoot,removeTestRoot } from '../helpers/test-root.js';
import { documentPythonCommand } from '../helpers/python-command.js';

const cleanup:Array<()=>Promise<unknown>>=[];
afterEach(async()=>{for(const fn of cleanup.splice(0).reverse())await fn();});
async function setup(){
 const root=await makeTestRoot();cleanup.push(()=>removeTestRoot(root));
 const config={...loadConfig({},process.cwd()),runtimeRoot:root,pythonCommand:documentPythonCommand!};
 const native=new SpawnCommandRunner();const calls:string[]=[];
 const runner={async run(request:CommandRequest){
   if(!request.args.includes('--output-last-message')&&!request.args.includes('--json-schema'))return native.run(request);
   const match=request.stdin!.match(/BEGIN_SOURCE_([a-f0-9]+)\r?\n(.*?)\r?\nEND_SOURCE_\1/s)!;
   const batch=JSON.parse(match[2]!);
   const output={schemaVersion:2,batchId:batch.batchId,sourceHash:batch.sourceHash,warnings:[],
     reviewedIds:batch.blocks.map((b:any)=>b.id),blocks:[]};
   const claude=request.args.includes('--json-schema');calls.push(claude?'claude':'codex');
   expect(request.args[request.args.indexOf('--model')+1]).toBe(claude?'claude-sonnet-5':'gpt-6-astra');
   expect(request.args).toContain(claude?'low':'model_reasoning_effort="low"');
   if(!claude)await writeFile(request.args[request.args.indexOf('--output-last-message')+1]!,JSON.stringify(output));
   return {exitCode:0,stdout:claude?JSON.stringify({is_error:false,subtype:'success',structured_output:output}):'',stderr:'',termination:'exit' as const};
 }};
 const doc=new DocumentEngine(config,runner);
 const app=createApp({config,documentEngine:doc,queue:new TransformQueue({maxActive:1,maxAccepted:3}),
   engine:{async transform(){throw new Error('Plain text engine must not process Office files');}},
   preflight:{ready:true,nodeVersion:'24',pythonVersion:'3.14.7',codexVersion:'0.153.4',humanizeVersion:'2.3.2'}});
 cleanup.push(()=>app.locals.documentStore.close());
 const server=await listen(app);cleanup.push(()=>close(server.server));
 return {...server,calls,store:app.locals.documentStore};
}
// Office extraction runs in Python with lxml; skip rather than fail on an interpreter without it.
const officeIt=documentPythonCommand?it:it.skip;
for(const format of ['docx','pptx'])for(const cli of ['codex','claude'])officeIt(`imports, verifies and downloads ${format} with selected ${cli}`,async()=>{
 const t=await setup();const original=await readFile(path.resolve(`tests/fixtures/documents/mixed.${format}`));
 const response=await fetch(t.baseUrl+'/api/documents',{method:'POST',headers:{'x-file-name':encodeURIComponent(`보고서.${format}`)},body:original});
 expect(response.status).toBe(201);const doc=await response.json() as any;
 expect(doc.editableBlocks).toBeGreaterThan(0);expect(doc.preview).toContain('가지고 있다');
 const headers={authorization:`Bearer ${doc.token}`};
 const run=await fetch(`${t.baseUrl}/api/documents/${doc.id}/transform?engine=${cli}&model=${cli==='codex'?'gpt-6-astra':'claude-sonnet-5'}&effort=low`,{method:'POST',headers});
 const events=(await run.text()).trim().split('\n').map(x=>JSON.parse(x));
 expect(events.at(-1).type).toBe('done');expect(events.find(e=>e.type==='document-result').name).toBe(`보고서-humanized.${format}`);
 expect(t.calls.every(x=>x===cli)).toBe(true);
 expect((await fetch(`${t.baseUrl}/api/documents/${doc.id}/result`)).status).toBe(404);
 const result=await fetch(`${t.baseUrl}/api/documents/${doc.id}/result`,{headers});
 expect(result.status).toBe(200);expect(result.headers.get('content-type')).toContain(format==='docx'?'wordprocessingml':'presentationml');
 expect(Buffer.from(await result.arrayBuffer()).subarray(0,2).toString()).toBe('PK');
 await fetch(`${t.baseUrl}/api/documents/${doc.id}`,{method:'DELETE',headers});
 expect(t.store.records.size).toBe(0);
 expect((await fetch(`${t.baseUrl}/api/documents/${doc.id}/result`,{headers})).status).toBe(404);
},30000);
officeIt('rejects foreign origins, malformed packages and extension spoofing before a model call',async()=>{
 const t=await setup();
 expect((await fetch(t.baseUrl+'/api/documents',{method:'POST',headers:{origin:'https://other.example','x-file-name':'a.docx'},body:'bad'})).status).toBe(403);
 const malformed=await fetch(t.baseUrl+'/api/documents',{method:'POST',headers:{'x-file-name':'a.docx'},body:'bad'});
 expect(malformed.status).toBe(400);expect(await malformed.json()).toMatchObject({code:'DOCUMENT_FORMAT_INVALID'});
 expect((await fetch(t.baseUrl+'/api/documents',{method:'POST',headers:{'x-file-name':'a.pptx'},body:await readFile('tests/fixtures/documents/mixed.docx')})).status).toBe(400);
 expect(t.calls).toEqual([]);expect(t.store.records.size).toBe(0);
});
it('does not reveal internal paths from failed Office imports',async()=>{
 const t=await setup();
 vi.spyOn(t.store.engine,'prepare').mockRejectedValue(new Error('비밀 경로 /private/auth.json'));
 const response=await fetch(t.baseUrl+'/api/documents',{method:'POST',headers:{'x-file-name':'a.docx'},body:'PK'});
 const body=await response.text();
 expect(response.status).toBe(500);
 expect(body).not.toContain('/private/auth.json');
 expect(body).toContain('DOCUMENT_IMPORT_FAILED');
});

it('keeps known Office import failures actionable without exposing Python text',async()=>{
 for(const [failure,status,code] of [
   ['문서 압축 해제 크기 제한을 초과했습니다.',413,'DOCUMENT_TOO_LARGE'],
   ['암호화된 문서는 지원하지 않습니다.',400,'DOCUMENT_PROTECTED'],
   ['편집 보호가 설정된 문서는 지원하지 않습니다.',400,'DOCUMENT_PROTECTED'],
   ['문서를 처리할 디스크 공간이 부족합니다.',507,'INSUFFICIENT_DISK']
 ] as const){
   const t=await setup();
   vi.spyOn(t.store.engine,'prepare').mockRejectedValue(new Error(failure));
   const response=await fetch(t.baseUrl+'/api/documents',{method:'POST',headers:{'x-file-name':'a.docx'},body:'PK'});
   expect(response.status).toBe(status);
   expect(await response.json()).toMatchObject({code});
 }
});
