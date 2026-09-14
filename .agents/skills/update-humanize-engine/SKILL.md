---
name: update-humanize-engine
description: "원본 epoko77-ai/im-not-ai의 변경을 사용자 포크 himangga01/im-not-ai_fork에 동기화한 뒤 ai-text-makes-likes-human의 엔진·패치·스킬·Windows 앱을 갱신하고 검증한다. 업스트림 반영, 엔진 동기화, 포크 업데이트 요청에 사용한다. 일반 문장 윤문에는 사용하지 않는다."
---

# Humanize 엔진 업데이트

업데이트 또는 스킬 실행 요청에는 **원본 확인 → 사용자 포크 동기화·push → 서비스 갱신·검증 → 배포물 재빌드**가 포함된다. 포크가 오래되었다는 이유로 사용자에게 동기화를 맡기고 종료하지 않는다. 사용자가 점검만 요청하거나 쓰기를 명시적으로 제한하면 그 범위를 따른다. 스킬 생성 요청을 실제 업데이트 실행이나 정기 작업 등록으로 확대하지 않는다. 이 워크플로에서는 superpowers 스킬을 사용하지 않는다.

## 대상과 현재 상태

- 원본: `https://github.com/epoko77-ai/im-not-ai.git`.
- 배포용 사용자 포크: `https://github.com/himangga01/im-not-ai_fork.git`. 원본 변경을 이 포크에 먼저 통합하고, 서비스는 동기화된 포크 커밋을 핀으로 사용한다.
- 서비스 기본 위치: `C:/project/2026/ai-text-makes-likes-human`. 사용자가 다른 체크아웃을 지정하면 그 위치를 사용한다.
- 서비스 저장소: `himangga01/ai-text-makes-likes-human`. 업스트림은 이 저장소의 `main`에 직접 merge하는 대상이 아니다. `vendor/humanize-engine`을 통해 통합한다.
- 현재 핀과 규칙은 매번 `vendor/humanize-engine/ENGINE_VERSION`, `UPSTREAM.md`, `scripts/sync-engine.ps1`, `docs/operations.md`에서 읽는다. 버전 문자열이 같아도 커밋은 달라질 수 있다.

## 1. 원본을 사용자 포크에 동기화

원본과 포크의 기본 브랜치 및 HEAD를 원격에서 조회한다. 두 HEAD가 같으면 포크 clone·push를 생략하고 2단계로 진행한다. 다르면 고유한 격리 작업 폴더에 포크를 clone하고 `upstream` 원격으로 원본을 fetch한다. 기존 사용자 체크아웃이나 테스트용 가짜 커밋이 있는 저장소는 동기화·push에 재사용하지 않는다.

1. `git rev-list --left-right --count origin/<fork-branch>...upstream/<source-branch>`와 ancestry를 확인한다.
2. 포크 고유 커밋이 없으면 `git merge --ff-only <고정한 원본 SHA>`로 진행한다.
3. 포크 고유 변경이 있으면 정상 merge로 보존한다. 충돌은 양쪽 코드를 검토해 해결하고 관련 검증을 수행한다. force-push나 reset으로 포크 변경을 지우지 않는다.
4. 포크 원격에 일반 `git push origin HEAD:refs/heads/<fork-branch>`를 실행하고 `git ls-remote`로 반영을 확인한다. 이 포크 동기화는 업데이트 실행의 기본 범위이므로 별도 확인을 반복하지 않는다.
5. 동시 push로 거부되면 포크를 다시 fetch해 상대 변경을 통합한 뒤 재시도한다. 인증·권한 오류는 원인을 확인해 보고하되 강제 push로 우회하지 않는다.
6. 동기화된 포크 SHA를 이번 서비스 업데이트 대상으로 고정한다. 원본의 로컬 사본이나 테스트 커밋을 포크에 반영된 커밋처럼 기록하지 않는다.

이미 원본 변경이 모두 포크에 있으면 push 없이 다음 단계로 진행한다. 원본과 포크에 공통 이력이 없거나 사용자 고유 변경의 의미를 판단할 수 없는 충돌이 남으면 해당 문제를 구체적으로 보고한다.

## 2. 서비스 핀과 동기화된 포크 비교

아래 경로의 `<skill-dir>`는 현재 읽은 SKILL.md의 부모 디렉터리다.

```powershell
python "<skill-dir>/scripts/check_upstream.py" --project-root "C:/project/2026/ai-text-makes-likes-human"
```

이 도우미는 현재 핀과 원격 HEAD, 출처 불일치, 작업 폴더 변경 여부를 JSON으로 출력하며 서비스 파일이나 Git ref를 변경하지 않는다. 기본 브랜치는 원격 HEAD에서 알아낸다. 특정 브랜치 요청에는 `--ref refs/heads/<branch>`를 쓴다.

해시가 다르다는 사실만으로 새 버전이라고 판단하지 않는다. 최초 조회에서 `history_required`가 나오면 별도 체크아웃에서 두 커밋의 이력을 확보하고 `--history-repo <그 체크아웃>`으로 재검사한다. 도우미 자체는 fetch하거나 체크아웃을 변경하지 않는다. 원격이 현재 핀의 후손임이 확인된 경우에만 `update_available`을 반환한다.

- `up_to_date`: 기록된 핀과 원격이 같다. 새 작업을 만들지 말고 현재 커밋을 보고하되, `worktree_dirty`가 참이면 미커밋 변경도 알린다. 핀 일치만으로 실제 vendor 파일이 원본과 같다고 단정하지 않는다.
- `update_available`: 반환된 `latest_commit`을 이번 작업의 고정 대상으로 삼는다.
- `upstream_behind`: 오래된 포크를 서비스에 적용하지 않는다. 1단계의 원본→포크 동기화를 수행한 뒤 다시 검사한다. 동기화 후에도 서비스가 더 앞서면 현재 핀의 출처·이력을 확인하고 차이를 보고한다.
- `history_diverged`: 이력이 갈라졌다. ahead/behind 수와 코드 차이를 검토하고 단순 덮어쓰기를 금지한다.
- `history_required`: 기존 핀·대상 커밋 또는 충분한 이력이 없다. 기록된 원출처나 검증된 로컬 체크아웃에서 비교용 객체를 격리된 저장소로 가져온다. 이력 확보는 업데이트 대상 포크를 바꾸는 것이 아니다. 판단할 근거를 구하지 못하면 안전한 업데이트라고 보고하지 않는다.
- `provenance_update_required`: 코드는 같지만 출처가 다르다. 업데이트 요청이라면 동기화 스크립트와 출처 기록을 포크 기준으로 정리한다.
- 도우미 실패는 최신 상태를 뜻하지 않는다. 접속·인증·핀 형식 문제를 해결하거나 확인하지 못한 사실을 보고한다.

## 3. 변경 분석과 보존

먼저 `git status`, 현재 브랜치, 원격과의 차이를 확인한다. 기존 변경을 버리거나 일괄 덮어쓰지 않는다. 필요한 백업과 격리된 작업 디렉터리를 마련한 뒤 계속 진행하며, dirty 상태만을 이유로 사용자에게 승인을 다시 요구하지 않는다.

포크의 고정 대상 커밋을 별도 체크아웃에 가져온다. 사용자의 기존 형제 저장소를 checkout/reset하거나 업스트림 설치 스크립트를 실행하지 않는다. 기존 핀부터 대상 커밋까지 코드·규칙·의존성·라이선스를 검토한다. 기존 핀이 없거나 대상의 조상이 아니면 commit 수로 업데이트 방향을 단정하지 말고 두 트리를 비교한다.

업데이트를 구현하기 전에 [references/portal-integration.md](references/portal-integration.md)를 읽는다. 문서만 바뀌었는지, 포털이 사용하지 않는 파일만 바뀌었는지도 구분한다. 런타임이 같으면 불필요한 서비스 기능 변경 없이 핀·출처 기록만 갱신할 수 있다.

## 4. 서비스에 통합

별도 스테이징에서 기존 동기화 스크립트의 파일 목록과 포털 패치를 새 커밋에 맞춘다. **기존 sync-engine.ps1은 패치 검증 전에 vendor 파일을 덮어쓴다.** 패치 호환성을 확인하기 전에 공유 작업 폴더에서 실행하지 않는다.

패치 충돌은 양쪽 구현 의도를 읽고 해결한다. upstream이 같은 기능을 구현했다면 중복 hunk를 제거하되 포털 계약은 검증한다. 필요한 Python 의존 파일, 규칙 생성 입력, 어댑터와 테스트를 함께 갱신한다. 검사 실패를 숨기려고 검증 기준이나 테스트를 약화하지 않는다.

`sync-engine.ps1`의 소스 위치·기대 커밋·버전 검증·출처 생성문, `ENGINE_VERSION`, `UPSTREAM.md`, 핀 테스트를 일치시킨다. 현재 앱의 모델 선택, effort, 큐 동시성, 포트는 관련 변경이 필요한 경우에만 수정한다.

동기화는 `powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/sync-engine.ps1 -Source <고정한 깨끗한 포크 체크아웃 경로>`로 호출한다. `-Source`는 필수이며, 커밋되지 않은 수정이나 필수 런타임 파일 누락을 먼저 해결한다.

## 5. 검증과 마무리

실제 모델을 호출하지 않는 검증부터 수행한다. 아래 명령은 검증 대상 서비스 루트에서 실행하고 각 exit code를 확인한다.

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
$env:PYTHONUTF8='1'
$env:RUN_CODEX_LIVE='0'
python vendor/humanize-engine/scripts/build_quick_rules.py --check
python vendor/humanize-engine/scripts/build_diagnosis_rules.py --check
npm.cmd run typecheck
npm.cmd test
npm.cmd run build
npm.cmd run test:e2e
npm.cmd run test:skills
npm.cmd run desktop:build
npm.cmd run test:documents
npm.cmd run test:desktop
npm.cmd run skills:build
node scripts/verify-skill-packages.mjs
npm.cmd run desktop:portable
git diff --check
```

브라우저 테스트는 실제 모델 요청을 모의해야 한다. 활성 포털의 포트·server.lock·jobs와 충돌하면 격리된 체크아웃 및 테스트 포트를 사용한다. 테스트를 위해 운영 서버를 종료하거나 활성 jobs를 정리하지 않는다. 스냅샷 차이는 화면을 확인하고 의도된 변화만 갱신한다.

live 검증과 성능 벤치마크는 계정 쿼터를 소비한다. 현재 요청의 허용 범위와 `docs/operations.md`를 확인하며, 이미 허용된 실행은 다시 묻지 않는다. 허용되지 않은 live 실행을 생략했다면 결과에 명시한다. 특히 12회 성능 벤치마크는 문서의 명시적 승인 조건을 따른다. 기존 `high` 측정값을 다른 effort의 성능 증거로 재사용하지 않는다.

대상 핀으로 재동기화했을 때 동일한 vendor 트리가 생성되는지 스테이징에서 확인한다. 검증된 변경만 원래 서비스 작업 폴더에 반영하고, 로컬 고유 변경이 남아 있는지 diff를 다시 확인한다. 해결되지 않은 실패가 있으면 이전 서비스 상태를 보존하고 구체적 차단 원인을 보고한다.

포크 동기화·push는 1단계의 기본 실행 범위다. 서비스 저장소의 커밋·push는 현재 세션의 기존 승인 범위를 따르고 이미 승인된 작업을 다시 묻지 않는다. 운영 서버 재시작이나 공개 릴리스 업로드는 별도 배포 범위가 있을 때 수행한다. 최종 답변에는 원본·포크의 동기화 결과, 이전/새 서비스 핀, 패치 조정, 검증 결과, 새 EXE·스킬 경로와 Git 상태를 남긴다.

기존 배포물이 자체서명 방식이면 사용 가능한 기존 인증서로 `scripts/sign-selfsigned.ps1`을 실행해 새 EXE 사본도 자체서명하고 체크섬을 갱신한다. 이미 같은 버전의 서명 파일이 있으면 `-VerifyExisting`으로 검증한다. 이 명령은 기존 서명 기록의 원본·서명본 해시가 현재 파일과 모두 같아야 성공한다. 같은 버전의 원본 EXE를 다시 빌드해 해시가 달라졌다면 기존 서명본과 기록을 보존하고, 새 버전으로 빌드·서명한다. 이전 서명본에 새 원본의 해시를 연결하거나 서명 기록을 수동 수정하지 않는다. 인증서를 새 신뢰 루트로 등록하거나 사용자에게 새 인증서를 요구하는 작업으로 확대하지 않는다. 이전 버전의 EXE·서명 파일은 롤백을 위해 유지한다.

감지 도우미를 수정할 때는 `python "<skill-dir>/scripts/test_check_upstream.py"`로 임시 Git 저장소를 사용하는 오프라인 동작 검증을 실행한다.

앱·스킬 배포 시 `engine_runtime/workflow.py`의 보존 정책, `skill_gateway.py`의 상태·원문 hash 계약을 유지한다. `release/build-info.json`, 두 스킬의 `distribution.json` 및 vendor 핀이 일치하는지 확인한다. EXE는 `node scripts/smoke-portable.mjs`로 복사 경로에서 모의 CLI 검증할 수 있다. `--live`는 실제 계정 호출이므로 일반 검증과 구분한다. 자세한 빌드·설치 경로는 서비스의 `docs/desktop.md`를 읽는다.

DOCX/PPTX 지원도 함께 검증한다. 문서 전용 보존 제약은 upstream의 목록 산문화·제목 삭제보다 우선한다. `engine_runtime/documents`와 응답 JSON schema, `python-document-deps.lock.json`의 lxml 버전이 EXE·두 스킬 ZIP에 실제 포함되는지 확인한다. `verify-skill-packages.mjs`의 Office 문서 왕복 검사를 통과하고, 문서 코드·규칙 변경 시 Word/PowerPoint 렌더링과 선택 CLI 검증 결과를 남긴다. upstream 파일 동기화로 제품용 문서 어댑터를 덮어쓰지 않는다.
