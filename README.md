# 한국어 문장 다듬기

PC에 설치·로그인된 **Claude Code 또는 Codex CLI**와 Humanize KR 규칙으로 한국어 문체를 다듬습니다. Windows portable 앱, Claude·Codex 윤문 스킬, 기존 LAN 웹 포털을 제공합니다.

- **Windows 앱:** `release/HumanizeKR-0.5.0-win-x64-self-signed.exe`를 실행하고 Claude Code·Codex 중 사용할 엔진을 선택합니다. 앱에 Electron과 Python이 포함되어 있어 앱용 Node.js·Python 설치나 포털 실행이 필요하지 않습니다.
- **Claude·Codex 스킬:** `release/`의 호스트별 ZIP 또는 설치 도우미로 `humanize-kr`를 추가합니다. `/humanize-kr` 또는 `$humanize-kr`로 현재 세션에서 윤문합니다.
- **LAN 포털:** 아래의 Windows 서버 설정과 `start-portal.cmd`를 사용합니다.
- **MCP 서버:** Claude Code·Codex 같은 MCP 클라이언트가 포털을 도구(`humanize_text`·`humanize_file`·`humanize_status`)로 부릅니다. 등록과 사용법은 [MCP 서버로 쓰기](#mcp-서버로-쓰기)에 있습니다.

앱 실행·스킬 설치·개발 빌드 안내는 [docs/desktop.md](docs/desktop.md)에 있습니다. EXE와 ZIP은 빌드 산출물이므로 Git 소스 이력에 포함하지 않습니다.

현재 소스의 구조와 제약은 [코드 분석](docs/code-analysis.md), 사용 흐름과 운영 범위는 [서비스 분석](docs/service-analysis.md)에 정리했습니다(2026-10-03 검토 작업 트리 기준). 소스·운영 서버·EXE·설치된 스킬은 갱신 시점이 다를 수 있으므로 버전명만으로 같은 코드라고 판단하지 않습니다. 0.5.0의 EXE와 스킬 ZIP은 Windows PC에서 빌드합니다([재빌드 계획](docs/plans/2026-10-10-windows-skill-zip-rebuild.md)). 변경 내역은 [0.5.0 릴리스 노트](docs/releases/0.5.0.md)에 있습니다.

직접 입력하거나 붙여넣은 텍스트와 TXT·MD 파일은 **보통·중간·강하게·매우 강하게·매우 강하게(다시쓰기)** 중 변환 강도를 선택합니다. 각 버튼에서 편집 범위 설명을 볼 수 있습니다. 완료 후 추가·변경된 문구는 연노랑, 삭제된 문구는 빨강 취소선으로 표시하며 **최종문**으로 전환해 정리된 결과를 확인할 수 있습니다. 복사·저장은 삭제 표시를 제외한 최종 문구만 사용합니다. 변경 표시는 직접 입력에만 적용합니다. TXT·MD 파일은 고른 강도로 다듬고 결과에 사용한 강도를 표시합니다. DOCX·PPTX는 서식을 지키기 위해 강도 선택 없이 보통으로 다듬습니다.

높은 강도에서도 숫자·인용·조건 등 보호 대상과 핵심 내용을 우선합니다. 검증 결과에 따라 수정 범위가 줄거나 원문으로 돌아갈 수 있으며, 강도가 변경량이나 처리 시간을 보장하지는 않습니다.

사실·수치·고유명사·직접 인용을 보존하는 검증 절차가 포함되어 있지만, 중요한 문서는 최종 사용 전에 사람이 다시 확인하세요.

문장을 고치는 일은 모델이 하고, 무엇을 고칠지 정하고 고친 결과를 문장마다 검사하는 일은 이 프로젝트가 직접 만든 **[슈퍼세종엔진](#슈퍼세종엔진)**이 맡습니다. 현재 기본 엔진은 기존 오픈소스 윤문 엔진이며, 슈퍼세종엔진은 설정 하나로 켤 수 있습니다.

## 슈퍼세종엔진

슈퍼세종엔진은 오픈소스 윤문 엔진(`vendor/humanize-engine`)을 대체하려고 이 프로젝트가 직접 만든 한국어 윤문 엔진입니다. 글을 고치는 일은 지금처럼 Claude Code·Codex 모델이 맡고, 엔진은 고칠 문장을 골라 요청하고 돌아온 결과를 문장마다 검사합니다.

### 원칙

- **문장마다 원래 말투를 지킵니다.** 종결 어미(합쇼체·해요체·해체 등), 높임 '-시-', 겸양 표현(드리다·뵙다), 문장 유형(질문·요청·청유), 화자 표현(저·저희), ㅋㅋ·^^·~ 같은 표기를 지킵니다. 글 전체를 한 말투로 맞추지 않습니다.
- **구어 표기는 기본으로 둡니다.** '할께', '가 보려구요' 같은 표기는 그대로 두고 `SUPER_SEJONG_FIX_COLLOQUIAL=1`일 때만 고칩니다. '되요→돼요', '뵈요→봬요', '몇일→며칠', '할수 있다→할 수 있다' 같은 확실한 맞춤법·띄어쓰기 오류는 모델을 부르지 않고 엔진이 바로 고칩니다(Office 문서는 서식 보존을 위해 엔진이 직접 고치지 않고 모델에게 필수 수정으로 요청합니다).
- **뜻을 바꾸지 않습니다.** 부정·가능·당위·조건, 시간 순서(전·후), 행위자와 대상, 숫자·날짜·요일, 인용문·이름, 행동 요청(CTA)의 강도·기한·연락 수단, 시간·대상·비용 같은 핵심 낱말이 바뀐 수정은 받아들이지 않습니다.
- **어색한 한국어를 고칩니다.** 번역투(…이 가능하다, …이 이루어지다, …을 가지고 있다, …중에 있다, …에 대해서 안내드립니다), 이중 피동(되어지다), 중복 표현(같이 동행, 미리 예약), 국립국어원 교정 유형 27가지를 기준으로 요청합니다.

### 처리 흐름

1. **진단**: 문장마다 고칠 곳과 지켜야 할 것(숫자·인용 같은 보호 구간, 말투)을 찾습니다.
2. **계획**: 고칠 문장만 모델에 요청합니다. 고칠 곳이 없으면 모델을 호출하지 않습니다. 강도 '중간' 이상에서는 모델이 어색한 문장을 몇 개 직접 골라 고치는 열린 검토가 더해집니다.
3. **최소 수정**: 모델은 요청받은 문장만 문장 단위로 고쳐 돌려줍니다.
4. **복구**: 확실한 맞춤법 수정, 지켜야 할 표기와 말투, 조사, 원문의 쉼표를 되살립니다.
5. **문장별 검사**: 보존(숫자·인용·이름·요일), 의미, 말투, CTA, 흐름, 맞춤법을 문장마다 확인합니다. 명료성(문장 길이 등)은 기본으로 기록만 하고 막지 않습니다.
6. **문장별 결정**: 통과한 문장은 채택합니다. 걸린 문장은 이유를 알려 한 번 더 요청하고, 그래도 걸리면 **그 문장만** 원래 문장으로 되돌립니다. 글 전체를 되돌리는 경우는 숫자·인용 같은 보존 검사가 끝내 실패할 때뿐입니다.

### 검증 기록 (2026-10-05)

| 비교 | 기존 엔진 | 슈퍼세종엔진 |
|---|---|---|
| 고쳐야 하는 문장 통과 (직접 만든 32쌍) | 30 | 32 |
| 망가뜨린 문장 차단 (직접 만든 36쌍) | 18 | 36 |
| 실제 모델(Codex) 시험 5편 중 고친 글 | 2 (3편은 통째로 되돌림) | 5 (모두 말투 유지) |
| 시드 평가 세트에 심어 둔 오류 92개 중 고친 수 (가짜 작성자) | — | 91 |

시험 문장은 직접 만든 짧은 글이고 실제 모델 시험은 5편뿐입니다. 실제 글에서 맞는 수정을 얼마나 잘못 막는지는 운영 서버의 기록 모드로 확인하고 있습니다. 기존 엔진 수치는 Python 검사만 잰 것이며, 서비스에는 말투 잠금이 따로 있습니다.

### 사용 상태와 설정

기본 엔진은 아직 **기존 엔진**(오픈소스 윤문 엔진 + 슈퍼세종 v1 검사)입니다. 운영 서버는 기존 엔진으로 결과를 만들면서 슈퍼세종엔진의 판정을 함께 기록합니다(기록 모드).

| 환경 변수 | 값 | 의미 |
|---|---|---|
| `SUPER_SEJONG_ENGINE` | `legacy`(기본) · `v2` | 결과를 만드는 엔진. 포털 서버는 `v2`로 바꾸고 재시작하면 직접 입력·파일·Office 모두 슈퍼세종엔진으로 처리하고, 값을 지우고 재시작하면 기존 엔진으로 돌아갑니다. 스킬 경로는 서버가 아니라 Claude·Codex 호스트 세션의 환경 변수를 따르며, 한 작업 안에서는 값을 바꾸면 안 됩니다. |
| `SUPER_SEJONG_V2_SHADOW` | `0`(기본) · `1` | 기존 엔진 작업 옆에서 슈퍼세종엔진 판정을 숫자로만 기록합니다(`diagnostics.v2ShadowCounts`). 결과물과 모델 호출 수는 바뀌지 않으며 Office 문서는 기록하지 않습니다. |
| `SUPER_SEJONG_MODE` | `enforce`(기본) · `shadow` · `off` | 검사 적용 방식. 기존 엔진에서는 v1 의미 검사, 슈퍼세종엔진에서는 검사 묶음의 기본값입니다. |
| `SUPER_SEJONG_FIX_COLLOQUIAL` | `0`(기본) · `1` | 구어 표기('할께' 등)도 고칠지 정합니다. |
| `SUPER_SEJONG_OPEN_REVIEW` | `medium`(기본) · `strong` · `always` · `off` | 모델이 어색한 문장을 직접 골라 고치는 열린 검토를 어떤 강도부터 쓸지 정합니다. |
| `SUPER_SEJONG_DETERMINISTIC_FIX` | `all`(기본) · `edited-only` · `off` | 확실한 맞춤법 수정을 모든 문장에 할지, 모델이 고친 문장에만 할지, 하지 않을지 정합니다. |
| `SUPER_SEJONG_GENRE_DEFAULT` | `general`(기본) · `blog` · `essay` · `report` · `notice` · `document` | 장르별 진단 규칙을 고릅니다. 스킬 경로는 따로 지정하지 않으면 `blog`를 씁니다. |

운영 서버에 값을 넣는 방법과 watchdog 주의 사항은 [운영 문서](docs/operations.md#슈퍼세종엔진-모드)에 있습니다. 기록 모드 결과는 `python3 scripts/sejong-shadow-report.py`로 정리합니다.

### 기존 엔진의 v1 검사

기존 엔진에서도 슈퍼세종 v1 검사가 돌아갑니다. 부정·가능성·당위·참여자 역할·수량과 단위 변화를 검사하고, 윤문 과정에서 "~해야 한다"·"~로 판단된다" 같은 당위·유보 표현이 사라진 문장은 원문으로 되돌리며, 윤문이 새로 넣은 연결어미 뒤 쉼표를 지웁니다. 되돌린 문장이 있으면 결과 화면에 안내가 표시됩니다.

### 더 보기

- 설계 문서: [docs/research/super-sejong/v2/DESIGN.md](docs/research/super-sejong/v2/DESIGN.md)
- v1 연구 종합: [docs/research/super-sejong/RESEARCH-SYNTHESIS.md](docs/research/super-sejong/RESEARCH-SYNTHESIS.md)
- 코드: `engine_runtime/sejong/`(진단·검사·결정, Python), `engine_runtime/sejong_cli.py`(CLI), `src/engine/sejong/`(서버 연결, TypeScript)

규칙은 뜻이 같음이나 문장의 자연스러움을 보증하지 않습니다. 중요한 문서는 최종 사용 전에 사람이 다시 확인하세요.

## Claude·Codex 스킬 사용하기

`humanize-kr`는 현재 로그인한 **Claude Code 또는 Codex 세션**에서 한국어 문장을 다듬는 스킬입니다. 사용할 호스트 하나만 준비하면 됩니다. 같은 와이파이에 연결하거나 웹 포털·Windows 앱을 실행할 필요가 없습니다. Windows용 스킬 ZIP에는 검증에 필요한 Python·Node가 포함되어 있습니다.

### 설치 또는 업데이트

아래는 두 호스트용 `0.5.0` 스킬 ZIP의 설치·업데이트 안내입니다. 프로젝트 루트에서 사용할 호스트의 명령을 실행합니다. 해당 ZIP이 `release/`에 있어야 하며, ZIP은 Git 소스에 포함되지 않습니다. 실제 설치본에 반영된 수정은 배포물과 설치 기록을 기준으로 확인합니다.

```powershell
# Claude Code
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\install-humanize-skill.ps1 -HostName Claude -Scope User -Archive .\release\humanize-kr-claude-0.5.0-win-x64.zip -Replace

# Codex
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\install-humanize-skill.ps1 -HostName Codex -Scope User -Archive .\release\humanize-kr-codex-0.5.0-win-x64.zip -Replace
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
| 매우 강하게(다시쓰기) | 뜻은 유지하고 글 전체를 가장 크게 다시 씁니다. 기본 엔진에서는 매우 강하게와 같이 처리하고, 슈퍼세종엔진 v2(`SUPER_SEJONG_ENGINE=v2`)에서는 문단마다 크게 다시 쓰되 말투를 그 문단에서 가장 많이 쓴 말투로 맞추고 숫자·인용·이름·뜻·행동 요청은 그대로 둡니다. |

강도를 생략하면 **보통**으로 처리합니다. 비교가 필요하면 예시처럼 **변경 비교 HTML도 만들어 달라**고 요청하세요. 검증된 최종 텍스트 파일과 비교 HTML을 받을 수 있습니다. HTML은 브라우저에서 바로 열리며, 추가·변경은 연노랑, 삭제는 빨강 취소선으로 표시됩니다. **최종문 보기·복사**에는 삭제 표시를 제외한 최종 문구만 들어갑니다.

### 파일 다듬기

TXT·MD·DOCX·PPTX는 파일 경로를 지정해 요청합니다. 예를 들어 Claude Code에서는 다음과 같이 입력하고, Codex에서는 앞부분을 `$humanize-kr`로 바꿉니다.

```text
/humanize-kr "C:\문서\보고서.docx"를 다듬고 원본과 다른 새 파일로 저장해 줘.
```

**TXT·MD 파일도 강도를 요청할 수 있습니다**(예: "보고서.md를 강하게 다듬어 줘"). 같은 강도의 직접 입력과 같은 범위·보호 규칙으로 처리합니다. HTML 변경 비교는 직접 입력에만, DOCX·PPTX는 강도 선택 없이 보통으로 처리합니다. Word·PowerPoint는 서식과 구조를 보존하며 같은 형식의 새 파일로 저장합니다. 원본은 덮어쓰지 않습니다. 숫자·인용·조건 등 보호 대상과 검증 결과에 따라 일부 문장은 유지되거나 복원될 수 있으므로 결과와 안내를 함께 확인하세요.

일반 윤문에는 `humanize-kr`를 사용합니다. `update-humanize-engine`은 오픈소스 엔진 갱신을 위한 개발용 관리 스킬입니다. 자세한 설치 안내는 [Windows 앱·스킬 안내](docs/desktop.md), 처리 절차는 [스킬 설명](skills/humanize-kr/SKILL.md)을 참고하세요. 두 스킬의 설치·호출·Gateway 명령·문제 해결을 정리한 영문 가이드는 [Skills Usage Guide](docs/skills-guide.md)에 있습니다.

## MCP 서버로 쓰기

Claude Code·Codex처럼 MCP를 지원하는 에이전트는 포털을 도구로 바로 부를 수 있습니다. 도구 호출 하나가 포털 작업 하나라서 웹 화면과 같은 대기열·모델·보존 검사를 거친 결과만 돌려줍니다. 추가로 설치할 패키지는 없습니다.

### 준비

1. **포털을 띄웁니다.** 이 Mac에서는 Hermes 서비스가 `http://127.0.0.1:7882`로 띄워 둡니다. Windows에서는 아래 [LAN 웹 포털](#lan-웹-포털-처음-한-번만-설정하기) 설정을 마친 뒤 `start-portal.cmd`로 띄웁니다. 주소는 같습니다.
2. **MCP 서버를 빌드합니다.** 저장소에서 빌드를 한 번 실행해 `dist/mcp/server.js`를 만듭니다. 기존 Windows 포털은 `dist\server.js`가 있으면 다시 빌드하지 않으므로, 최신 코드를 받은 뒤에는 직접 빌드해야 합니다.
   - Mac: `npm run build`
   - Windows(PowerShell): `npm.cmd run build`
3. **Node 24가 필요합니다.** Mac에서는 Hermes의 Node(`~/.hermes/node/bin/node`)를 그대로 씁니다. Windows에서는 포털용으로 설치한 Node.js(`node`)를 씁니다. 위치는 `where.exe node`로 확인합니다(보통 `C:\Program Files\nodejs\node.exe`).

### 등록하기

한 번만 등록하면 됩니다. 아래 Windows 예시의 저장소 경로 `C:\work\ai-text-makes-likes-human`은 예시이므로 실제로 받은 위치로 바꿉니다.

**Claude Code** — `-s user`를 붙이면 모든 프로젝트에서, 빼면 지금 프로젝트에서만 쓸 수 있습니다.

Mac:

```bash
claude mcp add -s user humanize-kr -- ~/.hermes/node/bin/node /Users/wisdom/wisdom_project/gpt/ai-text-makes-likes-human/dist/mcp/server.js
claude mcp list        # humanize-kr가 Connected로 나오면 준비 완료
```

Windows(PowerShell):

```powershell
claude mcp add -s user humanize-kr -- node C:\work\ai-text-makes-likes-human\dist\mcp\server.js
claude mcp list        # humanize-kr가 Connected로 나오면 준비 완료
```

세션 안에서는 `/mcp`로 연결 상태를 볼 수 있습니다.

**Codex** — 설정 파일에 아래 표를 넣습니다. Codex는 도구 호출을 기본 60초에 끊기 때문에 `tool_timeout_sec`를 넉넉하게 잡아야 합니다. 윤문은 대기열을 포함해 몇 분에서 수십 분 걸릴 수 있으므로 1시간(3600초)을 권장합니다. `codex mcp add` 명령으로는 이 값을 넣을 수 없으니 파일을 직접 고칩니다.

Mac(`~/.codex/config.toml`):

```toml
[mcp_servers.humanize-kr]
command = "/Users/wisdom/.hermes/node/bin/node"
args = ["/Users/wisdom/wisdom_project/gpt/ai-text-makes-likes-human/dist/mcp/server.js"]
tool_timeout_sec = 3600
```

Windows(`%USERPROFILE%\.codex\config.toml`). 작은따옴표로 감싸면 TOML이 역슬래시를 그대로 둡니다.

```toml
[mcp_servers.humanize-kr]
command = 'C:\Program Files\nodejs\node.exe'
args = ['C:\work\ai-text-makes-likes-human\dist\mcp\server.js']
tool_timeout_sec = 3600
```

`codex mcp list`에 `humanize-kr`가 보이면 등록된 것입니다.

**그 밖의 MCP 클라이언트** — stdio 방식으로 명령 `node`, 인자 `<저장소 경로>/dist/mcp/server.js`를 등록합니다.

**등록 확인** — 등록한 뒤 다음을 실행해 상태가 `ready`로 나오면 됩니다. Mac·Windows 모두 같은 명령입니다.

```bash
claude -p "humanize_status를 한 번 호출하고 상태를 알려 줘." --allowedTools mcp__humanize-kr__humanize_status
```

Mac에서 설정을 바꾸지 않고 먼저 시험해 보려면 다음을 실행합니다.

```bash
echo "humanize_status를 한 번 호출하고 상태를 알려 줘." | claude -p --strict-mcp-config \
  --mcp-config '{"mcpServers":{"humanize-kr":{"command":"node","args":["<저장소 경로>/dist/mcp/server.js"]}}}' \
  --allowedTools mcp__humanize-kr__humanize_status
```

### 도구

| 도구 | 하는 일 | 인자 |
|---|---|---|
| `humanize_text` | 글을 다듬어 검증된 결과와 짧은 보고(강도·구간 수·시간·안내)를 돌려줍니다. | `text`(필수, 최대 100,000자), `strength`, `engine`, `model`, `effort` |
| `humanize_file` | TXT·MD·DOCX·PPTX를 다듬어 새 파일로 저장하고 저장 위치를 알려 줍니다. | `path`(필수, 절대 경로), `outputPath`, `strength`, `engine`, `model`, `effort` |
| `humanize_status` | 포털 상태, 강도 설명, 모델 목록과 기본값, 입력 한도, 대기 작업 수를 알려 줍니다. | 없음 |

- `strength`: `normal`(보통, 기본값), `medium`(중간), `strong`(강하게), `very-strong`(매우 강하게), `rewrite`(매우 강하게·다시쓰기). 직접 입력한 글과 TXT·MD 파일에 적용되며, DOCX·PPTX에 강도를 주면 오류로 돌려보냅니다.
- `engine`: `codex`(기본값) 또는 `claude`. `model`·`effort`를 생략하면 포털 기본값을 씁니다. 쓸 수 있는 값은 `humanize_status`가 알려 줍니다.

### 사용 예

등록한 뒤에는 에이전트에게 평소처럼 말하면 됩니다. 에이전트가 알맞은 도구를 골라 부릅니다.

```text
humanize-kr로 다음 글을 중간 강도로 다듬어 줘: 본 보고서는 시장 동향에 대한 분석을 수행한다.
/Users/wisdom/문서/보고서.md를 강하게 다듬어 줘.
C:\문서\발표.pptx를 다듬어 줘.
윤문 포털 상태 알려 줘.
```

파일 경로는 MCP 서버가 도는 PC 기준의 절대 경로입니다(Mac은 `/Users/...`, Windows는 `C:\...`).

### 파일 저장 규칙

- 결과는 원본 옆에 `<이름>-humanized.<확장자>`로 저장합니다. 같은 이름이 있으면 `-humanized-2`, `-humanized-3`…으로 번호를 붙입니다. 원본과 기존 파일은 덮어쓰지 않습니다.
- `outputPath`로 저장 위치를 정할 수 있습니다. 절대 경로여야 하고 원본과 확장자가 같으며 아직 없는 파일이어야 합니다.
- TXT·MD는 웹 화면과 같은 방식(UTF-8, BOM 있는 UTF-16, CP949)으로 읽어 UTF-8로 저장하며 최대 1 MiB입니다. DOCX·PPTX는 최대 50 MiB이며 서식을 지킨 같은 형식의 파일로 저장합니다.

### 다른 PC에서 쓰기

같은 LAN의 다른 PC에서도 쓸 수 있습니다. 그 PC에 이 저장소를 받아 빌드한 뒤 포털 주소를 `HUMANIZE_PORTAL_URL`로 넘깁니다. 파일은 MCP 서버가 도는 PC에서 읽고 저장합니다.

```bash
# Mac
claude mcp add -s user humanize-kr -e HUMANIZE_PORTAL_URL=http://192.168.0.10:7882 -- node <저장소 경로>/dist/mcp/server.js
```

```powershell
# Windows(PowerShell)
claude mcp add -s user humanize-kr -e HUMANIZE_PORTAL_URL=http://192.168.0.10:7882 -- node C:\work\ai-text-makes-likes-human\dist\mcp\server.js
```

Codex는 `[mcp_servers.humanize-kr]` 표에 `env = { HUMANIZE_PORTAL_URL = "http://192.168.0.10:7882" }`를 더합니다. 포털은 사설망 접속만 받고 로그인이 없으므로 MCP 서버도 포털 PC나 같은 LAN에서만 씁니다.

### 시간 제한과 문제 해결

MCP 서버 자체에는 시간 제한이 없고, 포털이 한 구간을 10분 넘게 처리하면 작업을 `ENGINE_TIMEOUT`으로 끝냅니다. 그래서 클라이언트 쪽 제한을 넉넉하게 잡아도 호출이 끝없이 걸려 있지 않습니다.

| 증상 | 원인과 해결 |
|---|---|
| `PORTAL_UNREACHABLE` | 포털이 꺼져 있거나 `HUMANIZE_PORTAL_URL`이 틀렸습니다. Mac은 `node dist/ops/hermes-service.js status`로 확인합니다. Windows는 `start-portal.cmd` 창이 열려 있는지, 브라우저에서 `http://localhost:7882`가 열리는지 확인합니다. |
| 1분쯤 지나 클라이언트가 포기함 | 클라이언트의 도구 시간 제한이 짧습니다. Codex는 `tool_timeout_sec`를 늘립니다. Claude Code는 `MCP_TOOL_TIMEOUT`(밀리초)을 늘려 시작합니다. Mac은 `MCP_TOOL_TIMEOUT=3600000 claude`, Windows PowerShell은 `$env:MCP_TOOL_TIMEOUT='3600000'; claude`입니다. |
| `QUEUE_FULL` | 포털이 이미 작업 3건을 받았습니다. 잠시 뒤 다시 시도합니다. |
| `INVALID_MODEL_SETTINGS` | 제공하지 않는 모델이나 추론 수준입니다. `humanize_status`로 목록을 확인합니다. |
| "DOCX·PPTX는 … 보통으로만" | Office 파일에 강도를 줬습니다. `strength`를 빼고 다시 요청합니다. |

영문 상세 안내는 [MCP Server Guide](docs/mcp.md)에 있습니다.

## LAN 웹 포털: 처음 한 번만 설정하기

서버로 사용할 Windows PC에 다음 프로그램이 필요합니다.

- Node.js 24.19 이상
- Python 3.11 이상
- Codex CLI 0.149 이상
- Codex CLI의 ChatGPT 로그인

변환 엔진은 화면에서 GPT와 Claude 중 선택할 수 있습니다.

서버 런타임은 Python과 Humanize 엔진이 준비되고 두 CLI 중 하나가 설치·로그인돼 있으면 동작합니다. 다만 위 Windows 설정 도우미 `setup-portal.cmd`는 현재 Codex 설치·로그인을 필수로 확인합니다. Claude만 사용할 때의 런타임 조건과 이 설정 도우미의 조건은 다릅니다.

- **GPT** (기본): 기본값은 `gpt-6.1-sol`, reasoning effort `high`이며 연결 설정에서 모델과 추론 수준을 선택할 수 있습니다.
- **Claude**: 기본값은 `claude-opus-5-5`, effort `xhigh`이며 연결 설정에서 변경할 수 있습니다. 서버 PC에 Claude CLI 설치와 로그인이 필요합니다.

추가 지원 모델: GPT-6.1 Sol (`gpt-6.1-sol`, `low`~`ultra`), GPT-6 Sol (`gpt-6-sol`, `low`~`ultra`), GPT-6 Luna (`gpt-6-luna`, `low`~`max`), Claude Opus 5.5 (`claude-opus-5-5`, `low`~`max`), Claude Sonnet 5.5 (`claude-sonnet-5-5`, `low`~`max`), Claude Haiku 5.5 (`claude-haiku-5-5`, `low`~`max`). 웹·데스크톱 앱의 연결 설정에서 선택할 수 있습니다. Claude Opus 5.5는 Claude Code 2.1.280 이상, Claude Sonnet 5.5는 2.1.284 이상, Claude Haiku 5.5는 2.1.293 이상이 필요하며, 실제 모델 이용 가능 여부는 로그인한 계정의 권한에 따릅니다. GPT-5.2는 ChatGPT 계정으로 로그인한 Codex에서 더 이상 지원되지 않고, GPT-5.5는 2026년 10월 14일 지원 종료 예정이라 목록에서 제외했습니다. 모델 정보는 [OpenAI 공식 문서](https://learn.chatgpt.com/docs/models)와 [Claude Code 공식 문서](https://code.claude.com/docs/en/model-config)를 참고하세요.

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

파일에서 불러온 TXT·MD 내용을 직접 수정하면 파일 정보가 해제되고 다음 작업은 직접 입력으로 처리됩니다. 고른 강도는 그대로 쓰며, 변경 비교와 다운로드 방식이 달라집니다.

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

위 측정은 당시 `gpt-5.6-sol` + `high` 설정의 기록입니다. 현재 GPT 엔진 기본값은 `gpt-6.1-sol` + `high`이므로 동일 조건의 성능 기록으로 간주하지 않습니다. 추가 벤치마크는 현재 모델 설정으로 12회 변환하는 데 필요한 시간과 쿼터를 명시적으로 승인받은 경우에만 실행합니다.

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

운영 점검과 복구 절차는 [docs/operations.md](docs/operations.md)를 참고하세요. 2026-10-04 시점의 개발 인수인계 기록은 [Codex 인수인계 문서](docs/HANDOFF-2026-10-04.md)에 있습니다.

## 릴리스 기록

0.3.1에서는 웹·Windows 앱의 연결 설정에서 모델과 추론 레벨을 선택할 수 있습니다. CLI 상태 아이콘, 같은 높이의 원문·결과 필드, 전체 진행률 옆 경과 시간을 추가했습니다. [0.3.1 변경 내용](docs/releases/0.3.1.md)

0.3.0부터 웹·Windows 앱·Claude/Codex 스킬에서 Word와 PowerPoint 문서를 윤문하고 같은 형식의 새 파일로 저장합니다. 서식·표·도형 구조를 보존하며, 처리하지 않는 객체와 원문 복원 구간을 고지합니다. [사용법과 지원 범위](docs/documents.md) · [릴리스 기록](docs/releases/0.3.0.md)
