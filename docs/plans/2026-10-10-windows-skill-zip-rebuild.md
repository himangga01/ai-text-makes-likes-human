# Windows 스킬 ZIP 재빌드 계획

작성일: 2026-10-10 · 기준: main `63d2e4b` · 작업 위치: Windows PC

스킬 ZIP 빌드(`npm run skills:build`)와 패키지 검증(`scripts/verify-skill-packages.mjs`)은 Windows 전용이다. 빌드 중에 내장 Windows `python.exe`·`node.exe`를 직접 실행하고, 검증은 PowerShell 설치 도우미로 ZIP을 실제로 설치해 본다. 그래서 Mac에서는 만들 수 없고, 이 계획대로 Windows PC에서 진행한다.

## 1. 왜 다시 만드는가

마지막으로 배포한 ZIP은 0.4.0(2026-09-10, [릴리스 노트](../releases/0.4.0.md))이다. 0.4.0 릴리스 노트 커밋 `b28dae7` 뒤로 스킬 ZIP에 들어가는 코드(`skills/`, `engine_runtime/`, `vendor/humanize-engine/`, 스킬 브리지가 묶는 `src/engine/`)에 커밋 70개가 쌓였다. 주요 변경은 다음과 같다.

| 변경 | 커밋(대표) | 스킬에 미치는 영향 |
|---|---|---|
| 슈퍼세종엔진 v2 | 2026-10-05 머지 | `engine_runtime/sejong/**`가 ZIP에 함께 들어간다(기본은 기존 엔진). |
| 다섯 번째 강도 '매우 강하게(다시쓰기)'(`rewrite`) | 2026-10-09 머지 | 직접 입력 강도 5단계. |
| 보존 검사 오탐 수정 | `002505b` | 기존 엔진·v2 모두 정상 수정을 원문으로 되돌리던 경우가 줄었다. |
| TXT·MD 파일 강도 | `6379973` | `--input-kind text-file --strength <강도>`가 받아들여진다. 0.4.0 ZIP은 이 요청을 거절한다. |

지금 설치된 0.4.0 스킬은 위 기능이 없거나 동작이 다르다.

## 2. 시작 전 확인

1. 저장소를 최신 main으로 받는다(`git pull`). `git log -1`이 이 계획서 커밋 이후인지 확인한다.
2. `git status`가 깨끗해야 한다. 빌드는 작업 트리의 `skills/humanize-kr/SKILL.md`·`references/`를 그대로 ZIP에 넣는다. Mac에만 있는 개인 설정 줄(Hermes 모델 정책)이 ZIP에 섞이면 안 된다. 그 줄은 Mac 작업 트리에만 있고 커밋하지 않았으므로 Windows 체크아웃에는 없다.
3. Node.js 24.19 이상과 PowerShell을 준비하고 `npm.cmd ci`를 실행한다.

## 3. 코드 수정: 패키지 검증 보강

`scripts/verify-skill-packages.mjs`가 새 기능을 검사하지 않는다. ZIP을 만들기 전에 아래를 고친다.

1. **마지막 출력 문구.** 실제로는 다섯 강도를 검사하는데 출력은 "four direct strengths"다. `five`로 고친다.
2. **TXT·MD 강도 검사 추가.** 설치한 패키지의 Gateway로 다음을 확인한다. 기대값은 `tests/skills/test_direct_gateway.py`의 `test_text_file_above_normal_takes_the_direct_text_route`와 같다.
   - `.md` 파일을 `--input-kind text-file --strength strong`으로 prepare하면 `rewriteOptions`가 `{inputKind: "text-file", strength: "strong"}`이다. `instructionsPath`에 `요청 강도: strong`이 들어 있고 `sentencesPath` 파일이 있다.
   - 같은 파일을 `--strength rewrite`로 prepare하면 지시문이 `요청 강도: very-strong`이다(기존 엔진).
   - 강도 없이 prepare하면 `strength: "normal"`이고 `instructionsPath`가 없다(파일 경로 유지).
   - 원문을 그대로 돌려줘 finalize하면 결과가 원문과 같다. 각 작업은 cleanup으로 지운다.
3. **Office 강도 거절 검사 추가.** `tests/fixtures/documents/mixed.docx`를 `--input-kind text-file --strength strong`으로 prepare하면 실패하고, 메시지에 `Strength is available for direct text and TXT/MD files only`가 들어 있어야 한다. `--input-kind` 없이 `--strength`만 주면 그보다 먼저 `Strength requires explicit input kind`로 실패한다.

## 4. 테스트

```powershell
npm.cmd run typecheck
npm.cmd test
npm.cmd run test:skills
```

Mac 기준선은 vitest 764 통과 / 9 건너뜀이고, Python 스킬 테스트는 기존 엔진·v2 모두 통과다. Windows 결과가 다르면 빌드 전에 원인을 먼저 본다.

## 5. 빌드와 검증

```powershell
npm.cmd run skills:build
node scripts/verify-skill-packages.mjs
```

- `release/`에 `humanize-kr-claude-<버전>-win-x64.zip`, `humanize-kr-codex-<버전>-win-x64.zip`, 각각의 `.sha256`, `install-humanize-skill.ps1`이 생긴다.
- 검증은 두 호스트 모두 다음을 통과해야 한다: 두 번 설치(두 번째는 "Already installed"), 내장 Python에서 v2 엔진 import, TXT·DOCX·PPTX, 직접 입력 5단계, 3절에서 더한 TXT·MD 강도와 Office 강도 거절, HTML 비교, cleanup.
- ZIP과 EXE는 빌드 산출물이라 Git에 넣지 않는다(`release/`는 무시 목록에 있다).

## 6. 설치와 실제 사용 확인

```powershell
powershell -ExecutionPolicy Bypass -File release\install-humanize-skill.ps1 -HostName Claude
powershell -ExecutionPolicy Bypass -File release\install-humanize-skill.ps1 -HostName Codex
```

- 기본은 사용자 범위(`-Scope User`)다. 설치 도우미는 ZIP의 SHA-256을 기록해 두므로, 버전 이름이 같아도 내용이 바뀌면 다시 설치한다. 기존 스킬은 `skill-backups`에 보존된다.
- 실제 확인: Claude Code에서 `/humanize-kr`로 짧은 MD 파일을 "강하게" 다듬기를, Codex에서 `$humanize-kr`로 같은 요청을 한 번씩 해 본다. 결과 파일이 새 이름으로 저장되는지, 원본이 그대로인지 본다.

## 7. 마무리

1. 3절의 검증 스크립트 수정을 커밋한다. ZIP의 SHA-256 두 개, 테스트 수, 검증 결과를 `works-log.md`에 적는다.
2. main 반영과 푸시는 평소처럼 요청할 때 한다.

## 8. 결정이 필요한 것

- **버전 번호.** 지금 `package.json`은 0.4.0이라서 새 ZIP의 파일 이름이 9월 배포본과 같다. README도 "버전명만으로 같은 코드라고 판단하지 않는다"고 경고한다. **권장:** 0.5.0으로 올리고 `docs/releases/0.5.0.md`를 쓴다. 다만 버전을 바꾸면 데스크톱 EXE 이름도 바뀌므로 함께 결정한다.
- **데스크톱 앱 EXE.** Windows 앱(`release/HumanizeKR-*-win-x64-self-signed.exe`)도 0.4.0 이후 서버 변경이 반영되지 않았다. "서버 로직을 바꾸면 모든 사용 경로를 함께 갱신한다"는 원칙에 따르면 같이 다시 만드는 것이 맞다. 같은 PC에서 이어서 하려면 [docs/desktop.md](../desktop.md)의 순서를 따른다(`desktop:build` → `test:desktop` → `desktop:portable` → `smoke-portable.mjs`).

## 9. 이 계획 밖에 남은 것

- **Hermes `portal-service` 스킬**(Mac, `~/.hermes/skills/portal-service/SKILL.md`). 아직 강도를 4개로 적고 있다. 5단계(`rewrite` 포함)와 TXT·MD 강도를 반영하도록 사용자가 직접 고친다.
- **MCP 서버.** ZIP에 들어가지 않는다. 포털을 부르는 별도 경로라서 포털 PC에서 `dist/mcp/server.js`로 쓴다. Windows PC에서도 쓰려면 저장소를 빌드한 뒤 `HUMANIZE_PORTAL_URL`로 포털 주소를 넘긴다([MCP Server Guide](../mcp.md)).
- **플러그인.** 이 저장소에는 아직 없다.
