"""읽기 전용 메트릭 (설계안 §1 analysis).

이벤트 로그만 입력으로 받는 순수 함수 — 시장 실행을 교란할 수 없다
(보고서 3.4 '관측은 복제본에서'의 번역).
"""

import math


def compute_metrics(log):
    trades = [ev for ev in log if ev["type"] == "trade"]
    prices = [ev["price"] for ev in trades]
    volume = sum(ev["qty"] for ev in trades)

    # tick별 마지막 체결가 (가격 경로)
    series, tick, last = [], 0, None
    for ev in log:
        if ev["type"] == "clock_advanced":
            series.append(last)
            tick += 1
        elif ev["type"] == "trade":
            last = ev["price"]

    # 단순 로그수익률 표준편차 (체결가 기준)
    rets = [math.log(b / a) for a, b in zip(prices, prices[1:]) if a and b]
    ret_std = (math.sqrt(sum(r * r for r in rets) / len(rets)) if rets else None)

    return {
        "n_trades": len(trades),
        "volume": volume,
        "vwap": (sum(ev["price"] * ev["qty"] for ev in trades) / volume
                 if volume else None),
        "first_price": prices[0] if prices else None,
        "last_price": prices[-1] if prices else None,
        "price_by_tick": series,
        "ret_std": ret_std,
        "n_rejections": sum(1 for ev in log if ev["type"] == "rejected"),
        "n_abstains": sum(1 for ev in log if ev["type"] == "abstained"),
    }
