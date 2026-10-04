# 한국어 문장 다듬기

PC에 설치·로그인된 **Claude Code 또는 Codex CLI**와 Humanize KR 규칙으로 한국어 문체를 다듬습니다. Windows portable 앱, Claude·Codex 윤문 스킬, 기존 LAN 웹 포털을 제공합니다.

- **Windows 앱:** `release/HumanizeKR-0.4.0-win-x64-self-signed.exe`를 실행하고 Claude Code·Codex 중 사용할 엔진을 선택합니다. 앱에 Electron과 Python이 포함되어 있어 앱용 Node.js·Python 설치나 포털 실행이 필요하지 않습니다.
- **Claude·Codex 스킬:** `release/`의 호스트별 ZIP 또는 설치 도우미로 `humanize-kr`를 추가합니다. `/humanize-kr` 또는 `$humanize-kr`로 현재 세션에서 윤문합니다.
- **LAN 포털:** 아래의 Windows 서버 설정과 `start-portal.cmd`를 사용합니다.

앱 실행·스킬 설치·개발 빌드 안내는 [docs/desktop.md](docs/desktop.md)에 있습니다. EXE와 ZIP은 빌드 산출물이므로 Git 소스 이력에 포함하지 않습니다.

현재 소스의 구조와 제약은 [코드 분석](docs/code-analysis.md), 사용 흐름과 운영 범위는 [서비스 분석](docs/service-analysis.md)에 정리했습니다(2026-10-03 검토 작업 트리 기준). 소스·운영 서버·EXE·설치된 스킬은 갱신 시점이 다를 수 있으므로 `0.4.0` 버전명만으로 같은 코드라고 판단하지 않습니다.

직접 입력하거나 붙여넣은 텍스트는 **보통·중간·강하게·매우 강하게** 중 변환 강도를 선택합니다. 각 버튼에서 편집 범위 설명을 볼 수 있습니다. 완료 후 추가·변경된 문구는 연노랑, 삭제된 문구는 빨강 취소선으로 표시하며 **최종문**으로 전환해 정리된 결과를 확인할 수 있습니다. 복사·저장은 삭제 표시를 제외한 최종 문구만 사용합니다. TXT·MD·DOCX·PPTX 파일 입력에는 이 강도·변경 표시 기능을 적용하지 않습니다.

높은 강도에서도 숫자·인용·조건 등 보호 대상과 핵심 내용을 우선합니다. 검증 결과에 따라 수정 범위가 줄거나 원문으로 돌아갈 수 있으며, 강도가 변경량이나 처리 시간을 보장하지는 않습니다.

사실·수치·고유명사·직접 인용을 보존하는 검증 절차가 포함되어 있지만, 중요한 문서는 최종 사용 전에 사람이 다시 확인하세요.

**슈퍼세종엔진 시제품**은 일부 한국어 부정·가능성·당위·참여자 역할·수사와 단위 변화를 추가로 검사하고, 원문의 위치를 짚어 문체 점검 후보를 모델에 전달합니다. 규칙으로 뜻의 동일성이나 자연스러움을 보증하지는 않습니다. 구현 범위와 14개 연구 축, 남은 평가 과제는 [연구 종합 문서](docs/research/super-sejong/RESEARCH-SYNTHESIS.md)에 정리했습니다.

다른 개발 환경에서 이 미커밋 작업을 이어받을 때는 [Codex 인수인계 문서](docs/HANDOFF-2026-10-04.md)를 먼저 확인하세요. 두 차례 리뷰, 20개 블로그 글 실측, 파일별 구현 위치, 검증 시점과 이전되지 않는 임시 자료를 함께 정리했습니다.

검증 게이트 직전에 결정적 후처리 두 단계가 실행됩니다. 윤문 과정에서 "~해야 한다"·"~로 판단된다" 같은 당위·유보 표현이 사라진 문장은 원문 문장으로 되돌리고, 윤문이 새로 쓴 문장에 끼어든 연결어미 뒤 쉼표는 제거합니다. 되돌린 문장이 있으면 결과 화면에 안내가 표시됩니다.

## Claude·Codex 스킬 사용하기

`humanize-kr`는 현재 로그인한 **Claude Code 또는 Codex 세션**에서 한국어 문장을 다듬는 스킬입니다. 사용할 호스트 하나만 준비하면 됩니다. 같은 와이파이에 연결하거나 웹 포털·Windows 앱을 실행할 필요가 없습니다. Windows용 스킬 ZIP에는 검증에 필요한 Python·Node가 포함되어 있습니다.

### 설치 또는 업데이트

아래는 두 호스트용 `0.4.0` 스킬 ZIP의 설치·업데이트 안내입니다. 프로젝트 루트에서 사용할 호스트의 명령을 실행합니다. 해당 ZIP이 `release/`에 있어야 하며, ZIP은 Git 소스에 포함되지 않습니다. 실제 설치본에 반영된 수정은 배포물과 설치 기록을 기준으로 확인합니다.

```powershell
# Claude Code
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\install-humanize-skill.ps1 -HostName Claude -Scope User -Archive .\release\humanize-kr-claude-0.4.0-win-x64.zip -Replace

# Codex
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\install-humanize-skill.ps1 -HostName Codex -Scope User -Archive .\release\humanize-kr-codex-0.4.0-win-x64.zip -Replace
```

`-Replace`는 기존 스킬을 백업한 뒤 갱신합니다. Claude는 `%USERPROFILE%\.claude\skills\humanize-kr`, Codex는 `%USERPROFILE%\.agents\skills\humanize-kr`에 설치됩니다. 스킬이 목록에 바로 보이지 않으면 새 세션을 시작하세요.

### 텍스트 다듬기와 변경 비교

아래 예시를 **각 호스트의 대화 입력란**에 입력합니다. PowerShell 명령이 아닙니다.

Claude Code:

```text
/humanize-kr 아래 글을 매우 강하게 다듬고, 변경 비교 HTML도 만들어 줘.

담당자는 자료의 정리 작업을 수행한다. 이 방안은 강한 경쟁력을 가지고 있다.
```

Codex:

```text
$humanize-kr 아래 글을 매우 강하게 다듬고, 변경 비교 HTML도 만들어 줘.

담당자는 자료의 정리 작업을 수행한다. 이 방안은 강한 경쟁력을 가지고 있다.
```

| 요청할 강도 | 편집 범위 |
|---|---|
| 보통 · 기본값 | 원래 표현을 살려 어색한 부분을 다듬습니다. |
| 중간 | 어휘와 길어진 표현을 더 자연스럽게 정리합니다. |
| 강하게 | 문장 구조와 반복 표현까지 적극적으로 바꿉니다. |
| 매우 강하게 | 뜻은 유지하고 글 전반의 표현과 문장 구성을 크게 바꿉니다. |

강도를 생략하면 **보통**으로 처리합니다. 비교가 필요하면 예시처럼 **변경 비교 HTML도 만들어 달라**고 요청하세요. 검증된 최종 텍스트 파일과 비교 HTML을 받을 수 있습니다. HTML은 브라우저에서 바로 열리며, 추가·변경은 연노랑, 삭제는 빨강 취소선으로 표시됩니다. **최종문 보기·복사**에는 삭제 표시를 제외한 최종 문구만 들어갑니다.

### 파일 다듬기

TXT·MD·DOCX·PPTX는 파일 경로를 지정해 요청합니다. 예를 들어 Claude Code에서는 다음과 같이 입력하고, Codex에서는 앞부분을 `$humanize-kr`로 바꿉니다.

```text
/humanize-kr "C:\문서\보고서.docx"를 다듬고 원본과 다른 새 파일로 저장해 줘.
```

**파일 입력에는 강도 선택과 HTML 변경 비교를 적용하지 않습니다.** Word·PowerPoint는 서식과 구조를 보존하며 같은 형식의 새 파일로 저장합니다. 원본은 덮어쓰지 않습니다. 숫자·인용·조건 등 보호 대상과 검증 결과에 따라 일부 문장은 유지되거나 복원될 수 있으므로 결과와 안내를 함께 확인하세요.

일반 윤문에는 `humanize-kr`를 사용합니다. `update-humanize-engine`은 오픈소스 엔진 갱신을 위한 개발용 관리 스킬입니다. 자세한 설치 안내는 [Windows 앱·스킬 안내](docs/desktop.md), 처리 절차는 [스킬 설명](skills/humanize-kr/SKILL.md)을 참고하세요. 두 스킬의 설치·호출·Gateway 명령·문제 해결을 정리한 영문 가이드는 [Skills Usage Guide](docs/skills-guide.md)에 있습니다.

## LAN 웹 포털: 처음 한 번만 설정하기

서버로 사용할 Windows PC에 다음 프로그램이 필요합니다.

- Node.js 24.19 이상
- Python 3.11 이상
- Codex CLI 0.149 이상
- Codex CLI의 ChatGPT 로그인

변환 엔진은 화면에서 GPT와 Claude 중 선택할 수 있습니다.

서버 런타임은 Python과 Humanize 엔진이 준비되고 두 CLI 중 하나가 설치·로그인돼 있으면 동작합니다. 다만 위 Windows 설정 도우미 `setup-portal.cmd`는 현재 Codex 설치·로그인을 필수로 확인합니다. Claude만 사용할 때의 런타임 조건과 이 설정 도우미의 조건은 다릅니다.

- **GPT** (기본): 기본값은 `gpt-5.6-sol`, reasoning effort `medium`이며 연결 설정에서 모델과 추론 수준을 선택할 수 있습니다.
- **Claude**: 기본값은 `claude-fable-5-1`, effort `high`이며 연결 설정에서 변경할 수 있습니다. 서버 PC에 Claude CLI 설치와 로그인이 필요합니다.

추가 지원 모델: GPT-6 Sol (`gpt-6-sol`, `low`~`ultra`), GPT-6 Luna (`gpt-6-luna`, `low`~`max`), Claude Opus 5.5 (`claude-opus-5-5`, `low`~`max`), Claude Sonnet 5.5 (`claude-sonnet-5-5`, `low`~`max`). 웹·데스크톱 앱의 연결 설정에서 선택할 수 있습니다. Claude Opus 5.5는 Claude Code 2.1.280 이상, Claude Sonnet 5.5는 2.1.284 이상이 필요하며, 실제 모델 이용 가능 여부는 로그인한 계정의 권한에 따릅니다. GPT-5.2는 ChatGPT 계정으로 로그인한 Codex에서 더 이상 지원되지 않고, GPT-5.5는 2026년 10월 14일 지원 종료 예정이라 목록에서 제외했습니다. 모델 정보는 [OpenAI 공식 문서](https://learn.chatgpt.com/docs/models)와 [Claude Code 공식 문서](https://code.claude.com/docs/en/model-config)를 참고하세요.

Codex 로그인 확인:

```powershell
codex login status
```

프로젝트 폴더에서 `setup-portal.cmd`를 더블클릭하세요. 필요한 패키지를 설치하고 포털을 빌드합니다.

다른 PC에서도 접속하려면 `scripts\allow-lan-firewall.ps1`을 한 번만 관리자 권한으로 실행하세요.

1. 파일 탐색기에서 `scripts` 폴더 열기
2. `allow-lan-firewall.ps1`을 관리자 PowerShell에서 실행
3. Windows 네트워크 프로필이 **개인 네트워크**인지 확인

방화벽 허용은 TCP 7882 포트와 개인 네트워크에만 적용됩니다.

## 포털 시작하기

`start-portal.cmd`를 더블클릭하세요.

- 서버 PC 브라우저에서 `http://localhost:7882`이 자동으로 열립니다.
- 콘솔에 `http://192.168.x.x:7882` 형태의 와이파이 주소가 표시됩니다.
- 같은 와이파이의 다른 PC는 이 주소를 브라우저에 입력합니다.
- 서버 콘솔을 닫거나 `Ctrl+C`를 누르면 포털이 종료됩니다.

서버가 실행되는 동안 콘솔 창을 닫지 마세요.

## 사용하는 방법

### 직접 붙여넣기

1. 왼쪽 **원본 문구 입력**에 글을 붙여넣습니다.
2. **문장 변환하기**를 누릅니다.
3. 대기·처리 상태를 확인합니다.
4. 오른쪽 결과가 나오면 **복사**를 누릅니다.

입력하거나 붙여넣는 것만으로는 변환이 시작되지 않습니다. 반드시 버튼을 눌러야 합니다.

### TXT·MD 파일 불러오기

1. **TXT·MD 불러오기**를 누릅니다.
2. 파일명, 인코딩, 내용을 확인합니다.
3. **문장 변환하기**를 누릅니다.
4. MD 파일로 시작한 작업은 완료 후 **MD 다운로드**로 결과를 저장할 수 있습니다.

지원 인코딩:

- UTF-8 및 UTF-8 BOM
- BOM이 포함된 UTF-16LE·UTF-16BE
- Windows 한글 TXT에 흔한 CP949·EUC-KR 계열

TXT·MD 선택만으로 파일이 서버에 전송되지 않습니다. 파일은 브라우저에서 먼저 열리고, 변환 버튼을 눌렀을 때만 텍스트가 서버로 전달됩니다. MD 결과 파일명은 `<원본파일명>-humanized.md`입니다.

### DOCX·PPTX 불러오기

DOCX·PPTX를 선택하면 파일을 서버에 올려 구조와 위치별 텍스트를 확인합니다. 이 미리보기는 실제 페이지·슬라이드 렌더링이 아니며, 모델 윤문은 **문장 변환하기**를 눌러야 시작됩니다. 완료 후 입력과 같은 형식의 새 파일을 다운로드합니다. 지원 객체와 보존 범위는 [문서 안내](docs/documents.md)를 참고하세요.

파일에서 불러온 TXT·MD 내용을 직접 수정하면 파일 정보가 해제되고 다음 작업은 직접 입력으로 처리됩니다. 이에 따라 강도·변경 비교와 다운로드 방식이 달라집니다.

## 장문과 동시 사용자

- 웹·앱의 직접 입력과 TXT·MD 파일은 줄바꿈을 LF로 통일한 뒤 Unicode code point 기준 100,000자 이하만 변환합니다. TXT·MD 파일은 1 MiB를 넘으면 열지 않습니다. 더 긴 글은 나눠서 변환해 주세요. DOCX·PPTX는 파일 50 MiB, 추출 텍스트 100,000자 이하입니다. 호스트 세션의 스킬 TXT·MD 처리에는 웹·앱의 두 입력 제한을 적용하지 않습니다.
- 줄바꿈은 서버 수신 단계에서 LF로 통일됩니다. Windows CRLF 파일을 불러와도 변환 결과는 LF 줄바꿈입니다.
- 포털의 텍스트 자동 라우팅은 기본으로 켜집니다. 15,000자 이하이면서 진단 결과가 `light` 또는 `standard`인 문서는 본문을 하나의 처리 구간으로 준비합니다. 선택한 CLI로 처리하며 검증 결과에 따라 한 번 더 호출할 수 있습니다.
- `heavy` 진단 문서, 15,000자 초과 문서, 단일 처리 여부를 안전하게 판정할 수 없는 문서는 문단·문장 경계로 자동 분할합니다.
- 분량이 많을수록 완료까지 오래 걸립니다.
- 최대 3건을 동시에 접수합니다.
- 변환 작업은 한 번에 1건만 실행하며 나머지는 대기 순서가 표시됩니다.
- 분할된 청크의 Codex 실행은 기본적으로 한 번에 1개입니다. 검증되지 않은 실험 옵션 `CODEX_CHUNK_CONCURRENCY=2`를 명시한 경우에만 한 작업 안에서 최대 2개를 병렬 처리합니다.
- 네 번째 요청은 앞선 작업이 끝난 뒤 다시 시도해야 합니다.
- Office 파일은 변환 큐와 별도로 준비·완료 상태를 포함해 최대 3개를 보관합니다. 결과를 다시 받기 위한 보관 시간은 마지막 사용 후 30분이며, 이전 문서를 닫으면 보관 자리를 해제합니다.

## 개인정보와 저장

- 포털 로그인과 사용자 계정이 없습니다.
- 데이터베이스와 변환 이력이 없습니다.
- 원문과 결과를 로그에 남기지 않습니다.
- 처리 중에는 원문·중간 결과·최종 결과를 로컬 임시 파일로 사용합니다. 일반 텍스트 작업은 성공·실패·취소·연결 종료 후 정리합니다.
- DOCX·PPTX의 준비된 입력과 완료 결과는 마지막 사용 후 30분까지 보관합니다. 활성 작업·다운로드 중에는 정리를 미루며 초기화·취소·실패·서버 종료 시 관련 작업을 정리합니다.
- Codex 호출은 ephemeral 모드, Claude 호출은 CLI 세션 저장을 끈 상태로 실행합니다. 스킬의 호스트 대화 기록은 호스트 설정에 따릅니다.
- 원문은 선택한 모델 제공자에게 전달되며, 웹 포털에서는 서버 PC의 해당 계정 사용량과 쿼터를 사용합니다. 로컬 임시 파일 정리가 제공자의 원격 보관 정책까지 보장하지는 않습니다.

포털은 사용자 로그인 대신 접속 소켓의 사설·로컬 주소, 요청 Host, 브라우저 Origin을 확인합니다. 접속 주소에는 `localhost` 또는 사설망 IP 주소를 직접 사용해야 하며 mDNS·기타 DNS 호스트 이름은 허용하지 않습니다. 이는 같은 와이파이 여부나 사용자를 식별하는 인증이 아니므로 신뢰할 수 있는 네트워크에서 사용합니다.

## 자주 발생하는 문제

### 변환 엔진을 사용할 수 없다고 나옵니다

서버 콘솔에서 다음을 확인하세요.

```powershell
python --version
codex --version
codex login status
```

Codex 로그인이 풀렸다면 `codex login`을 실행한 뒤 포털을 다시 시작하세요.

### 다른 PC에서 접속할 수 없습니다

- 두 PC가 같은 와이파이에 연결됐는지 확인합니다.
- 서버 PC의 네트워크 프로필을 **개인**으로 설정합니다.
- 관리자 PowerShell에서 `scripts\allow-lan-firewall.ps1`을 실행합니다.
- 서버 콘솔에 표시된 최신 와이파이 주소를 사용합니다. 공유기 재연결 후 IP가 바뀔 수 있습니다.

### TXT·MD 파일의 한글이 깨집니다

TXT·MD를 UTF-8, UTF-8 BOM, UTF-16 BOM, CP949 중 하나로 다시 저장해 불러오세요. BOM이 없는 UTF-16은 지원하지 않습니다. Word·PowerPoint는 DOCX·PPTX로 불러올 수 있으며, 구형 DOC·PPT와 PDF·HWP는 지원하지 않습니다.

### 현재 3건이 처리 중이라고 나옵니다

작업 한 건이 완료되거나 취소된 뒤 다시 시도하세요.

### 변환 시간이 초과됐습니다

일시적인 Codex 지연일 수 있습니다. 다시 시도하거나 매우 긴 글을 몇 부분으로 나눠 처리하세요.

## 방화벽 허용 제거

포털을 더 이상 LAN에 공개하지 않으려면 관리자 PowerShell에서 실행하세요.

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\remove-lan-firewall.ps1
```

## 개발 및 검증

```powershell
npm.cmd ci
npm.cmd run typecheck
npm.cmd test
npm.cmd run build
npm.cmd run test:e2e
```

실제 Codex를 호출하는 선택적 검증:

```powershell
npm.cmd run test:live
```

### 선택적 성능 벤치마크

성능 벤치마크는 짧은 문서의 기존·자동 라우팅과 긴 문서의 직렬·2개 병렬 처리를 각각 3회 측정해 총 12회의 변환을 실행합니다. 서버 PC에 로그인된 Codex 사용량과 쿼터를 소비하므로 활성 포털 작업이 없는 유지보수 시간에만 실행하세요. 벤치마크는 원문·결과문이나 해당 파일 경로를 출력하지 않고, 소스·결과 아티팩트를 남기지 않으며 메타데이터 측정값만 콘솔에 보고합니다.

2026-08-24의 수정된 픽스처 측정에서 3,872자 짧은 문서는 기존 경로 p50 262.215초, 자동 라우팅 p50 106.083초로 40.456481%를 기록했습니다. 승인 기준인 40% 이하를 넘어서 통과하지 못했습니다. 17,344자 긴 문서는 직렬 3회차 도중 사용자가 남은 측정을 취소해 직렬·병렬 p50과 70% 기준을 평가하지 못했습니다. 따라서 청크 동시성 기본값은 `1`이며 `2`는 검증되지 않은 선택적 실험값입니다. 이 결과를 임계값 완화나 기본값 승격의 근거로 사용하지 않습니다.

```powershell
$env:CODEX_CHUNK_CONCURRENCY='1'
npm.cmd run test:performance
Remove-Item Env:CODEX_CHUNK_CONCURRENCY
```

위 측정은 당시 `gpt-5.6-sol` + `high` 설정의 기록입니다. 현재 GPT 엔진과 벤치마크는 `medium`을 사용하므로 동일 조건의 성능 기록으로 간주하지 않습니다. 추가 벤치마크는 현재 모델 설정으로 12회 변환하는 데 필요한 시간과 쿼터를 명시적으로 승인받은 경우에만 실행합니다.

운영 기본값과 명시적 롤백은 모두 직렬 처리입니다.

```powershell
$env:CODEX_CHUNK_CONCURRENCY='1'
npm.cmd start
```

긴 문서 병렬 처리를 별도로 실험할 때만 다음처럼 `2`를 지정합니다. 안정성 또는 품질 문제가 있으면 서버를 종료한 뒤 위의 `1`로 되돌립니다.

```powershell
$env:CODEX_CHUNK_CONCURRENCY='2'
npm.cmd start
```

운영 점검과 복구 절차는 [docs/operations.md](docs/operations.md)를 참고하세요.

## DOCX · PPTX 지원 (0.3.0)

0.3.1에서는 웹·Windows 앱의 연결 설정에서 모델과 추론 레벨을 선택할 수 있습니다. CLI 상태 아이콘, 같은 높이의 원문·결과 필드, 전체 진행률 옆 경과 시간을 추가했습니다. [0.3.1 변경 내용](docs/releases/0.3.1.md)

웹·Windows 앱·Claude/Codex 스킬에서 Word와 PowerPoint 문서를 윤문하고 같은 형식의 새 파일로 저장합니다. 서식·표·도형 구조를 보존하며, 처리하지 않는 객체와 원문 복원 구간을 고지합니다. [사용법과 지원 범위](docs/documents.md) · [릴리스 기록](docs/releases/0.3.0.md)
