from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from engine_runtime.workflow import verify
from engine_runtime.super_sejong import polarity_count


class ContentFidelityTest(unittest.TestCase):
    def gate(self, source, candidate, attempt):
        with tempfile.TemporaryDirectory() as folder:
            before, after = Path(folder) / 'before.txt', Path(folder) / 'after.txt'
            suffix = ' 다음 문장은 그대로 둔다. 마지막 문장도 그대로다.\n'
            before.write_text(source + suffix, encoding='utf-8')
            after.write_text(candidate + suffix, encoding='utf-8')
            return verify(before, after, attempt=attempt)

    def test_signed_quantities_and_units_cannot_change(self):
        for source, candidate in [('올해 수익률은 -5%다.', '올해 수익률은 5%다.'),
                                  ('최종 권장량은 5mg이다.', '최종 권장량은 5g이다.'),
                                  ('배송은 세 시간 걸렸다.', '배송은 세 분 걸렸다.'),
                                  ('배송은 3시간 걸렸다.', '배송은 3분 걸렸다.')]:
            for attempt, policy in [(1, 'retry'), (2, 'rollback')]:
                with self.subTest(source=source, attempt=attempt):
                    result = self.gate(source, candidate, attempt)
                    self.assertEqual(result['policy'], policy)
                    self.assertIn('quantity_changed', result['hardFailures'])

    def test_short_attributed_speech_is_immutable(self):
        result = self.gate('담당자는 "승인한다"라고 말했다.', '담당자는 "거부한다"라고 말했다.', 2)
        self.assertEqual(result['policy'], 'rollback')
        self.assertIn('quote_altered', result['hardFailures'])

    def test_number_formatting_and_unchanged_quotes_stay_valid(self):
        result = self.gate('가격은 1,000원이다. 담당자는 "승인한다"라고 말했다.',
                           '가격은 1000원이다. 담당자는 "승인한다"라고 말했다.', 1)
        self.assertEqual(result['hardFailures'], [])

    def test_written_and_digit_duration_are_equivalent(self):
        result = self.gate('배송은 세 시간 걸렸다.', '배송은 3시간 걸렸다.', 1)
        self.assertNotIn('quantity_changed', result['hardFailures'])

    def test_predicate_negation_cannot_flip_in_either_direction(self):
        for source, candidate in [
            ('서비스를 이용하지 않는다.', '서비스를 이용한다.'),
            ('서비스를 이용한다.', '서비스를 이용하지 않는다.'),
        ]:
            with self.subTest(source=source):
                result = self.gate(source, candidate, 2)
                self.assertEqual(result['policy'], 'rollback')
                self.assertIn('polarity_changed', result['hardFailures'])

    def test_negative_copula_cannot_flip_in_either_direction(self):
        for source, candidate in [
            ('이 신청은 신고 대상이 아닙니다.', '이 신청은 신고 대상입니다.'),
            ('이 신청은 신고 대상입니다.', '이 신청은 신고 대상이 아닙니다.'),
        ]:
            with self.subTest(source=source):
                result = self.gate(source, candidate, 2)
                self.assertEqual(result['policy'], 'rollback')
                self.assertIn('polarity_changed', result['hardFailures'])

    def test_attributive_negative_copula_is_still_negative(self):
        self.assertEqual(polarity_count('신고 대상이 아닌 경우'), 1)

    def test_spacing_correction_for_an_doeda_keeps_negative_meaning(self):
        result = self.gate('서류를 제출하면 안됩니다.', '서류를 제출하면 안 됩니다.', 2)
        self.assertNotIn('polarity_changed', result['hardFailures'])

    def test_participant_roles_cannot_swap(self):
        result = self.gate('직원은 관리자를 돕는다.', '직원을 관리자는 돕는다.', 2)
        self.assertEqual(result['policy'], 'rollback')
        self.assertIn('participant_role_changed', result['hardFailures'])

    def test_reordered_participants_cannot_exchange_roles(self):
        result = self.gate('민수는 지수를 도왔다.', '지수는 민수를 도왔다.', 2)
        self.assertIn('participant_role_changed', result['hardFailures'])

    def test_short_negation_before_a_connective_is_preserved(self):
        result = self.gate('그는 안 먹고 집에 갔다.', '그는 먹고 집에 갔다.', 2)
        self.assertIn('polarity_changed', result['hardFailures'])

    def test_short_negation_cannot_move_between_predicates(self):
        result = self.gate('그는 안 먹고 집에 갔다.', '그는 먹고 집에 안 갔다.', 2)
        self.assertIn('polarity_changed', result['hardFailures'])

    def test_one_hour_is_not_one_minute(self):
        result = self.gate('배송은 한 시간 걸렸다.', '배송은 한 분 걸렸다.', 2)
        self.assertIn('quantity_changed', result['hardFailures'])

    def test_duration_units_and_one_are_normalized(self):
        for before, after in [('행사는 세 달 이어졌다.', '행사는 세 주 이어졌다.'),
                              ('행사는 3달 이어졌다.', '행사는 3주 이어졌다.')]:
            with self.subTest(before=before):
                self.assertIn('quantity_changed', self.gate(before, after, 2)['hardFailures'])
        self.assertNotIn('quantity_changed', self.gate('한 시간 걸렸다.', '1시간 걸렸다.', 2)['hardFailures'])

    def test_possibility_cannot_move_to_a_different_sentence(self):
        before = '서울 사업은 내년부터 시행이 가능하다. 부산 사업은 현재 시행이 어렵다.'
        after = '서울 사업은 내년부터 시행이 어렵다. 부산 사업은 현재 시행이 가능하다.'
        self.assertIn('modality_changed', self.gate(before, after, 2)['hardFailures'])

    def test_clear_decision_and_trend_antonyms_cannot_flip(self):
        for before, after in [('위원회는 신청서를 승인했다.', '위원회는 신청서를 거절했다.'),
                              ('올해 매출은 증가했다.', '올해 매출은 감소했다.')]:
            with self.subTest(before=before):
                self.assertIn('lexical_polarity_changed', self.gate(before, after, 2)['hardFailures'])

    def test_topic_to_subject_particle_can_be_a_valid_rewrite(self):
        result = self.gate('민수는 책을 읽었다.', '민수가 책을 읽었다.', 2)
        self.assertNotIn('participant_role_changed', result['hardFailures'])

    def test_rhetorical_quotes_do_not_become_immutable(self):
        result = self.gate('이것이 "정답"일까?', '이것이 "해답"일까?', 2)
        self.assertNotIn('quote_altered', result['hardFailures'])
