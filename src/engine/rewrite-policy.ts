export const REWRITE_OPTIONS = [
  { id: 'normal', label: '보통', description: '원래 표현을 살려 어색한 부분을 다듬습니다.' },
  { id: 'medium', label: '중간', description: '어휘와 길어진 표현을 더 자연스럽게 정리합니다.' },
  { id: 'strong', label: '강하게', description: '문장 구조와 반복 표현까지 적극적으로 바꿉니다.' },
  { id: 'very-strong', label: '매우 강하게', description: '뜻은 유지하고 글 전반의 표현과 문장 구성을 크게 바꿉니다.' }
] as const;
export type RewriteStrength = typeof REWRITE_OPTIONS[number]['id'];
export interface RewriteOptions { inputKind: 'direct-text' | 'text-file'; strength: RewriteStrength }

export function parseRewriteStrength(value: unknown): RewriteStrength {
  if (!REWRITE_OPTIONS.some(option => option.id === value)) throw new Error('지원하지 않는 변환 강도입니다.');
  return value as RewriteStrength;
}
export function parseRewriteOptions(inputKind?: unknown, strength?: unknown): RewriteOptions | undefined {
  if (inputKind === undefined && strength === undefined) return undefined;
  if (inputKind !== 'direct-text' && inputKind !== 'text-file') throw new Error('입력 종류를 확인해 주세요.');
  const selected = strength === undefined ? 'normal' : parseRewriteStrength(strength);
  if (inputKind === 'text-file' && selected !== 'normal') throw new Error('변환 강도는 직접 입력에서만 선택할 수 있습니다.');
  return { inputKind, strength: selected };
}

export function rewriteInstructions(options: RewriteOptions | undefined, attempt: 1 | 2, reviewingCandidate = false): string {
  if (options?.inputKind !== 'direct-text') return '';
  const scope: Record<RewriteStrength, string> = {
    normal: '원래 표현을 살려 룰북에 근거가 있는 어색한 부분을 국소 교정한다.',
    medium: '한 문장 안의 여러 어색한 구절, 비핵심 명사화와 중복 수식을 함께 정리하고 주어·서술 연결을 자연스럽게 다듬는다.',
    strong: '문제 문장의 구문 전체를 재구성할 수 있다. 원문에 명시된 행위자를 보존한 피동·능동 전환, 문장 내부 어순 재배치, 긴 수식 구조 정리와 반복 구문 변주를 적극적으로 적용한다.',
    'very-strong': '재서술 가능한 모든 문장을 검토하고 글 전반의 많은 문장을 실제로 재서술한다. 이미 문법적으로 맞는 문장도 유효한 대안이 있으면 구문·어순·서술 방식·호흡을 재구성한다. 원래 문장 형태 유지를 우선하지 않는다. 한두 단어 치환만으로 끝내지 않는다. 다만 변경량을 채우려고 의미 없는 동의어를 넣지 않는다.'
  };
  const structuralGuidance = attempt === 1 && (options.strength === 'strong' || options.strength === 'very-strong')
    ? '보존해야 할 핵심 개념어를 문장 속 자연스러운 자리에 둔다. 문장 끝에 명사를 억지로 덧붙이지 않는다. 기존 표현을 줄이거나 바꾸는 과정에서 ‘중요한 역할을 수행한다’ 같은 금지된 상투 표현을 새로 만들지 않는다. 구조 변경 예: X가 Y에서 중요한 역할을 수행한다 → Y에서 X의 역할은 중요하다. X의 핵심은 Y하는 것이다 → Y하는 것이 X의 핵심이다. 예시의 X와 Y를 결과에 그대로 쓰지 않는다. 원문에 없는 사실을 추가하지 않는다.'
    : '';
  return `\n<rewrite_policy>\n요청 강도: ${options.strength}.\n우선순위: 서비스 보호 제약 > 룰북의 발동 조건 및 hold > 단계별 편집 범위 > 예시.\n문장 분할·병합, 문단 이동·병합, 제목·목록 변경은 금지한다. 각 원문 문장의 정보·시간·조건·인과·책임 주체·말투를 유지한다. 문장마다 끝맺음(합니다체·해요체 등)과 '-시-' 높임, 질문·요청 형태, 겸양 표현(드리다), ㅋㅋ·^^·~ 같은 표지를 원문 그대로 둔다.\n숫자·날짜·직접 인용은 글자 그대로 두고, 가능성·부정·의무·조건 표현과 여러 주체 사이의 관계는 원문과 같게 유지한다. 이런 표현이 있는 문장도 그 밖의 어색한 표현은 고칠 수 있다. 정확성·안전성·경쟁력 등 핵심 개념어와 전문 용어를 다른 말로 치환하지 않는다. 원문에 없는 행위자·근거·예시를 추가하지 않는다. 룰북의 조건과 보류 규칙은 강도와 무관하게 준수한다.\n${attempt === 2 && reviewingCandidate ? '아래 후보 검토 지침에 따라 원문과 대조하여 보수적으로 검토한다. 요청 강도보다 보호를 우선한다.' : attempt === 2 ? '검증 실패로 보수적 재시도를 적용한다. 요청 강도보다 보호를 우선하여 확실한 국소 교정만 수행한다.' : scope[options.strength]}\n${structuralGuidance}\n${attempt === 1 && options.strength !== 'normal' ? '위 단계별 범위는 룰북의 국소 수정만 허용하거나 탐지 구절 외 수정을 금지하는 지침을 대체한다. 서비스 보호 제약은 항상 유지한다.' : ''}\n</rewrite_policy>\n`;
}
