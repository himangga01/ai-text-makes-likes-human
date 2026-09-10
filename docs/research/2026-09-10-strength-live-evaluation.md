# 직접 입력 강도 실제 CLI 평가

## 보완 전 32회 기준선

커밋 `33ce3da`, 합성 장문(846자·12문장·편집 가능9문장)과 보호 표본(5문장·편집 가능1문장), 두 CLI ×4단계×2표본×2회. Codex gpt-6-astra/low, Claude claude-sonnet-5/low, 직렬 실행. 기존 로그인 사용. 사용자 문서는 사용하지 않았다. 이 결과는 출시 품질 통과 기록이 아니라 후속 보완의 기준선이다.

32회 중31회 완료,1회 출력 편집 순서 오류. 완료31회 모두 인식된 보호 문장을 그대로 유지했다. 장문에서는 재시도 후 수정 범위가 좁아져 상위 단계의 품질 목표를 충족하지 못했다.

|실행|상태|시간(초)|CLI 호출|변경 가능 문장 중 변경|보호 문장 동일|
|---|---|---:|---:|---:|---|
|codex-normal-long-1|done|44.3|2|3/9|예|
|codex-normal-protected-1|done|6.0|1|1/1|예|
|claude-normal-long-1|error|25.3|1|—|—|
|claude-normal-protected-1|done|4.4|1|1/1|예|
|codex-medium-long-1|done|32.8|2|2/9|예|
|codex-medium-protected-1|done|6.3|1|1/1|예|
|claude-medium-long-1|done|24.6|2|0/9|예|
|claude-medium-protected-1|done|5.0|1|1/1|예|
|codex-strong-long-1|done|36.6|2|4/9|예|
|codex-strong-protected-1|done|6.7|1|1/1|예|
|claude-strong-long-1|done|47.7|2|1/9|예|
|claude-strong-protected-1|done|5.5|1|1/1|예|
|codex-very-strong-long-1|done|33.5|2|2/9|예|
|codex-very-strong-protected-1|done|8.0|1|1/1|예|
|claude-very-strong-long-1|done|56.1|2|1/9|예|
|claude-very-strong-protected-1|done|6.1|1|1/1|예|
|codex-very-strong-long-2|done|37.6|2|4/9|예|
|codex-very-strong-protected-2|done|8.4|1|1/1|예|
|claude-very-strong-long-2|done|35.5|2|1/9|예|
|claude-very-strong-protected-2|done|5.7|1|1/1|예|
|codex-strong-long-2|done|34.7|2|1/9|예|
|codex-strong-protected-2|done|9.0|1|1/1|예|
|claude-strong-long-2|done|60.9|2|2/9|예|
|claude-strong-protected-2|done|5.0|1|1/1|예|
|codex-medium-long-2|done|31.2|2|3/9|예|
|codex-medium-protected-2|done|6.4|1|1/1|예|
|claude-medium-long-2|done|22.9|2|0/9|예|
|claude-medium-protected-2|done|5.4|1|1/1|예|
|codex-normal-long-2|done|37.5|2|1/9|예|
|codex-normal-protected-2|done|15.8|1|1/1|예|
|claude-normal-long-2|done|22.9|2|0/9|예|
|claude-normal-protected-2|done|5.5|1|1/1|예|

### 직접 확인한 원인과 품질

완료 출력31개의 변경 문장을 원문과 대조했다. 보호 표본의 변경은 경쟁력 문장 재구성에 한정됐다. 장문의 최종 변경은 주로 관련된→관한, 과정에 있어서→과정에서, 작업을 진행하다 생략에 그쳤다. 광범위한 구문 재서술을 제공했다고 판단할 수 없다.

- Codex 매우 강하게 장문1회차 초안은 편집 가능9문장을 모두 바꿨지만 최종2문장만 남았다. 문자 변경률17.21%로30/50상한 문제가 아니었다. 표현했는지·구성했는지 등 명사 동사형과 기능적 과정 생략을 개념 검사에서 거절했다.
- Claude 매우 강하게 장문2회차는 직접 검증 실패0, 보호 문장3개 복원 뒤에도 문체 통계 P1 경고로 재시도해 최종1문장만 변경했다. 일반 재시도가 유효한 넓은 편집을 함께 폐기하는 문제가 별도로 확인됐다.
- Claude 보통 장문1회차 오류는 유일하고 겹치지 않는 편집3개를 원문 순서와 다르게 반환해서 발생했다. 모호한 앵커가 아니라 순서 문제였다.

후속 보완은 정확한 어미 검사, 문맥 제한 과정 처리, 직접 입력의 편집 순서 정규화, P1 단독 경고에서 검증된 초안을 참고하는 실제 보수적 재시도로 제한한다. 사실·문장 구조·보호 문장 검사 및30/50임계값은 유지한다. 자동 검사는 완전한 의미 동등성 보증이 아니다.

원본 측정값과 각 출력은 로컬 `runtime/test-tmp/strength-live/release-33ce3da/`에 보존한다. 후속 검증 결과를 아래에 추가한다.
