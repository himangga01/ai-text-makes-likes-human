import type { Express } from 'express';
import { createWriteStream, createReadStream } from 'node:fs';
import { statfs } from 'node:fs/promises';
import path from 'node:path';
import { pipeline } from 'node:stream/promises';
import { Transform } from 'node:stream';
import { ArtifactStore, type DocumentRecord } from './artifact-store.js';
import type { AppDependencies } from '../app.js';
import { NdjsonWriter } from '../transport/ndjson.js';
import { parseModelSettings } from '../engine/model-policy.js';

export function mountDocumentRoutes(app:Express,deps:AppDependencies) {
  const engine=deps.documentEngine;
  if(!engine) return;
  const store=new ArtifactStore(path.join(deps.config.runtimeRoot,'document-artifacts'),engine);
  app.locals.documentStore=store;
  const token=(request:any)=>String(request.headers.authorization??'').replace(/^Bearer /,'');
  app.post('/api/documents',async(request,response)=>{
    let record:DocumentRecord|undefined;let completed=false;let disconnected=false;
    const onDisconnect=()=>{if(!completed){disconnected=true;record?.controller.abort();}};
    request.once('aborted',onDisconnect);response.once('close',onDisconnect);
    try {
      const name=decodeURIComponent(String(request.headers['x-file-name']??''));
      record=await store.create(name);
      if(disconnected)record.controller.abort();
      const space=await statfs(record.dir);
      if(space.bavail*space.bsize<deps.config.minFreeBytes) throw new Error('문서를 처리할 디스크 공간이 부족합니다.');
      let received=0;
      const limiter=new Transform({transform(chunk,_enc,done){received+=chunk.length;done(received>50*1024**2?new Error('파일은 50 MiB 이하만 지원합니다.'):null,chunk);}});
      await pipeline(request,limiter,createWriteStream(record.input,{flags:'wx'}),{signal:record.controller.signal});
      const info=await store.inspect(record,name);
      if(record.controller.signal.aborted||response.destroyed)throw new Error('문서 읽기가 취소되었습니다.');
      completed=true;
      response.status(201).json(info);
    } catch(e) {if(record){record.busy=false;await store.remove(record);}if(!response.headersSent&&!response.destroyed)response.status(400).json({message:e instanceof Error?e.message:'문서를 읽지 못했습니다.'});}
    finally {request.removeListener('aborted',onDisconnect);response.removeListener('close',onDisconnect);}
  });
  app.post('/api/documents/:id/transform',async(request,response)=>{
    let record; let reservation; let writer:NdjsonWriter|undefined; let finished=false; let owns=false;
    let removeAbortListener:(()=>void)|undefined;
    try {
      record=store.get(String(request.params.id),token(request));
      if(record.busy||record.output||!record.state) throw new Error('진행 중이거나 완료한 문서입니다. 새로 선택해 주세요.');
      const choice=request.query.engine;
      if(choice!=='claude'&&choice!=='codex') throw new Error('CLI를 선택해 주세요.');
      const settings = parseModelSettings(choice,request.query.model,request.query.effort);
      if(deps.preflight.providers&&!deps.preflight.providers[choice].ready) throw new Error('선택한 CLI의 설치·로그인 상태를 확인해 주세요.');
      reservation=deps.queue.reserve(record.id);
      if(!reservation) throw new Error('작업 대기열이 가득 찼습니다.');
      record.busy=true;
      owns=true;
      const r=record;
      const reserved=reservation;
      const onAbort=()=>reserved.release();
      r.controller.signal.addEventListener('abort',onAbort,{once:true});
      removeAbortListener=()=>r.controller.signal.removeEventListener('abort',onAbort);
      if(r.controller.signal.aborted)onAbort();
      response.setHeader('Content-Type','application/x-ndjson; charset=utf-8');response.setHeader('Cache-Control','no-store');
      response.flushHeaders();writer=new NdjsonWriter(response);
      response.once('close',()=>{if(!finished)r.controller.abort();});
      writer.write({type:'accepted',jobId:r.id,position:0});
      await reservation.submit(async signal=>{
        const result=await engine.transform(r.state!,choice,r.dir,AbortSignal.any([signal,r.controller.signal]),event=>writer!.write(event),settings);
        r.state=result.state;r.output=result.output;
        r.expires=Date.now()+30*60000;
        writer!.write({type:'document-result',artifactId:r.id,name:store.public(r).name,format:r.state.format,
          bytes:result.bytes,sha256:result.sha256,preview:r.state.preview});
        writer!.write({type:'done',sourceChars:r.state.sourceChars,outputChars:r.state.sourceChars,chunks:r.state.totalChunks,elapsedMs:result.elapsedMs});
      },position=>writer!.write({type:'queued',position}));
      finished=true;
    } catch(e) {
      const message=e instanceof Error?e.message:'문서 변환에 실패했습니다.';
      if(writer) writer.write({type:'error',code:'VALIDATION_FAILED',message,retryable:true});
      else response.status(400).json({message});
    } finally {
      removeAbortListener?.();
      reservation?.release();
      if(record&&owns){record.busy=false;if(!finished)await store.remove(record);}
      writer?.end();
    }
  });
  app.get('/api/documents/:id/result',async(request,response)=>{
    let record;
    try {
      record=store.get(String(request.params.id),token(request));
      if(!record.output||record.busy) throw new Error('검증된 문서 결과가 없습니다.');
      record.readers++;
      const mime=record.state!.format==='docx'?'application/vnd.openxmlformats-officedocument.wordprocessingml.document':'application/vnd.openxmlformats-officedocument.presentationml.presentation';
      response.setHeader('Content-Type',mime);response.setHeader('Cache-Control','no-store');
      response.setHeader('Content-Disposition',`attachment; filename*=UTF-8''${encodeURIComponent(record.name??record.state!.name)}`);
      await pipeline(createReadStream(record.output),response);
    } catch(e) {if(!response.headersSent)response.status(404).json({message:'문서 결과가 없거나 접근할 수 없습니다.'});}
    finally {if(record){record.readers=Math.max(0,record.readers-1);await store.sweep();}}
  });
  app.delete('/api/documents/:id',async(request,response)=>{
    try {await store.remove(store.get(String(request.params.id),token(request)));response.json({ok:true});}
    catch {response.status(404).json({message:'문서를 찾을 수 없습니다.'});}
  });
}
