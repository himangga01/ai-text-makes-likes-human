# 한국어 문장 다듬기

같은 와이파이에 연결된 PC에서 로그인 없이 사용하는 한국어 윤문 포털입니다. 원문을 직접 붙여넣거나 TXT·MD 파일을 불러온 뒤 **문장 변환하기** 버튼을 누르면, 서버 PC에 로그인된 Codex와 Humanize KR 규칙이 문체를 자연스럽게 다듬습니다.

사실·수치·고유명사·직접 인용을 보존하는 검증 절차가 포함되어 있지만, 중요한 문서는 최종 사용 전에 사람이 다시 확인하세요.

## 처음 한 번만 설정하기

서버로 사용할 Windows PC에 다음 프로그램이 필요합니다.

- Node.js 24.19 이상
- Python 3.11 이상
- Codex CLI 0.149 이상
- Codex CLI의 ChatGPT 로그인

변환 모델은 사용자 Codex 설정과 관계없이 `gpt-5.6-sol`, reasoning effort `high`로 고정됩니다.

Codex 로그인 확인:

```powershell
codex login status
```

프로젝트 폴더에서 `setup-portal.cmd`를 더블클릭하세요. 필요한 패키지를 설치하고 포털을 빌드합니다.

다른 PC에서도 접속하려면 `scripts\allow-lan-firewall.ps1`을 한 번만 관리자 권한으로 실행하세요.

1. 파일 탐색기에서 `scripts` 폴더 열기
2. `allow-lan-firewall.ps1`을 관리자 PowerShell에서 실행
3. Windows 네트워크 프로필이 **개인 네트워크**인지 확인

방화벽 허용은 TCP 3210 포트와 개인 네트워크에만 적용됩니다.

## 포털 시작하기

`start-portal.cmd`를 더블클릭하세요.

- 서버 PC 브라우저에서 `http://localhost:3210`이 자동으로 열립니다.
- 콘솔에 `http://192.168.x.x:3210` 형태의 와이파이 주소가 표시됩니다.
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

## 장문과 동시 사용자

- 고정 글자 수 제한은 없습니다.
- 긴 글은 문단·문장 경계로 자동 분할해 순서대로 처리합니다.
- 분량이 많을수록 완료까지 오래 걸립니다.
- 최대 3건을 동시에 접수합니다.
- Codex 변환은 한 번에 1건씩 실행하며 나머지는 대기 순서가 표시됩니다.
- 네 번째 요청은 앞선 작업이 끝난 뒤 다시 시도해야 합니다.

## 개인정보와 저장

- 포털 로그인과 사용자 계정이 없습니다.
- 데이터베이스와 변환 이력이 없습니다.
- 원문과 결과를 로그에 남기지 않습니다.
- Codex 호출은 ephemeral 모드로 실행합니다.
- 성공·실패·취소·브라우저 종료 후 임시 작업 폴더를 삭제합니다.
- 서버 PC의 Codex 계정 사용량과 쿼터가 사용됩니다.

같은 와이파이에 접속한 사람은 누구나 포털을 사용할 수 있으므로 신뢰할 수 있는 네트워크에서만 실행하세요.

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

TXT·MD를 UTF-8, UTF-8 BOM, UTF-16 BOM, CP949 중 하나로 다시 저장해 불러오세요. Word·PDF·한글 문서 파일은 지원하지 않습니다.

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

운영 점검과 복구 절차는 [docs/operations.md](docs/operations.md)를 참고하세요.
