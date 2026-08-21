# LAN 한국어 윤문 웹포탈 설계

**상태:** 승인된 요구사항을 바탕으로 확정  
**작성일:** 2026-08-21  
**작업 루트:** `C:\project\2026\ai-text-makes-likes-human`

## 1. 목표

비개발자가 같은 와이파이에 연결된 PC의 브라우저에서 원문을 붙여 넣고 **변환** 버튼을 눌러, `im-not-ai`의 한국어 윤문 규칙과 서버 PC에 로그인된 Codex CLI를 통해 자연스럽게 수정된 문구를 받는 로컬 웹포탈을 만든다.

포털 사용자는 로그인하지 않는다. 서버 PC 한 대가 웹 서버와 변환 엔진을 함께 실행하며, 최대 3명의 동시 사용 요청을 받아 한 건씩 안전하게 처리한다.

## 2. 확정 요구사항

- 모든 소스, 문서, 테스트, 벤더 엔진 파일, 런타임 임시 파일은 `C:\project\2026\ai-text-makes-likes-human` 아래에만 둔다.
- 화면은 데스크톱에서 좌측 **원본 문구 입력**, 우측 **수정된 문구 출력**의 2열 구조다.
- 사용자는 직접 붙여넣기 외에 `.txt` 파일을 선택해 좌측 입력란으로 불러올 수 있다.
- `.txt` 선택은 변환을 실행하지 않는다. 파일 내용 확인 후 사용자가 **변환** 버튼을 눌러야 서버 요청을 보낸다.
- 사용자가 **변환** 버튼을 눌렀을 때만 서버 요청을 보낸다. 입력·붙여넣기만으로 자동 변환하지 않는다.
- 웹포탈 로그인과 사용자 계정은 만들지 않는다.
- 서버 PC의 현재 ChatGPT 로그인 상태를 사용하는 Codex CLI를 공용 변환 엔진으로 호출한다.
- 같은 와이파이에서 최대 3명이 동시에 요청할 수 있다.
- 고정 글자 수 제한을 두지 않는다. 긴 글은 문단·문장 경계로 자동 분할해 순차 처리한다.
- 분량이 길수록 처리 시간이 증가한다는 안내와 진행률을 표시한다.
- 변환 이력을 저장하지 않는다. 원문·결과·Codex 세션은 영속화하지 않는다.
- 요청 처리에 필요한 임시 파일은 작업 완료, 실패, 취소, 연결 종료 시 삭제한다.
- 인터넷 공개 배포가 아니라 Windows 서버 PC의 사설 LAN 전용 포털로 제공한다.

## 3. 범위 밖

- 회원가입, 로그인, 권한별 사용자 관리
- 변환 이력, 즐겨찾기, 데이터베이스
- 결제, 크레딧, 사용량 과금
- PDF·Word 및 `.txt` 이외의 파일 업로드
- 인터넷 도메인, HTTPS 인증서, 클라우드 배포
- 관리자 대시보드
- 여러 모델 선택 UI
- 입력 중 자동 변환

## 4. 권장 아키텍처

단일 Node.js 프로세스가 정적 웹 UI, HTTP API, 작업 큐, 엔진 오케스트레이션을 담당한다. UI는 React 없이 HTML·CSS·브라우저 JavaScript로 구성한다. 현재 화면은 상태가 단순하므로 프런트엔드 프레임워크를 추가하지 않는 편이 설치와 운영에 유리하다.

```text
[LAN 브라우저 최대 3대]
          |
          | POST /api/transform (text/plain)
          | NDJSON 스트리밍 응답
          v
[Express 서버 : 0.0.0.0:3210]
  |- LAN 주소·보안 헤더·상태 점검
  |- TransformQueue (1 active + 2 waiting)
  |- RequestWorkspace (runtime/jobs/<uuid>)
  |- HumanizeEngine
  |    |- vendored prepare_monolith_input.py
  |    |- CodexRunner (codex exec --ephemeral)
  |    |- vendored verify_gates.py
  |    `- vendored reassemble_chunks.py
  `- NDJSON progress/result stream
```

### 기술 스택

- Node.js `>=24.19.0`
- npm `>=11.17.0` (`npm.ps1`이 아니라 `npm.cmd` 사용)
- TypeScript, Express
- Python `>=3.11` — 기존 결정적 엔진 스크립트 실행
- Codex CLI `>=0.149.0`, 서버 PC에서 `codex login status` 성공 필수
- Vitest + Supertest — 단위·API 통합 테스트
- Playwright — 실제 브라우저 사용자 흐름 테스트

## 5. 파일 경계

```text
ai-text-makes-likes-human/
|- package.json
|- package-lock.json
|- tsconfig.json
|- vitest.config.ts
|- playwright.config.ts
|- .gitignore
|- README.md
|- start-portal.cmd
|- setup-portal.cmd
|- scripts/
|  |- allow-lan-firewall.ps1
|  |- remove-lan-firewall.ps1
|  `- sync-engine.ps1
|- public/
|  |- index.html
|  |- styles.css
|  |- text-file.js
|  `- app.js
|- src/
|  |- server.ts
|  |- app.ts
|  |- config.ts
|  |- contracts.ts
|  |- network/
|  |  |- private-address.ts
|  |  `- lan-addresses.ts
|  |- transport/
|  |  |- ndjson.ts
|  |  `- request-body.ts
|  |- queue/
|  |  `- transform-queue.ts
|  `- engine/
|     |- humanize-engine.ts
|     |- codex-runner.ts
|     |- prompt-builder.ts
|     |- python-runner.ts
|     |- workspace.ts
|     |- output-schema.json
|     `- errors.ts
|- vendor/humanize-engine/
|  |- ENGINE_VERSION
|  |- UPSTREAM.md
|  |- LICENSE
|  |- scripts/
|  `- skills/humanize-korean/references/
|- runtime/jobs/.gitkeep
|- tests/
|  |- unit/
|  |- integration/
|  |- e2e/
|  |- fixtures/
|  `- helpers/
`- docs/superpowers/
   |- specs/
   `- plans/
```

각 파일은 한 책임만 가진다. HTTP 계층은 Codex 프로세스 세부사항을 모르고 `HumanizeEngine.transform()`만 호출한다. 엔진은 Express 응답 객체를 모르고 콜백으로 진행 이벤트를 발행한다. 큐는 변환 내용에 관여하지 않고 실행 순서와 취소만 관리한다.

## 6. 엔진 통합

### 6.1 엔진 자산

`im-not-ai` v2.3.2의 다음 자산을 `vendor/humanize-engine`에 복사해 런타임을 형제 저장소와 분리한다.

- Codex 단일 호출 스킬 지침
- `quick-rules.md`, taxonomy, rewriting playbook
- `prepare_monolith_input.py`, `sanitize_text.py`
- `verify_gates.py`, `verify_change_rate.py`, `checks.py`
- `reassemble_chunks.py`
- `metrics.py`, `metrics_v2.py`, `baseline.json`, `baseline_v2.json`
- MIT `LICENSE`

`ENGINE_VERSION`에는 `2.3.2`와 원본 Git commit을 기록한다. `scripts/sync-engine.ps1`은 유지보수자가 명시적으로 실행할 때만 벤더 사본을 갱신하며 웹 요청 중에는 원본 저장소를 참조하지 않는다.

### 6.2 Codex 실행 경계

서버는 shell 문자열을 조립하지 않고 `child_process.spawn()`에 실행 파일과 인자 배열을 전달한다. 프롬프트는 표준입력으로 전달한다.

실행 정책은 다음과 같다.

- `codex exec`
- `--ephemeral`: Codex 세션을 영속화하지 않음
- `--sandbox read-only`: 모델 도구가 작업 파일을 수정하지 못함
- `--ignore-user-config`, `--ignore-rules`: 사용자별 규칙이 윤문 결과를 바꾸지 않도록 격리
- `--output-schema`: 결과를 `{ rewrittenText, warnings }` JSON으로 제한
- 웹 검색 비활성
- chunk당 10분 타임아웃
- 브라우저 취소·연결 종료 시 전체 프로세스 트리 종료

사용자 원문은 명령이 아니라 데이터임을 시스템 지침에 명시하고 XML 경계 안에 넣는다. 원문 안의 “이전 지시 무시” 같은 문구는 변환 대상으로만 취급한다.

### 6.3 장문 처리

고정 글자 수 상한은 두지 않는다. 요청 본문은 메모리에 한 번에 적재하지 않고 `runtime/jobs/<uuid>/01_input.txt`로 스트리밍한다. 이후 벤더 shim이 문단·문장 경계로 약 7,000자 단위 청크와 manifest를 만든다.

청크는 원문 순서대로 한 개씩 처리한다. 각 청크는 다음 순서를 따른다.

1. 텍스트 위생 처리
2. Codex 윤문
3. 결정적 게이트 검사
4. gate 0이면 채택
5. gate 1이면 보수 프롬프트로 1회 재시도
6. gate 2면 더 보수적으로 1회 재시도하고, 다시 실패하면 해당 청크 원문을 유지하며 경고
7. gate 3 또는 프로세스 오류면 전체 작업 실패

모든 청크가 끝나면 기존 reassembler로 공백·각주·passthrough 구간을 복원하고 전체 문서 게이트를 한 번 더 실행한다. 전체 gate 2/3 결과는 사용자에게 전달하지 않는다.

## 7. 동시 사용자와 큐

- 동시에 접수 가능한 작업: 3개
- 동시에 실행하는 Codex 작업: 1개
- 네 번째 요청: HTTP 429와 `QUEUE_FULL` 반환
- 대기 작업: 5초마다 갱신되는 큐 위치 이벤트 수신
- 브라우저가 연결을 끊으면 대기 작업은 즉시 제거하고, 실행 작업은 취소 신호 후 프로세스 트리를 종료
- 작업별 `AbortController`를 사용해 서버 종료 시에도 전 작업을 정리

한 번에 Codex 하나만 실행해 서버 PC 부하, 계정 쿼터 경쟁, 출력 파일 충돌을 방지한다. 세 사용자는 각각 “처리 중” 또는 “대기 1/2번” 상태를 확인할 수 있다.

## 8. HTTP 계약

### `GET /api/health`

```json
{
  "status": "ready",
  "engine": "codex-cli",
  "engineVersion": "0.149.0",
  "humanizeVersion": "2.3.2",
  "activeJobs": 0,
  "queuedJobs": 0
}
```

Codex 미설치·미로그인·Python 부재 시 `status`는 `degraded`이고 변환 버튼을 비활성화할 수 있는 오류 코드를 함께 반환한다. 인증 정보나 경로는 응답하지 않는다.

### `POST /api/transform`

- 요청 `Content-Type`: `text/plain; charset=utf-8`
- 요청 본문: 원문 전체
- 응답 `Content-Type`: `application/x-ndjson; charset=utf-8`
- 캐시: `no-store`

이벤트 형식:

```ts
type TransformEvent =
  | { type: "accepted"; jobId: string; position: number }
  | { type: "queued"; position: number }
  | { type: "progress"; phase: "sanitize" | "chunk" | "transform" | "verify" | "assemble"; current: number; total: number; message: string }
  | { type: "result-start" }
  | { type: "result-delta"; text: string }
  | { type: "warning"; code: string; message: string }
  | { type: "done"; sourceChars: number; outputChars: number; chunks: number; elapsedMs: number }
  | { type: "error"; code: string; message: string; retryable: boolean };
```

결과는 검증 완료 후 작은 `result-delta` 이벤트로 스트리밍해 서버가 전체 결과를 메모리에 보관하지 않도록 한다.

`.txt` 파일에는 별도 업로드 API를 만들지 않는다. 브라우저가 선택한 파일을 로컬에서 해석해 기존 textarea에 넣고, 사용자가 변환 버튼을 누를 때만 동일한 `POST /api/transform` 계약으로 텍스트를 보낸다.

## 9. UI/UX

### 데스크톱

- 상단: 서비스명, “같은 와이파이 전용 · 로그인 없음” 안내
- 본문: 동일 너비의 입력·출력 카드 2개
- 좌측: 편집 가능한 textarea, **TXT 불러오기** 버튼, 선택 파일명·감지 인코딩, 글자 수, 초기화
- 우측: 읽기 전용 textarea, 결과 복사
- 중앙 하단: 큰 기본 버튼 **변환**
- 실행 중: 변환 버튼 대신 진행 상태와 **취소** 버튼
- 대기 중: “앞에 N건의 작업이 있습니다” 표시
- 장문: “분량에 따라 처리 시간이 오래 걸릴 수 있습니다” 표시

### 모바일·좁은 화면

두 카드를 위아래로 배치한다. 변환 버튼, 진행률, 오류 메시지는 카드 사이에 둔다.

입력 이벤트는 글자 수만 갱신한다. 네트워크 요청은 버튼 click 핸들러에서만 발생하도록 브라우저 테스트로 고정한다.

### TXT 불러오기

- 파일 선택기는 `accept=".txt,text/plain"`으로 제한한다.
- 확장자가 `.txt`가 아니면 입력란을 바꾸지 않고 “TXT 파일만 불러올 수 있습니다.”라고 안내한다.
- 디코딩 순서는 BOM이 있는 UTF-8 → UTF-16LE → UTF-16BE, BOM이 없으면 strict UTF-8, 마지막으로 `TextDecoder("euc-kr")` fallback이다. 브라우저 Encoding Standard의 `euc-kr` 디코더가 Windows CP949 계열 문서를 처리한다.
- BOM은 textarea에 넣지 않는다. 줄바꿈은 읽은 상태 그대로 유지한다.
- 파일을 읽으면 기존 입력을 교체하고 파일명·감지 인코딩·글자 수를 표시한다.
- 파일 선택만으로 `/api/transform`을 호출하지 않는다.
- 읽기·디코딩 실패 시 기존 입력을 보존한다.

## 10. 데이터·개인정보 정책

- 데이터베이스 없음
- 선택한 `.txt` 원본은 변환 버튼을 누르기 전까지 브라우저 밖으로 전송하지 않음
- 원문·결과를 애플리케이션 로그에 기록하지 않음
- 로그 허용 값: job ID, 글자 수, 청크 수, 처리 시간, 결과 코드
- Codex는 `--ephemeral` 실행
- 서버 임시 경로는 프로젝트 내부 `runtime/jobs`만 사용
- 성공·실패·취소·클라이언트 종료·서버 종료 모두 동일 cleanup 경로 사용
- 최종 결과 전송이 끝나면 작업 디렉터리 재귀 삭제
- 디스크 잔여 공간이 1 GiB 미만이면 입력 스트림을 중단하고 `INSUFFICIENT_DISK` 반환

## 11. LAN 보안

- 서버는 `0.0.0.0:3210`에 바인딩한다.
- API는 loopback, RFC1918 IPv4, IPv4-mapped 사설 주소, 로컬 IPv6만 허용한다.
- CORS를 열지 않고 동일 출처 요청만 사용한다.
- `Content-Security-Policy`, `X-Content-Type-Options`, `Referrer-Policy`, `Cache-Control: no-store`를 설정한다.
- Windows 방화벽 규칙은 Private 네트워크 프로필과 TCP 3210 포트로 한정한다.
- 방화벽 허용·제거 스크립트를 모두 제공하고, 관리자 권한이 필요한 작업은 사용자가 명시적으로 실행한다.
- 시작 시 LAN IPv4 주소를 찾아 `http://<LAN-IP>:3210` 형태로 표시한다.

로그인이 없으므로 같은 LAN의 모든 사용자가 서버 PC의 Codex 사용량을 소비할 수 있다. 이를 큐 3건, 사설 주소 검사, Windows Private 방화벽 규칙으로 제한한다.

## 12. 오류 처리

| 코드 | 사용자 메시지 | 처리 |
|---|---|---|
| `EMPTY_INPUT` | 원본 문구를 입력해 주세요. | 요청 시작 안 함 |
| `INVALID_TEXT_FILE` | TXT 파일만 불러올 수 있습니다. | 클라이언트에서 선택 거부 |
| `TEXT_FILE_DECODE_FAILED` | 텍스트 파일을 읽지 못했습니다. 다른 인코딩으로 저장해 다시 시도해 주세요. | 기존 입력 보존 |
| `QUEUE_FULL` | 현재 3건이 처리 중입니다. 잠시 후 다시 시도해 주세요. | HTTP 429 |
| `ENGINE_UNAVAILABLE` | 서버의 변환 엔진을 사용할 수 없습니다. | health degraded |
| `ENGINE_TIMEOUT` | 한 구간의 처리 시간이 초과되었습니다. | child 종료·cleanup |
| `ENGINE_OUTPUT_INVALID` | 변환 결과 형식을 확인하지 못했습니다. | 1회 재시도 후 실패 |
| `VALIDATION_FAILED` | 내용 보존 검증을 통과하지 못했습니다. | 결과 미전달 |
| `INSUFFICIENT_DISK` | 서버 저장 공간이 부족합니다. | 입력 중단·cleanup |
| `CLIENT_ABORTED` | 변환을 취소했습니다. | queue 제거 또는 child 종료 |
| `INTERNAL_ERROR` | 처리 중 오류가 발생했습니다. 다시 시도해 주세요. | 내용 없는 메타 로그 |

스택 추적과 원문은 브라우저에 보내지 않는다.

## 13. 시작과 운영

- `setup-portal.cmd`: `node`, `python`, `codex`, Codex 로그인 상태를 검사하고 `npm.cmd ci`, build를 실행한다.
- `start-portal.cmd`: 빌드 유무를 검사하고 서버를 시작한 뒤 localhost 브라우저를 열며 LAN 접속 주소를 콘솔에 표시한다.
- 방화벽 허용은 `scripts/allow-lan-firewall.ps1`, 원상복구는 `scripts/remove-lan-firewall.ps1`로 분리한다.
- 콘솔을 닫거나 `Ctrl+C`를 누르면 서버가 새 요청을 중단하고 활성 작업을 취소·정리한 뒤 종료한다.

## 14. 테스트 전략

### 자동 테스트

- 사설 IP 판별과 LAN 주소 선택
- NDJSON 인코딩·부분 라인 파싱
- 요청 본문 스트리밍과 UTF-8 처리
- 1 active + 2 waiting, 네 번째 429
- 대기·실행 중 클라이언트 취소
- Codex 명령 인자 배열과 shell 미사용
- 프롬프트 인젝션 문구가 데이터 경계 밖으로 나오지 않는지 검사
- chunk gate 재시도·원문 롤백·전체 실패
- 모든 종료 경로의 임시 디렉터리 삭제
- 입력만으로 요청이 발생하지 않고 변환 버튼 click에서 한 번만 발생
- UTF-8 BOM·UTF-16LE·UTF-16BE·CP949 계열 `.txt`를 올바르게 textarea로 불러옴
- `.txt` 선택만으로 서버 요청이 발생하지 않고, 잘못된 확장자·디코딩 실패 시 기존 입력을 보존
- 2열/1열 반응형 UI와 결과 복사

### 실엔진 테스트

`RUN_CODEX_LIVE=1`일 때만 작은 한국어 fixture를 실제 Codex로 처리한다. 테스트는 “2026년, 1,200명, OpenAI” 같은 보호 토큰이 결과에 남고 출력이 비어 있지 않으며 임시 폴더가 삭제됐는지를 검증한다.

### 수동 인수 테스트

1. 서버 PC에서 `start-portal.cmd` 실행
2. 서버 PC 브라우저에서 변환 성공
3. 같은 와이파이의 다른 PC 두 대에서 URL 접속
4. 세 PC가 동시에 변환해 1건 실행·2건 대기 표시 확인
5. 네 번째 요청이 친절한 혼잡 메시지를 받는지 확인
6. 15,000자 초과 문서가 여러 청크로 처리되고 순서·문단·수치가 보존되는지 확인
7. UTF-8 및 Windows 한글 인코딩 `.txt`를 선택하면 좌측 입력에 나타나되 아직 변환 요청은 없는지 확인
8. 파일을 확인한 뒤 변환 버튼을 눌러 정상 결과를 받는지 확인
9. 처리 중 브라우저 취소 후 Codex 프로세스와 `runtime/jobs`가 남지 않는지 확인
10. 서버 종료 후 포트가 닫히고 임시 파일이 없는지 확인

## 15. 완료 기준

- 비개발자가 `start-portal.cmd`를 더블클릭해 포털을 실행할 수 있다.
- 같은 와이파이의 PC 세 대에서 로그인 없이 접속할 수 있다.
- 입력만으로는 변환이 실행되지 않고 버튼 click으로만 실행된다.
- `.txt` 파일을 UTF-8·BOM 포함 UTF-16LE/BE·CP949 계열에서 불러올 수 있고, 파일 선택만으로는 변환이 실행되지 않는다.
- 짧은 글과 장문 모두 원문 순서대로 결과가 생성된다.
- 동시 3요청의 큐 상태가 각 브라우저에 표시된다.
- 원문·결과가 로그·DB·Codex 세션·runtime 폴더에 남지 않는다.
- 결정적 게이트를 통과하지 못한 결과는 사용자에게 정상 결과로 표시되지 않는다.
- 단위, 통합, E2E, 선택적 live 테스트와 LAN 수동 인수 항목이 통과한다.
