import re


def parse_price(raw: str) -> float | None:
    if not raw:
        return None
    cleaned = re.sub(r"[^\d.]", "", raw)
    try:
        return float(cleaned)
    except ValueError:
        return None


def parse_discount_text(text: str) -> float | None:
    """解析折扣文字，回傳 0.0~1.0。
    例：「45折」→ 0.45、「5折」→ 0.5、「50% off」→ 0.5、「-50%」→ 0.5
    """
    if not text:
        return None

    # 「X折」或「X.X折」
    m = re.search(r"(\d+(?:\.\d+)?)折", text)
    if m:
        val = float(m.group(1)) / 10.0
        return round(val, 4)

    # 「XX%」或「-XX%」或「XX% off」
    m = re.search(r"(\d+(?:\.\d+)?)\s*%", text)
    if m:
        pct = float(m.group(1))
        # 若是折扣百分比（如「50% off」→ 剩 50%）
        return round(pct / 100.0, 4)

    return None


def calc_ratio(original: float, sale: float) -> float | None:
    if not original or original <= 0:
        return None
    return round(sale / original, 4)
