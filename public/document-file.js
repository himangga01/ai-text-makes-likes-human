import { desktop, networkError, request } from './transport.js';
export const isOfficeFile = name => /\.(docx|pptx)$/i.test(name ?? '');
export async function importDocument(file) {
  if(file.size>50*1024**2)throw new Error('파일은 50 MiB 이하만 지원합니다.');
  const response=await request('/api/documents',{method:'POST',headers:{'content-type':'application/octet-stream','x-file-name':encodeURIComponent(file.name)},body:file});
  const info=await response.json();if(!response.ok)throw new Error(info.message||'문서를 읽지 못했습니다.');return info;
}
export async function closeDocument(document) {
  if(!document)return;
  try {
    if(desktop)await window.humanizeDesktop.closeDocument({id:document.id,token:document.token});
    else await fetch(`/api/documents/${document.id}`,{method:'DELETE',headers:{authorization:`Bearer ${document.token}`}});
  } catch {}
}
export async function transformDocument(document,engine,signal,onEvent,settings) {
  if(desktop) {
    let error;
    let finish;
    const completed=new Promise(resolve=>{finish=resolve;});
    const unsubscribe=window.humanizeDesktop.onEvent(value=>{
      if(!error)try{onEvent(value);}catch(e){error=e;}
      if(value.type==='done'||value.type==='error')finish();
    });
    const cancel=()=>window.humanizeDesktop.cancel().catch(()=>{});
    signal.addEventListener('abort',cancel,{once:true});
    let timer;
    try {
      await window.humanizeDesktop.transformDocument({id:document.id,token:document.token,engine,settings});
      await Promise.race([completed,new Promise((_,reject)=>{timer=setTimeout(()=>reject(new Error('문서 완료 응답을 받지 못했습니다.')),5000);})]);
      if(signal.aborted)throw new DOMException('Cancelled','AbortError');
      if(error)throw error;
    }
    finally {clearTimeout(timer);unsubscribe();signal.removeEventListener('abort',cancel);}
    return;
  }
  const query=new URLSearchParams({engine,...(settings?{model:settings.model,effort:settings.effort}:{})});
  const response=await request(`/api/documents/${document.id}/transform?${query}`,{method:'POST',headers:{authorization:`Bearer ${document.token}`},signal});
  if(!response.ok||!response.body){const info=await response.json().catch(()=>({}));throw Object.assign(new Error(info.message||'문서 변환을 시작하지 못했습니다.'),{code:info.code});}
  const reader=response.body.getReader();const decoder=new TextDecoder();let buffer='';
  try {
    while(true){const {done,value}=await reader.read().catch(error=>{throw networkError(error);});buffer+=decoder.decode(value,{stream:!done});const lines=buffer.split('\n');buffer=lines.pop()??'';for(const line of lines)if(line.trim())onEvent(JSON.parse(line));if(done)break;}
    if(buffer.trim())onEvent(JSON.parse(buffer));
  } finally {await reader.cancel().catch(()=>{});reader.releaseLock();}
}
export async function saveDocument(doc,name) {
  if(desktop)return window.humanizeDesktop.saveDocument({id:doc.id,token:doc.token});
  const response=await request(`/api/documents/${doc.id}/result`,{headers:{authorization:`Bearer ${doc.token}`}});
  if(!response.ok)throw new Error('문서가 만료되었습니다. 다시 선택해 변환해 주세요.');
  const blob=await response.blob();const url=URL.createObjectURL(blob);const link=document.createElement('a');
  link.href=url;link.download=name;document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);return true;
}
