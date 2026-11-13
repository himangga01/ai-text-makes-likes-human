import {request as httpRequest} from 'node:http';
import {readFile,writeFile} from 'node:fs/promises';
import path from 'node:path';
import {expect,it} from 'vitest';
import {createApp} from '../../src/app.js';
import {loadConfig} from '../../src/config.js';
import {PublicAuth,writePublicPassword} from '../../src/network/public-auth.js';
import {TransformQueue} from '../../src/queue/transform-queue.js';
import {listen,close} from '../helpers/http-app.js';
import {makeTestRoot,removeTestRoot} from '../helpers/test-root.js';

const HOST='sejong.example.com', ORIGIN='https://sejong.example.com';

// The test server listens on 127.0.0.1, so every request here arrives the way a local tunnel connector's would.
async function setup(options:{publicHosts?:string[];password?:string;delayMs?:number;heartbeatMs?:number}={}) {
  const root=await makeTestRoot(), queue=new TransformQueue({maxActive:1,maxAccepted:3});
  const authFile=path.join(root,'public-auth.json');
  if(options.password)await writePublicPassword(authFile,options.password);
  let calls=0;
  const app=createApp({config:{...loadConfig({},process.cwd()),runtimeRoot:root,minFreeBytes:1,publicHosts:options.publicHosts??[]},queue,
    preflight:{ready:true,nodeVersion:process.version},logger:{info(){},error(){}},heartbeatMs:options.heartbeatMs,publicAuth:new PublicAuth(authFile),
    engine:{async transform(req){calls++;if(options.delayMs)await new Promise(r=>setTimeout(r,options.delayMs));
      const file=req.workspace.path('final.txt');
      await writeFile(file,await readFile(req.workspace.path('01_input.txt')));
      return {finalPath:file,sourceChars:6,outputChars:6,chunks:1,warnings:[],diagnostics:{} as any};}}});
  const server=await listen(app);
  return {...server,root,calls:()=>calls,async cleanup(){await queue.shutdown();await close(server.server);await removeTestRoot(root);}};
}

type Reply={status:number;body:string;location?:string;cookie?:string};
function send(url:string,headers:Record<string,string>,body?:string,method=body===undefined?'GET':'POST') {
  return new Promise<Reply>((resolve,reject)=>{
    const client=httpRequest(url,{method,headers},res=>{
      let text='';res.setEncoding('utf8');res.on('data',chunk=>{text+=chunk;});
      res.on('end',()=>resolve({status:res.statusCode??0,body:text,location:res.headers.location,cookie:res.headers['set-cookie']?.[0]}));
    });
    client.on('error',reject);client.end(body);
  });
}
const login=(baseUrl:string,password:string,client='203.0.113.7')=>send(baseUrl+'/api/public-login',
  {host:HOST,origin:ORIGIN,'content-type':'application/x-www-form-urlencoded','cf-connecting-ip':client},`password=${encodeURIComponent(password)}`);

it('asks for the password on the public name, then serves it with its HTTPS origin',async()=>{
  const t=await setup({publicHosts:[HOST],password:'fixture-pass-7'});
  try {
    expect(await send(t.baseUrl+'/',{host:HOST})).toMatchObject({status:303,location:'/login'});
    const page=await send(t.baseUrl+'/login',{host:HOST});
    expect(page.status).toBe(200);expect(page.body).toContain('action="/api/public-login"');
    expect((await send(t.baseUrl+'/login.css',{host:HOST})).status).toBe(200);
    const health=await send(t.baseUrl+'/api/health',{host:HOST});
    expect(health.status).toBe(401);expect(JSON.parse(health.body)).toMatchObject({code:'LOGIN_REQUIRED'});
    expect(await login(t.baseUrl,'1234')).toMatchObject({status:303,location:'/login?e=wrong',cookie:undefined});
    const ok=await login(t.baseUrl,'fixture-pass-7');
    expect(ok).toMatchObject({status:303,location:'/'});
    const cookie=ok.cookie!.split(';')[0]!;
    expect((await send(t.baseUrl+'/',{host:HOST,cookie})).status).toBe(200);
    expect(await send(t.baseUrl+'/login',{host:HOST,cookie})).toMatchObject({status:303,location:'/'});
    const accepted=await send(t.baseUrl+'/api/transform',{host:HOST,origin:ORIGIN,cookie,'content-type':'text/plain'},'source');
    expect(accepted.status).toBe(200);expect(accepted.body).toContain('"type":"done"');
    for(const origin of ['https://evil.example.com','https://sejong.example.com.evil.example','http://evil.example.com']) {
      const denied=await send(t.baseUrl+'/api/transform',{host:HOST,origin,cookie,'content-type':'text/plain'},'source');
      expect(denied.status).toBe(403);expect(JSON.parse(denied.body)).toMatchObject({code:'ORIGIN_NOT_ALLOWED'});
    }
    expect((await send(t.baseUrl+'/api/health',{host:'other.example.com',cookie})).status).toBe(403);
    const out=await send(t.baseUrl+'/api/public-logout',{host:HOST,origin:ORIGIN,cookie},'');
    expect(out).toMatchObject({status:303,location:'/login'});expect(out.cookie).toContain('Max-Age=0');
    expect(t.calls()).toBe(1);
  } finally {await t.cleanup();}
});

it('keeps LAN and localhost access open and gives them no login routes',async()=>{
  const t=await setup({publicHosts:[HOST],password:'fixture-pass-7'});
  try {
    expect((await send(t.baseUrl+'/',{})).status).toBe(200);
    const accepted=await send(t.baseUrl+'/api/transform',{'content-type':'text/plain'},'source');
    expect(accepted.body).toContain('"type":"done"');
    expect((await send(t.baseUrl+'/api/public-login',{'content-type':'application/x-www-form-urlencoded'},'password=fixture-pass-7')).status).toBe(404);
  } finally {await t.cleanup();}
});

it('serves nothing on the public name until a password is set',async()=>{
  const t=await setup({publicHosts:[HOST]});
  try {
    expect(await send(t.baseUrl+'/',{host:HOST})).toMatchObject({status:303,location:'/login'});
    const page=await send(t.baseUrl+'/login',{host:HOST});
    expect(page.status).toBe(503);expect(page.body).toContain('설정되지 않았습니다');
    expect(await login(t.baseUrl,'fixture-pass-7')).toMatchObject({status:303,location:'/login?e=unconfigured',cookie:undefined});
    expect((await send(t.baseUrl+'/api/health',{host:HOST})).status).toBe(401);
  } finally {await t.cleanup();}
});

it('without a public-hosts file a public name is refused as before',async()=>{
  const t=await setup({password:'fixture-pass-7'});
  try {
    const denied=await send(t.baseUrl+'/api/health',{host:HOST});
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
