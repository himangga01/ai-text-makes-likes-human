export function connectionState(provider) {
  if (!provider) return {state:'checking',icon:'◌',label:'점검 중'};
  if (provider.ready) return {state:'ready',icon:'✓',label:'로그인 확인'};
  if (provider.reason==='unsupported-version') return {state:'error',icon:'×',label:'CLI 업데이트 필요'};
  if (provider.reason) return {state:'error',icon:'×',label:'CLI 확인 필요'};
  if (provider.installed && !provider.authenticated) return {state:'auth',icon:'!',label:'로그인 필요'};
  return {state:'error',icon:'×',label:provider.installed?'점검 실패':'CLI 확인 필요'};
}
export function formatElapsed(milliseconds) {
  const seconds=Math.floor(Math.max(0,milliseconds)/1000);
  const minutes=Math.floor(seconds/60); const rest=String(seconds%60).padStart(2,'0');
  return minutes<60?`${String(minutes).padStart(2,'0')}:${rest}`:`${Math.floor(minutes/60)}:${String(minutes%60).padStart(2,'0')}:${rest}`;
}
export const effortLabels={low:'Low · 빠르게',medium:'Medium · 기본',high:'High · 깊게',xhigh:'Xhigh · 더 깊게',max:'Max · 최대',ultra:'Ultra · 최고'};
