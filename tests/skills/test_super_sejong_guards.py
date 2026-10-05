"""Super Sejong meaning guards (engine_runtime/super_sejong.py).

Preserved/Changed/Roles cases come from the 2026-10-04 guard review; the evaluation-set test
locks in the measured rates so that later rule changes cannot silently regress them.
"""
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from engine_runtime import super_sejong as ss
from engine_runtime.workflow import verify

DATA = Path(__file__).resolve().parent / 'data' / 'super_sejong_pairs.json'


def flagged(source, candidate):
    """Union of the four workflow guards plus the Office document drift guard."""
    return {
        'polarity': ss.changed_polarity(source, candidate),
        'modality': ss.changed_sentence_modality(source, candidate),
        'lexical': ss.changed_lexical_polarity(source, candidate),
        'roles': ss.changed_participant_roles(source, candidate),
        'drift': ss.document_sentence_drift(source, candidate),
    }


class Preserved(unittest.TestCase):
    PAIRS = [
        ('이 방식으로는 해결이 불가능하다.', '이 방식으로는 해결이 가능하지 않다.'),
        ('올해 안에 완공하기는 어렵다.', '올해 안에 완공하기는 쉽지 않다.'),
        ('설명 없이 결정이 내려졌다.', '설명하지 않고 결정이 내려졌다.'),
        ('이 앱은 속도뿐만 아니라 안정성도 좋다.', '이 앱은 속도에 더해 안정성도 좋다.'),
        ('그의 실력은 프로 못지않다.', '그의 실력은 프로 수준이다.'),
        ('잘못 입력된 값은 자동으로 수정된다.', '오입력된 값은 자동으로 수정된다.'),
        ('그는 어쩔 수 없이 계약을 받아들였다.', '그는 불가피하게 계약을 받아들였다.'),
        ('그 일은 곧 끝난다.', '그 일은 머지않아 끝난다.'),
        ('이것은 단순한 실수가 아니라 구조적 문제다.', '이것은 단순한 실수가 아닌 구조적 문제다.'),
        ('그 팀은 틀림없이 이길 것이다.', '그 팀이 이길 것은 확실하다.'),
        ('서울은 한국의 수도이다.', '서울이 한국의 수도이다.'),
        ('경찰이 범인을 체포했다.', '범인이 경찰에게 체포되었다.'),
        ('정부가 보고서를 발표했다.', '보고서가 정부에 의해 발표되었다.'),
        ('기자가 총리를 인터뷰했다.', '총리가 기자에게 인터뷰를 받았다.'),
        ('비가 올 가능성이 크다.', '비가 올 확률이 크다.'),
        ('비용이 늘었다.', '비용이 증가했다.'),
        ('보고서를 제출해야 한다.', '보고서의 제출이 필요하다.'),
        ('마스크 착용은 금지되어 있다.', '마스크를 착용해서는 안 된다.'),
        ('참가자는 10명 이상이어야 한다.', '참가자는 열 명 이상이어야 한다.'),
        ('가격은 5만 원 이하이다.', '가격은 50,000원 이하이다.'),
        ('비가 왔다. 그래서 행사가 취소되었다.', '비가 와서 행사가 취소되었다.'),
        ('그는 아침에 일어나 운동하고 샤워한 뒤 출근했다.', '그는 아침에 일어나 운동했다. 샤워한 뒤에는 출근했다.'),
        ('환자는 이 약을 임의로 중단해서는 안 됩니다.', '환자는 이 약을 마음대로 끊으면 안 됩니다.'),
        ('이 문제는 혼자서 풀기에는 어렵다.', '이 문제는 혼자서 풀기에는 쉽지 않다.'),
        ('그는 영어뿐 아니라 중국어도 한다.', '그는 영어와 함께 중국어도 한다.'),
        # 필요로 하다 -> 필요하다, the translationese fix (2026-10-04 v2 Tier-B finding)
        ('행사 참가자는 신분증을 필요로 합니다.', '행사 참가자는 신분증이 필요합니다.'),
        ('이 작업은 많은 시간을 필요로 한다.', '이 작업에는 많은 시간이 필요하다.'),
        ('이 기능은 별도 설치를 필요로 하지 않는다.', '이 기능은 별도 설치가 필요하지 않다.'),
    ]

    def test_meaning_preserving_rewrites_are_not_flagged(self):
        for source, candidate in self.PAIRS:
            with self.subTest(source=source):
                self.assertFalse(any(flagged(source, candidate).values()), flagged(source, candidate))

    def test_nouns_in_su_and_geo_are_not_the_bound_nouns(self):
        # code review 2026-10-05: 실수/일수/말수 are nouns, not 할 수; 증거/근거/과거/이거 are not the hedge 거 같다
        for source, candidate in [('실수가 없도록 주의하세요.', '실수하지 않도록 주의하세요.'),
                                  ('실수가 있었습니다.', '제가 잘못했습니다.'),
                                  ('근무 일수가 없는 경우 지급하지 않습니다.', '근무한 날이 없으면 지급하지 않습니다.'),
                                  ('그는 말수가 없는 편이다.', '그는 말수가 없는 사람이다.'),
                                  ('확실한 증거 같은 게 있어요.', '확실한 증거가 있어요.'),
                                  ('근거 같은 건 없어요.', '근거라고 할 만한 건 없어요.'),
                                  ('요즘은 과거 같지 않아요.', '요즘은 예전과 달라요.'),
                                  ('이거 같이 먹자.', '이것을 함께 먹자.')]:
            with self.subTest(source=source):
                self.assertFalse(any(flagged(source, candidate).values()), flagged(source, candidate))

    def test_spacing_only_changes_never_flag(self):
        for source, candidate in [('할 수있다.', '할 수 있다.'), ('할 수 있다.', '할 수  있다.'),
                                  ('서류를 제출하면 안됩니다.', '서류를 제출하면 안 됩니다.'),
                                  ('그 사건의 배후가 있을 수 있다.', '그 사건의  배후가  있을 수  있다.'),
                                  # attached bound noun 수, fixed by the writer (2026-10-04 live false positive)
                                  ('참가를 원하시는 분은 15일까지 신청하실수 있어요.', '참가를 원하시는 분은 15일까지 신청하실 수 있어요.'),
                                  ('그날은 비가 와서 볼수 없었다.', '그날은 비가 와서 볼 수 없었다.'),
                                  ('혼자서는 할수가 없다.', '혼자서는 할 수가 없다.'),
                                  ('누구나 참여할수도 있다.', '누구나 참여할 수도 있다.'),
                                  # attached 안 + 되다 and the 되요 misspelling, fixed by the writer
                                  ('그건 안되요.', '그건 안 돼요.'), ('그건 안돼요.', '그건 안 돼요.'),
                                  ('거기 가면 안되나요?', '거기 가면 안 되나요?'), ('벌써 다 됬어요.', '벌써 다 됐어요.'),
                                  # spoken 거 of 거 같다 is the 것 of the hedge (2026-10-04 real-model run)
                                  ('역시 가을 산이 최고인거 같아.', '역시 가을 산이 최고인 것 같아.'),
                                  ('그게 맞는 거 같아.', '그게 맞는 것 같아.'), ('내일은 비가 올거 같아요.', '내일은 비가 올 거 같아요.'),
                                  ('문제일수 있다.', '문제일 수 있다.')]:
            with self.subTest(source=source):
                self.assertFalse(any(flagged(source, candidate).values()))


class Changed(unittest.TestCase):
    def assertCaught(self, source, candidate, *guards):
        result = flagged(source, candidate)
        self.assertTrue(any(result[g] for g in guards) if guards else any(result.values()), (source, candidate, result))

    def test_negation_and_type(self):
        for s, c in [('서버가 정상적으로 작동한다.', '서버가 정상적으로 작동하지 않는다.'),
                     ('이 약은 부작용이 없다.', '이 약은 부작용이 있다.'),
                     ('그는 술을 마시지 않는다.', '그는 술을 마시지 못한다.'),
                     ('그는 안 먹는다.', '그는 못 먹는다.'),
                     ('답이 틀리지 않았다.', '답이 틀렸다.'),
                     ('그는 안 먹고 집에 갔다.', '그는 먹고 집에 안 갔다.')]:
            with self.subTest(s=s):
                self.assertCaught(s, c, 'polarity', 'modality', 'lexical')

    def test_attached_forms_still_read_meaning(self):
        # the spacing normalisation must not hide a real change: attached 할수 있다 / 안됐다 still count
        for s, c in [('그는 범인일수 있다.', '그는 범인이다.'), ('오늘은 갈수 없다.', '오늘은 갈 수 있다.'),
                     ('일이 다 안됐어요.', '일이 다 됐어요.'),
                     ('이 기능은 별도 설치를 필요로 한다.', '이 기능은 별도 설치가 필요하지 않다.'),
                     ('내일은 비가 올 거 같아요.', '내일은 비가 와요.')]:
            with self.subTest(s=s):
                self.assertCaught(s, c, 'polarity', 'modality', 'lexical')

    def test_modality_and_obligation(self):
        for s, c in [('그는 범인일 수 있다.', '그는 범인이다.'), ('결과는 좋을 것으로 예상된다.', '결과는 좋다.'),
                     ('이번 조치로 물가가 안정될 것으로 기대한다.', '이번 조치로 물가가 안정된다.'),
                     ('직원은 보고서를 작성해야 한다.', '직원은 보고서를 작성할 수 있다.'),
                     ('수강을 권장한다.', '수강을 의무화한다.'),
                     ('서류를 가져오면 좋다.', '서류를 가져와야 한다.'),
                     ('이 방법은 확실하다.', '이 방법은 불확실하다.'),
                     ('내일 눈이 올 가능성이 높다.', '내일 눈이 올 가능성이 낮다.'),
                     ('그 계획은 가능하다.', '그 계획은 불가능하다.'),
                     ('참석은 선택 사항이다.', '참석은 필수 사항이다.')]:
            with self.subTest(s=s):
                self.assertCaught(s, c, 'modality', 'lexical')

    def test_roles(self):
        for s, c in [('영희가 민수를 도왔다.', '민수가 영희를 도왔다.'),
                     ('경찰이 범인을 체포했다.', '경찰이 범인에게 체포되었다.'),
                     ('A사가 B사를 인수했다.', 'A사가 B사에 인수되었다.'),
                     ('민수가 영희에게 책을 빌렸다.', '민수가 영희에게 책을 빌려주었다.'),
                     ('원청이 하청업체에 대금을 지급했다.', '하청업체가 원청에 대금을 지급했다.'),
                     ('직원은 관리자를 돕는다.', '직원을 관리자는 돕는다.'),
                     ('그는 사과만 샀다.', '그는 사과도 샀다.'),
                     ('이 길이 저 길보다 빠르다.', '저 길이 이 길보다 빠르다.')]:
            with self.subTest(s=s):
                self.assertCaught(s, c, 'roles', 'lexical')

    def test_antonyms_beyond_the_original_two_pairs(self):
        pairs = [('주가가 상승했다.', '주가가 하락했다.'), ('정부는 지원을 확대했다.', '정부는 지원을 축소했다.'),
                 ('당국은 외출을 허용했다.', '당국은 외출을 금지했다.'), ('실험은 성공했다.', '실험은 실패했다.'),
                 ('회사는 흑자를 기록했다.', '회사는 적자를 기록했다.'), ('금리를 인상했다.', '금리를 인하했다.'),
                 ('그는 주식을 매수했다.', '그는 주식을 매도했다.'), ('그는 시험에 합격했다.', '그는 시험에 불합격했다.'),
                 ('팀이 경기에서 승리했다.', '팀이 경기에서 패배했다.'), ('피고인은 유죄 판결을 받았다.', '피고인은 무죄 판결을 받았다.'),
                 ('그는 혐의를 인정했다.', '그는 혐의를 부인했다.'), ('비행기가 서울에 도착했다.', '비행기가 서울에서 출발했다.'),
                 ('의회는 예산안을 가결했다.', '의회는 예산안을 부결했다.'), ('보안이 강화되었다.', '보안이 약화되었다.'),
                 ('위원회는 신청서를 승인했다.', '위원회는 신청서를 거절했다.'), ('올해 매출은 증가했다.', '올해 매출은 감소했다.')]
        for s, c in pairs:
            with self.subTest(s=s):
                self.assertTrue(ss.changed_lexical_polarity(s, c) or ss.changed_sentence_modality(s, c), (s, c))

    def test_bounds_comparatives_and_time(self):
        for s, c in [('참가자는 10명 이상이어야 한다.', '참가자는 10명 이하여야 한다.'),
                     ('만 18세 미만은 입장할 수 없다.', '만 18세 이하는 입장할 수 없다.'),
                     ('점수가 70점 이상이면 합격이다.', '점수가 70점 초과이면 합격이다.'),
                     ('가격은 최대 1만 원이다.', '가격은 최소 1만 원이다.'),
                     ('서울이 부산보다 크다.', '서울이 부산보다 작다.'),
                     ('올해 매출이 작년보다 높다.', '올해 매출이 작년보다 낮다.'),
                     ('식사 전에 약을 먹는다.', '식사 후에 약을 먹는다.'),
                     ('그는 졸업하기 전에 취직했다.', '그는 졸업한 후에 취직했다.'),
                     ('수술 이후 열이 났다.', '수술 이전 열이 났다.'),
                     ('먼저 신청하고 나중에 결제한다.', '먼저 결제하고 나중에 신청한다.'),
                     ('모든 학생이 합격했다.', '일부 학생이 합격했다.'),
                     ('주민 대부분이 찬성했다.', '주민 일부가 찬성했다.')]:
            with self.subTest(s=s):
                self.assertCaught(s, c)

    def test_unchanged_sentence_with_two_order_frames_is_not_a_swap(self):
        for s in ('회의에 들어가기 전에 자료를 다시 읽으면 회의가 끝난 후에 질문이 훨씬 줄어든다.',
                  '계약하기 전에 서류를 확인하면 계약한 후에 문제가 생기지 않습니다.'):
            with self.subTest(s=s):
                self.assertFalse(any(flagged(s, s).values()), flagged(s, s))
        self.assertCaught('서류를 낸 후에 수수료를 냅니다.', '수수료를 낸 후에 서류를 냅니다.')

    def test_document_drift_dropped_sentence(self):
        self.assertTrue(ss.document_sentence_drift('서버가 멈췄다. 원인을 찾았다. 조치를 완료했다.', '서버가 멈췄다. 조치를 완료했다.'))
        self.assertTrue(ss.document_sentence_drift('서버가 멈췄다. 원인을 찾았다.', '서버가 멈췄다. 원인을 찾지 못했다.'))


class Compat(unittest.TestCase):
    def test_public_names(self):
        for name in ('sentences', 'polarity_count', 'short_negation_targets', 'obligation_count', 'changed_polarity',
                     'changed_participant_roles', 'changed_sentence_modality', 'changed_lexical_polarity',
                     'document_sentence_drift'):
            self.assertTrue(callable(getattr(ss, name)), name)

    def test_existing_repo_expectations(self):
        self.assertEqual(ss.polarity_count('신고 대상이 아닌 경우'), 1)
        self.assertTrue(ss.changed_polarity('이 신청은 신고 대상이 아닙니다.', '이 신청은 신고 대상입니다.'))
        self.assertFalse(ss.changed_polarity('서류를 제출하면 안됩니다.', '서류를 제출하면 안 됩니다.'))
        self.assertFalse(ss.changed_participant_roles('민수는 책을 읽었다.', '민수가 책을 읽었다.'))
        self.assertEqual(ss.sentences('가격은 3.5 퍼센트다. 다음 문장이다.'), ['가격은 3.5 퍼센트다.', '다음 문장이다.'])


class Performance(unittest.TestCase):
    """Linear-time guard: 100k-character adversarial inputs must stay well under a second or two."""
    N = 100_000

    def run_all(self, text):
        t = time.perf_counter()
        ss.changed_polarity(text, text)
        ss.changed_sentence_modality(text, text)
        ss.changed_lexical_polarity(text, text)
        ss.changed_participant_roles(text, text)
        ss.document_sentence_drift(text, text)
        return time.perf_counter() - t

    def test_adversarial_100k(self):
        rep = lambda unit: (unit * (self.N // len(unit) + 1))[:self.N]
        for name, text in {'digits': rep('1'), 'digits_commas': rep('1,'), 'digit_space': rep('1 '), 'hangul': rep('가'),
                           'neg_dense': rep('않없못아니'), 'short_neg': rep('안 '), 'particles': rep('철수는영희를'),
                           'bounds': rep('30분 이상 최대 3명 '), 'compare': rep('올해 매출은 작년보다 많다. '),
                           'axis': rep('증가 감소 가능하지 않다 '), 'man_words': rep('만 ' + '가' * 40 + ' '),
                           'tiny_sentences': rep('가. '), 'spaces': rep(' ')}.items():
            with self.subTest(case=name):
                self.assertLess(self.run_all(text), 3.0)




class LeadCases(unittest.TestCase):
    def test_reworded_negation_and_double_negation_are_preserving(self):
        for source, candidate in [('비용을 줄이지 않으면 안 됩니다.', '비용을 줄여야 합니다.'),
                                  ('그는 그 사실을 알지 못했다.', '그는 그 사실을 몰랐다.'),
                                  ('그는 틀림없이 온다.', '그는 반드시 온다.'),
                                  ('이 제도는 누구나 이용할 수 있다.', '누구든 이 제도를 이용할 수 있다.')]:
            with self.subTest(source=source):
                self.assertFalse(any(flagged(source, candidate).values()), flagged(source, candidate))

    def test_short_negation_with_any_ending_and_more_axes_are_caught(self):
        for source, candidate in [('그는 학교에 안 갔어.', '그는 학교에 갔어.'),
                                  ('비가 와서 안 가니까 괜찮다.', '비가 와서 가니까 괜찮다.'),
                                  ('그건 안 해도 된다.', '그건 해도 된다.'),
                                  ('그는 그 사실을 알았다.', '그는 그 사실을 몰랐다.'),
                                  ('내년 예산을 늘린다.', '내년 예산을 줄인다.'),
                                  ('우리 팀이 상대 팀을 이겼다.', '상대 팀이 우리 팀을 이겼다.')]:
            with self.subTest(source=source):
                self.assertTrue(any(flagged(source, candidate).values()), (source, candidate))

    def test_never_again_idiom_is_not_a_count(self):
        from engine_runtime.quantities import signed_quantities
        self.assertEqual(signed_quantities('그런 일은 두 번 다시 없다.'), signed_quantities('그런 일은 다시는 없다.'))
        self.assertNotEqual(signed_quantities('두 번 확인했다.'), signed_quantities('세 번 확인했다.'))

    def test_locative_an_is_not_negation(self):
        self.assertFalse(any(flagged('상자 안 자료를 확인했다.', '상자 안에 든 자료를 확인했다.').values()))


class EvaluationSet(unittest.TestCase):
    # Measured 2026-10-04. 'res1' was never used for tuning; the others were.
    LIMITS = {'lead': (0.10, 0.05), 'res1': (0.15, 0.20), 'code1': (0.05, 0.02)}

    def test_rates_per_author_set(self):
        pairs = json.loads(DATA.read_text(encoding='utf-8'))['pairs']
        for name, (max_over, max_unsafe) in self.LIMITS.items():
            rows = [p for p in pairs if p['set'] == name]
            preserve = [p for p in rows if p['label'] == 'preserve']
            change = [p for p in rows if p['label'] == 'change']
            over = sum(any(flagged(p['source'], p['rewrite']).values()) for p in preserve) / len(preserve)
            unsafe = sum(not any(flagged(p['source'], p['rewrite']).values()) for p in change) / len(change)
            with self.subTest(set=name):
                self.assertLessEqual(over, max_over)
                self.assertLessEqual(unsafe, max_unsafe)


class FullGatePerformance(unittest.TestCase):
    def test_long_paragraph_without_line_breaks_stays_fast(self):
        # Pasted text often has no line breaks; the change-rate diff used to be quadratic on it
        # (20k repetitive chars took 86 s, past the 120 s Python timeout at 85k).
        source = ''.join(f'{i}번째 문장은 강한 경쟁력을 가지고 있다. 서울 지사는 {i}명이고 그는 “승인한다”고 말했다. ' for i in range(700))
        output = source.replace('가지고 있다', '갖추고 있다')
        with tempfile.TemporaryDirectory() as folder:
            before, after = Path(folder) / 'before.txt', Path(folder) / 'after.txt'
            before.write_text(source, encoding='utf-8')
            after.write_text(output, encoding='utf-8')
            started = time.perf_counter()
            verify(before, after, attempt=2)
            self.assertLess(time.perf_counter() - started, 20.0)


class Modes(unittest.TestCase):
    def gate(self, source, candidate):
        with tempfile.TemporaryDirectory() as folder:
            before, after = Path(folder) / 'before.txt', Path(folder) / 'after.txt'
            before.write_text(source, encoding='utf-8')
            after.write_text(candidate, encoding='utf-8')
            return verify(before, after, attempt=1)

    def test_shadow_reports_without_blocking_and_off_skips(self):
        source, candidate = '요청을 승인했다.\n', '요청을 반려했다.\n'
        previous = os.environ.get('SUPER_SEJONG_MODE')
        try:
            os.environ['SUPER_SEJONG_MODE'] = 'enforce'
            self.assertIn('lexical_polarity_changed', self.gate(source, candidate)['hardFailures'])
            os.environ['SUPER_SEJONG_MODE'] = 'shadow'
            shadow = self.gate(source, candidate)
            self.assertNotIn('lexical_polarity_changed', shadow['hardFailures'])
            self.assertIn('lexical_polarity_changed', shadow['shadowFailures'])
            os.environ['SUPER_SEJONG_MODE'] = 'off'
            off = self.gate(source, candidate)
            self.assertNotIn('lexical_polarity_changed', off['hardFailures'])
            self.assertNotIn('shadowFailures', off)
        finally:
            if previous is None:
                os.environ.pop('SUPER_SEJONG_MODE', None)
            else:
                os.environ['SUPER_SEJONG_MODE'] = previous


if __name__ == '__main__':
    unittest.main()
