import {request as httpRequest} from 'node:http';
import {readFile,writeFile} from 'node:fs/promises';
import {expect,it} from 'vitest';
import {createApp} from '../../src/app.js';
import {loadConfig} from '../../src/config.js';
import {TransformQueue} from '../../src/queue/transform-queue.js';
import {listen,close} from '../helpers/http-app.js';
import {makeTestRoot,removeTestRoot} from '../helpers/test-root.js';

// The test server listens on 127.0.0.1, so every request here arrives the way a local tunnel connector's would.
async function setup(options:{publicHosts?:string[];delayMs?:number;heartbeatMs?:number}={}) {
  const root=await makeTestRoot(), queue=new TransformQueue({maxActive:1,maxAccepted:3});
  let calls=0;
  const app=createApp({config:{...loadConfig({},process.cwd()),runtimeRoot:root,minFreeBytes:1,publicHosts:options.publicHosts??[]},queue,
    preflight:{ready:true,nodeVersion:process.version},logger:{info(){},error(){}},heartbeatMs:options.heartbeatMs,
    engine:{async transform(req){calls++;if(options.delayMs)await new Promise(r=>setTimeout(r,options.delayMs));
      const file=req.workspace.path('final.txt');
      await writeFile(file,await readFile(req.workspace.path('01_input.txt')));
      return {finalPath:file,sourceChars:6,outputChars:6,chunks:1,warnings:[],diagnostics:{} as any};}}});
  const server=await listen(app);
  return {...server,root,calls:()=>calls,async cleanup(){await queue.shutdown();await close(server.server);await removeTestRoot(root);}};
}

function send(url:string,headers:Record<string,string>,body?:string) {
  return new Promise<{status:number;body:string}>((resolve,reject)=>{
    const client=httpRequest(url,{method:body===undefined?'GET':'POST',headers},res=>{
      let text='';res.setEncoding('utf8');res.on('data',chunk=>{text+=chunk;});
      res.on('end',()=>resolve({status:res.statusCode??0,body:text}));
    });
    client.on('error',reject);client.end(body);
  });
}

it('serves a listed public name with its HTTPS origin and still refuses other names and origins',async()=>{
  const t=await setup({publicHosts:['sejong.example.com']});
  try {
    expect((await send(t.baseUrl+'/',{host:'sejong.example.com'})).status).toBe(200);
    expect((await send(t.baseUrl+'/api/health',{host:'other.example.com'})).status).toBe(403);
    const accepted=await send(t.baseUrl+'/api/transform',{host:'sejong.example.com',origin:'https://sejong.example.com','content-type':'text/plain'},'source');
    expect(accepted.status).toBe(200);expect(accepted.body).toContain('"type":"done"');
    for(const origin of ['https://evil.example.com','https://sejong.example.com.evil.example','http://evil.example.com']) {
      const denied=await send(t.baseUrl+'/api/transform',{host:'sejong.example.com',origin,'content-type':'text/plain'},'source');
      expect(denied.status).toBe(403);expect(JSON.parse(denied.body)).toMatchObject({code:'ORIGIN_NOT_ALLOWED'});
    }
    expect(t.calls()).toBe(1);
  } finally {await t.cleanup();}
});

it('without a public-hosts file a public name is refused as before',async()=>{
  const t=await setup();
  try {
    const denied=await send(t.baseUrl+'/api/health',{host:'sejong.example.com'});
    expect(denied.status).toBe(403);expect(JSON.parse(denied.body)).toMatchObject({code:'HOST_NOT_ALLOWED'});
  } finally {await t.cleanup();}
});

it('sends heartbeats while a slow job is silent, and none on a quick one',async()=>{
  const slow=await setup({delayMs:350,heartbeatMs:100});
  try {
    const response=await fetch(slow.baseUrl+'/api/transform',{method:'POST',headers:{'content-type':'text/plain'},body:'source'});
    const events=(await response.text()).trim().split('\n').map(line=>JSON.parse(line) as {type:string});
    expect(events.filter(event=>event.type==='heartbeat').length).toBeGreaterThanOrEqual(2);
    expect(events.at(-1)?.type).toBe('done');
  } finally {await slow.cleanup();}
  const quick=await setup({heartbeatMs:10_000});
  try {
    const response=await fetch(quick.baseUrl+'/api/transform',{method:'POST',headers:{'content-type':'text/plain'},body:'source'});
    expect(await response.text()).not.toContain('heartbeat');
  } finally {await quick.cleanup();}
});
