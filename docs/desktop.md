# Windows 앱과 Claude·Codex 윤문 스킬

## Windows 앱 실행

`HumanizeKR-0.3.3-win-x64-self-signed.exe` 한 개를 원하는 폴더에 두고 실행합니다. 설치 마법사나 관리자 권한이 필요하지 않습니다. 내부 리소스는 실행할 때 TEMP에 추출됩니다.

1. 사용할 **Claude Code 또는 Codex의 네이티브 CLI**를 PC에 설치하고 로그인해 둡니다.
2. EXE를 실행합니다. 두 CLI를 각각 점검하므로 한쪽만 준비되어 있어도 사용할 수 있습니다.
3. `Claude · Codex 연결 설정`에서 상태를 확인합니다. 자동으로 찾지 못하면 해당 CLI의 **EXE 경로 선택**을 사용합니다.
4. 원문을 붙여넣거나 TXT·MD·DOCX·PPTX를 불러온 다음, 원하는 엔진·모델·추론 수준을 선택하고 **문장 변환하기**를 누릅니다.
5. 완료 후 경고를 확인하고 **복사** 또는 **결과 저장**을 사용합니다.

로그인 명령은 `codex login`, `claude auth login`입니다. 앱은 기존 CLI 로그인 환경을 이용하며 API 키를 직접 입력받거나 사용자의 CLI를 자동으로 설치·갱신하지 않습니다. 다른 CLI로 자동 전환하지 않으므로 사용할 엔진은 화면에서 선택합니다. `.cmd`·`.ps1` 래퍼 대신 네이티브 `.exe`를 선택하세요.

앱 자체에 Electron과 Python 3.14.7이 포함됩니다. 같은 와이파이, LAN 포털, 사용자 Node.js·Python은 앱 실행의 전제조건이 아닙니다. AI 변환에는 인터넷과 선택한 CLI 계정의 이용 가능 상태가 필요합니다. CLI가 없거나 로그인이 만료돼도 앱과 설정 화면은 열립니다.

## 파일과 작업 정리

- 읽기: TXT·MD는 UTF-8/BOM, UTF-16 BOM, CP949 계열. DOCX·PPTX는 원본 Office 구조를 검증해 읽습니다.
- 쓰기: UTF-8 TXT·MD 또는 원본과 같은 DOCX·PPTX. Windows 저장 대화상자로 위치를 선택합니다.
- 원문·결과 이력은 앱에 저장하지 않습니다. CLI 경로와 엔진·모델·추론 수준 선택을 사용자 앱 데이터의 `settings.json`에 기록합니다.
- 앱 작업은 사용자 앱 데이터의 `jobs` 아래 UUID 디렉터리에서 실행합니다. 완료·실패·취소·정상 종료 때 정리하고 재실행 시 자신의 오래된 작업만 정리합니다.
- 실행 파일이 있는 폴더와 ASAR 리소스에는 작업 파일을 쓰지 않습니다. 기존 LAN 포털과 스킬의 작업 폴더는 별개입니다.
- 검증은 수치·인용 등 보존 문제를 탐지하고 필요하면 원문을 복원합니다. 중요한 문서는 결과와 경고를 검토하세요.

## 스킬 설치

`release/`에 생성되는 호스트별 ZIP과 설치 도우미를 같은 폴더에 두고 실행합니다. 사용자 범위가 기본입니다.

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\install-humanize-skill.ps1 -HostName Claude
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\install-humanize-skill.ps1 -HostName Codex
```

프로젝트 범위로 설치할 때는 `-Scope Project -ProjectRoot <프로젝트 경로>`를 추가합니다. Claude는 `.claude/skills/humanize-kr`, Codex는 `.agents/skills/humanize-kr` 아래에 설치됩니다. 같은 ZIP을 재실행하면 기존 설치를 유지합니다. 다른 버전이나 같은 이름의 스킬이 있으면 기본적으로 보존하며, `-Replace`를 지정하면 호스트 설정 폴더의 `skill-backups`에 복사한 후 갱신합니다.

Claude에서 `/humanize-kr 이 문서를 다듬어 줘`, Codex에서 `$humanize-kr 이 문서를 다듬어 줘`로 요청합니다. 목록에 바로 나타나지 않으면 새 세션에서 확인하세요. 현재 세션이 윤문하고 포함된 Python Gateway가 검증하므로 Electron이나 포털을 띄우지 않습니다. 스킬 ZIP에는 Windows용 Python도 포함되어 있습니다.

스킬의 임시 작업은 사용자 TEMP의 `humanize-kr-skills` 아래에 생성됩니다. 검증된 결과 파일을 먼저 제공한 후 해당 job을 cleanup합니다. 사용자 원본은 덮어쓰지 않습니다. 호스트의 대화 기록은 Claude/Codex 설정에 따릅니다.

`update-humanize-engine`은 upstream 갱신을 위한 개발용 관리 스킬이고 `humanize-kr`는 실제 문장 윤문용 스킬입니다.

## 개발·빌드

빌드 PC에서는 Node.js 24.19+, npm, Windows용 개발 환경을 사용합니다. `prepare-python.mjs`는 `python-runtime.json`의 URL·SHA-256으로 Python을 검증해 포함합니다. Electron 다운로드도 고정된 패키지 버전과 체크섬을 사용합니다. 아이콘 렌더링과 자동 검증에는 Playwright Chromium이 필요합니다.

```powershell
npm.cmd ci
npx.cmd playwright install chromium
npm.cmd run typecheck
npm.cmd test
npm.cmd run test:skills
npm.cmd run desktop:build
npm.cmd run test:desktop
npm.cmd run skills:build
node scripts/verify-skill-packages.mjs
npm.cmd run desktop:portable
```

개발 실행은 `npm.cmd run desktop:dev`입니다. 서버와 Electron 빌드 출력은 `dist/`, `desktop-dist/`로 나눕니다. 설치되지 않은 Python을 가정하는 배포물 검증은 다음과 같습니다.

```powershell
$env:DESKTOP_PACKAGED='1'
npm.cmd run test:desktop
Remove-Item Env:DESKTOP_PACKAGED
node scripts/smoke-portable.mjs
```

`smoke-portable.mjs`는 EXE를 한글·공백 경로로 복사하고 개발용 Node.js·Python이 없는 PATH에서 모의 네이티브 CLI로 변환을 확인합니다. `--live`를 추가하면 실제 사용자 CLI 계정을 사용하며, Claude 확인에는 `--claude`를 추가합니다. 모의 테스트와 실제 계정 테스트의 결과를 구분해 기록합니다.

일반 테스트는 실제 LLM을 호출하지 않습니다. 기존 `test:live`와 `test:performance`는 별도 명령이며, 특히 12회 성능 벤치마크는 [운영 문서](operations.md)의 실행 조건을 따릅니다.

## 배포 결과와 제한

EXE, 스킬 ZIP, SHA-256 및 `build-info.json`은 `release/`에 생성됩니다. `build-info.json`은 앱·Electron·Python 버전, engine commit, EXE hash를 기록합니다. 빌드와 검증은 원격 업로드나 기존 운영 서버 재시작을 수행하지 않습니다.

초기 타깃은 Windows x64입니다. 실제 검증한 OS와 CLI는 릴리스 검증 기록에 남깁니다. 기본 EXE와 별도로 `HumanizeKR-0.2.1-win-x64-self-signed.exe` 자체서명본도 제공합니다. 자체서명은 공개적으로 신뢰되는 인증서가 아니므로 Windows 경고가 남을 수 있습니다. 업데이트는 기존 앱을 닫고 새 EXE를 실행하는 방식입니다.

`update-humanize-engine`은 원본 저장소를 사용자 포크에 먼저 동기화·push한 뒤 서비스와 EXE·스킬을 갱신합니다. 포크가 오래됐다는 이유로 작업을 종료하지 않습니다. 현재 엔진 핀은 `9747f036cdc28a1a8aea4dc71fef1f7846eb96f7`이며 [0.2.1 갱신 기록](releases/0.2.1.md)에 검증 결과가 있습니다.
