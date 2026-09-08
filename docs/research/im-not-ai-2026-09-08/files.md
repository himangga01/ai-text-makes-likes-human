# 전체 파일 및 규칙 인벤토리

기준: 9747f036cdc28a1a8aea4dc71fef1f7846eb96f7

원본 119개 추적 파일의 역할을 빠짐없이 나열했다. 실행 함수별 위치·docstring·import·해시는 [inventory.json](inventory.json)에 있다.

| 파일 | 줄 수 | 역할 |
|---|---:|---|
| [.claude-plugin/marketplace.json](https://github.com/epoko77-ai/im-not-ai/blob/9747f036cdc28a1a8aea4dc71fef1f7846eb96f7/.claude-plugin/marketplace.json) | 20 | Claude 마켓플레이스 등록 메타데이터 |
| [.claude-plugin/plugin.json](https://github.com/epoko77-ai/im-not-ai/blob/9747f036cdc28a1a8aea4dc71fef1f7846eb96f7/.claude-plugin/plugin.json) | 19 | Claude 플러그인 매니페스트, 버전 2.3.2 |
| [.github/workflows/test.yml](https://github.com/epoko77-ai/im-not-ai/blob/9747f036cdc28a1a8aea4dc71fef1f7846eb96f7/.github/workflows/test.yml) | 28 | Ubuntu Python 3.11/3.12 CI, pytest·생성물·Bash 검사 |
| [.gitignore](https://github.com/epoko77-ai/im-not-ai/blob/9747f036cdc28a1a8aea4dc71fef1f7846eb96f7/.gitignore) | 27 | 작업 데이터·캐시 등을 Git 추적에서 제외 |
| [CLAUDE.md](https://github.com/epoko77-ai/im-not-ai/blob/9747f036cdc28a1a8aea4dc71fef1f7846eb96f7/CLAUDE.md) | 205 | 저장소 개발/운영 가이드와 파이프라인 설명 |
| [CONTRIBUTORS.md](https://github.com/epoko77-ai/im-not-ai/blob/9747f036cdc28a1a8aea4dc71fef1f7846eb96f7/CONTRIBUTORS.md) | 371 | 기여자와 변경 계보; runtime 없음 |
| [GEMINI.md](https://github.com/epoko77-ai/im-not-ai/blob/9747f036cdc28a1a8aea4dc71fef1f7846eb96f7/GEMINI.md) | 179 | Gemini 단일 호출용 내장 규칙; 독립적인 구형 정책 포함 |
| [INSTALL.md](https://github.com/epoko77-ai/im-not-ai/blob/9747f036cdc28a1a8aea4dc71fef1f7846eb96f7/INSTALL.md) | 178 | 호스트별 설치·업데이트 안내, 일부 Claude 경로 표기 불일치 |
| [LICENSE](https://github.com/epoko77-ai/im-not-ai/blob/9747f036cdc28a1a8aea4dc71fef1f7846eb96f7/LICENSE) | 21 | MIT 원문 고지 |
| [README.en.md](https://github.com/epoko77-ai/im-not-ai/blob/9747f036cdc28a1a8aea4dc71fef1f7846eb96f7/README.en.md) | 111 | 영문 소개·설치·아키텍처 |
| [README.md](https://github.com/epoko77-ai/im-not-ai/blob/9747f036cdc28a1a8aea4dc71fef1f7846eb96f7/README.md) | 729 | 사용법·전체 아키텍처·과거 릴리스 설명 |
| [RELEASING.md](https://github.com/epoko77-ai/im-not-ai/blob/9747f036cdc28a1a8aea4dc71fef1f7846eb96f7/RELEASING.md) | 67 | 릴리스·버전·생성물 검사 절차와 Gemini 별도 트랙 |
| [agents/humanize-diagnostician.md](https://github.com/epoko77-ai/im-not-ai/blob/9747f036cdc28a1a8aea4dc71fef1f7846eb96f7/agents/humanize-diagnostician.md) | 80 | 런타임: 문서 전체 지배 패턴 3~6개 진단 |
| [agents/humanize-finalizer.md](https://github.com/epoko77-ai/im-not-ai/blob/9747f036cdc28a1a8aea4dc71fef1f7846eb96f7/agents/humanize-finalizer.md) | 90 | 런타임: 원문과 결과 대조, 국소 보정·accept/corrected/hold |
| [agents/humanize-monolith.md](https://github.com/epoko77-ai/im-not-ai/blob/9747f036cdc28a1a8aea4dc71fef1f7846eb96f7/agents/humanize-monolith.md) | 150 | 런타임: 원문+quick 규칙으로 탐지·윤문·자체검증 |
| [agents/korean-ai-tell-taxonomist.md](https://github.com/epoko77-ai/im-not-ai/blob/9747f036cdc28a1a8aea4dc71fef1f7846eb96f7/agents/korean-ai-tell-taxonomist.md) | 66 | 유지보수: 신규 패턴 검토와 분류표 관리 |
| [agents/korean-translation-scholar.md](https://github.com/epoko77-ai/im-not-ai/blob/9747f036cdc28a1a8aea4dc71fef1f7846eb96f7/agents/korean-translation-scholar.md) | 118 | 개발 보조: 번역학 연구와 이론 종합 |
| [agents/post-editese-metric-engineer.md](https://github.com/epoko77-ai/im-not-ai/blob/9747f036cdc28a1a8aea4dc71fef1f7846eb96f7/agents/post-editese-metric-engineer.md) | 138 | 개발 보조: 지표·baseline 구현 지시 |
| [agents/quick-rules-integrator.md](https://github.com/epoko77-ai/im-not-ai/blob/9747f036cdc28a1a8aea4dc71fef1f7846eb96f7/agents/quick-rules-integrator.md) | 136 | 개발 보조: 연구 결과의 quick/런타임 반영과 회귀 점검 |
| [agents/taxonomy-gap-analyzer.md](https://github.com/epoko77-ai/im-not-ai/blob/9747f036cdc28a1a8aea4dc71fef1f7846eb96f7/agents/taxonomy-gap-analyzer.md) | 86 | 개발 보조: 연구와 현재 분류표의 중복·공백 대조 |
| [agents/translationese-research-distiller.md](https://github.com/epoko77-ai/im-not-ai/blob/9747f036cdc28a1a8aea4dc71fef1f7846eb96f7/agents/translationese-research-distiller.md) | 84 | 개발 보조: 외부 연구 보고서를 구조화된 근거로 압축 |
| [assets/social-preview-v1.png](https://github.com/epoko77-ai/im-not-ai/blob/9747f036cdc28a1a8aea4dc71fef1f7846eb96f7/assets/social-preview-v1.png) | 이미지 | 홍보 이미지 1280×640; runtime 미사용 |
| [assets/social-preview-v2.0.png](https://github.com/epoko77-ai/im-not-ai/blob/9747f036cdc28a1a8aea4dc71fef1f7846eb96f7/assets/social-preview-v2.0.png) | 이미지 | 홍보 이미지 1280×640; runtime 미사용 |
| [assets/social-preview.png](https://github.com/epoko77-ai/im-not-ai/blob/9747f036cdc28a1a8aea4dc71fef1f7846eb96f7/assets/social-preview.png) | 이미지 | 홍보 이미지 1280×640; runtime 미사용 |
| [codex/skills/humanize-korean/SKILL.md](https://github.com/epoko77-ai/im-not-ai/blob/9747f036cdc28a1a8aea4dc71fef1f7846eb96f7/codex/skills/humanize-korean/SKILL.md) | 45 | Codex/Copilot 단일 호출 편집·자가검증 스킬 |
| [codex/skills/humanize-korean/references](https://github.com/epoko77-ai/im-not-ai/blob/9747f036cdc28a1a8aea4dc71fef1f7846eb96f7/codex/skills/humanize-korean/references) | 1 | Git 심볼릭 링크; 현재 Windows checkout에서는 42바이트 일반 파일 |
| [commands/humanize-korean.toml](https://github.com/epoko77-ai/im-not-ai/blob/9747f036cdc28a1a8aea4dc71fef1f7846eb96f7/commands/humanize-korean.toml) | 17 | Gemini 커스텀 명령: GEMINI.md 규칙에 사용자 인자 전달 |
| [commands/humanize-redo.toml](https://github.com/epoko77-ai/im-not-ai/blob/9747f036cdc28a1a8aea4dc71fef1f7846eb96f7/commands/humanize-redo.toml) | 19 | Gemini 커스텀 명령: GEMINI.md 규칙에 사용자 인자 전달 |
| [commands/humanize.toml](https://github.com/epoko77-ai/im-not-ai/blob/9747f036cdc28a1a8aea4dc71fef1f7846eb96f7/commands/humanize.toml) | 18 | Gemini 커스텀 명령: GEMINI.md 규칙에 사용자 인자 전달 |
| [docs/en/evidence.md](https://github.com/epoko77-ai/im-not-ai/blob/9747f036cdc28a1a8aea4dc71fef1f7846eb96f7/docs/en/evidence.md) | 81 | 영문 실증 문서, 한국어 문서를 권위본으로 안내 |
| [docs/en/integration.md](https://github.com/epoko77-ai/im-not-ai/blob/9747f036cdc28a1a8aea4dc71fef1f7846eb96f7/docs/en/integration.md) | 78 | 제품·모델 통합 단계 설명; 일부 공식/규칙 설명은 현재 코드와 상이 |
| [docs/en/quick-rules.en.md](https://github.com/epoko77-ai/im-not-ai/blob/9747f036cdc28a1a8aea4dc71fef1f7846eb96f7/docs/en/quick-rules.en.md) | 116 | 수동 영문 규칙 요약, 현재 한글 생성물과 별개 |
| [docs/en/taxonomy.md](https://github.com/epoko77-ai/im-not-ai/blob/9747f036cdc28a1a8aea4dc71fef1f7846eb96f7/docs/en/taxonomy.md) | 214 | 수동 영문 분류표, 과거 패턴 범위 중심 |
| [docs/watermark-baseline-runbook.md](https://github.com/epoko77-ai/im-not-ai/blob/9747f036cdc28a1a8aea4dc71fef1f7846eb96f7/docs/watermark-baseline-runbook.md) | 92 | 반복 계측 운영 절차·교란 요인; 워터마크 제거 구현 아님 |
| [gemini-extension.json](https://github.com/epoko77-ai/im-not-ai/blob/9747f036cdc28a1a8aea4dc71fef1f7846eb96f7/gemini-extension.json) | 5 | Gemini 확장 이름과 별도 버전 1.5.0 |
| [install.sh](https://github.com/epoko77-ai/im-not-ai/blob/9747f036cdc28a1a8aea4dc71fef1f7846eb96f7/install.sh) | 212 | CLI 감지, 링크/복사 설치, 충돌 백업, 소유 링크 정리 |
| [plugin.json](https://github.com/epoko77-ai/im-not-ai/blob/9747f036cdc28a1a8aea4dc71fef1f7846eb96f7/plugin.json) | 13 | Copilot 플러그인: Codex skills 디렉터리 노출 |
| [scripts/build_calibration.py](https://github.com/epoko77-ai/im-not-ai/blob/9747f036cdc28a1a8aea4dc71fef1f7846eb96f7/scripts/build_calibration.py) | 187 | 외부 사람/AI 코퍼스에서 패턴 밀도와 모델별 비교 통계 산출 |
| [scripts/build_diagnosis_rules.py](https://github.com/epoko77-ai/im-not-ai/blob/9747f036cdc28a1a8aea4dc71fef1f7846eb96f7/scripts/build_diagnosis_rules.py) | 261 | 공유 파서로 진단용 인덱스 생성 및 drift 검사 |
| [scripts/build_quick_rules.py](https://github.com/epoko77-ai/im-not-ai/blob/9747f036cdc28a1a8aea4dc71fef1f7846eb96f7/scripts/build_quick_rules.py) | 212 | taxonomy 메타에서 윤문용 규칙 생성 및 drift 검사 |
| [scripts/build_social_preview_v2.py](https://github.com/epoko77-ai/im-not-ai/blob/9747f036cdc28a1a8aea4dc71fef1f7846eb96f7/scripts/build_social_preview_v2.py) | 180 | Pillow 기반 1280×640 홍보 이미지 제작, macOS 폰트 경로 |
| [scripts/build_social_preview_v2_3.py](https://github.com/epoko77-ai/im-not-ai/blob/9747f036cdc28a1a8aea4dc71fef1f7846eb96f7/scripts/build_social_preview_v2_3.py) | 127 | v2.3 홍보 이미지 제작, 출력 파일은 social-preview.png |
| [scripts/checks.py](https://github.com/epoko77-ai/im-not-ai/blob/9747f036cdc28a1a8aea4dc71fef1f7846eb96f7/scripts/checks.py) | 477 | 격식·상투구·헤딩·각주·발화 인용·숫자 주입 검사 |
| [scripts/console.py](https://github.com/epoko77-ai/im-not-ai/blob/9747f036cdc28a1a8aea4dc71fef1f7846eb96f7/scripts/console.py) | 58 | Windows UTF-8 출력, 게이트 예외를 exit 3으로 매핑 |
| [scripts/corruption_engine.py](https://github.com/epoko77-ai/im-not-ai/blob/9747f036cdc28a1a8aea4dc71fef1f7846eb96f7/scripts/corruption_engine.py) | 321 | 13개 역주입기로 정상/오염 학습쌍 생성; 모델 학습은 없음 |
| [scripts/eval_baseline.py](https://github.com/epoko77-ai/im-not-ai/blob/9747f036cdc28a1a8aea4dc71fef1f7846eb96f7/scripts/eval_baseline.py) | 291 | Claude fixture 반복 호출 및 품질 스냅샷 기록 |
| [scripts/eval_compare.py](https://github.com/epoko77-ai/im-not-ai/blob/9747f036cdc28a1a8aea4dc71fef1f7846eb96f7/scripts/eval_compare.py) | 194 | 스냅샷 평균 변화와 pooled 표준편차 비교 |
| [scripts/make_thumbnail.py](https://github.com/epoko77-ai/im-not-ai/blob/9747f036cdc28a1a8aea4dc71fef1f7846eb96f7/scripts/make_thumbnail.py) | 158 | 초기 홍보 이미지 제작, top-level 실행 시 파일 출력 |
| [scripts/prepare_monolith_input.py](https://github.com/epoko77-ai/im-not-ai/blob/9747f036cdc28a1a8aea4dc71fef1f7846eb96f7/scripts/prepare_monolith_input.py) | 973 | 입력 정규화, 지표 결합, route_hint, 청킹 manifest 생성 |
| [scripts/reassemble_chunks.py](https://github.com/epoko77-ai/im-not-ai/blob/9747f036cdc28a1a8aea4dc71fef1f7846eb96f7/scripts/reassemble_chunks.py) | 177 | 원문 SHA와 청크 범위 대조, passthrough와 경계 공백 복원, 길이비 보고 |
| [scripts/restore_modality.py](https://github.com/epoko77-ai/im-not-ai/blob/9747f036cdc28a1a8aea4dc71fef1f7846eb96f7/scripts/restore_modality.py) | 288 | 문장 정렬 후 당위·추측이 소실된 문장 국소 복원 |
| [scripts/sanitize_text.py](https://github.com/epoko77-ai/im-not-ai/blob/9747f036cdc28a1a8aea4dc71fef1f7846eb96f7/scripts/sanitize_text.py) | 296 | NFC, 비가시 문자, 공백·줄바꿈 정리 |
| [scripts/strip_injected_commas.py](https://github.com/epoko77-ai/im-not-ai/blob/9747f036cdc28a1a8aea4dc71fef1f7846eb96f7/scripts/strip_injected_commas.py) | 126 | 새 문장 또는 --all의 연결어미 쉼표 제거 |
| [scripts/verify_change_rate.py](https://github.com/epoko77-ai/im-not-ai/blob/9747f036cdc28a1a8aea4dc71fef1f7846eb96f7/scripts/verify_change_rate.py) | 109 | 문자 변경률 단축 게이트, exit 0/1/2/3 |
| [scripts/verify_gates.py](https://github.com/epoko77-ai/im-not-ai/blob/9747f036cdc28a1a8aea4dc71fef1f7846eb96f7/scripts/verify_gates.py) | 410 | P0~P5 통합 게이트 및 문장 터치율 보고 |
| [skills/humanize-korean/SKILL.md](https://github.com/epoko77-ai/im-not-ai/blob/9747f036cdc28a1a8aea4dc71fef1f7846eb96f7/skills/humanize-korean/SKILL.md) | 331 | Claude용 light/standard/heavy 오케스트레이터 지시 |
| [skills/humanize-korean/references/ai-tell-taxonomy.md](https://github.com/epoko77-ai/im-not-ai/blob/9747f036cdc28a1a8aea4dc71fef1f7846eb96f7/skills/humanize-korean/references/ai-tell-taxonomy.md) | 931 | 원본 분류표; 85개 패턴 헤딩, J-1은 헤딩 깊이 오류로 생성 누락 |
| [skills/humanize-korean/references/baseline.json](https://github.com/epoko77-ai/im-not-ai/blob/9747f036cdc28a1a8aea4dc71fef1f7846eb96f7/skills/humanize-korean/references/baseline.json) | 326 | v1 장르별 사람/AI 평균과 어휘 사전 |
| [skills/humanize-korean/references/baseline_v2.json](https://github.com/epoko77-ai/im-not-ai/blob/9747f036cdc28a1a8aea4dc71fef1f7846eb96f7/skills/humanize-korean/references/baseline_v2.json) | 118 | 5장르 × 14개 placeholder mean/stdev |
| [skills/humanize-korean/references/design-notes.md](https://github.com/epoko77-ai/im-not-ai/blob/9747f036cdc28a1a8aea4dc71fef1f7846eb96f7/skills/humanize-korean/references/design-notes.md) | 55 | 과거 실행 구조, 콜 수·청킹 비용 설계 근거 |
| [skills/humanize-korean/references/diagnosis-rules.md](https://github.com/epoko77-ai/im-not-ai/blob/9747f036cdc28a1a8aea4dc71fef1f7846eb96f7/skills/humanize-korean/references/diagnosis-rules.md) | 206 | 자동 생성 진단 인덱스 84개, 표시된 71개 문구는 오래됨 |
| [skills/humanize-korean/references/empirical-validation.md](https://github.com/epoko77-ai/im-not-ai/blob/9747f036cdc28a1a8aea4dc71fef1f7846eb96f7/skills/humanize-korean/references/empirical-validation.md) | 157 | 자체 코퍼스 통계·규칙 기각·모델/과업 교란 기록 |
| [skills/humanize-korean/references/metrics.py](https://github.com/epoko77-ai/im-not-ai/blob/9747f036cdc28a1a8aea4dc71fef1f7846eb96f7/skills/humanize-korean/references/metrics.py) | 415 | v1 8개 지표·baseline·proxy z·위험도 |
| [skills/humanize-korean/references/metrics_v2.py](https://github.com/epoko77-ai/im-not-ai/blob/9747f036cdc28a1a8aea4dc71fef1f7846eb96f7/skills/humanize-korean/references/metrics_v2.py) | 824 | v1 상속, 14개 추가 지표·대구 카운트·간섭 합성·변경률 |
| [skills/humanize-korean/references/quick-rules.footer.md](https://github.com/epoko77-ai/im-not-ai/blob/9747f036cdc28a1a8aea4dc71fef1f7846eb96f7/skills/humanize-korean/references/quick-rules.footer.md) | 20 | 생성물 자체검증·자가 등급 지침 |
| [skills/humanize-korean/references/quick-rules.header.md](https://github.com/epoko77-ai/im-not-ai/blob/9747f036cdc28a1a8aea4dc71fef1f7846eb96f7/skills/humanize-korean/references/quick-rules.header.md) | 17 | 생성물 공통 제약: 내용 앵커·서법·인용 보존 |
| [skills/humanize-korean/references/quick-rules.md](https://github.com/epoko77-ai/im-not-ai/blob/9747f036cdc28a1a8aea4dc71fef1f7846eb96f7/skills/humanize-korean/references/quick-rules.md) | 129 | 자동 생성 윤문 지침 61개와 공통 제약·자가검증 |
| [skills/humanize-korean/references/rewriting-playbook.md](https://github.com/epoko77-ai/im-not-ai/blob/9747f036cdc28a1a8aea4dc71fef1f7846eb96f7/skills/humanize-korean/references/rewriting-playbook.md) | 212 | 상세 편집 처방, 일부 구형 정책·변경률 정의 잔존 |
| [skills/humanize-korean/references/scholarship.md](https://github.com/epoko77-ai/im-not-ai/blob/9747f036cdc28a1a8aea4dc71fef1f7846eb96f7/skills/humanize-korean/references/scholarship.md) | 357 | 번역학 문헌·자체 인과 가설·C1~C9 한계 명시 |
| [skills/humanize-korean/references/web-service-spec.md](https://github.com/epoko77-ai/im-not-ai/blob/9747f036cdc28a1a8aea4dc71fef1f7846eb96f7/skills/humanize-korean/references/web-service-spec.md) | 219 | 웹/API/DB/UX/요금 확장 설계; 실행 서비스 구현은 아님 |
| [skills/humanize-redo/SKILL.md](https://github.com/epoko77-ai/im-not-ai/blob/9747f036cdc28a1a8aea4dc71fef1f7846eb96f7/skills/humanize-redo/SKILL.md) | 32 | 2차 윤문 진입 지시; 은퇴한 에이전트·파일 계약 참조 잔존 |
| [skills/humanize/SKILL.md](https://github.com/epoko77-ai/im-not-ai/blob/9747f036cdc28a1a8aea4dc71fef1f7846eb96f7/skills/humanize/SKILL.md) | 35 | humanize-korean으로 연결하는 명시 슬래시 진입점 |
| [tests/README.md](https://github.com/epoko77-ai/im-not-ai/blob/9747f036cdc28a1a8aea4dc71fef1f7846eb96f7/tests/README.md) | 64 | 단위·고정 fixture·live의 3계층 평가 안내 |
| [tests/baselines/2026-08-17-anchor-K8-after.json](https://github.com/epoko77-ai/im-not-ai/blob/9747f036cdc28a1a8aea4dc71fef1f7846eb96f7/tests/baselines/2026-08-17-anchor-K8-after.json) | 323 | 과거 품질 스냅샷 |
| [tests/baselines/2026-08-17-anchor-K8-before.json](https://github.com/epoko77-ai/im-not-ai/blob/9747f036cdc28a1a8aea4dc71fef1f7846eb96f7/tests/baselines/2026-08-17-anchor-K8-before.json) | 325 | 과거 품질 스냅샷 |
| [tests/baselines/2026-08-17-anchor-ledger-verify.json](https://github.com/epoko77-ai/im-not-ai/blob/9747f036cdc28a1a8aea4dc71fef1f7846eb96f7/tests/baselines/2026-08-17-anchor-ledger-verify.json) | 555 | 과거 품질 스냅샷 |
| [tests/baselines/2026-08-17-pre-watermark.json](https://github.com/epoko77-ai/im-not-ai/blob/9747f036cdc28a1a8aea4dc71fef1f7846eb96f7/tests/baselines/2026-08-17-pre-watermark.json) | 1601 | 과거 품질 스냅샷 |
| [tests/baselines/2026-08-23-threshold-calibration.json](https://github.com/epoko77-ai/im-not-ai/blob/9747f036cdc28a1a8aea4dc71fef1f7846eb96f7/tests/baselines/2026-08-23-threshold-calibration.json) | 292 | 외부 코퍼스에서 산출한 파생 빈도 통계·한계 기록 |
| [tests/baselines/2026-08-29-task-matched-calibration.json](https://github.com/epoko77-ai/im-not-ai/blob/9747f036cdc28a1a8aea4dc71fef1f7846eb96f7/tests/baselines/2026-08-29-task-matched-calibration.json) | 579 | 외부 코퍼스에서 산출한 파생 빈도 통계·한계 기록 |
| [tests/baselines/2026-08-29-threshold-calibration.json](https://github.com/epoko77-ai/im-not-ai/blob/9747f036cdc28a1a8aea4dc71fef1f7846eb96f7/tests/baselines/2026-08-29-threshold-calibration.json) | 703 | 외부 코퍼스에서 산출한 파생 빈도 통계·한계 기록 |
| [tests/fixtures.json](https://github.com/epoko77-ai/im-not-ai/blob/9747f036cdc28a1a8aea4dc71fef1f7846eb96f7/tests/fixtures.json) | 160 | 6개 입력·고정 출력·불변식/변경률/신호 기준 및 judge rubric |
| [tests/generate_fixtures.py](https://github.com/epoko77-ai/im-not-ai/blob/9747f036cdc28a1a8aea4dc71fef1f7846eb96f7/tests/generate_fixtures.py) | 76 | Claude로 fixture output_text 재생성 |
| [tests/golden/README.md](https://github.com/epoko77-ai/im-not-ai/blob/9747f036cdc28a1a8aea4dc71fef1f7846eb96f7/tests/golden/README.md) | 79 | golden의 방향성 채점 기준과 fixture 확장 안내 |
| [tests/golden/fixtures/01_register_downgrade/bad_output.txt](https://github.com/epoko77-ai/im-not-ai/blob/9747f036cdc28a1a8aea4dc71fef1f7846eb96f7/tests/golden/fixtures/01_register_downgrade/bad_output.txt) | 1 | 검출해야 하는 손상 출력 |
| [tests/golden/fixtures/01_register_downgrade/expected_failures.json](https://github.com/epoko77-ai/im-not-ai/blob/9747f036cdc28a1a8aea4dc71fef1f7846eb96f7/tests/golden/fixtures/01_register_downgrade/expected_failures.json) | 4 | 손상 출력의 기대 실패 코드 |
| [tests/golden/fixtures/01_register_downgrade/good_output.txt](https://github.com/epoko77-ai/im-not-ai/blob/9747f036cdc28a1a8aea4dc71fef1f7846eb96f7/tests/golden/fixtures/01_register_downgrade/good_output.txt) | 1 | 보존해야 하는 정상 출력 |
| [tests/golden/fixtures/01_register_downgrade/input.txt](https://github.com/epoko77-ai/im-not-ai/blob/9747f036cdc28a1a8aea4dc71fef1f7846eb96f7/tests/golden/fixtures/01_register_downgrade/input.txt) | 1 | 구조·격식 회귀 원문 |
| [tests/golden/fixtures/02_academic_structure/bad_output.txt](https://github.com/epoko77-ai/im-not-ai/blob/9747f036cdc28a1a8aea4dc71fef1f7846eb96f7/tests/golden/fixtures/02_academic_structure/bad_output.txt) | 9 | 검출해야 하는 손상 출력 |
| [tests/golden/fixtures/02_academic_structure/expected_failures.json](https://github.com/epoko77-ai/im-not-ai/blob/9747f036cdc28a1a8aea4dc71fef1f7846eb96f7/tests/golden/fixtures/02_academic_structure/expected_failures.json) | 12 | 손상 출력의 기대 실패 코드 |
| [tests/golden/fixtures/02_academic_structure/good_output.txt](https://github.com/epoko77-ai/im-not-ai/blob/9747f036cdc28a1a8aea4dc71fef1f7846eb96f7/tests/golden/fixtures/02_academic_structure/good_output.txt) | 23 | 보존해야 하는 정상 출력 |
| [tests/golden/fixtures/02_academic_structure/input.txt](https://github.com/epoko77-ai/im-not-ai/blob/9747f036cdc28a1a8aea4dc71fef1f7846eb96f7/tests/golden/fixtures/02_academic_structure/input.txt) | 23 | 구조·격식 회귀 원문 |
| [tests/humanize_asserts.py](https://github.com/epoko77-ai/im-not-ai/blob/9747f036cdc28a1a8aea4dc71fef1f7846eb96f7/tests/humanize_asserts.py) | 74 | 테스트용 변경률·보호 토큰·격식·v1 신호 계산 |
| [tests/humanize_runner.py](https://github.com/epoko77-ai/im-not-ai/blob/9747f036cdc28a1a8aea4dc71fef1f7846eb96f7/tests/humanize_runner.py) | 66 | 실제 Claude -p 호출, 구형 모드 문구·본문 sentinel 파싱 |
| [tests/test_agent_inventory.py](https://github.com/epoko77-ai/im-not-ai/blob/9747f036cdc28a1a8aea4dc71fef1f7846eb96f7/tests/test_agent_inventory.py) | 106 | 에이전트 인벤토리 정합 — SKILL.md의 서술이 `agents/` 실물과 맞는지. |
| [tests/test_chunking.py](https://github.com/epoko77-ai/im-not-ai/blob/9747f036cdc28a1a8aea4dc71fef1f7846eb96f7/tests/test_chunking.py) | 376 | 청킹·재조립 (prepare_monolith_input.py --chunk / reassemble_chunks.py) 검증. |
| [tests/test_console_encoding.py](https://github.com/epoko77-ai/im-not-ai/blob/9747f036cdc28a1a8aea4dc71fef1f7846eb96f7/tests/test_console_encoding.py) | 156 | Windows(cp949) 콘솔에서 게이트가 죽지 않는지 검증 (#84). |
| [tests/test_content_anchor_contract.py](https://github.com/epoko77-ai/im-not-ai/blob/9747f036cdc28a1a8aea4dc71fef1f7846eb96f7/tests/test_content_anchor_contract.py) | 61 | 핵심 내용 명사·개념어 보존 계약의 배포 경로 정합을 검증한다. |
| [tests/test_corruption_engine.py](https://github.com/epoko77-ai/im-not-ai/blob/9747f036cdc28a1a8aea4dc71fef1f7846eb96f7/tests/test_corruption_engine.py) | 72 | 오염 엔진 단위 테스트 — 주입의 결정성·의미 중립·자가 검증을 고정한다. |
| [tests/test_diagnosis_rules_build.py](https://github.com/epoko77-ai/im-not-ai/blob/9747f036cdc28a1a8aea4dc71fef1f7846eb96f7/tests/test_diagnosis_rules_build.py) | 102 | diagnosis-rules.md 가 taxonomy(SSOT)에서 재생성 가능하고 최신인지 검증한다. |
| [tests/test_golden.py](https://github.com/epoko77-ai/im-not-ai/blob/9747f036cdc28a1a8aea4dc71fef1f7846eb96f7/tests/test_golden.py) | 322 | Golden-fixture regression tests for humanize-korean. |
| [tests/test_humanize_asserts.py](https://github.com/epoko77-ai/im-not-ai/blob/9747f036cdc28a1a8aea4dc71fef1f7846eb96f7/tests/test_humanize_asserts.py) | 63 | 판정 헬퍼 자체의 단위 테스트 — 결정적, 에이전트 불필요, 항상 실행 가능. |
| [tests/test_humanize_e2e.py](https://github.com/epoko77-ai/im-not-ai/blob/9747f036cdc28a1a8aea4dc71fef1f7846eb96f7/tests/test_humanize_e2e.py) | 89 | 계층2(behavioral) E2E — fixtures.json의 (원문, 윤문본) 쌍을 불변식/밴드/지표델타로 검증. |
| [tests/test_humanize_live.py](https://github.com/epoko77-ai/im-not-ai/blob/9747f036cdc28a1a8aea4dc71fef1f7846eb96f7/tests/test_humanize_live.py) | 69 | 계층3 (live integration) — 실제 스킬을 돌려 갓 나온 출력에 판정. |
| [tests/test_install_flags.sh](https://github.com/epoko77-ai/im-not-ai/blob/9747f036cdc28a1a8aea4dc71fef1f7846eb96f7/tests/test_install_flags.sh) | 113 | 임시 홈에서 설치 선택·에이전트 범위·소유 링크 정리의 --dry-run 검사 |
| [tests/test_metrics.py](https://github.com/epoko77-ai/im-not-ai/blob/9747f036cdc28a1a8aea4dc71fef1f7846eb96f7/tests/test_metrics.py) | 233 | Tests for humanize-ko v1.6 metrics module. |
| [tests/test_metrics_v2.py](https://github.com/epoko77-ai/im-not-ai/blob/9747f036cdc28a1a8aea4dc71fef1f7846eb96f7/tests/test_metrics_v2.py) | 475 | Tests for humanize-ko v2.0 metrics module. |
| [tests/test_metrics_v2_import.py](https://github.com/epoko77-ai/im-not-ai/blob/9747f036cdc28a1a8aea4dc71fef1f7846eb96f7/tests/test_metrics_v2_import.py) | 55 | metrics_v2.py import-path 회귀 테스트. |
| [tests/test_plugin_manifests.py](https://github.com/epoko77-ai/im-not-ai/blob/9747f036cdc28a1a8aea4dc71fef1f7846eb96f7/tests/test_plugin_manifests.py) | 24 | The Copilot plugin exposes the single-call skill and shared references. |
| [tests/test_quick_rules_build.py](https://github.com/epoko77-ai/im-not-ai/blob/9747f036cdc28a1a8aea4dc71fef1f7846eb96f7/tests/test_quick_rules_build.py) | 63 | quick-rules.md 가 taxonomy(SSOT)에서 재생성 가능하고 최신인지 검증한다. |
| [tests/test_restore_modality.py](https://github.com/epoko77-ai/im-not-ai/blob/9747f036cdc28a1a8aea4dc71fef1f7846eb96f7/tests/test_restore_modality.py) | 138 | 서법 국소 복원기(scripts/restore_modality.py) 단위 테스트. |
| [tests/test_route_hint.py](https://github.com/epoko77-ai/im-not-ai/blob/9747f036cdc28a1a8aea4dc71fef1f7846eb96f7/tests/test_route_hint.py) | 239 | route_hint 경로 판정 + 청킹 임계 상향(v2.1) 회귀 검증. |
| [tests/test_run_dir_resolution.py](https://github.com/epoko77-ai/im-not-ai/blob/9747f036cdc28a1a8aea4dc71fef1f7846eb96f7/tests/test_run_dir_resolution.py) | 113 | --run-dir·--diagnosis 상대경로가 **cwd 기준**으로 풀리는지 검증 (#71). |
| [tests/test_runtime_boundary.py](https://github.com/epoko77-ai/im-not-ai/blob/9747f036cdc28a1a8aea4dc71fef1f7846eb96f7/tests/test_runtime_boundary.py) | 175 | 프로덕션 런타임이 tests/ 트리에 의존하지 않는지 검증 (#59). |
| [tests/test_sanitize.py](https://github.com/epoko77-ai/im-not-ai/blob/9747f036cdc28a1a8aea4dc71fef1f7846eb96f7/tests/test_sanitize.py) | 200 | scripts/sanitize_text.py 회귀 테스트. |
| [tests/test_strip_injected_commas.py](https://github.com/epoko77-ai/im-not-ai/blob/9747f036cdc28a1a8aea4dc71fef1f7846eb96f7/tests/test_strip_injected_commas.py) | 78 | strip_injected_commas — C-11 역주입 결정적 후처리 단위 테스트. |
| [tests/test_verify_gates.py](https://github.com/epoko77-ai/im-not-ai/blob/9747f036cdc28a1a8aea4dc71fef1f7846eb96f7/tests/test_verify_gates.py) | 446 | Tests for scripts/verify_gates.py — Tier 1 구조 게이트 (4축 통합). |
| [tests/test_version_sync.py](https://github.com/epoko77-ai/im-not-ai/blob/9747f036cdc28a1a8aea4dc71fef1f7846eb96f7/tests/test_version_sync.py) | 115 | 패키징 매니페스트 버전 동기화 — 결정적, CI에서 항상 실행. |
| [uninstall.sh](https://github.com/epoko77-ai/im-not-ai/blob/9747f036cdc28a1a8aea4dc71fef1f7846eb96f7/uninstall.sh) | 47 | 자기 저장소를 가리키는 링크 제거 및 Gemini 확장 해제 |
| [update.sh](https://github.com/epoko77-ai/im-not-ai/blob/9747f036cdc28a1a8aea4dc71fef1f7846eb96f7/update.sh) | 73 | 원격 ancestry 비교 후 fast-forward pull과 설치 재적용 |

## 패턴별 윤문 경로

아래 84개는 빌더가 인식한 항목이다. quick=true이면 단일 윤문 모델의 기본 규칙집에 들어간다. false이면 진단 인덱스에는 있으나 quick 규칙집에는 없다. 홀드·문맥 조건을 무시하고 모두 강제 적용해서는 안 된다.

| ID | 이름 | quick | 처방 또는 범위 |
|---|---|---|---|
| A-1 | "~에 대하여/대해서" 남발 | true | 목적격 조사로 직결("X에 대해 논의" → "X를 논의") |
| A-2 | "~를 통하여/통해" 남발 | true | 일부만 "~로", "~해서", "~함으로써"로 분산(1~2회 보존) |
| A-3 | "~에 있어(서)" | true | "~에서" 또는 "~을 볼 때" |
| A-4 | "~라는 점에서" | true | "~서", "~라는 이유로" |
| A-5 | "~와 관련하여" / "~와 관련된" | true | "~에", "~의" |
| A-6 | "~에 기반하여" / "~을 바탕으로" 남발 | true | "~로", "~을 보고" |
| A-7 | "가지고 있다" | true | 형용사-동사 환원 또는 이중주어("강한 경쟁력을 가지고 있다" → "경쟁력이 강하다") |
| A-8 | 이중 피동 "~되어진다" / "~지게 된다" | true | 능동 또는 단일 피동("판단되어진다" → "판단된다") |
| A-9 | "~에 의해" 피동문 | true | 행위자를 주어로("AI에 의해 생성" → "AI가 만든") |
| A-10 | "~할 수 있다" 남발 · v2.4 처방 전환 | true | **단정 전환 금지**. 일부만 다른 완곡 표현("~할 여지가 있다·~할 수도 있다")으로 분산해 리듬만 깬다 |
| A-11 | "~을 위해" 목적절 남발 | true | "~려고", "~도록", "~위한" |
| A-12 | "만들어지다" / "이루어지다" | false | quick 처방 없음; 진단 모델의 문맥 판단에 의존 |
| A-13 | 명사 나열 (조사 생략) | false | quick 처방 없음; 진단 모델의 문맥 판단에 의존 |
| A-14 | 접속부사 "그리고" 절 연결 | false | quick 처방 없음; 진단 모델의 문맥 판단에 의존 |
| A-15 | 추상 주어 + 만능 동사 [S2] · v1.1 신규 | true | 구체 주어로 환원, 사역은 "X 때문에/덕분에/로 인해" 부사절, 인지 동사(suggest/show/indicate)는 "~에 따르면 ~이다" |
| A-16 | 문맥이 허락하지 않는 지시·인칭 대명사 [S1] · v2.0 신규 · **v2.7 조준 교체** | true | 0개 → 명사구 복원(확정 불가면 유지) / 1개 → 영형 / 2개+ → 명사구 되짚기. **삭제 비율 목표 없음. 불확실하면 유지** |
| A-17 | (보류 — v2.0 hold) 무정물·추상명사 '-들' 복수 표지 기계적 부착 | false | 진단용 정의 참조; A-17은 관찰용 hold |
| A-18 | 관계대명사절 직역 — 긴 좌향 수식 (관형구 3중 이상 중첩) [S2] · v2.0 신규 | true | 문장 분리 또는 후치 동격절("X를 만났는데, 그 X는 ~") |
| A-19 | 이중 조사 결합 (-에서의·-에로의·-으로의·-에의·-으로부터의·-로부터의) [S2] · v2.0 신규 | true | 절-구로 풀어쓰기, 단순 "~의"는 비대상 |
| A-20 | 피동 진행 "~되고 있다 / ~지고 있다" 남발 · v2.6 신규 (팀 채굴) | true | 일부만 추세 단언("심해졌다")으로 — 고립 사용은 보존 |
| A-21 | 범위 상승 "단순한 X를 넘어 Y" · v2.6 신규 (팀 채굴) | true | "X만이 아니라 Y다"로 풀거나 넘어-구 삭제 |
| A-22 | 평가 술어 얹기 "~은 명확하다 / 분명하다" [S2] · v2.7 신규 | true | 평가 술어를 걷고 명제를 단언으로. 확신 강도는 부사로 보존. 앞에서 논증한 결론이면 유지 |
| A-23 | 기반 마련 공식 "발판·토대를 마련하다 / 지평을 열다" [S2] · v2.7 신규 | false | quick 처방 없음; 진단 모델의 문맥 판단에 의존 |
| A-24 | "더 이상 ~ 않다/아니다" (no longer) [S2] · v2.7 신규 | true | "더 이상"을 "이제"로 환원하거나 변화 동사로 편다. 부정 명제를 긍정 단언으로 올리지 마라. **윤문 중 "더 이상 A가 아니라 B"를 새로 만들지 마라** |
| B-1 | 괄호 병기 관습 | true | 첫 등장만 병기, 이후 한글만 |
| B-2 | 불필요한 영어 장식·일회성 jargon | true | 광고성만 한국어로 풀고 표준 technical term(API·prompt·token 등)은 원어 보존, 기계적 직역 금지 |
| B-3 | 과도한 영어 인용구 | false | quick 처방 없음; 진단 모델의 문맥 판단에 의존 |
| B-4 | "~라고 알려진", "~로 일컬어지는" | false | quick 처방 없음; 진단 모델의 문맥 판단에 의존 |
| C-1 | 기계적 병렬 열거 | false | quick 처방 없음; 진단 모델의 문맥 판단에 의존 |
| C-2 | 과도한 불릿 리스트 | true | 문단 산문으로 통합, 나열이 의미 있는 지점만 유지 |
| C-3 | 반복적 섹션 헤딩 | false | quick 처방 없음; 진단 모델의 문맥 판단에 의존 |
| C-4 | 문단 첫 문장 요약 공식 | false | quick 처방 없음; 진단 모델의 문맥 판단에 의존 |
| C-5 | 이모지 남발 | true | 칼럼-리포트 장르면 전부 삭제 |
| C-6 | 헤딩 아래 한 줄 요약 박스 | false | quick 처방 없음; 진단 모델의 문맥 판단에 의존 |
| C-7 | 문단 간 기계적 "먼저·반면·결국" 3단 공식 [S2] · v1.1 신규 | true | 접속사 1~2개로 줄이거나 본문에 녹여 제거 |
| C-8 | 대칭 대구 공식 "A인가, B인가" 반복 [S1] · v1.1 신규 · v2.3 실측 최강 신호 | true | 한 번만 살리고 나머지는 비대칭 평서문·직접 단언으로. 전멸 금지. 사람 필자도 다용하는 수사이므로(532편 중 31편 실측) 연쇄로 몰려 있지 않으면 보존 우선 |
| C-9 | 숫자 괄호 인덱싱 "1) 2) 3)" [S2] · v1.3 신규 | true | 본문에 녹이거나 "우선~", "다음으로~"로 어휘 변주 |
| C-10 | 콜론 부제 헤딩 공식 "X: Y" 또는 "X: A에서 B로" [S2] · v1.3.1 신규 | true | 헤딩을 단일 명사구로 압축, 단 학술-보고서의 실제 절 제목은 보존 |
| C-11 | 연결어미 뒤 쉼표 [S1] · v1.6 신규 | true | 쉼표 제거, 6회+ = 강한 신호(KatFish 4.84배 분리도). **윤문이 새 연결어미 쉼표를 만들지 말 것 — 윤문 후 개수가 원문보다 늘면 실패** |
| C-12 | 쉼표 포함률 (문서 단위) [S2] · v1.6 신규 | false | quick 처방 없음; 진단 모델의 문맥 판단에 의존 |
| D-1 | 종결·요약류 | true | 3회 초과 시 1~2건만 남기고 삭제-치환 |
| D-2 | 의의·중요성 과장 | true | 삭제 또는 구체 결론으로 |
| D-3 | 열거 도입 | true | 도입구 삭제하고 바로 본론 서술로 |
| D-4 | AI 티 특화 | true | 구체 수치-사실로 환원 |
| D-5 | 의인화된 추상 주어 [S2] · v1.1 신규 | true | 사람-기관 주어로 교체 또는 의인화 동사 약화 |
| D-6 | 완결 공식형 결말 "~할 때입니다 / 시점입니다" [S2] · v1.1 신규 | true | 구체 동사 단언으로, 문서당 1회 이하 |
| D-7 | 변환 공식 "X에서 Y로 / X을 넘어 Y로" [S2] · v1.3.1 신규 | true | 직접 단언으로, 문서당 1회 이하 |
| D-8 | 분열문 공식 "필요한/중요한 것은 X이다" [S2] · v2.5 신규 (코퍼스 채굴) | true | 주어-서술 직결로("필요한 것은 방향이다" → "방향이 필요하다" / "논쟁의 핵심은 생산성이다" → "논쟁은 생산성을 둘러싼 것이다") |
| D-9 | 인과 결산 "결국 ~로 이어진다" [S2] · v2.5 신규 (코퍼스 채굴) | true | 인과 경로를 구체로 쓰거나 단문 단언으로. "결국"은 1회만 남긴다. **결말을 다듬으며 "결국·이유다"를 새로 만들지 마라(주입 금지)** |
| D-10 | 역방향 결산 "~하는 이유다" · v2.6 신규 (팀 채굴) | true | 순방향 단언("그래서 ~다")으로, 문서당 1회 이하. **결말을 다듬으며 이 도치를 새로 만들지 마라(주입 금지)** |
| D-11 | 결말부 막연한 시간지평 "향후·앞으로·중장기적으로" · v2.6 신규 (팀 채굴) | true | 시간어 삭제 또는 원문에 있는 실제 시점·조건으로 교체(날조 금지) |
| D-12 | 내용 없는 반론 슬롯 "과제도 남아 있다" · v2.6 신규 (팀 채굴·blader §6 수렴) | true | 문패 삭제, 실제 과제를 첫 문장으로 |
| D-13 | 에세이 성찰 부사 공식 "어쩌면·비로소·천천히" · v2.6 신규 (팀 채굴·장르 한정) | true | 성찰 부사를 빼고 구체 서술로(에세이 장르 한정) |
| D-14 | 생성형 은유 남용 (가족 판정) · v2.6.1 신규 (사용자 통점 실증) | true | 직역화 — 감각 술어는 관용구·구체 서술로("서늘하다"→"정곡을 찌른다"), 사전 은유는 명제로("잠식한다"→"점유율을 뺏는다"). 관통 은유는 가장 효과적인 1회만 남김("쥐다"→"가지다"). 명제 불명이면 보존, 주입 금지 |
| E-1 | 문장 길이 표준편차 낮음 — 특히 장문 부재 | true | 단문 1~2개 + 인접 문장을 이어 만든 장문 1개를 문단마다(내용 추가 금지) |
| E-2 | 동일 종결어미 반복 | true | 종결어미 다양화, "~고 있다"는 단순 시제로 환원 가능 시 환원("읽고 있다" → "읽는다") |
| E-3 | 모든 문단 3~4문장 공식 | false | quick 처방 없음; 진단 모델의 문맥 판단에 의존 |
| E-4 | 단문 일변도 (복문·중문 부재) [S2] · v1.5.1 신규 | false | quick 처방 없음; 진단 모델의 문맥 판단에 의존 |
| E-5 | 쉼표 분절 평균 길이 (긴 절 구조) [S2] · v1.6 신규 | false | quick 처방 없음; 진단 모델의 문맥 판단에 의존 |
| E-6 | 쉼표 전후 POS 다양성 높음 (구문 복잡도) [S2] · v1.6 신규 · 장르 가드 | false | quick 처방 없음; 진단 모델의 문맥 판단에 의존 |
| E-7 | 청자 경어법 일관성 손실 (해라/하게/하오/해요/합쇼체) [S2 · estimated] · v2.0 신규 | true | 격식 등급 하나로 일관 유지 |
| F-1 | 정도부사 중독 | false | quick 처방 없음; 진단 모델의 문맥 판단에 의존 |
| F-2 | 동의어 이중 수식 | false | quick 처방 없음; 진단 모델의 문맥 판단에 의존 |
| F-3 | 기능+역할 복합구 | false | quick 처방 없음; 진단 모델의 문맥 판단에 의존 |
| F-4 | 과잉 접두·접미 | true | 동사-형용사 어근으로 환원("the implementation of the policy" → "정책 시행") |
| F-5 | "~적 N" 복합 추상어 체인 [S2] · v1.1 신규 | true | 명사+명사 또는 풀어쓰기("전략 함의", "실천의 기반") |
| F-7 | 범용 정책동사 수렴 (확대·강화·개선 + 만능 "설계") · v2.6 신규 (팀 채굴) | true | 구체 행위 동사로 해체(당위 표지 증폭 금지) |
| G-1 | 추측·관측형 종결 · v2.4 처방 전환 | true | **단정 전환 금지**. 유보 강도는 유지한 채 종결 형태만 변주. 부정·이중부정이 낀 문장은 극성 확인 후 손대고 애매하면 원문 보존 |
| G-2 | 이중·삼중 완곡 | true | 완곡 하나만 남김 — 남긴 완곡은 원문 극성·확신도 유지. 부정 낀 중첩과 협상·계약 문서는 접지 말고 원문 보존 |
| G-3 | 안전 균형 lexicon (Safe Balance Score) [S2] · v1.6 신규 | true | 한쪽 단언, 구체 비교, 조건부로 치환 |
| H-1 | 문두 접속사 과다 · v2.5 근거 재검토(모델 의존) | true | 그 문단에서 절반가량만 덜어낸다(문서 일괄 제거 금지 — 모델 의존 신호) |
| H-2 | "하지만"과 "그러나" 혼용 남발 | false | quick 처방 없음; 진단 모델의 문맥 판단에 의존 |
| H-3 | "이는 ~" 지시 반복 | true | 그중 일부만 본 서술로 직진(문서 단위 일괄 삭제 금지 — 사람도 쓰는 패턴) |
| H-4 | 재정의 접속사 "즉" 남발 [S2] · v1.1 신규 | true | "곧", "말하자면" 등으로 변주 또는 생략, 문서당 2회 이하 |
| I-1 | "것이다" 종결 남발 | true | 일부만 확정 서술 "~다"로(기본 보존) |
| I-2 | "점", "바", "수", "데" 반복 | true | "X는 ~다" 직설로 |
| I-3 | "~라는 것" | true | "~다" 직접 종결로, 합산 2회 이하 |
| I-4 | "~할 필요가 있다" + 정책 보고서 권고형 결말 | true | 당위 문장을 문단 끝에서 앞·중간으로 이동해 결말 자리를 비움. 병합·삭제·서법 치환·명사화 금지. 전후 의무 표지 총수 동일 |
| I-5 | "~이/가 필요하다" | false | quick 처방 없음; 진단 모델의 문맥 판단에 의존 |
| I-6 | "~능력" 추상명사 연쇄 [S2] · v1.1 신규 | false | quick 처방 없음; 진단 모델의 문맥 판단에 의존 |
| I-7 | 무주체 판정 "~다는 분석이다·평가다" · v2.6 신규 (팀 채굴·장르 조건) | true | 앞뒤에 출처 있으면 보존, 없으면 직접 서술로(출처 날조 금지) |
| J-2 | 따옴표 과다 | true | 진짜 인용만 남기고 평어로 |
| J-3 | 대시(—) 남용 | true | 쉼표, 괄호, 별도 문장으로 분해 — 단 원문에 이미 있던 대시는 보존 |
| J-4 | 괄호 부연 과다 | false | quick 처방 없음; 진단 모델의 문맥 판단에 의존 |

J-1은 원본 795행에 `## J-1.`로 존재하고 quick=true 메타도 있지만, 파서는 `### ID.`만 읽어 생성물에 빠진다. 이 파일은 원본을 수정하지 않고 관찰한 목록이다.
