"""Shared signed-number and recognized-unit invariant for text and Office."""
from collections import Counter
from decimal import Decimal
import re

# 숫자에 바로 붙은 천·백·만·억·조는 자릿값이다. 자릿값과 단위 사이의 띄어쓰기는 값에 영향이
# 없으므로 "5억원" == "5억 원" == "500,000,000원", "10,000명" == "1만 명"이다.
_QUANTITY = re.compile(
    r"(?<![\d.])([+\-−]?\d+(?:,\d{3})*(?:\.\d+)?)([천백]?[만억조]?)"
    r"(?:[ \t\u00a0]*(%|℃|°[CF]|kg|mg|μg|µg|g|km|cm|mm|mL|ml|L|l|m|ms|s|Hz|kHz|MHz|GHz|"
    r"원|개월|시간|분|초|달|주|년|월|일|명|건|개|회|번)(?![A-Za-z]))?"
)
_MAGNITUDE = {"천": 1000, "백": 100, "만": 10**4, "억": 10**8, "조": 10**12}
_UNITS ={"개월", "시간", "분", "초", "달", "주", "년", "월", "일", "명", "건", "개", "회", "번", "원"}

# 전각 숫자·기호는 반각과 같은 값이다("２０％" == "20%").
_WIDTH = str.maketrans({**{chr(0xFF10 + d): str(d) for d in range(10)},
                        "％": "%", "，": ",", "．": ".", "－": "-", "＋": "+"})

# 수사 + 단위명사("세 배", "열 명", "삼십 일")도 숫자와 같은 값으로 센다. "세 배"→"3배"는
# 같은 값이고 "세 배"→"네 배"는 변경이다. 오탐을 줄이려고 관용 표현이 대부분인
# 한/하나(1)는 단독으로 세지 않고("한 번 더"), 서수("두 번째")도 제외한다. 한자어 수는
# 두 음절 이상이거나 십·백·천일 때만 센다("이 명령"의 '이'는 지시어다).
_ONES = {"한": 1, "하나": 1, "두": 2, "둘": 2, "세": 3, "셋": 3, "석": 3, "네": 4, "넷": 4,
         "넉": 4, "다섯": 5, "여섯": 6, "일곱": 7, "여덟": 8, "아홉": 9}
_TENS = {"열": 10, "스무": 20, "스물": 20, "서른": 30, "마흔": 40, "쉰": 50, "예순": 60,
         "일흔": 70, "여든": 80, "아흔": 90}
_SINO = {"일": 1, "이": 2, "삼": 3, "사": 4, "오": 5, "육": 6, "칠": 7, "팔": 8, "구": 9}
_COUNTERS = ("개월", "가지", "차례", "군데", "시간", "퍼센트", "단계", "가구", "마리", "배", "명",
             "개", "번", "회", "살", "권", "장", "대", "곳", "년", "해", "달", "주", "일", "시",
             "분", "초", "층", "건", "원", "쪽", "줄", "채", "잔")
# 단위명사 뒤에 올 수 있는 조사·어미의 첫 음절. "명령", "배우"처럼 단어의 일부인 경우를 거른다.
# 서술격 조사·높임 어미("세 가지다", "두 명입니다", "세 개예요", "세 명밖에")도 포함한다.
_AFTER_COUNTER = set("이가을를은는의에로으와과도만씩쯤께뿐까부보였인나간내동전후당여라란며면다입예밖한짜")
# 단위명사에 붙여 쓴 세·열·두·네·십·백·천은 대개 다른 낱말이다(세대, 열대, 천장, 십분, 세배,
# 세시, 천명). 수로 셀 때는 "세 대"처럼 띄어 쓴 경우만 센다.
_ATTACHED_WORDS = {"세", "열", "두", "네", "십", "백", "천"}
_NUMBER_WORD = re.compile(
    r"(?<![가-힣])(?:(?P<native>(?:" + "|".join(sorted(_TENS, key=len, reverse=True)) + r")?"
    r"(?:" + "|".join(sorted(_ONES, key=len, reverse=True)) + r")?)"
    r"|(?P<sino>[일이삼사오육칠팔구십백천]+))"
    r"[ \t\u00a0]?(?P<counter>" + "|".join(sorted(_COUNTERS, key=len, reverse=True)) + r")"
)


def _native_value(word: str) -> int | None:
    tens = next((t for t in sorted(_TENS, key=len, reverse=True) if word.startswith(t)), "")
    ones = word[len(tens):]
    if ones and ones not in _ONES:
        return None
    if tens == "스무" and ones or tens == "스물" and not ones:
        return None
    value = _TENS.get(tens, 0) + _ONES.get(ones, 0)
    return value or None


def _sino_value(word: str) -> int | None:
    if len(word) < 2 and word not in ("십", "백", "천"):
        return None
    total, digit = 0, None
    for ch in word:
        if ch in _SINO:
            if digit is not None:
                return None
            digit = _SINO[ch]
        else:
            place = {"십": 10, "백": 100, "천": 1000}[ch]
            total += (digit or 1) * place
            digit = None
    return total + (digit or 0)


def number_words(text: str) -> Counter:
    found: Counter = Counter()
    for m in _NUMBER_WORD.finditer(text):
        after = text[m.end():m.end() + 1]
        if after and "가" <= after <= "힣" and after not in _AFTER_COUNTER:
            continue
        if m.group("counter") == "번" and after == "째":
            continue
        # "두 번 다시 …않다/없다" means "never again", not a count of two.
        if m.group(0).replace(" ", "") == "두번" and re.match(r"\s*다시", text[m.end():m.end() + 4]):
            continue
        numeral = m.group("native") or m.group("sino")
        counter = m.group("counter")
        # "한 번 더" is often idiomatic, while a precise duration, count or
        # monetary amount of one must compare with its digit spelling.
        if numeral in ("한", "하나") and counter not in _UNITS - {"번"}:
            continue
        if numeral in _ATTACHED_WORDS and m.group(0) == numeral + m.group("counter"):
            continue
        value = _native_value(m.group("native")) if m.group("native") else (
            _sino_value(m.group("sino")) if m.group("sino") else None)
        if value is None:
            continue
        # 숫자 표기와 같은 단위 규칙("3배"→단위 없음, "3명"→명)을 따라야 "세 배"=="3배"다.
        found[(Decimal(value), counter if counter in _UNITS else "")] += 1
    return found


def fold_width(text: str) -> str:
    return text.translate(_WIDTH)


def _magnitude(prefix: str) -> int:
    value = 1
    for ch in prefix:
        value *= _MAGNITUDE[ch]
    return value


def signed_quantities(text: str) -> Counter:
    text = fold_width(text)
    return Counter((Decimal(number.replace(',', '').replace('−', '-')) * _magnitude(magnitude), unit or '')
                   for number, magnitude, unit in _QUANTITY.findall(text)) + number_words(text)
