# 포털 운영 점검표

현재 소스 기준: 2026-10-02, `d9df30e`(앱 `0.4.0`). 이 문서의 명령은 운영 절차이며 이번 문서 갱신에서 실행한 명령이 아닙니다. 현재 코드의 구조·제약은 [코드 분석](code-analysis.md), 서비스 범위는 [서비스 분석](service-analysis.md)을 참고합니다.

## 운영 원칙

- 서비스 주소: `http://localhost:7882`, LAN은 서버 콘솔에 표시된 주소
- 서버 바인딩: `0.0.0.0:7882`
- 방화벽 범위: Windows Private 프로필, TCP 7882
- 동시 접수: 3건
- 실행 중인 변환 작업: 1건
- 위 접수 수에는 일반 텍스트 업로드 예약·대기·실행 중 변환이 포함됨. Office 업로드·파싱은 별도의 최대 3개 문서 보관소를 사용하고, 변환할 때 같은 실행 큐를 사용함. 완료한 Office 결과도 만료·삭제 전까지 보관 자리를 점유함
- 텍스트 자동 라우팅: 기본 활성화. 15,000자 이하의 `light`·`standard` 문서는 본문 1개 구간, `heavy`·15,000자 초과·안전하게 판정할 수 없는 문서는 청킹. 단일 구간도 검증 결과에 따라 선택한 CLI를 한 번 더 호출할 수 있음
- 청크 동시 Codex 실행: 기본 1개. `CODEX_CHUNK_CONCURRENCY=2`를 명시한 실험에서만 최대 2개
- 변환 모델 기본값: GPT는 `gpt-5.6-sol`, reasoning effort `medium`; Claude는 `claude-fable-5-1`, effort `high`. 연결 설정에서 바꿀 수 있으며 `/api/health`의 `modelDefaults`로 제공
- 모델 거부: CLI가 선택한 모델을 알지 못하거나 계정에 권한이 없으면 `MODEL_UNAVAILABLE`로 안내하고 재시도하지 않음
- CLI 실행 실패: 로그인 만료·사용 한도·네트워크 오류 등으로 CLI가 실패하면 `ENGINE_FAILED`로 작업을 중단하고 재시도할 수 있음을 알림. 원문을 결과로 돌려주지 않음. 로그에는 종료 코드와 CLI 상태 값만 남김
- 시간 초과(`ENGINE_TIMEOUT`)는 작업을 중단함. 형식이 잘못된 모델 응답만 해당 구간을 재시도한 뒤 원문으로 되돌리며, 모든 구간의 응답이 쓸 수 없으면 `ENGINE_OUTPUT_INVALID`로 중단함
- 입력 크기: 웹·앱의 직접 입력·TXT·MD는 LF 정규화 후 Unicode code point 기준 100,000자 이하(`src/engine/input-limits.ts`). `Content-Length`가 400,000바이트를 넘으면 받기 전에 `413 INPUT_TOO_LARGE`, 그 밖의 요청은 받는 도중 정규화한 글자 수가 100,000자를 넘으면 스트림 오류로 중단함. TXT·MD 파일은 1 MiB를 넘으면 브라우저와 앱이 읽기 전에 거절함. `/api/health`의 `inputLimits`로 제공하며 호스트 세션의 스킬 TXT·MD에는 이 제한을 적용하지 않음
- 서버 종료로 끊긴 변환은 사용자 취소(`CLIENT_ABORTED`)가 아닌 `SERVER_SHUTDOWN`으로 알림. 종료 중에 들어온 새 요청도 `503 SERVER_SHUTDOWN`으로 거절함
- 본문 이력·본문 로그: 없음. 처리 중 원문·중간 결과는 임시 파일로 사용함. 일반 텍스트는 완료·실패·취소 후 정리하고 Office는 마지막 사용 후 30분까지 보관함. 활성 작업과 읽기 임대 중에는 정리를 미룸
- 허용 로그: job ID, 글자 수, 청크 수, 처리 시간, 결과 코드, 서법 복원·쉼표 제거·조사 교정 건수, 게이트 실패 코드별 횟수, 문체 진단 건수(코드와 숫자만, 본문 없음)
- 게이트 직전 후처리: `restore_modality.py`, `strip_injected_commas.py`, `engine_runtime/super_sejong_josa.py`(수정으로 새로 틀어진 조사 형태 교정)를 청크마다 실행. `--all` 격상은 진단 단계가 없으므로 사용하지 않음
- 슈퍼세종엔진: `SUPER_SEJONG_MODE`가 `enforce`(기본)면 의미 보존 검사(부정·서법·어휘 극성·참여자 역할·조사 형태)가 실패 시 보수적 재시도·되돌림을 일으킴. `shadow`는 같은 검사를 실행해 `shadowFailureCounts`로만 기록하고 막지 않음. `off`는 검사·조사 교정·문체 힌트를 모두 끄고 기존 게이트만 사용함. 아래 [슈퍼세종엔진 모드](#슈퍼세종엔진-모드) 참고
- 줄바꿈: 수신 단계에서 CR·CRLF를 LF로 통일
- 준비 상태: Python 3.11+와 엔진 라벨 2.3.2가 준비되고 Codex 또는 Claude 중 하나가 설치·로그인돼 있으면 ready. Office 지원은 별도로 `lxml` import를 확인하며 `documentsAvailable`로 표시함
- 프로세스 상태: `/api/status`는 외부 CLI를 점검하지 않고 `status`·`pid`·`activeJobs`·`queuedJobs`만 즉시 반환함. supervisor가 사용하며, 이 경로가 없는 이전 빌드에는 `/api/health`로 대신 확인함
- 상태 갱신: `/api/health`는 3초 캐시·진행 중 조회 공유를 사용해 재점검함. 보이는 유휴 화면은 60초마다 조회하고 수동 점검·화면 복귀·관련 오류 때도 다시 조회함. 모델별 계정 권한은 실제 실행으로만 확인됨
- 상태 수치의 범위: `activeJobs`·`queuedJobs`에는 일반 텍스트 업로드 예약과 Office 보관·파싱·다운로드가 표시되지 않음. 두 값이 0이어도 모든 작업이 끝났다는 뜻은 아님
- 접근 범위: 소켓의 로컬·사설 IP, 로컬·사설 IP 또는 localhost Host, 제공된 Origin을 확인함. 사용자 로그인·TLS는 없으며 같은 와이파이 여부를 직접 확인하지 않음

## macOS 서버 운영

Windows 포털은 `start-portal.cmd`로 실행하지만, macOS 서버는 supervisor가 관리합니다.

```sh
node dist/ops/hermes-service.js status
node dist/ops/hermes-service.js restart
node dist/ops/hermes-service.js stop
node dist/ops/hermes-service.js start
node dist/ops/hermes-service.js logs 100
```

supervisor는 `PYTHON_COMMAND`로 서버용 Python을 전달합니다. 개발 명령과 테스트는 `PYTHON_COMMAND`가 없으면 PATH에서 Python 3.11 이상을 찾습니다. macOS 기본 `python3`는 3.9라 사용할 수 없고, Office 문서 기능은 `lxml`이 설치된 Python이 필요합니다.

```sh
export PYTHON_COMMAND=$HOME/.hermes/hermes-agent/venv/bin/python
npm run typecheck
npm test
npm run test:documents
npm run test:skills
E2E_PORT=7893 npm run test:e2e
```

`test:skills`는 직접 입력 경로에 Node 브리지가 필요하며, 없으면 자동으로 빌드합니다. 수동 빌드는 `node scripts/build-skill-bridge.mjs`입니다.

운영 중인 서비스는 기본 포트 7882와 `runtime/` 잠금을 점유합니다. 서비스를 멈추지 않고 e2e를 실행하려면 `E2E_PORT`를 지정하세요. 별도 포트로 실행하면 테스트 서버가 `runtime/test-tmp/e2e`를 사용해 운영 job 폴더와 잠금을 건드리지 않습니다. 다른 런타임 경로가 필요하면 `HUMANIZE_RUNTIME_ROOT`로 지정합니다.

`npm run test:e2e`는 Playwright 서버를 띄우기 전에 `npm run build`로 `dist/`를 다시 만듭니다. 운영 서버와 매시간 watchdog도 같은 `dist/`를 실행하므로 커밋하지 않은 코드로 e2e를 돌리면 다음 재시작부터 그 빌드가 운영에 쓰입니다. 운영 중인 저장소에서는 `dist/`를 백업한 뒤 실행하고 끝나면 되돌리거나, 별도 체크아웃에서 실행하세요.

Python 단계(`engine_runtime/`, `vendor/humanize-engine/`)는 작업마다 파일을 새로 읽으므로 저장하는 즉시 운영 게이트 동작이 바뀝니다. 진행 중인 작업이 없는지 `/api/status`로 확인한 뒤 수정하세요. TypeScript 변경은 빌드와 재시작 후에만 반영됩니다.

Windows 전용 검사는 macOS에서 자동으로 건너뜁니다. 방화벽·엔진 동기화 PowerShell 스크립트 검사, 데스크톱 앱 Playwright 검사, Windows 기준으로 캡처한 시각 스냅샷이 여기에 해당합니다. 릴리스 전 전체 검증은 Windows에서 수행하세요.

## 슈퍼세종엔진 모드

서버와 Python 단계는 실행한 프로세스의 환경 변수를 그대로 물려받습니다. supervisor로 모드를 바꾸려면 재시작 명령에 값을 지정합니다.

```sh
SUPER_SEJONG_MODE=shadow node dist/ops/hermes-service.js restart
```

watchdog이 서버를 다시 띄울 때는 watchdog 자신의 환경을 사용하므로, 기본값이 아닌 모드를 유지하려면 cron 항목에도 같은 값을 넣어야 합니다. 그렇지 않으면 자동 재시작 후 `enforce`로 돌아갑니다. Python 단계는 작업마다 값을 읽지만 서버가 시작할 때 받은 환경을 전달하므로, 모드 변경은 재시작해야 반영됩니다.

| 모드 | 의미 보존 검사 | 조사 교정 | 문체 힌트 | Office 순서 비교 |
| --- | --- | --- | --- | --- |
| `enforce` | 실패하면 재시도·되돌림 | 실행 | 첫 시도에만 전달 | 슈퍼세종 문장 정렬 비교로 대체 |
| `shadow` | 기록만(`shadowFailureCounts`) | 실행 | 첫 시도에만 전달 | 기존 서법·짧은 부정 목록 비교(Office는 shadow 기록 없음) |
| `off` | 실행 안 함 | 실행 안 함 | 전달 안 함 | 기존 서법·짧은 부정 목록 비교 |

`transform_complete` 로그의 `diagnostics`에서 다음 값을 확인합니다. 모두 코드와 숫자이며 본문은 들어가지 않습니다.

- `hardFailureCounts`: 구간·전체 게이트에서 막은 실패 코드별 횟수(`polarity_changed`, `modality_changed`, `lexical_polarity_changed`, `participant_role_changed`, `josa_mismatch` 등)
- `shadowFailureCounts`: shadow 모드에서 막았을 실패 코드별 횟수
- `repairedParticles`: 복원 단계에서 고친 조사 수
- `styleFindingsBefore`·`styleFindingsAfter`: 각 구간의 원문·결과에서 찾은 문체 진단 건수. 힌트가 실제로 효과가 있는지 비교하는 용도

새 검사의 과잉 차단이 의심되면 먼저 `shadow`로 바꿔 실패 코드 분포를 모은 뒤 판단합니다. 측정 근거와 한계는 [슈퍼세종엔진 평가](research/super-sejong/EVALUATION-2026-10-04.md)에 있습니다.

## 시작 전 점검

```powershell
node --version
python --version
codex --version
codex login status
cmd.exe /c setup-portal.cmd --check
```

선언된 요구 버전은 Node.js 24.19+, Python 3.11+이며 Codex를 사용하면 CLI 0.149+가 필요합니다. 서버 preflight는 Node 최소 버전을 강제하지 않으므로 운영자가 선언된 버전을 맞춥니다. Windows `setup-portal.cmd --check`는 Codex 설치·로그인을 필수로 확인하지만 서버 런타임은 Claude만 준비돼 있어도 사용할 수 있습니다. Claude 점검에는 `claude --version`, `claude auth status`를 사용하고 로그인은 `claude auth login`으로 진행합니다. 런타임은 Claude 모델별 최소 CLI 버전을 강제하지 않습니다.

## 정상 시작 확인

1. `start-portal.cmd` 실행
2. 콘솔에 localhost와 LAN URL이 출력되는지 확인
3. `http://localhost:7882/api/health`가 `status: ready`를 반환하는지 확인
4. `runtime/jobs`의 일반 텍스트 작업 폴더와 Office 보관소·Python 작업 폴더를 구분해 확인. Office는 완료 후에도 만료 전까지 남을 수 있으며 빈 관리 폴더가 있는 것만으로 정리 실패라고 판단하지 않음

```powershell
Get-ChildItem .\runtime\jobs -Force
```

## 로그 확인

정상 로그에는 다음 메타데이터만 있어야 합니다.

- `transform_complete` 또는 `transform_failed`
- job ID
- 원문·결과 글자 수
- 청크 수
- 처리 시간
- 서법 복원 문장 수와 제거한 쉼표 수
- 교정한 조사 수, 게이트 실패 코드별 횟수, 문체 진단 건수
- 오류 코드

원문 문장이나 결과 문장이 콘솔에 나오면 운영을 중단하고 로그 경계를 점검합니다.

## 방화벽 확인과 제거

```powershell
Get-NetFirewallRule -DisplayName 'AI Text Humanize Portal (Private TCP 7882)'
Get-NetFirewallRule -DisplayName 'AI Text Humanize Portal (Private TCP 7882)' |
  Get-NetFirewallPortFilter
```

규칙은 `Profile=Private`, `Protocol=TCP`, `LocalPort=7882`이어야 합니다.

제거:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\remove-lan-firewall.ps1
```

## 비정상 종료 복구

서버는 시작할 때 오래된 `runtime/jobs` 하위 폴더를 자동 삭제합니다. 수동 확인이 필요하면 서버를 완전히 종료한 뒤 다음을 실행합니다.

```powershell
Get-Process codex,node -ErrorAction SilentlyContinue
Get-ChildItem .\runtime\jobs -Force
```

현재 프로젝트의 서버·Codex 프로세스가 없는 것을 확인한 뒤 남은 job 폴더만 정리합니다. `.gitkeep`은 남겨둡니다.

## 엔진 업데이트

`$update-humanize-engine`을 실행하면 원본 `epoko77-ai/im-not-ai`를 사용자 포크 `himangga01/im-not-ai_fork`에 먼저 동기화·push하고 서비스 및 배포물을 갱신합니다. 현재 고정 커밋은 `9747f036cdc28a1a8aea4dc71fef1f7846eb96f7`입니다. 직접 동기화 스크립트를 실행할 때는 깨끗한 포크 체크아웃을 `-Source`로 지정해야 합니다.

Humanize 엔진은 `vendor/humanize-engine`에 고정되어 있어 형제 저장소를 런타임에 참조하지 않습니다. upstream `im-not-ai`는 규칙과 스크립트가 바뀌어도 SKILL.md의 version 문자열을 `2.3.2`로 유지하므로, 실제 고정 기준은 `ENGINE_VERSION`의 commit입니다. 승인된 upstream commit으로 갱신할 때:

1. `scripts/sync-engine.ps1`의 기대 버전과 commit을 검토
2. 동기화 실행
3. 룰 인덱스 검사
4. 전체 테스트와 live 테스트 실행

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\sync-engine.ps1 -Source '<동기화한 포크 체크아웃 절대 경로>'
$env:PYTHONDONTWRITEBYTECODE='1'
python .\vendor\humanize-engine\scripts\build_quick_rules.py --check
python .\vendor\humanize-engine\scripts\build_diagnosis_rules.py --check
npm.cmd test
npm.cmd run test:live
```

portal patch가 재적용됐는지 확인합니다. 패치는 `prepare_monolith_input.py`·`reassemble_chunks.py`의 LF 쓰기, `--portal-auto-route` 경로, 청킹 모드 route_hint에 원문을 넘기는 v2.6 티 계수 연결, `restore_modality.py`·`strip_injected_commas.py`의 줄바꿈 보존을 담고 있습니다. upstream 파일이 바뀌어 패치가 맞지 않으면 pristine 사본을 스테이징한 뒤 패치를 재적용·수정하고 `git diff`로 `scripts/patches/humanize-engine-portal.patch`를 다시 생성합니다.

## LAN 인수 테스트

검증 기록에는 날짜, 서버 LAN URL, 브라우저 이름, 통과 여부만 남기고 원문·결과는 기록하지 않습니다.

| 점검 | 기대 결과 |
|---|---|
| 서버 PC localhost | 포털이 열리고 health가 ready |
| 같은 와이파이 PC 두 대 | 로그인 없이 동일 포털 열림 |
| 세 PC 동시 변환 | 1건 실행, 2건 대기 순서 표시 |
| 네 번째 변환 | 친절한 queue-full 메시지 |
| 15,000자 이하 `light`·`standard` | 본문 청크 1개와 단일 처리 경로 사용 |
| `heavy`·15,000자 초과·판정 불가 | 여러 청크 사용, 기본값에서 한 번에 1개씩 처리 |
| UTF-8/BOM UTF-16/CP949 TXT·MD | 왼쪽 입력만 채워지고 버튼 전 요청 0건 |
| MD 변환 완료 | 원본 파일명 기반 `-humanized.md` 다운로드와 내용 일치 |
| DOCX·PPTX 선택 | 구조·위치별 미리보기와 윤문/보존 구간 표시; 선택 시 업로드·파싱, 변환 버튼 전 모델 호출 없음 |
| DOCX·PPTX 변환 완료 | 입력과 같은 형식의 새 결과 다운로드; 만료 전 재다운로드 가능 |
| 미지원 DOC·PPT·PDF·HWP 등 | 기존 입력 유지와 한글 오류 표시 |
| 실행 중 취소 | 선택한 CLI의 프로세스와 관련 임시 작업 정리 |
| 브라우저 강제 종료 | 활성 작업 취소와 job 폴더 제거 |
| 서버 종료 | 7882 포트 종료와 jobs 폴더 비움 |

## 릴리스 전 명령

```powershell
npm.cmd ci
npm.cmd run typecheck
npm.cmd test
npm.cmd run build
npm.cmd run test:e2e
npm.cmd run test:live
git status --short
```

실제로 실행한 명령과 결과를 기록합니다. 일반 텍스트 임시 작업은 정리돼야 하지만 Office 결과는 만료 전까지 남을 수 있으므로 보관 정책과 구분합니다. 빌드·준비 상태 확인만으로 실제 모델 품질·계정 권한·전체 배포물의 동일성을 입증하지 않습니다.

## 선택적 성능 벤치마크와 롤백

`test:performance`는 짧은 문서의 기존·자동 라우팅과 긴 문서의 직렬·2개 병렬 처리를 각각 3회 측정합니다. 총 12회의 변환이 서버 PC에 로그인된 Codex 쿼터를 소비하므로 `/api/health`의 `activeJobs`가 `0`인지 확인한 뒤 포털 서버를 완전히 종료하고 실행합니다. 벤치마크는 원문·결과문이나 파일 경로를 출력하지 않고, 소스·결과 아티팩트를 남기지 않으며 메타데이터만 보고합니다.

### 현재 승인 상태

2026-08-24 수정 픽스처 결과는 다음과 같습니다.

| 구간 | 측정 결과 | 승인 판정 |
|---|---|---|
| 짧은 문서 3,872자 | 기존 p50 262.215초, 자동 라우팅 p50 106.083초, 비율 40.456481% | 요구값 `<= 40%` 실패 |
| 긴 문서 17,344자 | 직렬 3회차 도중 사용자가 나머지 실행 취소 | 직렬·병렬 p50과 요구값 `<= 70%` 미평가 |

짧은 문서 기준이 실패했고 긴 문서 승인이 완료되지 않았으므로 운영 기본 청크 동시성은 `1`입니다. `2`는 검증되지 않은 실험값으로만 남기며 임계값을 낮추거나 이 부분 측정을 통과로 간주하지 않습니다. 자동 라우팅은 계속 기본 활성화되어 15,000자 이하 `light`·`standard` 문서를 단일 호출로 처리하고, 그 밖의 문서는 청킹합니다. 위 측정은 당시 GPT의 `high` 설정 기록이며, 현재 기본 effort는 GPT `medium`, Claude `high`입니다. 현재 설정의 성능은 별도 측정이 필요합니다.

```powershell
$env:CODEX_CHUNK_CONCURRENCY='1'
npm.cmd run test:performance
Remove-Item Env:CODEX_CHUNK_CONCURRENCY
```

이 전체 벤치마크는 12회의 live 변환 시간과 쿼터를 다시 승인받은 경우에만 실행합니다.

환경 변수가 없을 때도 기본값은 `1`입니다. 이전 세션이나 시작 스크립트에서 `2`를 지정했을 가능성이 있으면 서버 시작 전에 다음처럼 `1`을 명시해 직렬 처리로 롤백합니다.

```powershell
$env:CODEX_CHUNK_CONCURRENCY='1'
npm.cmd start
```

격리된 유지보수 시간에 긴 문서 병렬 처리를 실험할 때만 `2`를 명시합니다. 전역 Codex 실행 상한도 2이므로 이를 초과할 수 없습니다. 오류, 취소, 품질 또는 리소스 문제가 있으면 서버를 종료하고 위의 `1`로 되돌립니다.

```powershell
$env:CODEX_CHUNK_CONCURRENCY='2'
npm.cmd start
```
