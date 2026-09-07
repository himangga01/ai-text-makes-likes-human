---
name: update-humanize-engine
description: "himangga01/im-not-ai_fork의 새 커밋을 확인하고 ai-text-makes-likes-human 서비스의 vendored Humanize 엔진, 포털 패치, 어댑터와 테스트를 갱신한다. 업스트림 반영, Humanize 엔진 동기화, 포크 업데이트 요청에 사용한다. 일반 문장 윤문에는 사용하지 않는다."
---

# Humanize 엔진 업데이트

호출 시 업스트림 변경을 조사하고 서비스에 필요한 갱신을 구현·검증한다. 사용자가 점검만 요청하면 변경 내역까지 보고한다. 스킬을 만들어 달라는 요청은 엔진 업데이트 실행이나 정기 작업 등록으로 확대하지 않는다. 이 워크플로에서는 superpowers 스킬을 사용하지 않는다.

## 대상과 현재 상태

- 업스트림: `https://github.com/himangga01/im-not-ai_fork.git`. 사용자가 지정한 포크를 기준으로 하며 원본 `epoko77-ai/im-not-ai`로 대체하지 않는다.
- 서비스 기본 위치: `C:/project/2026/ai-text-makes-likes-human`. 사용자가 다른 체크아웃을 지정하면 그 위치를 사용한다.
- 서비스 저장소: `himangga01/ai-text-makes-likes-human`. 업스트림은 이 저장소의 `main`에 직접 merge하는 대상이 아니다. `vendor/humanize-engine`을 통해 통합한다.
- 현재 핀과 규칙은 매번 `vendor/humanize-engine/ENGINE_VERSION`, `UPSTREAM.md`, `scripts/sync-engine.ps1`, `docs/operations.md`에서 읽는다. 버전 문자열이 같아도 커밋은 달라질 수 있다.

## 1. 새 커밋 확인

아래 경로의 `<skill-dir>`는 현재 읽은 SKILL.md의 부모 디렉터리다.

```powershell
python "<skill-dir>/scripts/check_upstream.py" --project-root "C:/project/2026/ai-text-makes-likes-human"
```

이 도우미는 현재 핀과 원격 HEAD, 출처 불일치, 작업 폴더 변경 여부를 JSON으로 출력하며 서비스 파일이나 Git ref를 변경하지 않는다. 기본 브랜치는 원격 HEAD에서 알아낸다. 특정 브랜치 요청에는 `--ref refs/heads/<branch>`를 쓴다.

- `up_to_date`: 기록된 핀과 원격이 같다. 새 작업을 만들지 말고 현재 커밋을 보고하되, `worktree_dirty`가 참이면 미커밋 변경도 알린다. 핀 일치만으로 실제 vendor 파일이 원본과 같다고 단정하지 않는다.
- `update_available`: 반환된 `latest_commit`을 이번 작업의 고정 대상으로 삼는다.
- `provenance_update_required`: 코드는 같지만 출처가 다르다. 업데이트 요청이라면 동기화 스크립트와 출처 기록을 포크 기준으로 정리한다.
- 도우미 실패는 최신 상태를 뜻하지 않는다. 접속·인증·핀 형식 문제를 해결하거나 확인하지 못한 사실을 보고한다.

## 2. 변경 분석과 보존

먼저 `git status`, 현재 브랜치, 원격과의 차이를 확인한다. 기존 변경을 버리거나 일괄 덮어쓰지 않는다. 필요한 백업과 격리된 작업 디렉터리를 마련한 뒤 계속 진행하며, dirty 상태만을 이유로 사용자에게 승인을 다시 요구하지 않는다.

포크의 고정 대상 커밋을 별도 체크아웃에 가져온다. 사용자의 기존 형제 저장소를 checkout/reset하거나 업스트림 설치 스크립트를 실행하지 않는다. 기존 핀부터 대상 커밋까지 코드·규칙·의존성·라이선스를 검토한다. 기존 핀이 없거나 대상의 조상이 아니면 commit 수로 업데이트 방향을 단정하지 말고 두 트리를 비교한다.

업데이트를 구현하기 전에 [references/portal-integration.md](references/portal-integration.md)를 읽는다. 문서만 바뀌었는지, 포털이 사용하지 않는 파일만 바뀌었는지도 구분한다. 런타임이 같으면 불필요한 서비스 기능 변경 없이 핀·출처 기록만 갱신할 수 있다.

## 3. 서비스에 통합

별도 스테이징에서 기존 동기화 스크립트의 파일 목록과 포털 패치를 새 커밋에 맞춘다. **기존 sync-engine.ps1은 패치 검증 전에 vendor 파일을 덮어쓴다.** 패치 호환성을 확인하기 전에 공유 작업 폴더에서 실행하지 않는다.

패치 충돌은 양쪽 구현 의도를 읽고 해결한다. upstream이 같은 기능을 구현했다면 중복 hunk를 제거하되 포털 계약은 검증한다. 필요한 Python 의존 파일, 규칙 생성 입력, 어댑터와 테스트를 함께 갱신한다. 검사 실패를 숨기려고 검증 기준이나 테스트를 약화하지 않는다.

`sync-engine.ps1`의 소스 위치·기대 커밋·버전 검증·출처 생성문, `ENGINE_VERSION`, `UPSTREAM.md`, 핀 테스트를 일치시킨다. 현재 앱의 모델 선택, effort, 큐 동시성, 포트는 관련 변경이 필요한 경우에만 수정한다.

## 4. 검증과 마무리

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
npm.cmd run test:desktop
npm.cmd run skills:build
node scripts/verify-skill-packages.mjs
npm.cmd run desktop:portable
git diff --check
```

브라우저 테스트는 실제 모델 요청을 모의해야 한다. 활성 포털의 포트·server.lock·jobs와 충돌하면 격리된 체크아웃 및 테스트 포트를 사용한다. 테스트를 위해 운영 서버를 종료하거나 활성 jobs를 정리하지 않는다. 스냅샷 차이는 화면을 확인하고 의도된 변화만 갱신한다.

live 검증과 성능 벤치마크는 계정 쿼터를 소비한다. 현재 요청의 허용 범위와 `docs/operations.md`를 확인하며, 이미 허용된 실행은 다시 묻지 않는다. 허용되지 않은 live 실행을 생략했다면 결과에 명시한다. 특히 12회 성능 벤치마크는 문서의 명시적 승인 조건을 따른다. 기존 `high` 측정값을 다른 effort의 성능 증거로 재사용하지 않는다.

대상 핀으로 재동기화했을 때 동일한 vendor 트리가 생성되는지 스테이징에서 확인한다. 검증된 변경만 원래 서비스 작업 폴더에 반영하고, 로컬 고유 변경이 남아 있는지 diff를 다시 확인한다. 해결되지 않은 실패가 있으면 이전 서비스 상태를 보존하고 구체적 차단 원인을 보고한다.

현재 요청에서 커밋·push·배포가 허용되어 있으면 해당 범위까지 수행한다. 엔진 갱신 요청만으로 운영 서버 재시작이나 원격 push까지 허용됐다고 간주하지 않는다. 최종 답변에는 이전/새 커밋, 반영 내역, 패치 조정, 검증 결과와 생략한 live 검증, Git 및 배포 상태를 간단히 남긴다.

감지 도우미를 수정할 때는 `python "<skill-dir>/scripts/test_check_upstream.py"`로 임시 Git 저장소를 사용하는 오프라인 동작 검증을 실행한다.

앱·스킬 배포 시 `engine_runtime/workflow.py`의 보존 정책, `skill_gateway.py`의 상태·원문 hash 계약을 유지한다. `release/build-info.json`, 두 스킬의 `distribution.json` 및 vendor 핀이 일치하는지 확인한다. EXE는 `node scripts/smoke-portable.mjs`로 복사 경로에서 모의 CLI 검증할 수 있다. `--live`는 실제 계정 호출이므로 일반 검증과 구분한다. 자세한 빌드·설치 경로는 서비스의 `docs/desktop.md`를 읽는다.
