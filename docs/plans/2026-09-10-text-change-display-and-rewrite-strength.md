# 텍스트 변경 표시와 4단계 변환 강도 구현 계획

작성일: 2026-09-10 · 기준: 서비스 0.3.3 / `5f2e0e0`

추가 연구: [강도별 지원 범위 상세 정의](../research/2026-09-10-rewrite-strength-scope.md). 사용자의 ‘매우 강하게에서 변환 범위가 매우 많기를 원함’을 반영한 강도 정책은 이 상세 정의를 따른다.

## 1. 결론과 범위

두 기능 모두 웹과 Windows 앱의 공통 화면에 구현할 수 있다. 현재 포함된 오픈소스에 4단계 사용자 변환 강도 설정은 없으므로 서비스에서 편집 정책을 정의하고 CLI 프롬프트로 전달해야 한다. 모델/추론 수준 조절과는 별개다.

이번 계획은 **직접 입력하거나 붙여넣은 텍스트**에 두 기능을 적용한다. 사용자의 ‘문서 입력 제외’를 넓게 해석해 DOCX/PPTX뿐 아니라 파일 불러오기로 입력한 TXT/MD도 제외한다. 파일을 불러온 뒤 내용을 직접 수정하면 기존 앱의 동작대로 직접 입력으로 전환한다. 이 범위를 구현 전에 명시하며, 파일 입력까지 확대하는 것은 별도 변경이다.

- 웹 및 Windows 앱: 같은 표시·강도 정책 사용.
- 파일 입력: 기존 결과 표시와 기본 윤문 정책 유지. 강도 메뉴 및 변경 표시 숨김.
- Claude/Codex 호스트용 스킬의 강도 옵션, 문서 변경 추적, Word track changes, PPT 표시: 이번 범위 밖.
- 이 문서는 조사와 구현 계획이다. 기능 코드·실행파일은 아직 변경하지 않는다.

## 2. 조사 근거

외부 최신 브랜치가 아니라 **현재 서비스에 포함된 원본 코드**를 분석했다. 엔진은 `version=2.3.2`, commit `9747f036cdc28a1a8aea4dc71fef1f7846eb96f7`이다. 최신 원격 동기화는 이 작업에서 실행하지 않았다.

| 코드 | 확인 결과 / 설계 영향 |
|---|---|
| `public/index.html`, `styles.css` | 결과는 읽기 전용 textarea다. 문자열 일부를 다른 색으로 칠할 수 없으므로 변경 보기 전용 DOM이 필요하다. |
| `public/app.js`, `transport.js` | 웹/앱이 같은 화면을 사용하며 result-delta를 모아 done에서 완료한다. 직접 입력/파일/Office 상태를 이미 구분한다. |
| `src/engine/text-edits.ts` | 모델의 before/after 응답은 원문 일치 검사 후 전체 결과 문자열로 복원된다. 이 편집 목록은 최종 변경 표시의 기준으로 쓰면 안 된다. |
| `src/engine/humanize-engine.ts` | 복원 → 검증 → 최대 1회 재시도 → 필요한 청크 원문 복귀 → 재조립 → 전체 검증을 거친다. 화면 비교는 이 과정을 마친 최종 결과와 실행 당시 원문 사이에서 계산해야 한다. |
| `src/engine/prompt-builder.ts` | 현재는 규칙 기반의 보수적인 단일 편집 정책이다. 강도별 정책 입력을 추가할 수 있다. |
| `src/engine/model-policy.ts` | 모델과 effort만 있다. effort는 편집 강도 설정이 아니다. |
| `vendor/humanize-engine/scripts/prepare_monolith_input.py` | light/standard/heavy는 진단·라우팅 권고다. 요청한 4단계 편집 강도와 직접 대응하지 않는다. |
| `vendor/humanize-engine/skills/humanize-korean/references/quick-rules.md` | 어휘·문장 구조·반복·리듬 규칙과 의미 보존 원칙이 있다. 강도별로 편집 범위를 구체화할 근거가 된다. |
| `vendor/humanize-engine/scripts/verify_change_rate.py` | 변경률 30% 이상 경고, 50% 이상 중단. ‘매우 강하게’라도 이 검증을 통과하지 못하면 수정이 줄거나 원문으로 복귀할 수 있다. |
| `engine_runtime/workflow.py` | 숫자·인용·제목·각주 보존 위반을 강화해 차단한다. 강도와 관계없이 유지해야 한다. |

기존 속도 실험에서도 모델과 호출마다 어휘 선택·수정량이 달랐다. 프롬프트로 편집 경향을 조절하는 것은 가능하지만 ‘강하게 = 반드시 몇 % 변경’ 같은 정량 보장은 불가능하다. 검증 통과만으로 규칙 적용 강도의 차이가 입증되지는 않는다.

## 3. 변경 표시 UX

### 표시 규칙

- 변환 완료 시 직접 입력 텍스트에는 **변경 표시**를 기본으로 켠다.
- 수정되어 새로 들어간 구절 및 새로 추가된 표현: 연노랑 배경과 밑줄. 본문 글자색은 가독성을 위해 진한 색 유지.
- 삭제된 원문 구절: 연빨강 배경, 진한 빨강 글자, 취소선. 해당 삭제 위치에 검토용으로 삽입한다.
- 치환: 삭제된 이전 구절(빨강 취소선)과 새로운 구절(연노랑)을 함께 표시한다. 사용자가 전후 관계를 바로 볼 수 있어야 한다.
- 변경 없음: 무색으로 표시하고 ‘변경된 부분이 없습니다’ 안내.
- 공백·줄바꿈만 변경: 변경 보기에서만 접근 가능한 표식/설명을 제공한다. 최종 문자열에는 표식을 넣지 않는다.
- 범례: ‘연노랑: 수정·추가 / 빨강 취소선: 삭제’. 색상만으로 의미를 구분하지 않는다.
- 결과 상단에 `변경 표시 / 최종 문구` 전환을 둔다. 최종 문구에서는 삭제 흔적 없는 현재 결과만 보여준다.

예: 원문 `경쟁력을 가지고 있다.` → 결과 `경쟁력을 갖고 있다.`이면 공통 부분을 유지하고 실제 달라진 구절만 표시한다. 문장 전체를 일괄 노란색으로 칠하지 않는다. 다만 장문 비교가 복잡해 제한을 초과하면 문단 단위로 표시하고 정밀 표시가 아님을 알린다.

### 결과 데이터와 화면 분리

- `sourceSnapshot`: 변환 버튼을 누른 순간의 원문. 기존 입력 처리와 같은 CRLF/CR → LF 정규화만 적용하고 임의 trim/공백 축약은 하지 않는다.
- `finalText`: 게이트를 통과한 최종 출력. 기존 textarea/복사/다운로드의 원본 데이터다.
- `diffSegments`: 두 문자열에서 계산한 화면 표시용 equal/insert/delete 목록.
- 삭제 구절은 finalText에 다시 넣지 않는다. 복사 버튼, TXT 저장, 다운로드에는 finalText만 전달한다.
- 변경 보기에는 ‘복사하면 삭제된 문구는 제외됩니다’ 안내를 둔다. 해당 영역 안에서 선택 후 Ctrl+C 또는 컨텍스트 메뉴 복사를 하면 선택된 삽입/공통 텍스트만 `text/plain`으로 기록한다. HTML MIME 및 검토용 표식은 내보내지 않는다. 삭제만 선택한 경우 복사를 막고 ‘선택한 부분은 삭제된 문구입니다’라고 알리며 기존 클립보드는 유지한다. 영역 밖까지 걸친 선택은 임의로 잘라 복사하지 않고 최종 문구 보기에서 선택하도록 안내한다. 모바일 선택 메뉴도 동일 정책으로 검증한다.
- 웹 복사 버튼은 Clipboard API 사용이 불가능한 비보안 LAN HTTP도 지원한다. 숨긴 결과 textarea에 focus/select하지 말고 임시 오프스크린 selectable textarea에 finalText를 넣어 기존 execCommand fallback을 실행한다. 완료 후 임시 노드를 제거하고 이전 포커스·선택 범위를 복원한다. 앱은 기존 preload 복사 API를 유지한다.
- readonly textarea는 최종 문구 모드에 유지한다. 변경 표시 모드에서는 별도 읽기 전용 영역을 같은 크기로 제공하고 숨겨진 뷰는 접근성 트리에서도 제외한다.
- 변경 보기 영역은 이름 있는 읽기 영역으로 제공하고, 제목·전환 버튼·본문 스크롤까지 키보드로 접근 가능하게 한다. 일반 DOM을 textarea와 같은 캐럿 편집 컨트롤로 가장하지 않는다. 세밀한 키보드 문자열 선택은 ‘최종 문구’ textarea에서 제공하며 전환 시 그 필드로 포커스를 옮긴다. 스크린리더는 화면 색상에 의존하지 않고 삽입/삭제 시작·끝을 읽을 수 있게 한다. 원문을 숨김 설명으로 반복 낭독하거나 작업 전체를 live region에 넣지 않는다.
- 양쪽 필드 높이와 시작 위치, 스크롤, 모바일 배치는 기존 동일 높이 요구를 유지한다. HTML/Markdown은 텍스트 그대로 표시한다.

### 상태 전환

- 새 변환·초기화·입력 수정·파일 전환·실패·취소: 이전 diff, 이전 원문 스냅샷 및 변경 안내 제거.
- 결과를 받는 동안은 기존 일반 텍스트 누적 표시. 성공 완료 후 diff를 한 번 계산한다. LLM 호출은 추가하지 않는다.
- diff가 계산 중이면 최종 문구를 먼저 제공한다. 완료된 모델 작업 시간을 diff 계산 대기로 부풀리지 않는다.
- 작업 ID/세대 번호를 검사해 이전 diff 계산이 새 결과를 덮지 못하게 한다.
- 강도 선택을 바꾸는 것만으로 자동 재변환하지 않는다. 기존 결과에는 그 작업에 실제 사용한 강도를 표시해 새 선택과 혼동하지 않게 한다.

## 4. diff 구현 방안

새 공통 모듈 `public/text-diff.js`와 표시 모듈 `public/result-diff.js`를 추가한다.

1. 공통 접두·접미를 먼저 제외하고 줄/문단 단위로 대응한다.
2. 변경 블록 안에서 어절과 공백을 분리해 비교하고, 필요한 부분만 Unicode grapheme 단위로 정밀 비교한다. 한국어 조사·어미 변경, 이모지 ZWJ·결합 문자가 깨지지 않도록 한다.
3. 입력 전체에 O(n×m) 크기 배열을 만드는 구현은 피한다. diff 라이브러리가 필요하면 구현 단계에서 공식 소스·라이선스·ESM/worker 호환성과 번들 크기를 확인하고 버전을 고정한다. 지금 조사하지 않은 패키지의 성능을 전제로 계획하지 않는다.
4. 초기 구현 기준은 합산 10,000자 이상을 Web Worker로 보내고, worker 정밀 비교에 500ms 예산을 둔다. 메인 스레드 DOM 반영은 프레임당 8ms 이내로 나누고 표시 노드는 5,000개를 상한으로 한다. 이 수치는 최초 측정 목표이며 대상 PC의 실측에 따라 근거를 남겨 조정할 수 있다. 연산 예산 초과 시 변경 블록을 거친 삭제/삽입으로 표시한다. 취소 가능한 계산과 명시적인 제한을 두며, 느리다고 ‘변경 없음’으로 표시하지 않는다.
5. DOM은 `createElement`, `textContent`, `DocumentFragment`로 만든다. 원문·결과를 innerHTML로 넣지 않는다. 노드가 많으면 문단별 지연 렌더링 또는 거친 표시로 제한한다.
6. Electron의 `humanize://` 리소스 경로·CSP·worker 로딩과 웹 HTTP 환경을 모두 검증한다. 외부 CDN은 사용하지 않는다.

항상 아래 불변식을 만족해야 한다.

- equal + delete를 원문 순서로 합치면 sourceSnapshot과 완전히 같음.
- equal + insert를 결과 순서로 합치면 finalText와 완전히 같음.
- 롤백으로 최종 결과가 원문과 같으면 변경 표시 없음.

## 5. 변환 강도 4단계

화면 이름은 요청대로 `보통 / 중간 / 강하게 / 매우 강하게`를 사용한다. 기본값 보통은 현재 편집 정책을 유지한다. 짧은 설명을 함께 보여 단계 차이를 명확히 한다.

| 표시 / 내부 값 | 편집 정책 |
|---|---|
| 보통 / `normal` | 현재 수준. 명확한 번역투와 기계적 표현을 국소 수정하고 이미 자연스러운 표현은 보존한다. |
| 중간 / `medium` | 같은 의미를 유지하면서 어색한 어휘·명사화·불필요한 연결 표현을 더 넓게 다듬는다. |
| 강하게 / `strong` | 문장 전체를 살펴 반복 표현과 기계적인 구문을 적극적으로 정리하고 문장 내부 어순·호흡을 다듬는다. |
| 매우 강하게 / `very-strong` | 글 전반에서 많은 문장의 표현·어순·구문·호흡을 실제로 다시 구성한다. 재서술이 유효한 문장 전반을 대상으로 하며, 보호 문장에는 국소 수정/원문 보존을 적용한다. 1차 구현은 문장 경계를 유지하며 분할·병합은 허용하지 않는다. |

모든 단계에서 사실·주장·숫자·날짜·고유명사·인용·부정·당위·유보·제목·문단 순서·원문의 말투를 보존한다. 새로운 근거나 예시를 만들지 않는다. 제목/목록 구조와 문단 자체를 재배열하지 않는다. 원문이 자연스러우면 매우 강하게에서도 무수정이 가능하다.

매우 강하게는 원본의 국소 교정을 확장하는 서비스 정책이다. 문법적으로 맞는 문장도 글 전체의 반복·호흡을 개선할 유효한 대안이 있으면 재서술할 수 있다. ‘모든 문장을 검토’하는 것만으로 완료하지 않으며 실제 구문 변화를 평가한다. 모든 강도에서 기존 조건부 룰의 발동 조건과 내용 앵커 보존을 유지한다.

### 제약과 안내

- 강도는 편집 범위 정책이며 모델이나 effort를 자동 변경하지 않는다.
- 검증 상한을 강도별로 올리지 않는다. ‘매우 강하게’를 위해 50% 중단 조건을 해제하거나 숨기지 않는다.
- 검증 실패 뒤 재시도는 기존처럼 더 보수적으로 수행한다. 선택한 강도와 별개로 보존을 우선하고 원문 복귀/검토 안내를 유지한다.
- 기존 `restore_modality`는 분할·병합 또는 낮은 정렬 유사도에서 복원을 보류할 수 있고, 현재 HumanizeEngine은 `skippedSentences`를 처리하지 않는다. P5의 일부 손실은 경고이고 낮은 유사도는 판정에서 제외된다. 따라서 현재 게이트가 모든 의미 보존을 보장한다고 간주하지 않는다. 강도 기능의 직접 입력 경로에서는 복원 보류를 명시적으로 수집해 첫 시도는 보수적 재시도, 재시도에서도 보류가 남으면 해당 청크를 원문으로 되돌리는 처리를 먼저 마련한다. 보류를 숨기거나 일반 경고로만 수용하지 않는다. 문장 분할·병합 지원은 정렬 및 검증을 보완한 후 후속 범위로 검토한다.
- UI 설명: ‘강도를 높이면 표현과 문장 구성을 더 적극적으로 다듬습니다. 의미 보존 검증에 따라 일부 변경은 제한될 수 있습니다.’
- 강도가 높으면 출력 길이·재시도·시간이 늘 수 있다. 기존 속도 개선을 유지하되 모든 단계의 동일 속도를 약속하지 않는다.
- 규칙 강도와 결과 diff의 변경량은 서로 다른 개념이다. 임의 목표 변경률이나 강도별 최소 수정 개수를 넣지 않는다.
- 추가 결정적 실험에서 이름/숫자의 집합은 같아도 주체-행위 또는 대상-수치가 교환된 잘못된 문장이 현재 게이트를 통과했다. 따라서 복원 보류 처리만으로 검증 보완을 완료하지 않는다. 매우 강하게의 출시 전 문장별 대응·핵심 개념어·고위험 관계 보호를 설계하고 해당 실패 표본을 회귀 검사에 넣는다. 초기 버전은 관계 판정이 어려운 문장을 보호 또는 국소 수정으로 제한한다. 문장 ID만 보존해도 문장 내부 사실 교환은 발생할 수 있음을 고려한다.

## 6. 전달·저장 설계

- `src/engine/rewrite-policy.ts`: 4개 값 whitelist, 기본값, UI 라벨/설명, 강도별 프롬프트 정책을 중앙 정의한다.
- 모델/effort의 `ModelSettings`와 별도로 `RewriteOptions`를 둔다. 선택적 strength가 없으면 normal. 유효하지 않은 값·배열·객체는 요청 입구에서 거절한다.
- 웹: 직접 입력 변환 요청의 strength를 `public/transport.js` → `src/app.ts`에서 검증 → `HumanizeRequest`로 전달한다. 큐 대기 전에 값을 스냅샷으로 확정한다.
- 앱: preferences → preload → main 검증 → worker → HumanizeRequest로 전달한다. renderer가 보낸 값을 신뢰해 그대로 프롬프트에 넣지 않는다.
- 엔진: 모든 청크·두 CLI runner·재시도에 같은 선택 정책을 전달한다. 재시도 보존 지침은 강도 정책보다 우선한다.
- 프롬프트: 공통 룰북과 기존 compact 응답 계약은 유지한다. 보통은 현재 보수적 편집 지침을 기준선으로 유지한다. 상위 단계에서는 공통 '국소/수술적 수정만' 지침을 그대로 둔 채 모순되는 적극적 지침을 덧붙이지 않고, 해당 편집 범위 문장만 단계별 정책으로 대체한다. 우선순위는 내용 보존 제약 → 검증 후 재시도 제약 → 선택 강도의 편집 범위 → 일반 스타일 권고다. 안정적인 공통 프롬프트 뒤에 검증된 강도 지침을 배치하고 원문은 별도 데이터 경계로 유지한다.
- 웹 localStorage와 앱 settings.json에는 강도 선택만 저장한다. 기존 설정에 필드가 없거나 알 수 없는 값이면 normal로 복구한다. 원문·diff·결과는 설정에 저장하지 않는다.
- 강도는 엔진과 독립된 하나의 작업 설정이다. Claude↔Codex를 전환해도 유지한다. 파일 모드에서는 보관된 직접 입력 강도를 숨기고 파일 요청에는 전송하지 않는다.
- 진단 기록에 실제 선택한 strength를 추가한다. UI가 선택만 바꾸고 엔진에는 전달하지 않는 구현을 방지한다.
- 진단에는 요청 강도, 시도 번호, 보수적 재시도 여부, 복원 보류/원문 복귀 수를 구분한다. 강하게 요청했더라도 재시도에서 편집 범위가 제한됐다는 사실을 결과 안내와 일치시킨다.
- `/api/documents`와 `DocumentEngine`, 호스트 스킬 계약은 이번 기능 때문에 변경하지 않는다.
- 현재 일반 텍스트 API/IPC에는 TXT/MD 파일과 직접 입력을 구별하는 값이 없다. `inputKind: 'direct-text' | 'text-file'`을 웹 요청·앱 IPC·작업 스냅샷·HumanizeRequest에 추가하고 whitelist로 검증한다. 현재 UI는 파일 상태를 기준으로 값을 확정하며 직접 입력은 normal일 때도 명시한다. 파일 모드는 normal만 사용하고 비기본 강도를 함께 보내면 입력 오류로 거절한다. 기존 클라이언트처럼 inputKind가 없는 요청은 기존 normal 동작을 유지한다. 출처 표시는 정책 라우팅용 클라이언트 선언이며 실제 텍스트 출처를 증명하는 보안 장치로 취급하지 않는다.
- 보통의 **편집 프롬프트 기준선 유지**와 새 직접 입력 경로의 **복원 보류 검증 강화**는 구분한다. 강화 정책은 명시적 direct-text에만 적용하고 text-file·출처 없는 이전 클라이언트 및 Office에는 기존 검증 동작을 유지한다.

## 7. 구현 순서

1. 강도 정책과 평가 fixture 작성. 보통은 현재 지침을 기준선으로 고정하고, 상위 단계가 허용하는 편집과 금지 사항을 구체화한다.
   매우 강하게의 넓은 재서술을 위한 문장별 대응과 관계 보호 설계도 이 단계에 포함한다. 상세 연구의 6개 결정적 표본 중 숫자·주체 관계 교환을 놓치는 기존 검증 공백을 먼저 재현한다.
2. strength 요청·설정 저장·엔진 전달을 구현하고 두 CLI의 실제 프롬프트까지 검증한다. 기본값 및 기존 클라이언트 호환을 유지한다.
3. diff 순수 계산 모듈과 복원 불변식 테스트를 구현한다. 장문 연산 예산과 대체 표시도 이 단계에서 확인한다.
4. 공통 화면에 강도 선택, 결과 보기 전환, 색상·취소선·범례를 연결한다. 웹/앱, 직접 입력/파일 모드를 명확히 분리한다.
5. 입력 변경·취소·재실행·복사·저장·접근성·완료 이벤트 순서 회귀 테스트를 실행한다.
6. 동일 원문·모델·effort로 강도별 실제 CLI 평가를 수행한다. 차이가 불분명하면 지침을 보완하고 동일 표본으로 다시 측정한다. 검증을 느슨하게 해서 단계를 구별하지 않는다.
7. 빌드·패키징·최종 실행 테스트 후 새 버전 portable EXE를 만들고 기존 인증서로 자체 서명한다. 기존 EXE는 보존한다. 원문/결과를 Git에 넣지 않는다.

## 8. 검증과 완료 조건

### 자동 검증

- diff: 무수정, 추가만, 삭제만, 치환, 연속 삭제, 문두/문미 삭제, 동일 문구 반복, 조사·어미, 공백/줄바꿈, 이모지·결합 문자, 긴 입력, 모든 문자 교체.
- 원문/결과 복원 불변식과 XSS 입력(`<script>`, `<img onerror=...>`, Markdown 링크)의 텍스트 표시.
- 최종 출력과 복사·저장 내용이 정확히 같고 삭제 흔적이 섞이지 않음. Ctrl+C 선택 복사도 확인.
- 비보안 LAN HTTP의 Clipboard API 부재 상태에서 변경 보기의 복사 버튼이 동작하고 포커스가 복구됨. 삭제만 선택, 영역 경계 선택, 컨텍스트 메뉴 및 모바일 복사, HTML MIME 배제도 확인.
- 실제 후처리로 복원된 문장은 diff에서도 원문 유지로 표시됨.
- 4단계 whitelist, 누락 normal, 잘못된 값 거절, 기존 설정 마이그레이션, queued/running 중 강도 변경 방지.
- inputKind whitelist, 직접 입력 normal의 강화 정책 적용, 파일+비기본 강도 거절, 출처 없는 기존 요청 호환을 검사한다. 입력 출처와 강도는 큐에 들어간 작업마다 고정되어야 한다.
- 첫 호출 및 재시도, 모든 청크에서 선택한 strength와 모델/effort가 유지됨.
- 서법 복원 보류가 발생하는 분할·병합·낮은 유사도 표본은 성공 처리로 흘러가지 않고 재시도/원문 복귀함. 이미 자연스러운 글을 강제로 변경하지 않으며 4단계별 문장 경계 보존을 평가함.
- 직접 입력에만 메뉴/표시 제공. TXT/MD/DOCX/PPTX 파일 모드는 기존 동작 유지.
- 웹/앱 동일 높이, 모바일 줄바꿈, 키보드 조작, 색상 외 의미 표시, 테마 대비, 새 입력 시 이전 diff 제거.
- worker 완료 전 새 작업/취소 발생 시 이전 결과가 섞이지 않음. 10,000자/50,000자 스트레스 표본에서 UI 조작 가능 및 예산 초과 대체 표시를 확인한다.

### 실제 강도 평가

합성 한국어 표본 6개(이미 자연스러운 글, 번역투, 명사화, 반복 구조, 보고 문체, 숫자·인용·부정·유보 포함)를 사용한다. 우선 중간 길이 대표 표본으로 두 CLI × 4단계 = 8회 탐색한다. 통과한 지침으로 필요 표본을 확대하며, 실패/차이 불명확 시 지침 수정 후 해당 조합만 재검증한다.

8회 탐색은 완료 판정이 아니다. 출시 전 최소 평가는 재구성 표본과 보존 위험 표본 각각에 대해 두 CLI × 4단계 × 동일 조건 2회, 총 32회로 정한다. 모델/effort는 엔진별 고정하고 단계 실행 순서를 번갈아 배치한다. 정상문·경계 사례는 6개 표본 전체의 결정적 테스트와 수동 평가로 보완한다. 국소 어휘 교정, 구문 수정 범위, 문장 내부 리듬 재구성, 의미 보존, 과교정 여부를 고정 검토표로 비교한다. 단계 차이가 불명확하면 해당 조합을 추가 검증하고 결과를 기록한다. 재시도 없는 호출과 재시도 포함 작업의 시간을 구분한다.

측정값: 최종 출력·규칙 잔존·실제 편집 범위·게이트·재시도/복원·경과 시간·출력량. 사람이 의미와 자연스러움을 함께 검토한다. 표본별 변경률이 무조건 단조 증가해야 한다고 요구하지 않으며, 전체 평가에서 상위 단계의 허용된 편집 범위가 실제로 구분되는지 확인한다. ‘매우 강하게’가 계속 롤백된다면 이 제약과 결과를 보고하고 정책을 보완한다.

사용자의 넓은 변환 요구를 평가하기 위해 매우 강하게는 재서술에 적합한 합성 장문에서 편집 가능 문장의 약 70% 이상이 실질적으로 달라지는 것을 초기 연구 목표로 둔다. 사용자 글에 적용하는 강제 할당량은 아니다. 문장 수정률과 구문 재구성률을 따로 평가해 단순 쉼표·단어 치환만으로 목표를 충족시키지 않는다. 내용 보존 검증 실패를 수정량 목표보다 우선하며, 상한에 반복적으로 막히면 무조건 완화하지 않고 후속 정책 연구 결과를 보고한다.

완료 조건은 메뉴 4개가 보이는 것에 그치지 않는다. 최종 결과의 정확한 변경 표시, 순수 최종 문구 복사/저장, 두 CLI의 강도 전달, 의미 보존, 기존 속도·문서 경로 회귀 검사, 웹 및 portable 앱 실행을 모두 통과해야 한다.

## 9. 서브 에이전트 2개 교차검토 반영

UX 리뷰와 엔진 리뷰를 독립 수행한 뒤 서로의 발견을 재검토했다. 두 리뷰어가 동의한 P1 두 건은 계획에 반영했다: 숨겨진 textarea 때문에 깨질 수 있는 LAN 복사 fallback, 문장 분할·병합/정렬 불확실성에서 서법 복원이 보류되는 검증 공백.

P2 및 구현 명확화 항목도 반영했다: 선택 복사 경계·접근성, 직접 입력 출처 계약, 공통 보수 지침과 강도 지침의 우선순위, 요청 강도와 재시도 동작 구분, diff 연산/DOM 예산, 강도 평가의 최소 표본·반복수. 매우 강하게의 1차 범위는 문장 내부 재구성으로 제한한다. 이 리뷰는 계획 검토이며 위 검증 강화가 이미 구현됐다는 뜻은 아니다.

## Task 1: Strength policy, contracts and fidelity guards

Implement backend/desktop contracts using TDD. Worktree only; no subagents. Read `docs/research/2026-09-10-rewrite-strength-scope.md` for binding scope and examples. Own src/, desktop/, and related tests; leave public/ UI integration to Task 3. Commit only owned files.

- Four strengths normal/medium/strong/very-strong, independent from ModelSettings. Export validated policy and labels/descriptions from `src/engine/rewrite-policy.ts`. Health web/desktop exposes `rewriteOptions` array of `{id,label,description}`. Labels 보통/중간/강하게/매우 강하게; descriptions must explain actual changes. Very strong rewrites many eligible sentences throughout the text (syntax/order/rhythm), not mere token substitutions. Common fidelity constraints always outrank strength; replace conflicting local-only instructions for high strengths. Normal preserves existing editorial behavior.
- Wire top-level `inputKind` (direct-text/text-file) and `strength` through web query, desktop transform payload, request snapshot, HumanizeRequest, both CLI runners and retries. A `rewriteOptions?: RewriteOptions` internal request property may bundle them; parser `parseRewriteOptions(inputKind, strength)` returns undefined for fully absent legacy requests, validates all other values. Non-normal strength requires direct-text; text-file with non-normal rejects. File and legacy behavior remains unchanged. Missing strength with valid direct-text defaults normal. Validate before queue reservation. Do not alter Office API/DocumentEngine or host skills.
- Desktop preferences store `rewriteStrength` default normal, add validated `selectRewriteStrength(strength)` preload/main IPC. Existing/malformed saved preference safely defaults normal. UI later sends explicit captured selection and inputKind; backend never trusts arbitrary strings.
- Extend direct-text fidelity checks before accepting candidate: enforce sentence/paragraph boundaries and preserve risky factual sentences (numbers/dates/quotes, modality/conditions and multiple named-subject relations) conservatively where reliable relation validation is unavailable. Detect research swaps using deterministic fixtures. Preserve core concept vocabulary where reliably identified; do not claim complete semantic detection. Do not add a second LLM call. Reuse exact-source reconstruction and normal gates. If direct-text restore reports skippedSentences>0 or new guard fails, first retry conservatively and on persistent second failure restore chunk, with warnings and diagnostics. Full-source final guard also applies so cross-chunk omissions cannot leak. 30%/50% thresholds remain unchanged. Keep legacy/file semantics and warnings unchanged.
- Diagnostics distinguish requested strength, conservative retry and guard/restore counts, without persisting raw text. No automatic model/effort changes. Emit descriptive warnings when broad edits are restricted.
- TDD focused tests: whitelist/default/legacy/file isolation, actual request options reaching two CLI prompts/retry, direct-text swaps and hedge loss blocked/rolled back, unchanged eligible normal text, high-strength prompt scope, settings persistence validation. Mock native external CLI only; real policy/engine control flow. Watch fail before implement, then full unit/typecheck and document regressions. Report tests and limitations in task report. No release/build-version changes.

## Task 2: Bounded Unicode diff and read-only result component

Implement public/text-diff.js, public/text-diff-worker.js and public/result-diff.js with focused TDD tests; no app.js/index.html/styles.css wiring yet. No subagents. Use no CDN. Prefer bounded own algorithm (no NxM whole-input matrix), line alignment then word/grapheme refinement, exact source/output reconstruction, repeated phrases and emoji safe. Can use confirmed dependency only if locally justified and license/version checked. For total input >=10k use module worker, 500ms compute budget, <=5000 display nodes, chunk DOM work, cancellation/generation safe. Budget overflow must show truthful coarse replacement with notice, not false unchanged; fallback must preserve both strings exactly. Worker path must work under HTTP and humanize://app. Small-input computations also bounded.

Design result component exported API and report it for UI integrator: setResult(source, finalText), reset(), show mode diff/final via host controls, dispose if needed. You may instead export factory createResultDiff({container,onStatus}) with documented API. Render using text nodes, ins/del styling hooks, aria text for insert/delete start/end. Do not expose unsafe innerHTML, execute Markdown, or alter finalText. Preserve whitespace/newlines with exact pure reconstruction. Diff-specific Ctrl+C/contextmenu copy within selection should exclude del/markers and write text/plain only; deletion-only cancels with notice preserving clipboard; selection spanning outside instructs final-text view without silently dropping source. Provide explicit user hint for this behavior. Plain final textarea, global copy button and labels are Task 3. If selectioncopy requires UI integration, export the tested handler contract.

Tests fail first: identical, append/delete/replacement, Korean morphology, repeated anchors, CRLF normalized externally, ZWJ/combining grapheme, spaces/newlines, XSS text, all-changed and 10k/50k bounded cases, stale worker result ignored, reconstruction invariants. Commit owned files and report interface/performance evidence. Do not change backend or app wiring.

## Task 3: Shared web/app UX and option descriptions

Implement public/app.js,index.html,styles.css,transport.js integration and web/desktop UX tests using Task 1 contract and Task 2 component. No subagents. Four radio/option buttons with visible Korean label AND explanation of allowed changes; use health rewriteOptions metadata or shared bundled defaults. Options have selected state, accessible group/description, disabled while queued/running/importing. Persist web strength selection and desktop selectRewriteStrength. Engine switching preserves strength; selection alone never transforms. Result identifies strength actually used in that job. Direct typing/paste only: sourceFile/officeDocument excludes both feature controls; TXT/MD file requests get text-file and normal/omitted; legacy untouched.

Capture sourceSnapshot/inputKind/strength at click with existing LF normalization, set finalText on done only, never diff raw model patches. Default change view on success: inserted/replacement new text light yellow+underline, deleted old text pale red+red+strike at deletion location, equal uncolored; visible legend and switch to final textarea, same source/result height. Keyboard final-view switch focuses textarea for precise selection. New input/file/reset/failure/cancel clears diff and cancels pending comparison. Diff processing doesn't add model latency or block completed output. Restore/rollback exact source yields unchanged display. Copy/save uses pure finalText; web LAN no-Clipboard fallback uses temporary offscreen selectable textarea and restores focus/selection. Add test actual clipboard contents under HTTP fallback, partial diff selection contract from Task 2, display mode/XSS/accessibility/mobile and settings restored after restart. Keep existing stopwatch/IPC ordering fixes and document UI unchanged. Commit owned files, report red/green tests/full suites and any remaining integration gaps.

## Task 4: Live evaluation, release and review

Controller coordinates final cross-task review and live evaluation. Minimum 32 real runs: 2 CLI x 4 strengths x 2 synthetic classes (rewrite-dense, protected facts) x 2 repeats, fixed per-provider model/effort and alternating strength order. Record final gates/guards/retries, elapsed time, touched sentences and human syntax evaluation. Very strong target >=70% eligible sentences materially changed on suitable dense fixture; no quota imposed on user text and no gate relaxation to meet target. Refine if only trivial edits observed. Test final web, packaged desktop, document/legacy regression and portability; preserve private documents. New release version and signed portable artifact; update docs. Merge local finished feature into user working checkout only after review/tests (already authorized completion), no push unless requested. Final source must be available in main workspace; preserve untracked private documents.

## Task 5: Evidence-driven broad rewrite refinement (before final live evaluation)

Implementation follows concrete observed generation issues, not threshold changes. Worktree only, no subagents; backend files/tests only, no UI/version/releases. Read the existing Task1 report/API, plus observed examples in `runtime/test-tmp/strength-live/guided-full/report.json` and `diagnose/report.json` (synthetic texts only). Do not read the entire plan. TDD applies; commit and report.

Evidence: initial very-strong sparse replies touched only4/7 eligible sentences after generic retries. Experimental structural guidance+full-text response let Codex change7/7 eligible in one call. Claude first full-text candidate changed6 eligible sentences but also changed a protected generic sentence while claiming it was unchanged, so the whole chunk retried conservatively and lost good edits. Character change was <30%; do not relax 30/50 thresholds or accept other warning/fidelity failures.

Implement narrowly:
- For first-attempt very-strong only, choose existing schema's full rewrittenText response with edits=[], replacing conflicting sparse-only instructions. Retry retains existing conservative/adaptive output behavior; other strengths retain efficient compact protocol. Full-source and ordinary gates still validate the result.
- Add concise structural guidance for strong/very-strong first attempt: required concept words remain naturally positioned, not awkwardly appended; do not reduce existing phrases into newly forbidden clichés (e.g. important-role phrase). Abstract examples: `X는 Y에서 중요한 역할을 수행한다 → Y에서 X의 역할은 중요하다`; `X의 핵심은 Y하는 것이다 → Y하는 것이 X의 핵심이다`. Do not copy X/Y or introduce facts. Keep source-specific examples out of production; do not loosen concept matching or misclassify 핵심 just to meet a fixture target. Very strong should actually rewrite many eligible sentence structures, not merely inspect them. Preserve retry priority.
- Add safe deterministic restoration of recognized protected sentences for direct-text very-strong ONLY, analogous to existing modality restoration. Only restore when original/candidate line, paragraph and per-line sentence counts match exactly and corresponding unprotected sentence concepts and structural correspondence are valid. Replace each changed protected candidate sentence with the exact original using candidate offsets in reverse order. Revalidate the repaired complete candidate and ordinary gates; any unresolved structural/anchor/uncertain-restoration violation still follows existing one retry then rollback. This must never repair guessed alignments, permit moved/missing/extra sentence structure, or suppress skippedSentences. Keep legacy/file/normal/medium/strong behavior unchanged. Use this controlled literal repair to retain valid unprotected edits instead of discarding all work because the model touched one known protected sentence.
- Emit an explicit count/warning that protected sentences were restored, distinct from skipped restoration and whole-chunk rollback. Final diff uses final repaired result, so restored sentences appear unchanged. Count-only diagnostics; no raw text logs.
- Tests: capture current undesired whole-chunk retry after one protected change with otherwise valid broad edits; after fix protected original exact, valid surrounding structural edits kept, no extra CLI call. Tests for swapped protected facts (original restored), added/missing/moved structure or changed unprotected concept must still retry/rollback, skipped modality still retry/rollback, legacy/other strengths unchanged, both compact/full response paths and retry priority maintained. Verify real Python gate unchanged on repaired output. Existing model/effort must not change.
- Report scoped red/green plus full typecheck/Vitest once; native live quality evaluation belongs to controller after this commit. Any ambiguous cases preserve existing conservative path.

The interpretation above preserves the approved final-result fidelity contract: uncertain failures still retry; only exact, mechanically certain protected-sentence restoration occurs before acceptance checks. It expands the local restoration stage, not the permitted factual edit scope. This is a recorded implementation refinement driven by actual CLI evidence.
