# 포털 운영 점검표

## 운영 원칙

- 서비스 주소: `http://localhost:7882`, LAN은 서버 콘솔에 표시된 주소
- 서버 바인딩: `0.0.0.0:7882`
- 방화벽 범위: Windows Private 프로필, TCP 7882
- 동시 접수: 3건
- 실행 중인 변환 작업: 1건
- 자동 라우팅: 기본 활성화. 15,000자 이하의 `light`·`standard` 문서는 단일 호출, `heavy`·15,000자 초과·안전하게 판정할 수 없는 문서는 청킹
- 청크 동시 Codex 실행: 기본 1개. `CODEX_CHUNK_CONCURRENCY=2`를 명시한 실험에서만 최대 2개
- 변환 모델: GPT는 `gpt-5.6-sol`, reasoning effort `medium`; Claude는 `claude-opus-5`, effort `medium`
- 본문 저장: 없음
- 허용 로그: job ID, 글자 수, 청크 수, 처리 시간, 결과 코드, 서법 복원·쉼표 제거 건수
- 게이트 직전 후처리: `restore_modality.py`와 `strip_injected_commas.py`를 청크마다 실행. `--all` 격상은 진단 단계가 없으므로 사용하지 않음
- 줄바꿈: 수신 단계에서 CR·CRLF를 LF로 통일

## 시작 전 점검

```powershell
node --version
python --version
codex --version
codex login status
cmd.exe /c setup-portal.cmd --check
```

요구 버전은 Node.js 24.19+, Python 3.11+, Codex CLI 0.149+입니다. 로그인 상태가 아니면 `codex login` 후 다시 확인합니다.

## 정상 시작 확인

1. `start-portal.cmd` 실행
2. 콘솔에 localhost와 LAN URL이 출력되는지 확인
3. `http://localhost:7882/api/health`가 `status: ready`를 반환하는지 확인
4. `runtime/jobs`에 `.gitkeep` 외 파일이 없는지 확인

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

Humanize 엔진은 `vendor/humanize-engine`에 고정되어 있어 형제 저장소를 런타임에 참조하지 않습니다. upstream `im-not-ai`는 규칙과 스크립트가 바뀌어도 SKILL.md의 version 문자열을 `2.3.2`로 유지하므로, 실제 고정 기준은 `ENGINE_VERSION`의 commit입니다. 승인된 upstream commit으로 갱신할 때:

1. `scripts/sync-engine.ps1`의 기대 버전과 commit을 검토
2. 동기화 실행
3. 룰 인덱스 검사
4. 전체 테스트와 live 테스트 실행

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\sync-engine.ps1
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
| TXT·MD 아닌 파일 | 기존 입력 유지와 한글 오류 표시 |
| 실행 중 취소 | Codex 프로세스와 job 폴더 제거 |
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

모든 명령이 성공하고 `runtime/jobs`에 `.gitkeep`만 있을 때 운영 준비가 완료됩니다.

## 선택적 성능 벤치마크와 롤백

`test:performance`는 짧은 문서의 기존·자동 라우팅과 긴 문서의 직렬·2개 병렬 처리를 각각 3회 측정합니다. 총 12회의 변환이 서버 PC에 로그인된 Codex 쿼터를 소비하므로 `/api/health`의 `activeJobs`가 `0`인지 확인한 뒤 포털 서버를 완전히 종료하고 실행합니다. 벤치마크는 원문·결과문이나 파일 경로를 출력하지 않고, 소스·결과 아티팩트를 남기지 않으며 메타데이터만 보고합니다.

### 현재 승인 상태

2026-08-24 수정 픽스처 결과는 다음과 같습니다.

| 구간 | 측정 결과 | 승인 판정 |
|---|---|---|
| 짧은 문서 3,872자 | 기존 p50 262.215초, 자동 라우팅 p50 106.083초, 비율 40.456481% | 요구값 `<= 40%` 실패 |
| 긴 문서 17,344자 | 직렬 3회차 도중 사용자가 나머지 실행 취소 | 직렬·병렬 p50과 요구값 `<= 70%` 미평가 |

짧은 문서 기준이 실패했고 긴 문서 승인이 완료되지 않았으므로 운영 기본 청크 동시성은 `1`입니다. `2`는 검증되지 않은 실험값으로만 남기며 임계값을 낮추거나 이 부분 측정을 통과로 간주하지 않습니다. 자동 라우팅은 계속 기본 활성화되어 15,000자 이하 `light`·`standard` 문서를 단일 호출로 처리하고, 그 밖의 문서는 청킹합니다. 위 측정은 당시 GPT의 `high` 설정 기록이며, 현재 GPT·Claude의 effort는 모두 `medium`입니다. 현재 설정의 성능은 별도 측정이 필요합니다.

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
