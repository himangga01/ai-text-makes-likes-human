# 업스트림 업데이트 스킬 검증 결과

검증일: 2026-09-08. 기준 서비스: `896dcee`.

이 문서는 포크 동기화 전의 진단·모의 검증 기록이다. 이후 사용자 요청에 따라 원본→포크 동기화를 스킬 기본 흐름에 포함했고, 실제 포크·서비스 갱신을 완료했다. 최신 결과는 [0.2.1 갱신 기록](../releases/0.2.1.md)을 참고한다.

## 결과

감지 도우미의 오판 1건을 발견해 수정했다. 수정 후 감지 회귀 테스트 12개, 격리된 모의 업데이트 사본의 서비스 테스트 213개, EXE 및 스킬 ZIP 빌드·설치·실행 검증이 통과했다.

현재 지정 포크는 서비스보다 오래되어 실제 서비스 업데이트 대상으로 적용하지 않았다.

| 대상 | 커밋 |
|---|---|
| 서비스 엔진 핀 | `31a66d165a9cc6c26c4c1246553f95d0468d27fb` |
| 지정 포크 `himangga01/im-not-ai_fork`의 main | `c4d03d4859acda143f0b04b4bbdb56c5e6a94db1` |
| 관계 | 포크 HEAD가 서비스 핀의 조상이며 **60커밋 뒤처짐** |

포크의 전체 clone에는 서비스 핀 객체가 없었다. 읽기 전용으로 확인한 기존 `C:/project/2026/im-not-ai`에 해당 객체가 있어, 비교용 객체만 격리된 저장소로 fetch했다. 사용자의 기존 upstream 체크아웃은 변경하지 않았다.

## 발견한 문제와 수정

기존 `check_upstream.py`는 두 해시가 다르면 `update_available: true`로 반환했다. 그래서 버전 문자열이 같은 오래된 포크도 새 업데이트처럼 보고했다. 실제 포크에는 서비스가 사용하는 `restore_modality.py`, `strip_injected_commas.py`도 없었다.

다음 판정을 추가했다.

| 결과 | 의미와 처리 |
|---|---|
| `update_available` | 현재 핀의 후손임이 확인됨. 변경 분석·스테이징으로 진행 |
| `upstream_behind` | 대상이 현재 핀의 조상. 업데이트로 적용하지 않음 |
| `history_diverged` | 완전한 이력에서 분기가 확인됨. 양쪽 코드 검토 필요 |
| `history_required` | 이력 저장소가 없거나 커밋 누락·shallow 경계로 판단 불가. 업데이트라고 단정하지 않음 |
| `up_to_date` | 기록된 핀과 대상이 같음. 작업 폴더 변경 여부는 별도로 보고 |

`--history-repo`를 추가해 두 커밋을 가진 Git 저장소를 읽기 전용으로 검사한다. 도우미는 원격 HEAD 조회 외에 fetch·checkout·소스 수정을 하지 않는다. 스킬 지침과 개인 설치본에도 같은 변경을 반영했다.

## 검증한 시나리오

- 감지 테스트 12개: 동일 커밋, 버전 문자열이 같은 새 커밋, 출처 변경, 미커밋 파일 보존, 명시적/없는 브랜치, 잘못된 핀·프로젝트·ref, 이력 없음, 과거 브랜치, 기준 커밋 누락, shallow 이력, 분기 이력.
- 현재 포크를 기존 동기화 스크립트에 전달하면 핀 검사에서 거부되며 스테이징 vendor가 바뀌지 않음.
- 현재 핀 `31a66d1`로 동기화한 뒤 다시 실행해 vendor 파일이 바이트 단위로 동일함.
- **검증용 후속 커밋** `503fabae549ea33813639b1230a0da098f973d93`을 별도 저장소에 생성. 규칙 footer와 생성된 quick-rules를 변경하고, reassembly 파일에 호환되는 `errors="strict"` 인자를 추가해 기존 패치와 충돌시킴.
- 충돌을 감지한 뒤 새 upstream의 `errors="strict"`와 포털의 `newline=""`를 함께 보존하고, pristine 대비 패치를 재생성함.
- 갱신된 동기화 스크립트의 반복 실행, 새 규칙 전달, 핀·출처 메타데이터 일치가 확인됨.
- 실제 후속 커밋은 `update_available`, 갱신된 사본은 `up_to_date`, 실제 지정 포크는 `upstream_behind`로 구분됨.

검증용 커밋과 그 EXE/ZIP은 실제 포크의 새 버전이나 릴리스가 아니다. 실제 포크에 push하거나 서비스에 적용하지 않았다.

## 격리 사본의 실행 결과

| 검사 | 결과 |
|---|---|
| 규칙 인덱스 2종 | 통과 |
| 서버·Electron TypeScript 검사와 서버 빌드 | 통과 |
| 단위·통합 테스트 | 186개 통과, live 전용 3개 제외 |
| 웹·시각·접근성 회귀 | 17개 통과 |
| 스킬 Gateway | 3개 통과 |
| 패키징된 Electron 앱 | 7개 통과 |
| Claude·Codex 스킬 ZIP | 두 번 설치, 내장 Python Unicode roundtrip, cleanup 통과 |
| portable EXE | 빌드 및 복사 경로 실행 통과, Node/Python 없는 PATH와 모의 네이티브 CLI 사용 |
| 배포물 일관성 | EXE build-info와 두 ZIP의 engine commit 및 새 규칙 일치 |

서비스 테스트 수는 186 + 17 + 3 + 7 = **213개**이며 감지 테스트 12개는 별도다. 실제 LLM 호출과 12회 성능 벤치마크는 실행하지 않았다.

## 원본 보존과 로컬 증거

기존 파일 163개의 사전 hash를 기록했고, 수정한 스킬 4개 파일을 제외한 **159개 파일의 hash가 동일함**을 확인했다. `src/`, 실제 vendor, 기존 일반 EXE, 자체서명 EXE, 기존 미커밋 `scripts/sign-selfsigned.ps1`을 보존했다. 기존 설치된 윤문 스킬의 엔진도 `31a66d1` 그대로다.

로컬 검증 자료는 다음 위치에 있다.

```text
.worktrees/updater-test-evidence/before.json
.worktrees/updater-test-evidence/fork-file-comparison.json
.worktrees/updater-test-evidence/rejected-old-fork.log
.worktrees/updater-test-evidence/expected-patch-conflict.log
.worktrees/updater-test-evidence/rehearsal-result.json
.worktrees/updater-test-evidence/preservation-and-packages.json
.worktrees/updater-service-test/release/build-info.json
.worktrees/updater-service-test/release/smoke-fixture-codex.json
```

실제 갱신을 진행하려면 먼저 지정 포크를 원하는 upstream 상태로 동기화하고 새 커밋의 선후관계를 다시 확인해야 한다. 현재 오래된 포크를 서비스 위에 덮어쓰면 안 된다.
