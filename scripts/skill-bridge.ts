import { readFileSync, writeFileSync } from 'node:fs';
import { randomUUID } from 'node:crypto';
import { parseRewriteOptions, REWRITE_OPTIONS } from '../src/engine/rewrite-policy.js';
import { sourceSentences, checkDirectTextFidelity, restoreProtectedSentences } from '../src/engine/direct-text-fidelity.js';
import { parseTextResult } from '../src/engine/text-edits.js';
import { candidateReviewForRetry } from '../src/engine/candidate-review.js';
import { buildHumanizePrompt } from '../src/engine/prompt-builder.js';
import { diffText } from '../public/text-diff.js';
declare const COMPARISON_BROWSER: string;
const escapeHtml = (value: string) => value.replace(/[&<>"']/g, char => ({ '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;' }[char]!));
function comparison(source: string, finalText: string) {
  const diff = diffText(source, finalText);
  const body = diff.segments.map((segment: {type:string;text:string}) => segment.type === 'equal' ? escapeHtml(segment.text)
    : `<${segment.type === 'insert' ? 'ins' : 'del'}>${escapeHtml(segment.text)}</${segment.type === 'insert' ? 'ins' : 'del'}>`).join('');
  return { html: `<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>윤문 변경 비교</title>
<style>body{font:16px/1.7 system-ui,sans-serif;margin:2rem auto;padding:0 1rem;max-width:70rem;color:#242424;background:white}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:inherit}ins{background:#fff3b0;text-decoration:none}del{background:#ffe3e3;color:#a51d27;text-decoration:line-through}button{font:inherit;margin-right:.7rem;padding:.4rem .8rem}[hidden]{display:none}</style>
<main><h1>윤문 변경 비교</h1><p>연한 노랑: 삽입·변경 · 연한 빨강과 빨간 취소선: 삭제</p><p>비교에서 복사하면 삭제 내용은 제외됩니다. 전체 결과는 최종문 복사로 복사하세요.</p><button id="toggle">최종문 보기</button><button id="copy">최종문 복사</button><p id="status" role="status">${escapeHtml(diff.notice ?? '')}</p><pre id="changes" tabindex="0" aria-label="원문과 최종문의 변경 비교"><span>${body}</span></pre><pre id="final" tabindex="0" aria-label="최종문" hidden><span>${escapeHtml(finalText)}</span></pre></main><script>${COMPARISON_BROWSER}</script></html>`, coarse: diff.coarse };
}
try {
  const input = JSON.parse(readFileSync(process.argv[2]!, 'utf8'));
  const options = parseRewriteOptions(input.inputKind, input.strength);
  let result: unknown;
  switch (input.operation) {
    case 'options': result = { options, choices: REWRITE_OPTIONS }; break;
    case 'context': {
      let nonce; do { nonce = randomUUID(); } while (input.source.includes(nonce) || input.candidateReview?.candidate.includes(nonce));
      result = { sentences: sourceSentences(input.source), instructions: buildHumanizePrompt({ source: input.source,
        quickRules: input.quickRules, attempt: input.attempt, nonce, rewriteOptions: options, candidateReview: input.candidateReview }) }; break;
    }
    case 'parse': result = parseTextResult(JSON.stringify(input.response), input.source, 'Host', options); break;
    case 'protect': result = options?.strength === 'very-strong' ? restoreProtectedSentences(input.source, input.candidate)
      : { rewrittenText: input.candidate, restoredProtectedSentences: 0 }; break;
    case 'check': result = checkDirectTextFidelity(input.source, input.candidate); break;
    case 'review': {
      const code = input.gate.gate.exit_code;
      result = { candidateReview: candidateReviewForRetry({ source: input.source, candidate: input.candidate, options,
        gate: { status: ['ok','warn','abort','error'][code] as any, exitCode: code,
          gateCodes: [(['GATE_OK','GATE_WARN','GATE_ABORT','GATE_ERROR'] as const)[code]!],
          policy: input.gate.policy, hardFailures: input.gate.hardFailures, warningReasons: input.gate.warningReasons },
        parserIssues: input.parserIssues, skippedSentences: input.skippedSentences }) }; break;
    }
    case 'comparison': result = comparison(input.source, input.candidate); break;
    default: throw new Error('Unknown bridge operation');
  }
  writeFileSync(process.argv[3]!, JSON.stringify(result), 'utf8');
} catch {
  // Never echo source, candidate, upstream exceptions or model content to logs.
  process.stderr.write('Local text bridge failed.\n'); process.exitCode = 1;
}
