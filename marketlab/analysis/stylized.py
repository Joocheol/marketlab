"""스타일라이즈드 팩트 추정기 (설계안 §7 analysis, 미결 결정 B의 측정 도구).

이벤트 로그만 입력으로 받아 core의 순수 폴드로 상태를 다시 접으면서
틱 경계마다 표본을 뜬다 — 시장 실행을 교란할 수 없는 읽기 전용 계산.

틱 경계 표본 시점: 일괄 경매에서는 클리어링 이벤트들이 clock_advanced '뒤에'
오므로(engine.advance_clock: clock_advanced 발행 → mechanism.on_clock), 표본은
clock_advanced와 그에 딸린 auction_cleared·trade들을 모두 적용한 뒤 — 즉 다음
라운드의 첫 이벤트 직전 — 에 뜬다. CDA에서는 clock_advanced 직후와 동일하다.
(첫 구현은 clock_advanced 직전에 표본을 떠 경매의 교차 장부를 재는 버그가
있었고, 스모크 실행의 음수 스프레드로 검출되었다.)

지표:
  ret_std        로그수익률 표준편차 (가격 변동성)
  ex_kurtosis    수익률 초과 첨도 (두꺼운 꼬리: 정규분포면 0)
  acf1_ret       수익률 1차 자기상관 (효율적이면 ~0, 음수면 바운스백)
  acf1_abs       |수익률| 1차 자기상관 (변동성 군집: 양수면 군집)
  mean_spread    틱 경계 최우선 호가 스프레드 평균 (호가 양측 존재 시)
  mean_price / n_trades / volume
"""

import math

from marketlab.core.state import apply_event, new_state


def _acf(xs, lag):
    n = len(xs)
    if n <= lag + 1:
        return None
    m = sum(xs) / n
    var = sum((x - m) ** 2 for x in xs)
    if var == 0:
        return None
    cov = sum((xs[i] - m) * (xs[i + lag] - m) for i in range(n - lag))
    return cov / var


def stylized_facts(log):
    state = new_state()
    last_price = None
    prices, spreads = [], []
    n_trades = volume = 0

    def sample():
        prices.append(last_price)
        if state["bids"] and state["asks"]:
            spreads.append(state["orders"][state["asks"][0]]["price"]
                           - state["orders"][state["bids"][0]]["price"])

    pending = False                       # clock_advanced를 봤고 표본 대기 중
    for ev in log:
        if pending and ev["type"] not in ("auction_cleared", "trade"):
            sample()                      # 클리어링까지 반영된 틱 종료 상태
            pending = False
        apply_event(state, ev)
        if ev["type"] == "clock_advanced":
            pending = True
        elif ev["type"] == "trade":
            last_price = ev["price"]
            n_trades += 1
            volume += ev["qty"]
    if pending:
        sample()                          # 마지막 틱

    series = [p for p in prices if p is not None]
    rets = [math.log(b / a) for a, b in zip(series, series[1:]) if a > 0]
    out = {"n_ticks": len(prices), "n_trades": n_trades, "volume": volume,
           "mean_price": (sum(series) / len(series)) if series else None,
           "mean_spread": (sum(spreads) / len(spreads)) if spreads else None,
           "ret_std": None, "ex_kurtosis": None,
           "acf1_ret": None, "acf1_abs": None}
    if len(rets) >= 30:
        m = sum(rets) / len(rets)
        m2 = sum((r - m) ** 2 for r in rets) / len(rets)
        if m2 > 0:
            m4 = sum((r - m) ** 4 for r in rets) / len(rets)
            out["ret_std"] = math.sqrt(m2)
            out["ex_kurtosis"] = m4 / (m2 * m2) - 3
            out["acf1_ret"] = _acf(rets, 1)
            out["acf1_abs"] = _acf([abs(r) for r in rets], 1)
    return out
