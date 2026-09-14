"""Shared signed-number and recognized-unit invariant for text and Office."""
from collections import Counter
from decimal import Decimal
import re

_QUANTITY = re.compile(
    r"(?<![\d.])([+\-−]?\d+(?:,\d{3})*(?:\.\d+)?)"
    r"(?:[ \t\u00a0]*(%|℃|°[CF]|kg|mg|μg|µg|g|km|cm|mm|mL|ml|L|l|m|ms|s|Hz|kHz|MHz|GHz|"
    r"억원|만원|원|개월|년|월|일|명|건|개|회|번)(?![A-Za-z]))?"
)


def signed_quantities(text: str) -> Counter:
    return Counter((Decimal(number.replace(',', '').replace('−', '-')), unit or '')
                   for number, unit in _QUANTITY.findall(text))
