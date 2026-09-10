import { createDiffCopyHandlers } from '../public/result-diff.js';
const root = document.querySelector('main');
const changes = document.querySelector('#changes');
const final = document.querySelector('#final');
const status = document.querySelector('#status');
const handlers = createDiffCopyHandlers({ root, changes, onStatus: value => { status.textContent = value.message; } });
document.addEventListener('copy', handlers.handleCopy);
changes.addEventListener('contextmenu', handlers.handleContextMenu);
document.querySelector('#toggle').addEventListener('click', event => {
  final.hidden = !final.hidden;
  changes.hidden = !final.hidden;
  event.currentTarget.textContent = final.hidden ? '최종문 보기' : '변경 비교 보기';
});
document.querySelector('#copy').addEventListener('click', async () => {
  try {
    await navigator.clipboard.writeText(final.textContent);
    status.textContent = '최종문을 복사했습니다.';
  } catch {
    final.hidden = false; changes.hidden = true;
    document.querySelector('#toggle').textContent = '변경 비교 보기';
    const range = document.createRange(); range.selectNodeContents(final);
    const selection = document.getSelection(); selection.removeAllRanges(); selection.addRange(range);
    status.textContent = '선택된 최종문을 Ctrl+C로 복사하세요.';
  }
});
