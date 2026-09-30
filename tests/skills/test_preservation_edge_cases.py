"""Regression cases for preservation gates and deterministic restorers."""
from pathlib import Path
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'vendor/humanize-engine/scripts'))
from engine_runtime.workflow import restore, verify  # noqa: E402
import checks  # noqa: E402
import sanitize_text  # noqa: E402
import strip_injected_commas  # noqa: E402


class GateCase(unittest.TestCase):
    def run_gate(self, source, candidate, attempt=1, restore_first=False):
        with tempfile.TemporaryDirectory() as folder:
            before, after = Path(folder) / 'before.txt', Path(folder) / 'after.txt'
            before.write_text(source, encoding='utf-8')
            after.write_text(candidate, encoding='utf-8')
            if restore_first:
                restore(before, after)
            return verify(before, after, attempt=attempt), after.read_text(encoding='utf-8')


class ModalityRestoreTest(GateCase):
    def test_restore_never_duplicates_a_reordered_sentence(self):
        source = '상반기에는 신규 채용 규모를 줄여야 한다. 하반기에는 신규 채용 규모를 늘려야 한다.\n'
        candidate = '하반기에는 신규 채용 규모를 늘려야 한다. 상반기에는 신규 채용 규모를 줄인다.\n'
        _, output = self.run_gate(source, candidate, restore_first=True)
        sentences = [s for s in output.replace('\n', ' ').split('. ') if s.strip()]
        self.assertEqual(len(sentences), len(set(s.strip(' .') for s in sentences)), output)
        self.assertIn('상반기에는', output)


class DroppedContentTest(GateCase):
    SENTENCES = ['회사는 올해 새로운 물류 체계를 도입했다.', '이 체계는 창고 운영 방식을 크게 바꾸었다.',
                 '현장 직원들은 처음에 적응하는 데 어려움을 겪었다.', '관리자들은 교육 과정을 따로 마련했다.',
                 '고객 불만은 도입 초기에 잠시 늘었다.', '협력 업체와의 계약 조건도 일부 조정됐다.',
                 '노조는 인력 재배치에 반대 의견을 냈다.', '경영진은 안전 문제를 최우선으로 두겠다고 약속했다.',
                 '외부 감사는 개선 사항을 여럿 지적했다.', '회사는 내년에 체계를 전 지점으로 넓힌다.']

    def test_silently_dropped_sentences_are_a_hard_failure(self):
        source = ' '.join(self.SENTENCES) + '\n'
        candidate = ' '.join(self.SENTENCES[i] for i in (0, 1, 2, 3, 7, 9)) + '\n'
        for attempt, policy in ((1, 'retry'), (2, 'rollback')):
            result, _ = self.run_gate(source, candidate, attempt)
            self.assertIn('sentence_dropped', result['hardFailures'])
            self.assertEqual(result['policy'], policy)

    def test_a_single_dropped_sentence_is_detected(self):
        source = ' '.join(self.SENTENCES[:4]) + '\n'
        candidate = ' '.join(self.SENTENCES[i] for i in (0, 1, 3)) + '\n'
        result, _ = self.run_gate(source, candidate)
        self.assertIn('sentence_dropped', result['hardFailures'])

    def test_light_rewrite_of_every_sentence_is_not_a_drop(self):
        source = ' '.join(self.SENTENCES) + '\n'
        candidate = source.replace('도입했다', '들여왔다').replace('크게 바꾸었다', '크게 바꿨다')
        result, _ = self.run_gate(source, candidate)
        self.assertNotIn('sentence_dropped', result['hardFailures'])


class QuotePairingTest(GateCase):
    def test_an_inch_mark_does_not_disable_quote_protection(self):
        source = '정부 관계자는 "올해 수출은 전년보다 확실히 늘어날 것"이라고 말했다. 새 사무실에는 27" 모니터가 놓였다.\n'
        candidate = '정부 관계자는 "올해 수출은 전년보다 늘어날지도 모른다"라고 말했다. 새 사무실에는 27" 모니터가 놓였다.\n'
        result, _ = self.run_gate(source, candidate)
        self.assertIn('quote_altered', result['hardFailures'])

    def test_mismatched_marks_do_not_pair_across_paragraphs(self):
        source = ('김 장관은 “올해 수출은 늘 것"이라고 말했다.\n\n'
                  '전문가들은 여러 가지 요인이 복합적으로 작용하고 있다고 보고 있다. 시장의 흐름은 대체로 안정적인 편이었다.\n\n'
                  '박 대표는 “투자를 늘리겠다”고 밝혔다.\n')
        candidate = source.replace('여러 가지 요인이 복합적으로 작용하고 있다고 보고 있다', '여러 요인이 함께 작용한다고 본다')
        quotes = checks.extract_quotes(source)
        self.assertTrue(all('\n' not in q for q in quotes), quotes)
        result, _ = self.run_gate(source, candidate, 2)
        self.assertNotIn('quote_altered', result['hardFailures'])

    def test_balanced_curly_quote_is_still_protected(self):
        source = '박 대표는 “투자를 크게 늘리겠다”고 밝혔다.\n'
        result, _ = self.run_gate(source, source.replace('크게 늘리겠다', '늘리겠다'))
        self.assertIn('quote_altered', result['hardFailures'])


class NumberedListTest(GateCase):
    def test_parenthesized_list_items_are_not_footnote_definitions(self):
        source = ('추진 과제는 다음과 같다.\n1) 지역 인재를 적극적으로 양성하는 방안을 마련한다.\n'
                  '2) 중소기업의 연구 역량을 체계적으로 강화한다.\n\n이러한 과제는 단계적으로 추진될 예정이다.\n')
        candidate = ('추진 과제는 다음과 같다.\n1) 지역 인재를 적극 기르는 방안을 마련한다.\n'
                     '2) 중소기업의 연구 역량을 체계적으로 키운다.\n\n이 과제들은 단계적으로 추진될 예정이다.\n')
        result, _ = self.run_gate(source, candidate, 2)
        self.assertNotIn('footnote_def', result['hardFailures'])

    def test_short_numbered_list_items_are_not_headings(self):
        source = '검토 결과는 다음과 같다.\n1. 지역 인재 양성 방안 마련\n2. 중소기업 연구 역량 강화\n\n두 과제는 단계적으로 추진될 예정이다.\n'
        candidate = '검토 결과는 다음과 같다.\n1. 지역 인재를 기르는 방안 마련\n2. 중소기업 연구 역량 확충\n\n두 과제는 차례로 추진될 예정이다.\n'
        result, _ = self.run_gate(source, candidate, 2)
        self.assertNotIn('heading_lost', result['hardFailures'])

    def test_real_footnotes_and_headings_stay_protected(self):
        source = ('1. 서론\n\n매출은 30% 증가했다.1) 이 흐름은 계속된다.\n\n'
                  '2. 결론\n\n성장은 이어질 전망이다.\n\n1) 통계청, 2025년 보고서.\n')
        candidate = source.replace('1) 통계청, 2025년 보고서.', '1) 통계청 보고서, 2025년.')
        result, _ = self.run_gate(source, candidate, 2)
        self.assertIn('footnote_def', result['hardFailures'])
        candidate = source.replace('1. 서론\n', '')
        result, _ = self.run_gate(source, candidate, 2)
        self.assertTrue({'heading_lost', 'heading_absorbed'} & set(result['hardFailures']))


class NamesAndNumberWordsTest(GateCase):
    def test_latin_and_hanja_names_cannot_change(self):
        for source, candidate in [('삼성전자는 Apple과 경쟁한다.\n', '삼성전자는 Google과 경쟁한다.\n'),
                                  ('우리는 AI를 활용한다.\n', '우리는 ML을 활용한다.\n'),
                                  ('그는 李文學 교수의 자문을 받았다.\n', '그는 李文鶴 교수의 자문을 받았다.\n')]:
            with self.subTest(candidate=candidate):
                result, _ = self.run_gate(source, candidate)
                self.assertIn('name_changed', result['hardFailures'])

    def test_number_words_with_counters_cannot_change(self):
        for source, candidate in [('매출은 두 배로 늘었다.\n', '매출은 세 배로 늘었다.\n'),
                                  ('참석자는 열 명이었다.\n', '참석자는 스무 명이었다.\n'),
                                  ('이 규정은 삼십 일 이내에 적용된다.\n', '이 규정은 사십 일 이내에 적용된다.\n')]:
            with self.subTest(candidate=candidate):
                result, _ = self.run_gate(source, candidate)
                self.assertIn('quantity_changed', result['hardFailures'])

    def test_number_word_to_digit_notation_is_allowed(self):
        for source, candidate in [('매출은 세 배로 늘었다.\n', '매출은 3배로 늘었다.\n'),
                                  ('참석자는 열 명이었다.\n', '참석자는 10명이었다.\n'),
                                  ('점유율은 ２０％였다.\n', '점유율은 20%였다.\n')]:
            with self.subTest(candidate=candidate):
                result, _ = self.run_gate(source, candidate)
                self.assertEqual(result['hardFailures'], [])

    def test_common_words_that_look_like_numbers_do_not_fail(self):
        for source, candidate in [('문을 열 수 있다. 네 생각은 어떤가?\n', '문을 열 수도 있다. 너의 생각은 어떤가?\n'),
                                  ('한 번 더 확인한다.\n', '다시 확인한다.\n'),
                                  ('두 번째 과제는 교육이다.\n', '다음 과제는 교육이다.\n')]:
            with self.subTest(candidate=candidate):
                result, _ = self.run_gate(source, candidate)
                self.assertNotIn('quantity_changed', result['hardFailures'])


class CommaStripTest(unittest.TestCase):
    def test_noun_lists_ending_in_go_keep_their_commas(self):
        before = '회사는 재고와 부채와 광고비를 관리했다.\n'
        after = '회사는 재고, 부채, 광고비를 함께 관리했다. 비교 대상은 최고, 최저, 평균이다.\n'
        output, report = strip_injected_commas.strip_injected(before, after)
        self.assertIn('재고, 부채, 광고비', output)
        self.assertIn('최고, 최저, 평균', output)
        self.assertEqual(report['commas_removed'], 0)

    def test_connective_commas_are_still_removed(self):
        output, report = strip_injected_commas.strip_injected('그는 밥을 먹고 잤다.\n', '그는 밥을 먹고, 곧 잠들었다.\n')
        self.assertEqual(output, '그는 밥을 먹고 곧 잠들었다.\n')
        self.assertEqual(report['commas_removed'], 1)
        output, _ = strip_injected_commas.strip_injected('그는 먹고 자고 일했다.\n', '그는 먹고, 자고, 일만 했다.\n')
        self.assertEqual(output, '그는 먹고 자고 일만 했다.\n')

    def test_commas_inside_a_multi_sentence_quote_are_untouched(self):
        before = '김 대표는 “우리는 먼저 시장을 살핀다. 우리는 서두르지 않고, 신중하게 움직인다.” 그는 기자들에게 이렇게 말했다.\n'
        after = '김 대표는 “우리는 먼저 시장을 살핀다. 우리는 서두르지 않고, 신중하게 움직인다.” 그가 기자들에게 한 말이다.\n'
        output, report = strip_injected_commas.strip_injected(before, after)
        self.assertEqual(output, after)
        self.assertEqual(report['commas_removed'], 0)


class SanitizeTest(unittest.TestCase):
    def test_compatibility_hanja_and_signs_are_not_rewritten(self):
        text = ''.join(map(chr, (0xF9E1, 0x6587, 0x5B78, 0x20, 0xF914, 0x5712, 0x20, 0xF95C, 0x5712,
                                 0x20, 0x31, 0x212B, 0x20, 0x31, 0x30, 0x2126)))
        cleaned, _ = sanitize_text.sanitize(text)
        self.assertEqual(cleaned, text)

    def test_decomposed_hangul_is_still_recomposed(self):
        decomposed = '한글'  # 한글 in conjoining jamo
        cleaned, report = sanitize_text.sanitize(decomposed + ' 문장')
        self.assertEqual(cleaned, '한글 문장')
        self.assertEqual(report.counts['hangul_recomposed'], 2)


class LargeDocumentGateTest(unittest.TestCase):
    def test_full_document_gate_stays_fast_on_long_prose(self):
        import random
        random.seed(11)
        subjects = ['우리 팀은', '연구진은', '담당자는', '회사는', '학생들은', '시민들은', '위원회는', '개발자는']
        objects = ['새로운 방식을', '기존 절차를', '자료의 정리를', '업무 흐름을', '검토 결과를', '운영 계획을']
        verbs = ['도입하였다', '개선하였다', '검토하였다', '정리하였다', '공유하였다', '보완하였다']
        adverbs = ['지난 분기에', '올해 초에', '최근에', '회의 직후에', '연말을 앞두고', '꾸준히']
        paragraphs, total = [], 0
        while total < 60000:
            paragraph = ' '.join(f'{random.choice(subjects)} {random.choice(adverbs)} {random.choice(objects)} '
                                 f'{random.choice(verbs)}.' for _ in range(random.randint(3, 6)))
            paragraphs.append(paragraph)
            total += len(paragraph) + 2
        source = '\n\n'.join(paragraphs) + '\n'
        candidate = source.replace('하였다', '했다')
        with tempfile.TemporaryDirectory() as folder:
            before, after = Path(folder) / 'before.txt', Path(folder) / 'after.txt'
            before.write_text(source, encoding='utf-8')
            after.write_text(candidate, encoding='utf-8')
            started = time.monotonic()
            result = verify(before, after, attempt=2)
            elapsed = time.monotonic() - started
        self.assertLess(elapsed, 30, f'full-document gate took {elapsed:.1f}s')
        self.assertEqual(result['hardFailures'], [])


class CrossChunkFootnoteTest(unittest.TestCase):
    """R2-3.1: a chunk gate and the full-document gate agree on footnote definitions."""
    BODY = '선행 연구에 따르면 참여율은 높았다.1) 후속 조사에서도 비슷한 결과가 보고되었다.2)\n\n'
    DEFS = '1) 여기서 참여율은 전체 등록자 대비 실제 응답자의 비율을 말한다.\n2) 통계청, 2025년 조사 보고서.\n'

    def test_last_chunk_definition_edit_fails_with_the_full_source_markers(self):
        edited = self.DEFS.replace('전체 등록자 대비 실제 응답자의 비율을 말한다', '등록자 가운데 실제로 응답한 사람의 비율이다')
        with tempfile.TemporaryDirectory() as folder:
            full, chunk, output = (Path(folder) / name for name in ('full.txt', 'chunk.txt', 'out.txt'))
            full.write_text(self.BODY + self.DEFS, encoding='utf-8')
            chunk.write_text(self.DEFS, encoding='utf-8')
            output.write_text(edited, encoding='utf-8')
            result = verify(chunk, output, attempt=2, context=full)
            self.assertIn('footnote_def', result['hardFailures'])
            output.write_text(self.BODY + edited, encoding='utf-8')
            self.assertIn('footnote_def', verify(full, output, attempt=2)['hardFailures'])


class RoundTwoGateTest(GateCase):
    def test_nouns_that_contain_numerals_are_not_quantities(self):
        for source, candidate in [('젊은 세대는 변화를 원한다.\n', '청년층은 변화를 원한다.\n'),
                                  ('세대 간 갈등이 깊다.\n', '연령대 간 갈등이 깊다.\n'),
                                  ('열대 지방은 덥다.\n', '더운 지방은 덥다.\n'),
                                  ('자원을 십분 활용했다.\n', '자원을 충분히 활용했다.\n'),
                                  ('천장이 높은 방이다.\n', '층고가 높은 방이다.\n')]:
            with self.subTest(candidate=candidate):
                result, _ = self.run_gate(source, candidate, 2)
                self.assertNotIn('quantity_changed', result['hardFailures'])

    def test_a_number_drop_is_not_masked_by_a_look_alike_noun(self):
        result, _ = self.run_gate('성장률은 3배를 기록했다. 젊은 층이 이를 주도했다.\n',
                                  '성장률이 크게 올랐다. 젊은 세대가 이를 주도했다.\n', 2)
        self.assertTrue({'quantity_changed', 'number_dropped'} & set(result['hardFailures']), result)

    def test_name_casing_and_repeated_mentions_are_not_name_changes(self):
        for source, candidate in [('우리는 javascript로 만들었다.\n', '우리는 JavaScript로 만들었다.\n'),
                                  ('Github 저장소를 열었다.\n', 'GitHub 저장소를 열었다.\n'),
                                  ('Covid-19 이후 달라졌다.\n', 'COVID-19 이후 달라졌다.\n'),
                                  ('API 서버와 API 클라이언트를 함께 배포한다.\n', 'API 서버와 클라이언트를 함께 배포한다.\n'),
                                  ('이 제도는 향약(鄕約)에서 비롯되었다. 향약(鄕約)은 마을의 자치 규약이었다.\n',
                                   '이 제도는 향약(鄕約)에서 비롯되었다. 향약은 마을의 자치 규약이었다.\n')]:
            with self.subTest(candidate=candidate):
                result, _ = self.run_gate(source, candidate, 2)
                self.assertNotIn('name_changed', result['hardFailures'])

    def test_parallel_sentence_hedge_is_restored(self):
        _, output = self.run_gate('서울의 매출은 늘 수 있다. 부산의 매출은 늘었다.\n',
                                  '서울의 매출은 늘었다. 부산의 매출은 늘었다.\n', restore_first=True)
        self.assertIn('서울의 매출은 늘 수 있다.', output)

    def test_parallel_sentences_sharing_a_template_are_still_dropped(self):
        for source, candidate in [('회사는 신규 공장을 짓기로 했다. 회사는 기존 공장을 닫기로 했다. 투자 규모는 공개하지 않았다.\n',
                                   '회사는 신규 공장을 짓기로 했다. 투자 규모는 공개하지 않았다.\n'),
                                  ('여당은 법안에 찬성했다. 야당은 법안에 반대했다. 표결은 다음 주에 열린다.\n',
                                   '여당은 법안에 찬성했다. 표결은 다음 주에 열린다.\n')]:
            with self.subTest(candidate=candidate):
                result, _ = self.run_gate(source, candidate, 2)
                self.assertIn('sentence_dropped', result['hardFailures'])

    def test_loose_and_nested_lists_are_not_headings(self):
        for source, candidate in [('## 빠른 시작\n\n1. 저장소를 내려받습니다\n\n2. 환경 변수 파일을 복사합니다\n\n3. 개발 서버를 실행합니다\n',
                                   '## 빠른 시작\n\n1. 저장소를 내려받습니다\n\n2. 환경 변수 파일을 복사해 둡니다\n\n3. 개발 서버를 실행합니다\n'),
                                  ('## 배포\n\n1. 빌드 결과물을 확인합니다\n   - dist 폴더를 확인합니다\n2. 서버에 업로드합니다\n   - scp 명령을 사용합니다\n',
                                   '## 배포\n\n1. 빌드 결과물을 확인합니다\n   - dist 폴더를 확인합니다\n2. 서버에 올립니다\n   - scp 명령을 사용합니다\n')]:
            with self.subTest(candidate=candidate):
                result, _ = self.run_gate(source, candidate, 2)
                self.assertNotIn('heading_lost', result['hardFailures'])

    def test_table_of_contents_and_non_consecutive_headings_stay_protected(self):
        for source, candidate in [('목차\n1. 서론\n2. 연구 방법\n3. 결론\n\n본문이다.\n', '목차\n1. 서론\n2. 분석 절차\n3. 결론\n\n본문이다.\n'),
                                  ('2. 추진 계획\n1. 시범 운영 지역을 선정한다\n\n본문 내용이다.\n',
                                   '2. 향후 과제\n1. 시범 운영 지역을 선정한다\n\n본문 내용이다.\n')]:
            with self.subTest(candidate=candidate):
                result, _ = self.run_gate(source, candidate, 2)
                self.assertIn('heading_lost', result['hardFailures'])

    def test_definition_block_before_a_heading_is_protected(self):
        source = '선행 연구에 따르면 참여율은 높았다.1)\n\n1) 김철수, 참여 연구의 방법, 한국학회.\n\n## 부록\n\n설문지 원본을 싣는다.\n'
        result, _ = self.run_gate(source, source.replace('참여 연구의 방법', '참여 조사의 설계'), 2)
        self.assertIn('footnote_def', result['hardFailures'])

    def test_hyphenated_version_is_not_a_footnote_marker(self):
        source = '지원 환경(Python, Node, GPT-4)을 먼저 확인하세요.\n\n1) 저장소 복제\n2) 의존성 설치\n3) 환경 변수 설정\n4) 서버를 실행한다\n'
        result, _ = self.run_gate(source, source.replace('서버를 실행한다', '서버를 띄운다'), 2)
        self.assertNotIn('footnote_def', result['hardFailures'])

    def test_counts_before_copulas_and_polite_endings_are_compared(self):
        for source, candidate in [('이번 개편의 목적은 세 가지다.\n', '이번 개편의 목적은 네 가지다.\n'),
                                  ('참석자는 두 명입니다.\n', '참석자는 세 명입니다.\n')]:
            with self.subTest(candidate=candidate):
                result, _ = self.run_gate(source, candidate, 2)
                self.assertIn('quantity_changed', result['hardFailures'])

    def test_unit_spacing_and_magnitude_notation_are_the_same_quantity(self):
        for source, candidate in [('예산은 5억원이다.\n', '예산은 5억 원이다.\n'),
                                  ('참가자는 10,000명이다.\n', '참가자는 1만 명이다.\n'),
                                  ('후원금은 1만 원이다.\n', '후원금은 10,000원이다.\n')]:
            with self.subTest(candidate=candidate):
                result, _ = self.run_gate(source, candidate, 2)
                self.assertNotIn('quantity_changed', result['hardFailures'])
        result, _ = self.run_gate('예산은 5억원이다.\n', '예산은 6억 원이다.\n', 2)
        self.assertIn('quantity_changed', result['hardFailures'])


class RoundTwoCommaTest(unittest.TestCase):
    def test_noun_list_of_go_final_nouns_keeps_commas(self):
        output, report = strip_injected_commas.strip_injected('주요 비용은 재고와 창고와 광고비로 구분된다.\n',
                                                              '주요 비용은 재고, 창고, 광고비로 구분된다.\n')
        self.assertIn('재고, 창고, 광고비로', output)
        self.assertEqual(report['commas_removed'], 0)


if __name__ == '__main__':
    unittest.main()
