import { randomUUID, randomBytes, timingSafeEqual } from 'node:crypto';
import { mkdir, rm, copyFile, stat, readdir, writeFile, readFile } from 'node:fs/promises';
import path from 'node:path';
import { constants } from 'node:fs';
import type { DocumentEngine, DocumentState } from './document-engine.js';
import { DocumentLimitError, MAX_OFFICE_FILE_BYTES, OFFICE_FILE_TOO_LARGE } from './limits.js';

export interface DocumentRecord {
  id: string; token: string; dir: string; input: string; original?: string; state?: DocumentState;
  output?: string; name?: string; busy: boolean; readers: number; controller: AbortController;
  // Absolute: set when the document is stored and once more when its result is ready (resultReady). Reading a
  // record never extends it, so a client polling a document cannot keep one of the three slots forever.
  expires: number;
  // Downloads in progress (openDownload). Removal and expiry cut them short, so a client that stops reading
  // cannot hold the record either; the app's save lease (readResult) is local and is waited for instead.
  downloads: Set<Download>;
  // Set once removal is requested; a busy job finishing later must not revive the record.
  deleted?: boolean;
}
interface Download { controller: AbortController; done: Promise<void> }
/** How long a stored document, and then its finished result, stays available. */
export const DOCUMENT_WINDOW_MS = 30 * 60_000;
export class ArtifactStore {
  readonly records = new Map<string,DocumentRecord>();
  private timer: ReturnType<typeof setInterval>;
  private ready: Promise<void>;
  private closed=false;
  private imports=new Set<Promise<unknown>>();
  private removing=new Map<string,Promise<void>>();
  constructor(readonly root: string, readonly engine: DocumentEngine) {
    this.ready=this.initialize();
    this.timer=setInterval(()=>{void this.sweep().catch(()=>{});},60000); this.timer.unref();
  }
  private async initialize() {
    await mkdir(this.root,{recursive:true});
    for(const entry of await readdir(this.root,{withFileTypes:true})) {
      if(!entry.isDirectory()||entry.isSymbolicLink()||!/^doc-[a-f0-9-]{36}$/.test(entry.name))continue;
      const dir=path.resolve(this.root,entry.name);
      if(path.dirname(dir)!==path.resolve(this.root))continue;
      try {if((await readFile(path.join(dir,'.humanize-owned'),'utf8'))==='1')await rm(dir,{recursive:true,force:true});}catch{}
    }
    await mkdir(this.engine.root,{recursive:true});
    for(const entry of await readdir(this.engine.root,{withFileTypes:true})) {
      if(!entry.isDirectory()||entry.isSymbolicLink()||!/^job-[a-f0-9]{32}$/.test(entry.name))continue;
      const dir=path.resolve(this.engine.root,entry.name);
      if(path.dirname(dir)!==path.resolve(this.engine.root))continue;
      try {const s=JSON.parse(await readFile(path.join(dir,'job.json'),'utf8'));if(s.kind==='document'&&s.job===entry.name)await rm(dir,{recursive:true,force:true});}catch{}
    }
  }
  async create(name: string) {
    await this.ready;
    if(this.closed)throw new Error('Document store is closed');
    await this.sweep();
    if(this.closed)throw new Error('Document store is closed');
    if(this.records.size>=3) throw new Error('보관 중인 문서가 3개입니다. 이전 문서를 닫은 뒤 다시 시도해 주세요.');
    const ext=path.extname(name).toLowerCase();
    if(!['.docx','.pptx'].includes(ext)) throw new Error('DOCX 또는 PPTX 파일을 선택해 주세요.');
    const id=randomUUID(); const dir=path.join(this.root,'doc-'+id);
    const record:DocumentRecord={id,token:randomBytes(32).toString('hex'),dir,input:path.join(dir,'source'+ext),
      busy:true,readers:0,expires:Date.now()+DOCUMENT_WINDOW_MS,downloads:new Set(),controller:new AbortController()};
    this.records.set(id,record);
    try { await mkdir(dir,{recursive:true}); await writeFile(path.join(dir,'.humanize-owned'),'1'); return record; }
    catch(e) {this.records.delete(id);throw e;}
  }
  get(id: string, token: string) {
    const r=this.records.get(id);
    if(!r || r.deleted || !/^[a-f0-9]{64}$/.test(token) || !timingSafeEqual(Buffer.from(token),Buffer.from(r.token)) || (!r.busy&&r.expires<Date.now())) throw new Error('문서가 만료되었거나 접근 권한이 없습니다. 다시 선택해 주세요.');
    return r;
  }
  /** The result is ready: it can be downloaded for DOCUMENT_WINDOW_MS from now. A document is converted once,
   * so this extends a record once. */
  resultReady(record:DocumentRecord) {record.expires=Date.now()+DOCUMENT_WINDOW_MS;}
  inspect(record:DocumentRecord, name:string) {
    const task=this.inspectDocument(record,name);this.imports.add(task);
    return task.finally(()=>this.imports.delete(task));
  }
  private async inspectDocument(record:DocumentRecord, name:string) {
    try {
      if(this.closed)throw new Error('Document store is closed');
      record.state=await this.engine.prepare(record.input,record.controller.signal);
      if(this.closed||record.controller.signal.aborted)throw new Error('Document import was cancelled');
      record.state.name=path.basename(name,path.extname(name)).replace(/[<>:"/\\|?*]/g,'-')+'-humanized.'+record.state.format;
      record.name=record.state.name;
      record.busy=false;
      return this.public(record);
    } catch(error) {record.busy=false;await this.remove(record);throw error;}
  }
  public(record:DocumentRecord) {
    const s=record.state!;
    return {id:record.id,token:record.token,name:record.name??s.name,format:s.format,preview:s.preview,sourceChars:s.sourceChars,
      editableBlocks:s.editableBlocks,preservedBlocks:s.preservedBlocks,slides:s.slides,warnings:s.warnings};
  }
  importFile(file:string) {
    const task=this.importDocument(file);this.imports.add(task);
    return task.finally(()=>this.imports.delete(task));
  }
  private async importDocument(file:string) {
    if((await stat(file)).size>MAX_OFFICE_FILE_BYTES) throw new DocumentLimitError(OFFICE_FILE_TOO_LARGE);
    const record=await this.create(path.basename(file)); record.original=path.resolve(file);
    try {await copyFile(file,record.input,constants.COPYFILE_EXCL); return await this.inspect(record,path.basename(file));}
    catch(e) {record.busy=false;await this.remove(record);throw e;}
  }
  async remove(record:DocumentRecord) {
    if(this.records.get(record.id)!==record)return;
    record.deleted=true;
    record.controller.abort();
    record.expires=0;
    // Downloads end now and release their read; the record is gone when this resolves (or, during a running
    // job or an app save lease, as soon as that finishes).
    const downloads=[...record.downloads];
    for(const download of downloads)download.controller.abort();
    await Promise.all(downloads.map(download=>download.done));
    if(this.records.get(record.id)!==record)return;
    if(record.busy||record.readers)return;
    const existing=this.removing.get(record.id);if(existing)return existing;
    const task=(async()=>{
      if(record.state)await this.engine.cleanup(record.state.job);
      if(path.dirname(path.resolve(record.dir))!==path.resolve(this.root)||path.basename(record.dir)!=='doc-'+record.id)throw new Error('Invalid artifact cleanup path');
      await rm(record.dir,{recursive:true,force:true});this.records.delete(record.id);
    })();
    this.removing.set(record.id,task);
    try {await task;} finally {this.removing.delete(record.id);}
  }
  readResult(id:string,token:string) {
    const record=this.get(id,token);
    if(!record.output||record.busy)throw new Error('No document output');
    record.readers++;let released=false;
    return {record,release:async()=>{if(released)return;released=true;record.readers--;await this.sweep();}};
  }
  /** A read of the result over HTTP: `signal` aborts the stream when the record is removed or expires, and
   * `release` must run when the stream has settled. */
  openDownload(id:string,token:string) {
    const {record,release}=this.readResult(id,token);
    let settle!:()=>void;
    const download:Download={controller:new AbortController(),done:new Promise<void>(resolve=>settle=resolve)};
    record.downloads.add(download);
    return {record,signal:download.controller.signal,release:async()=>{
      if(!record.downloads.delete(download))return;
      record.readers--;settle();await this.sweep();
    }};
  }
  async sweep() {
    // Only an app save lease or a running job defers an expired record; its downloads are cut short.
    for(const r of this.records.values()) if(!r.busy&&r.readers===r.downloads.size&&r.expires<Date.now()) await this.remove(r);
  }
  async close() {
    this.closed=true;clearInterval(this.timer);await this.ready;
    for(const r of this.records.values())r.controller.abort();
    await Promise.allSettled([...this.imports]);
    for(const r of this.records.values())await this.remove(r);
  }
}
