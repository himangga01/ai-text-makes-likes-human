# 한국어 윤문 처리 성능 개선 설계

**상태:** 승인된 방향을 바탕으로 작성한 검토 대상 명세  
**작성일:** 2026-08-24  
**작업 루트:** `C:\project\2026\ai-text-makes-likes-human`

## 1. 배경

실제 Chrome 검증에서 Markdown 3,700자 문서가 8개 본문 청크로 분할되어 162.536초에 처리됐다. 문서에는 Markdown 제목이 8개 있었고, 현재 벤더 청커는 각 제목 앞을 강제 경계로 사용하므로 전체 분량이 목표 청크 크기 7,000자보다 작아도 제목 수만큼 청크가 생긴다.

각 본문 청크는 `codex exec`를 한 번 실행하고, 첫 검증 결과가 `warn` 또는 `abort`이면 보수 프롬프트로 한 번 더 실행한다. 따라서 본문 청크가 `B`개이고 재시도 청크가 `R`개이면 Codex 호출 수는 `B + R`이다. 관측 실행은 기본 8회에 최소 4회의 재시도가 확인되어 최소 12회 호출했다.

Codex 최소 진단 호출도 약 17,000 입력 토큰을 사용했다. 서비스는 각 호출마다 Codex 기본 지침과 약 10.8KB의 `quick-rules.md`를 다시 전달하므로, 작은 청크를 반복 호출하는 구조가 모델 자체보다 큰 지연 원인이다.

벤더 엔진은 이미 15,000자 이하 문서를 단일 호출 실증 범위로 정의하고 `light`, `standard`, `heavy` `route_hint`를 계산한다. 현재 포털은 manifest에서 이 값을 읽지 않고 항상 `--chunk` 결과를 그대로 실행한다.

## 2. 목표

- `gpt-5.6-sol`, reasoning effort `high`를 모든 변환의 고정 불변 조건으로 유지한다.
- `route_hint`가 `light` 또는 `standard`인 15,000자 이하 문서는 본문을 한 번에 윤문한다.
- `heavy` 문서와 15,000자 초과 문서는 현재의 손실 없는 청킹을 유지한다.
- 청킹 경로는 한 작업 안에서 최대 2개 청크를 동시에 처리한다.
- 검증, 재시도, 원문 롤백, 전체 문서 gate의 안전 기준은 완화하지 않는다.
- 원문과 결과를 기록하지 않고 처리 경로, 호출 수, 재시도 수, gate 코드, 단계별 시간만 계측한다.
- 동일 입력 기준으로 호출 수, 처리 시간, 품질, 취소 정리를 비교할 수 있는 반복 가능한 벤치마크를 제공한다.

## 3. 성공 기준

### 기능·품질

- 모든 Codex 실행 인자에 `--model gpt-5.6-sol`과 `--config model_reasoning_effort="high"`가 포함된다.
- 15,000자 이하 `light` 또는 `standard` 문서는 본문 청크가 정확히 1개다.
- 15,000자 이하라도 `heavy`이면 기존 청킹을 사용한다.
- 15,000자 초과 문서는 기존 문단·문장·제목·각주 경계를 보존한다.
- 제목, 목록 표식, 수치, 날짜, 고유명사, 직접 인용, 문단 순서, 줄바꿈, 말미 각주 passthrough가 기존 검증 수준으로 보존된다.
- 첫 gate `warn` 또는 `abort` 시 1회 재시도하고, 두 번째 `abort` 시 해당 입력을 원문으로 롤백한다.
- 전체 문서 gate `abort` 또는 `error` 결과는 사용자에게 전달하지 않는다.

### 성능

- 3,000~5,000자, 제목 6개 이상인 `light/standard` fixture는 gate 0 기준 Codex 호출 1회, 재시도 기준 최대 2회다.
- 기존 3,700자·8제목 형태의 기준 문서에서 현행 162.536초 대비 p50 처리 시간을 최소 60% 줄이는 것을 1차 목표로 한다.
- 청킹 문서는 직렬 기준 대비 동시성 2의 p50 처리 시간을 최소 30% 줄이는 것을 목표로 한다.
- 한 프로세스에서 동시에 실행되는 Codex 하위 프로세스는 최대 2개다.
- 처리량 개선 때문에 gate `warn`·`abort`, 원문 롤백, 전체 문서 실패 비율이 기준선보다 증가하면 해당 최적화를 활성화하지 않는다.

### 운영

- 브라우저 취소, 연결 종료, 작업 실패, 서버 종료 후 Codex·Python 자식 프로세스와 `runtime/jobs/<jobId>`가 남지 않는다.
- 기존 `POST /api/transform`의 `text/plain` 요청과 NDJSON 결과 계약을 유지한다.
- 기존 큐 용량 `1 active + 2 waiting`은 변경하지 않는다.
- 운영자는 환경 설정으로 청크 동시성을 `1`로 즉시 되돌릴 수 있다.

## 4. 범위 밖

- 모델 선택 UI 또는 요청별 모델 변경
- `gpt-5.6-sol` 이외 모델 사용
- reasoning effort `high` 이외 설정
- 첫 gate `warn` 재시도 생략 또는 gate 임계값 완화
- 여러 청크를 한 JSON 응답에 묶는 배치 프롬프트
- Codex 지속 세션, `resume`, 장기 실행 app-server 도입
- 동시 active 사용자 작업을 2개 이상으로 증가
- 데이터베이스, 원문·결과·프롬프트 로그
- Responses API 직접 연동으로의 전환

## 5. 검토한 접근법

### 5.1 권장: 자동 단일 호출 + 제한된 청크 풀

벤더가 계산하는 `route_hint`를 manifest 실행 경로에 반영한다. 작은 `light/standard` 문서는 본문 span을 하나로 만들고, `heavy` 또는 초장문만 현재 청킹한다. 청킹이 필요한 경우에만 동시성 2의 worker pool을 사용한다.

이 방식은 3,700자 사례의 호출 수를 최소 12회에서 1~2회로 줄이고, 초장문에서도 직렬 대기를 줄인다. 기존 gate와 reassembler를 그대로 사용하므로 품질 경계를 유지하기 쉽다.

### 5.2 대안: 청킹 유지 + 동시성만 증가

구현 범위는 작지만 모든 청크가 Codex 기본 지침과 규칙집을 반복 전송한다. 짧고 제목이 많은 문서의 토큰·호출 낭비를 해결하지 못하고, 동시 호출 제한이나 계정 쿼터에 더 빨리 도달할 수 있어 단독 해법으로 채택하지 않는다.

### 5.3 대안: 청크 배치 또는 지속 세션

고정 프롬프트 재전송을 줄일 수 있지만, 응답 하나의 JSON 손상이 여러 청크를 함께 실패시키고 부분 재시도·취소·schema 검증 경계를 새로 설계해야 한다. 현재 문제를 해결하는 데 필요한 범위를 넘어가므로 1차 설계에서 제외한다.

## 6. 고정 모델 실행 경계

모델 고정은 속도 최적화와 독립된 전제 조건이다. 모든 `CodexRunner.transform()` 호출은 다음 인자를 포함한다.

```text
codex exec
  --ephemeral
  --ignore-user-config
  --ignore-rules
  --model gpt-5.6-sol
  --config model_reasoning_effort="high"
  --sandbox read-only
  --output-schema <schema-path>
  --output-last-message <result-path>
  -
```

`--ignore-user-config`와 `--ignore-rules`는 유지한다. 사용자 PC의 모델·reasoning·플러그인·개인 규칙이 서비스 결과를 바꾸지 않으며, 모델과 effort는 실행 인자로만 결정한다. 공식 모델 지원 근거는 [GPT-5.6 Sol Model](https://developers.openai.com/api/docs/models/gpt-5.6-sol)이다.

## 7. 자동 라우팅

### 7.1 라우팅 규칙

준비 단계는 sanitize와 전문 metrics 계산을 먼저 완료한 뒤 다음 규칙으로 `processing_mode`를 결정한다.

| 조건 | `processing_mode` | 실행 |
|---|---|---|
| `source_chars <= 15000`이고 `route_hint`가 `light` 또는 `standard` | `single` | 본문 span 1개 |
| `route_hint`가 `heavy` | `chunked` | 기존 제목·문단·문장 청킹 |
| `source_chars > 15000` | `chunked` | 기존 제목·문단·문장 청킹 |
| route 계산 실패·누락·알 수 없는 값 | `chunked` | 안전 우선 fallback |

Markdown 제목 수는 라우팅 조건이 아니다. `single` 본문에는 여러 제목이 들어갈 수 있으며, 프롬프트의 Markdown 구조 보존 지침과 full-document gate가 이를 검증한다.

### 7.2 manifest

`chunk_manifest.json`에 다음 필드를 유지·추가한다.

```json
{
  "route_hint": "light | standard | heavy | null",
  "route_reason": "비식별 운영 설명",
  "processing_mode": "single | chunked"
}
```

TypeScript `ChunkManifest`는 세 필드를 검증해 읽는다. `route_reason`은 원문을 포함하지 않는 metrics 기반 설명만 허용하며 운영 로그에는 전체 문자열 대신 `route_hint`와 `processing_mode`만 기록한다.

### 7.3 single span 생성

`single` 모드도 기존 manifest와 reassembler를 사용한다.

- 본문이 있으면 문서 시작부터 말미 각주 블록 전까지 하나의 body span을 만든다.
- 말미 각주 passthrough가 있으면 두 번째 span으로 유지한다.
- body span의 `rewritten_file`은 기존 reassembler가 읽을 수 있는 안전한 파일명으로 지정한다.
- 원문 SHA-256, span 연속성, 전체 연결 결과가 원문과 같은지 기존 lossless self-check를 실행한다.
- 본문이 없고 passthrough만 있는 문서는 Codex를 호출하지 않고 원문을 그대로 재조립한다.

### 7.4 벤더 패치 소유권

라우팅은 manifest 생성 시점에 span을 결정해야 하므로 `prepare_monolith_input.py`의 포털 패치로 구현한다. 벤더 원본의 기본 동작은 바꾸지 않도록 포털 전용 CLI 플래그 `--portal-auto-route`를 추가하고 `PythonEngine.prepare()`만 이 플래그를 전달한다.

`scripts/patches/humanize-engine-portal.patch`는 기존 줄바꿈 보존 변경과 `--portal-auto-route` 변경을 함께 소유한다. `scripts/sync-engine.ps1`은 고정 upstream commit을 복사한 뒤 이 patch를 check하고 적용한다. patch가 원본에 맞지 않으면 동기화를 실패시켜 조용히 자동 라우팅이 사라지는 일을 막는다. `UPSTREAM.md`에는 두 포털 변경과 patch 경로를 기록한다.

## 8. 청크 동시성 2

### 8.1 실행 구조

`HumanizeEngine`의 청크 루프를 다음 세 책임으로 분리한다.

```ts
interface ChunkTaskResult {
  chunkIndex: number;
  warnings: HumanizeWarning[];
  codexCalls: number;
  retries: number;
  gateCodes: string[];
  timings: ChunkTiming;
}

processChunk(chunk, context): Promise<ChunkTaskResult>
runChunkPool(chunks, concurrency, processChunk): Promise<ChunkTaskResult[]>
flushChunkResults(results): void
```

`single` 모드는 항상 concurrency 1이다. `chunked` 모드는 `CODEX_CHUNK_CONCURRENCY`를 사용하며 허용값은 `1` 또는 `2`다. 최종 배포 목표 기본값은 `2`다. 구현 중 기준선과 첫 live benchmark는 환경값 `1`을 명시하고, 수용 기준을 통과한 뒤에만 기본값을 `2`로 전환한다. 기준 미달이면 릴리스 기본값은 `1`로 유지한다.

각 worker는 고유한 source, Codex result, rewritten 파일을 사용한다. 모든 worker가 완료된 뒤 manifest 순서로 warning과 통계를 정렬하고 기존 reassembler와 full-document gate를 한 번 실행한다.

### 8.2 전역 제한

작업 큐는 현재 active job을 1개로 제한한다. 이 전제를 유지하면서도 `CodexRunner` 앞에 최대 2 permit의 전역 semaphore를 둔다. 향후 active job 수가 변경되어도 전체 Codex 프로세스 수는 이 semaphore를 넘지 않는다.

재시도도 동일 permit을 사용한다. 첫 호출이 permit을 영구 점유한 채 gate와 재시도를 기다리지 않고, 각 Codex subprocess 실행 구간에만 permit을 획득한다.

### 8.3 실패와 취소

- worker 하나가 실패하면 job-local `AbortController`로 sibling worker를 취소한다.
- sibling의 Codex·Python 프로세스 종료를 `Promise.allSettled()`로 기다린 뒤 최초 오류를 전달한다.
- 사용자 취소 신호와 job-local 실패 신호는 `AbortSignal.any()`로 결합한다.
- 취소된 worker는 새 재시도를 시작하지 않는다.
- 모든 worker가 종료되기 전에는 reassembler와 workspace cleanup을 시작하지 않는다.
- 여러 오류가 발생해도 사용자에게는 기존 public error 하나만 반환하고 원문·프롬프트·하위 stderr를 노출하지 않는다.

## 9. 진행률 계약

동시 처리 완료 순서는 manifest 순서와 다를 수 있으므로 청크 번호를 전체 진행률로 직접 사용하지 않는다. `progress` 이벤트에 집계 단위를 추가한다.

```ts
type TransformProgressEvent = {
  type: "progress";
  phase: TransformPhase;
  current: number;
  total: number;
  completedUnits: number;
  totalUnits: number;
  message: string;
};
```

각 body chunk는 `Codex 완료`와 `gate 완료` 두 work unit을 가진다. 재시도는 총량을 늘리지 않고 현재 진행률을 유지한다. `completedUnits`는 atomic aggregate counter에서 증가하므로 완료 순서와 무관하게 단조 증가한다.

브라우저는 `completedUnits / totalUnits`를 15~90% 구간에 매핑한다. 기존 서버나 fixture가 새 필드를 제공하지 않으면 현재 phase 기반 계산을 fallback으로 사용한다. `assemble`은 90%, 결과 수신은 95%, `done`은 100%를 유지한다.

## 10. 비식별 계측

변환 결과에 내부 `TransformDiagnostics`를 추가한다.

```ts
interface TransformDiagnostics {
  model: "gpt-5.6-sol";
  reasoningEffort: "high";
  processingMode: "single" | "chunked";
  routeHint: "light" | "standard" | "heavy" | null;
  sourceChars: number;
  bodyChunks: number;
  codexCalls: number;
  retries: number;
  gateCodes: string[];
  maxObservedCodexConcurrency: number;
  prepareMs: number;
  codexMs: number;
  gateMs: number;
  assembleMs: number;
  totalMs: number;
}
```

허용 로그는 위 필드와 job ID뿐이다. `route_reason`, 원문·결과·프롬프트, 파일 내용, Codex 응답, gate stdout/stderr는 기록하지 않는다. `gateCodes`는 parser가 허용한 결정적 코드만 기록하고 자유 형식 문자열은 버린다.

## 11. 파일과 책임

| 파일 | 책임 |
|---|---|
| `src/config.ts` | `CODEX_CHUNK_CONCURRENCY` 검증, 허용값 1·2, 수용 기준 통과 후 목표 기본값 2와 rollback 1 |
| `src/engine/codex-runner.ts` | 고정 모델·effort, 전역 Codex semaphore 적용 지점 |
| `src/engine/python-engine.ts` | route·processing mode manifest 검증, 포털 auto-route flag 전달, gate 코드 파싱 |
| `src/engine/humanize-engine.ts` | single/chunked 공통 처리, `processChunk`, worker pool, 통계 집계 |
| `src/engine/chunk-pool.ts` | 순수 bounded worker pool과 실패 시 sibling abort |
| `src/engine/codex-semaphore.ts` | 전역 최대 2 Codex subprocess permit과 관측 동시성 |
| `src/contracts.ts` | aggregate progress 필드 추가 |
| `src/app.ts` | 비식별 완료·실패 diagnostics 로그 |
| `public/progress.js` | aggregate unit 우선, phase fallback 진행률 계산 |
| `vendor/.../prepare_monolith_input.py` | 포털 flag 사용 시 route 기반 single span 생성 |
| `scripts/patches/humanize-engine-portal.patch` | 줄바꿈 보존과 auto-route 포털 변경의 재적용 가능한 patch |
| `scripts/sync-engine.ps1` | 벤더 복사 후 포털 패치 검증·재적용 |
| `vendor/humanize-engine/UPSTREAM.md` | 포털 패치와 upstream 고정 근거 문서화 |

HTTP 요청 형식, 정적 UI 구조, 큐 클래스, 결과 다운로드 방식은 변경하지 않는다.

## 12. 테스트 전략

### 12.1 TDD 단위 테스트

- Codex 인자에서 모델·effort가 빠지거나 다른 값이면 실패한다.
- manifest parser가 route·processing mode를 허용 enum으로만 받아들인다.
- `light/standard` 15,000자 이하 Markdown 문서는 제목이 여러 개여도 body span 1개다.
- `heavy`, 15,000자 초과, route 누락은 기존 chunked 경로다.
- 말미 각주는 single body 뒤 passthrough로 남고 전체 span 연결이 원문과 같다.
- worker pool은 동시에 2개만 실행하고 결과를 manifest 순서로 반환한다.
- worker 하나가 실패하면 sibling을 취소하고 모든 worker 종료 후 reject한다.
- 사용자 취소 뒤 새 청크나 재시도를 시작하지 않는다.
- aggregate progress는 완료 순서가 뒤섞여도 감소하지 않는다.
- concurrency 환경값 `0`, `3`, 소수, 문자열은 시작 시 거부한다.

### 12.2 통합 테스트

- 실제 Python prepare/reassemble로 single·chunked manifest를 각각 생성하고 원문을 손실 없이 복원한다.
- fake Codex로 single 문서의 heading, 숫자, 인용, 각주가 보존되는지 검증한다.
- 4청크 fake Codex를 지연 순서가 다른 promise로 실행해 최대 동시성 2와 최종 순서를 검증한다.
- retry warn·abort·rollback과 full-document abort 동작이 직렬 기준과 같다.
- 취소 후 Codex/Python fake process와 workspace가 남지 않는다.

### 12.3 브라우저 테스트

- single 모드는 진행률이 15%에서 90%, 95%, 100%로 단조 증가한다.
- chunked concurrency 2는 완료 순서가 달라도 진행률과 상태 문구가 역행하지 않는다.
- warning 중 진행률을 유지하고 취소 시 입력을 보존한다.
- 기존 TXT·MD 업로드, MD 다운로드, 복사, 접근성, 모바일 visual snapshot을 모두 유지한다.

### 12.4 opt-in live benchmark

`RUN_CODEX_LIVE=1`에서만 실행되는 벤치마크를 추가한다. 입력 본문과 결과는 출력하지 않고 다음 값만 JSON으로 남긴다.

- fixture ID
- 입력 글자 수·제목 수
- model·reasoning effort
- processing mode·route hint
- body chunk 수
- Codex 호출·재시도·gate 코드 수
- 단계별 시간과 총시간
- 최종 full gate 결과
- protected anchor·heading 보존 통과 여부

fixture는 사용자 문서를 저장하지 않고 테스트 전용 한국어 문단으로 생성한다. short fixture는 3,000~5,000자와 8개 Markdown 제목, long fixture는 16,000~20,000자와 여러 문단·제목·숫자·인용을 포함한다.

각 구성을 최소 3회 실행해 p50을 비교한다. concurrency 2에서 429·CLI 실패·gate 악화가 발생하면 기본값을 1로 유지한다.

## 13. 구현·배포 순서

1. 현재 모델 고정 테스트와 비식별 단계 계측을 기준선으로 확정한다.
2. manifest route 필드와 포털 auto-route flag를 추가하고 concurrency 1에서 single 경로를 검증한다.
3. short live benchmark가 호출 수·품질·60% 시간 목표를 만족할 때 auto-route를 기본 활성화한다.
4. worker pool과 전역 semaphore를 추가하고 기본 concurrency 1에서 회귀 테스트한다.
5. long live benchmark에서 품질·실패율 기준을 통과하면 기본 concurrency를 2로 변경한다.
6. 전체 unit·integration·E2E·visual·live 테스트 후 새 빌드로 서버를 재시작한다.
7. 운영 문서에 rollback 값 `CODEX_CHUNK_CONCURRENCY=1`과 계측 확인 방법을 기록한다.

단계 2가 성능 목표를 충족하더라도 단계 4의 동시성 구현은 초장문 처리 개선을 위해 유지한다. 단, live benchmark가 품질 또는 안정성 기준을 통과하지 못하면 concurrency 기본값은 1로 남긴다.

## 14. 수용 기준

- 모델은 모든 경로에서 `gpt-5.6-sol`, reasoning `high`로 고정된다.
- short `light/standard` fixture의 body chunk 수가 1이고 Codex 호출 수가 1~2다.
- short live p50이 기준선보다 최소 60% 짧다.
- long chunked live p50이 직렬 기준보다 최소 30% 짧거나, 안정성 기준 미달 시 concurrency 1로 자동 rollback 가능한 상태다.
- 동일 fixture에서 heading·protected anchor·문단 순서·각주·full gate 결과가 기준선보다 나빠지지 않는다.
- 최대 Codex 동시성은 설정값과 전역 상한 2를 넘지 않는다.
- 취소·실패·서버 종료 후 활성 자식 프로세스와 job 파일이 남지 않는다.
- 원문·결과·프롬프트가 로그, benchmark report, 테스트 artifact에 포함되지 않는다.
- `npm.cmd run typecheck`, `npm.cmd test`, `npm.cmd run build`, `npm.cmd run test:e2e`, opt-in live benchmark가 모두 통과한다.
