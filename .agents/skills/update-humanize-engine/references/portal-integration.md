# 포털 통합 시 확인할 계약

이 문서는 저장소를 읽을 때의 점검 경로다. 실제 값과 구현은 현재 서비스 파일을 우선한다.

## 갱신 범위

| 파일 | 확인할 내용 |
|---|---|
| `scripts/sync-engine.ps1` | 핀, 실제 upstream 버전, 파일 허용 목록, 소스 위치, 출처 생성문 |
| `scripts/patches/humanize-engine-portal.patch` | 새 upstream의 pristine 파일에 적용되는 포털 차이만 포함 |
| `vendor/humanize-engine/ENGINE_VERSION`, `UPSTREAM.md`, `LICENSE` | 실제 배포 내용과 포크 URL·commit·version 일치, 라이선스 보존 |
| `src/engine/python-engine.ts` | prepare/restore/verify/reassemble 명령, 출력 형식, 종료 코드 |
| `src/engine/humanize-engine.ts` | 후처리 순서, 재시도·복원, 전체 문서 검사, 모델별 진단 정보 |
| `src/engine/prompt-builder.ts`, `codex-runner.ts`, `claude-runner.ts` | quick-rules 제공 방식, 원문 경계, JSON 출력 계약 |
| `src/process/preflight.ts`, `tests/unit/preflight.test.ts` | 엔진 version이 바뀔 때만 호환 버전 판단 수정 |
| `tests/unit/vendor-engine.test.ts` | 핀과 필요한 런타임 파일 목록 |
| `README.md`, `docs/operations.md` | 현재 동작·업데이트 출처·검증 상태 반영 |

동기화 목록은 고정된 완전 목록이 아니다. 새 스크립트의 import와 파일 읽기 경로를 따라 추가 의존성이 필요한지 확인한다. `checks.py` 같은 검증 코드를 upstream 테스트 디렉터리에서 런타임으로 import하지 않도록 배포 경계를 점검한다. 더 이상 쓰지 않는 파일은 이전/신규 목록과 참조를 확인한 뒤 해당 파일만 제거한다.

## 포털 전용 동작

- HTTP 수신 단계에서 CR·CRLF를 LF로 통일한다. Python 파일 I/O가 플랫폼 줄바꿈을 다시 주입하지 않아야 한다. restore 스크립트를 단독 호출한 CRLF 보존도 테스트한다.
- Python manifest의 start/end는 Unicode code point 기준이다. JavaScript에서 UTF-16 slice로 바꾸지 않는다. 이모지 포함 원문의 손실 없는 분할·재조립과 전체 범위 검증을 유지한다.
- `--portal-auto-route`와 `processing_mode`는 포털 어댑터의 계약이다. 짧은 light/standard의 단일 처리와 heavy/장문/판정 불가의 분할 처리를 유지한다. route 계산에 `_text`가 필요한 구현이면 원문 전달을 유지한다.
- 각 윤문 시도 뒤에 `restore_modality.py`와 `strip_injected_commas.py`를 실행하고 그 결과를 검증한다. upstream이 이 기능을 이동하거나 대체하면 동등한 동작으로 어댑터를 갱신한다.
- `strip_injected_commas.py --all`은 진단 단계가 없는 포털에서 무심코 켜지 않는다. 원문에 있던 쉼표까지 제거하는 범위 확대인지 확인한다.
- gate exit code와 JSON report가 일치해야 한다. 검증 실패를 성공으로 바꾸거나 경고·원문 복원 이벤트를 누락시키는 통합을 피한다. 정적 검증 통과를 의미 보존의 절대적 보증으로 표현하지 않는다.
- GPT와 Claude 모두 같은 Python 후처리·검증을 사용하며 model/effort 진단값은 선택된 엔진을 따라야 한다. `src/engine/model-policy.ts`의 현재 정책을 읽는다.
- 로그인 없는 LAN 사용, 제한된 접수·실행 큐, 취소와 프로세스 정리, 임시 작업 폴더 삭제, 본문 로그 금지 계약을 유지한다. 모델 별칭·포트·동시성 확대는 upstream 윤문 규칙 업데이트의 부수 작업으로 바꾸지 않는다.

## 패치 재작성과 재현성

1. 고정한 upstream 커밋에서 서비스가 배포하는 파일을 `vendor/humanize-engine` 레이아웃으로 별도 스테이징한다. 이 pristine 트리를 기준으로 기록한다.
2. 현재 포털 패치에 `git apply --check`를 수행한다. 현재 sync 스크립트는 먼저 파일을 복사하므로 반드시 스테이징 사본에서 실행한다.
3. 실패한 hunk는 원본 upstream, 새 upstream, 현재 포털 코드를 비교해 이식한다. upstream에 이미 구현된 것은 중복하지 않는다. `--reject`로 누락된 변경이 있는 상태를 성공으로 간주하지 않는다.
4. 새 pristine와 수정 트리의 `git diff`로 패치를 다시 만든다. 경로는 `a/vendor/humanize-engine/...`, `b/vendor/humanize-engine/...` 형식을 유지하며 ENGINE_VERSION·출처 문서 등 생성 메타데이터를 섞지 않는다.
5. 깨끗한 스테이징 사본에서 새 sync 스크립트를 실행하고 패치 적용, marker/source/license, 파일 목록과 내용이 기대 트리와 같은지 확인한다. 동일 커밋으로 다시 실행해 변경이 없어야 한다.
6. 검증된 파일만 서비스로 가져온다. 작업 디렉터리와 제거 대상을 절대 경로로 확인하며 서비스 루트나 사용자 체크아웃 전체를 재귀 삭제하지 않는다.

기존 핀이 대상의 조상이 아니어도 포크에 대응 코드가 있을 수 있다. 억지 merge나 force-push로 이력을 맞추지 말고 고정한 두 트리의 파일 차이로 이식한다. 작업 중 원격 HEAD가 바뀌어도 고정 대상을 조용히 변경하지 말고 다음 업데이트 대상으로 보고한다.

## 유의미한 검증 사례

- 새 규칙에 대응하는 한국어 입력/결과 사례와 사실·수치·인용 관련 검증 동작.
- 각 엔진 설정에서 유보 표현 복원과 제거한 쉼표 수가 실제 결과 및 진단값에 반영되는지.
- LF/CRLF, 이모지, Markdown 제목·각주, 15,000자 경계와 heavy 라우팅.
- 재시도, 원문 복원, 전체 문서 검사, 취소, 큐 용량, 임시 파일 정리.
- 규칙 인덱스 생성과 선택 배포된 vendor 파일만으로 Python 실행이 가능한지.

관련 구현이 바뀐 항목에 회귀 검증을 추가하고 기존 통합·브라우저 검증을 활용한다. 포트는 `src/config.ts`와 실행·방화벽 스크립트, E2E 설정 사이에서 일치해야 한다. 현재 화면의 변환 URL에는 engine query가 있으므로 E2E mock이 query까지 처리하는지 확인한다.
