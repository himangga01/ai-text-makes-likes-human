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
import { EngineError } from '../engine/errors.js';
import { PUBLIC_MESSAGES, publicEvent, shutdownAware } from '../transport/public-error.js';

function documentFailure(error:unknown) {
  if(error instanceof EngineError) return {...publicEvent(error),retryable:false};
  // The record is removed after any failure, so the same document cannot be retried.
  if(error instanceof Error && error.message==='보호된 서식이 바뀌어 저장하지 않았습니다.')
    return {type:'error' as const,code:'VALIDATION_FAILED' as const,
      message:'보호된 서식이 바뀌어 저장하지 않았습니다.',retryable:false};
  return {...publicEvent(error),retryable:false};
}

function documentImportFailure(error:unknown) {
  const message=error instanceof Error?error.message:'';
  if(message.includes('디스크 공간이 부족'))return {status:507,code:'INSUFFICIENT_DISK',message:'문서를 처리할 디스크 공간이 부족합니다.'};
  if(message.includes('50 MiB')||message.includes('크기 제한')||message.includes('너무 큰 문서'))
    return {status:413,code:'DOCUMENT_TOO_LARGE',message:'문서 크기 제한을 초과했습니다. 더 작은 파일을 선택해 주세요.'};
  if(message.includes('암호화')||message.includes('편집 보호')||message.includes('writeProtection'))
    return {status:400,code:'DOCUMENT_PROTECTED',message:'암호화 또는 편집 보호된 문서는 지원하지 않습니다.'};
  if(message==='DOCX 또는 PPTX 파일을 선택해 주세요.'||message.includes('확장자와 실제 문서 형식')||
     message.includes('Office 문서 패키지가 아닙니다.')||message.includes('ZIP 문서를 읽지 못')||message.includes('손상된 XML'))
    return {status:400,code:'DOCUMENT_FORMAT_INVALID',message:'DOCX 또는 PPTX 파일 형식을 확인해 주세요.'};
  if(message.includes('보관 중인 문서가 3개'))
    return {status:429,code:'DOCUMENT_CAPACITY',message:'보관 중인 문서가 3개입니다. 이전 문서를 닫은 뒤 다시 시도해 주세요.'};
  return {status:500,code:'DOCUMENT_IMPORT_FAILED',message:'문서를 읽지 못했습니다. 잠시 후 다시 시도해 주세요.'};
}

// Refused before any job starts: the server keeps the document, and the client
// keys on `code` (e.g. INVALID_MODEL_SETTINGS re-syncs the model list).
class Rejection extends Error {
  constructor(readonly status:number,readonly code:string,message:string){super(message);}
}

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
    } catch(e) {if(record){record.busy=false;await store.remove(record);}if(!response.headersSent&&!response.destroyed){const failure=documentImportFailure(e);response.status(failure.status).json({code:failure.code,message:failure.message});}}
    finally {request.removeListener('aborted',onDisconnect);response.removeListener('close',onDisconnect);}
  });
  app.post('/api/documents/:id/transform',async(request,response)=>{
    let record; let reservation; let writer:NdjsonWriter|undefined; let finished=false; let owns=false; let clientClosed=false;
    let removeAbortListener:(()=>void)|undefined;
    if(!deps.preflight.ready){response.status(503).json({code:'ENGINE_UNAVAILABLE',message:PUBLIC_MESSAGES.ENGINE_UNAVAILABLE});return;}
    try {
      if(deps.queue.isShuttingDown) throw new Rejection(503,'SERVER_SHUTDOWN',PUBLIC_MESSAGES.SERVER_SHUTDOWN);
      try {record=store.get(String(request.params.id),token(request));}
      catch(e){throw new Rejection(404,'DOCUMENT_NOT_FOUND',e instanceof Error?e.message:'문서를 찾을 수 없습니다.');}
      if(record.busy||record.output||!record.state) throw new Rejection(409,'DOCUMENT_BUSY','진행 중이거나 완료한 문서입니다. 새로 선택해 주세요.');
      const choice=request.query.engine;
      if(choice!=='claude'&&choice!=='codex') throw new Rejection(400,'INVALID_ENGINE','CLI를 선택해 주세요.');
      let settings;
      try {settings=parseModelSettings(choice,request.query.model,request.query.effort);}
      catch(e){throw new Rejection(400,'INVALID_MODEL_SETTINGS',(e as Error).message);}
      if(deps.preflight.providers&&!deps.preflight.providers[choice].ready) throw new Rejection(503,'ENGINE_UNAVAILABLE','선택한 CLI의 설치·로그인 상태를 확인해 주세요.');
      reservation=deps.queue.reserve(record.id);
      if(!reservation) throw new Rejection(429,'QUEUE_FULL',PUBLIC_MESSAGES.QUEUE_FULL);
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
      response.once('close',()=>{if(!finished){clientClosed=true;r.controller.abort();}});
      writer.write({type:'accepted',jobId:r.id,position:0});
      await reservation.submit(async signal=>{
        const result=await engine.transform(r.state!,choice,r.dir,AbortSignal.any([signal,r.controller.signal]),event=>writer!.write(event),settings);
        if(r.deleted||r.controller.signal.aborted)throw new EngineError('CLIENT_ABORTED',true,'Document was closed during the transform');
        r.state=result.state;r.output=result.output;
        r.expires=Date.now()+30*60000;
        writer!.write({type:'document-result',artifactId:r.id,name:store.public(r).name,format:r.state.format,
          bytes:result.bytes,sha256:result.sha256,preview:r.state.preview});
        writer!.write({type:'done',sourceChars:r.state.sourceChars,outputChars:r.state.outputChars,chunks:r.state.totalChunks,elapsedMs:result.elapsedMs});
      },position=>writer!.write({type:'queued',position}));
      finished=true;
    } catch(e) {
      if(writer) writer.write(documentFailure(shutdownAware(e,deps.queue.isShuttingDown,clientClosed)));
      else if(e instanceof Rejection) response.status(e.status).json({code:e.code,message:e.message});
      else response.status(400).json({code:'DOCUMENT_TRANSFORM_FAILED',message:'문서 변환에 실패했습니다. 다시 선택해 주세요.'});
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
