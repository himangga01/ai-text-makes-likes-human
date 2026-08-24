# 포털 운영 점검표

## 운영 원칙

- 서비스 주소: `http://localhost:3210`, LAN은 서버 콘솔에 표시된 주소
- 서버 바인딩: `0.0.0.0:3210`
- 방화벽 범위: Windows Private 프로필, TCP 3210
- 동시 접수: 3건
- 동시 Codex 실행: 1건
- 변환 모델: `gpt-5.6-sol`, reasoning effort `high` 고정
- 본문 저장: 없음
- 허용 로그: job ID, 글자 수, 청크 수, 처리 시간, 결과 코드

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
3. `http://localhost:3210/api/health`가 `status: ready`를 반환하는지 확인
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
- 오류 코드

원문 문장이나 결과 문장이 콘솔에 나오면 운영을 중단하고 로그 경계를 점검합니다.

## 방화벽 확인과 제거

```powershell
Get-NetFirewallRule -DisplayName 'AI Text Humanize Portal (Private TCP 3210)'
Get-NetFirewallRule -DisplayName 'AI Text Humanize Portal (Private TCP 3210)' |
  Get-NetFirewallPortFilter
```

규칙은 `Profile=Private`, `Protocol=TCP`, `LocalPort=3210`이어야 합니다.

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

Humanize 엔진은 `vendor/humanize-engine`에 고정되어 있어 형제 저장소를 런타임에 참조하지 않습니다. 승인된 upstream commit으로 갱신할 때:

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

Windows 줄바꿈 보존용 portal patch가 `prepare_monolith_input.py`와 `reassemble_chunks.py`에 재적용됐는지 확인합니다.

## LAN 인수 테스트

검증 기록에는 날짜, 서버 LAN URL, 브라우저 이름, 통과 여부만 남기고 원문·결과는 기록하지 않습니다.

| 점검 | 기대 결과 |
|---|---|
| 서버 PC localhost | 포털이 열리고 health가 ready |
| 같은 와이파이 PC 두 대 | 로그인 없이 동일 포털 열림 |
| 세 PC 동시 변환 | 1건 실행, 2건 대기 순서 표시 |
| 네 번째 변환 | 친절한 queue-full 메시지 |
| 15,000자 초과 | 여러 청크가 순서대로 처리됨 |
| UTF-8/BOM UTF-16/CP949 TXT·MD | 왼쪽 입력만 채워지고 버튼 전 요청 0건 |
| MD 변환 완료 | 원본 파일명 기반 `-humanized.md` 다운로드와 내용 일치 |
| TXT·MD 아닌 파일 | 기존 입력 유지와 한글 오류 표시 |
| 실행 중 취소 | Codex 프로세스와 job 폴더 제거 |
| 브라우저 강제 종료 | 활성 작업 취소와 job 폴더 제거 |
| 서버 종료 | 3210 포트 종료와 jobs 폴더 비움 |

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
