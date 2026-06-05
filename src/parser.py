"""Pure-function quote parser for Sina HQ API responses.

No side effects.  Imports limited to stdlib: ``re``, ``json``, ``logging``.
"""

import json
import logging
import re

log = logging.getLogger(__name__)

_LINE_RE = re.compile(r'var hq_str_(\w+)="(.+)"')
_MIN_FIELDS = 32


def _float(s: str) -> float | None:
    """Convert *s* to float, returning ``None`` for empty, zero, or invalid."""
    if not s:
        return None
    try:
        v = float(s)
        return v if v != 0.0 else None
    except (ValueError, TypeError):
        return None


def parse_quote(line: str) -> dict | None:
    """Parse a single Sina HQ quote line into a dict.

    Expected format::

        var hq_str_sh600519="贵州茅台,1750.00,..."

    Returns ``None`` if the line does not match the expected pattern or has
    fewer than 32 fields.
    """
    m = _LINE_RE.match(line.strip())
    if m is None:
        return None

    symbol = m.group(1)
    fields = m.group(2).split(",")

    if len(fields) < _MIN_FIELDS:
        log.debug("Skipping %s: only %d fields (need %d)", symbol, len(fields), _MIN_FIELDS)
        return None

    is_index = symbol.startswith("sh000") or symbol.startswith("sz399")

    result: dict = {
        "symbol": symbol,
        "name": fields[0],
        "open": _float(fields[1]),
        "prev_close": _float(fields[2]),
        "current": _float(fields[3]),
        "high": _float(fields[4]),
        "low": _float(fields[5]),
        "volume": _float(fields[8]),
        "amount": _float(fields[9]),
        "quote_date": fields[30],
        "quote_time": fields[31],
    }

    if is_index:
        result["order_book"] = None
    else:
        # bid 5 levels: fields[6..16) as (price, volume) pairs
        # ask 5 levels: fields[8..18) as (price, volume) pairs — but per Sina
        # layout the 5 bid prices are at indices 6,8,10,12,14  and volumes at 7,9,11,13,15
        # while ask prices are at 16,18,20,22,24 and volumes at 17,19,21,23,25
        # However, the common Sina stock layout places bid at fields[6:16] and ask at fields[16:26].
        # Using the standard interpretation:  fields 6-15 = bid (5 pairs), fields 16-25 = ask (5 pairs)
        bid = []
        for i in range(6, 16, 2):
            bp = _float(fields[i])
            bv = _float(fields[i + 1])
            if bp is not None and bv is not None:
                bid.append({"p": bp, "v": bv})
        ask = []
        for i in range(16, 26, 2):
            ap = _float(fields[i])
            av = _float(fields[i + 1])
            if ap is not None and av is not None:
                ask.append({"p": ap, "v": av})
        result["order_book"] = json.dumps({"bid": bid, "ask": ask}, ensure_ascii=False)

    return result


def parse_response(raw_text: str) -> list[dict]:
    """Parse a full Sina HQ API response into a list of quote dicts.

    Empty lines and lines that fail :func:`parse_quote` are silently skipped.
    """
    quotes: list[dict] = []
    for line in raw_text.split("\n"):
        line = line.strip()
        if not line:
            continue
        parsed = parse_quote(line)
        if parsed is not None:
            quotes.append(parsed)
    return quotes
