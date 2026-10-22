"""신호 변형: V~U[80,120] 불확실 펀더멘털 + 사적 신호 s=V+U[-8,8].

클론 5개의 수정 지시(전원 AMEND, 2026-10-23) 이식. 전원이 '자기 신호와
시장가격을 결합한 추정치'를 도입했으나 결합 방식이 서로 다르다 — 이 이질성이
거래의 원천이다. 수정 전문: state/policy-specs-signal.md

러너 계약: 런 시작에 agent.signal이 설정된다. ctx["recent"]는 최근 체결가
(≤5), ctx["new_trades"]는 직전 라운드의 체결가 목록.
"""

import random
import statistics

from policies import PolicyAgent, clamp


class MomentumSignal(PolicyAgent):
    """모멘텀: v̂ = w·s + (1-w)·mean(recent), w=max(0.3, 0.8-0.1·len(recent)).
    매수는 v̂-2 이하에서만(수취 또는 지정가), 매도는 bid≥v̂+2 또는
    (하락 추세 & last>v̂)의 보유 축소."""

    def decide(self, snap, ctx):
        rng = self.rng
        cash, shares = self.avail(snap["me"])
        last = snap["ref_price"]
        recent = ctx["recent"]
        if not recent:
            v_hat = max(82, min(118, self.signal))
        else:
            w = max(0.3, 0.8 - 0.1 * len(recent))
            v_hat = round(w * self.signal + (1 - w) * statistics.mean(recent))
        ba, bb = snap["best_ask"], snap["best_bid"]

        def buy(px):
            px = clamp(px)
            if px > v_hat - 2:
                return None
            qty = min(5, 1 + (v_hat - px) // 2, 50 - shares, (cash - 300) // px)
            if qty >= 1:
                return [{"side": "buy", "price": px, "qty": int(qty)}]
            return None

        if last is None:
            if ba is not None and ba <= v_hat - 2 and rng.uniform(0, 1) < 0.4:
                r = buy(ba)
                if r:
                    return r
            if rng.uniform(0, 1) < 0.7:
                return buy(v_hat - rng.randint(2, 4))
            return None
        if rng.uniform(0, 1) < 0.15:
            return None
        trend = (recent[-1] - recent[0]) if len(recent) >= 2 else 0
        if bb is not None and bb >= v_hat + 2 and shares >= 1:
            return [{"side": "sell", "price": clamp(bb), "qty": int(min(5, shares))}]
        if trend < 0 and last > v_hat and shares >= 1:
            px = bb if bb is not None else last - rng.randint(1, 2)
            return [{"side": "sell", "price": clamp(px), "qty": int(min(5, shares))}]
        if ba is not None and ba <= v_hat - 2:
            return buy(ba)
        return buy(v_hat - rng.randint(2, 4))


class ValueSignal(PolicyAgent):
    """가치: v0 = 신호의 가능 구간 [max(80,s-8), min(120,s+8)] 중점,
    v̂ = 0.6·v0 + 0.4·mean(recent). 안전마진 5의 즉시 매매 + ±(4~6) 대기주문."""

    def decide(self, snap, ctx):
        rng = self.rng
        cash, shares = self.avail(snap["me"])
        recent = ctx["recent"]
        v0 = (max(80, self.signal - 8) + min(120, self.signal + 8)) / 2
        v_hat = round(0.6 * v0 + 0.4 * statistics.mean(recent)) if recent else round(v0)
        bb, ba = snap["best_bid"], snap["best_ask"]
        qty = rng.randint(1, 3)
        can_sell = shares - qty >= 0
        if bb is not None and bb >= v_hat + 5 and can_sell:
            return [{"side": "sell", "price": clamp(bb), "qty": qty}]
        if (ba is not None and ba <= v_hat - 5 and shares + qty <= 40
                and cash >= ba * qty):
            return [{"side": "buy", "price": clamp(ba), "qty": qty}]
        if rng.uniform(0, 1) < 0.5:
            px_s = clamp(v_hat + 4 + rng.randint(0, 2))
            px_b = clamp(v_hat - 4 - rng.randint(0, 2))
            if can_sell and (bb is None or bb > v_hat):
                return [{"side": "sell", "price": px_s, "qty": qty}]
            if (bb is None or bb <= v_hat) and shares + qty <= 40 and cash >= px_b * qty:
                return [{"side": "buy", "price": px_b, "qty": qty}]
        return None


class MMSignal(PolicyAgent):
    """MM: est는 0.8·s+0.2·100에서 시작해 체결마다 0.7·est+0.3·체결가로 갱신.
    호가 중심 = 0.6·시장가 + 0.4·est, 역선택 대비 호가폭 확대(괴리>6이면 추가),
    테이킹은 est±5 이상의 확신 괴리에서만."""

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.est = None
        self.just_took = False

    def decide(self, snap, ctx):
        rng = self.rng
        cash, shares = self.avail(snap["me"])
        recent = ctx["recent"]
        if self.est is None:
            self.est = round(0.8 * self.signal + 0.2 * 100)
        for p in ctx.get("new_trades", []):
            self.est = round(0.7 * self.est + 0.3 * p)
        bb, ba = snap["best_bid"], snap["best_ask"]
        last = snap["ref_price"]
        # 확신 괴리 테이킹 (연속 테이킹 금지)
        if not self.just_took and rng.uniform(0, 1) < 0.15:
            if ba is not None and ba <= self.est - 5 and cash >= ba:
                self.just_took = True
                return [{"side": "buy", "price": clamp(ba), "qty": 1}]
            if bb is not None and bb >= self.est + 5 and shares >= 1:
                self.just_took = True
                return [{"side": "sell", "price": clamp(bb), "qty": 1}]
        self.just_took = False
        if last is not None:
            mkt = last
        elif bb is not None and ba is not None:
            mkt = (bb + ba) / 2
        else:
            mkt = self.est
        if len(recent) >= 3:
            drift = max(-2, min(2, statistics.mean(recent[-3:]) - mkt))
        else:
            drift = 0
        ref = round(0.6 * (mkt + 0.5 * drift) + 0.4 * self.est)
        if last is not None and abs(last - self.est) > 6:
            half = rng.choice([3, 4, 5])          # 역선택 경계: 호가폭 추가 확대
        else:
            half = rng.choice([2, 3, 4])
        skew = round((shares - 30) / 10)
        bid = clamp(ref - half - skew)
        ask = clamp(ref + half - skew)
        if ba is not None and bid >= ba:
            bid = clamp(ba - 1)
        if bb is not None and ask <= bb:
            ask = clamp(bb + 1)
        if ask <= bid:
            ask = clamp(bid + 1)
        if last is not None and last > self.est:
            q_buy, q_sell = 1, 2
        elif last is not None and last < self.est:
            q_buy, q_sell = 2, 1
        else:
            q_buy, q_sell = 2, 2
        if shares > 45:
            orders = [{"side": "sell", "price": ask, "qty": q_sell}]
        elif shares < 15:
            orders = [{"side": "buy", "price": bid, "qty": q_buy}] if cash >= bid * q_buy else []
        else:
            orders = []
            if cash >= bid * q_buy:
                orders.append({"side": "buy", "price": bid, "qty": q_buy})
            if shares >= q_sell:
                orders.append({"side": "sell", "price": ask, "qty": q_sell})
        return orders or None


class ConservativeSignal(PolicyAgent):
    """보수: ref = clamp(자기 신호, 80, 120) 고정, 경계 ±12%(노이즈 반영 확대),
    깊은 지정가 0.86/1.14. 기존 주문은 항상 유지."""

    def decide(self, snap, ctx):
        rng = self.rng
        cash, shares = self.avail(snap["me"])
        ref = max(80, min(120, self.signal))
        u = rng.uniform(0, 1)
        if snap["me"]["open_orders"]:
            return None
        bb, ba = snap["best_bid"], snap["best_ask"]
        can_sell = shares >= 1
        if can_sell and bb is not None and bb >= 1.12 * ref and u < 0.8:
            return [{"side": "sell", "price": clamp(bb), "qty": 1}]
        if ba is not None and ba <= 0.88 * ref and cash - ba >= 1800 and u < 0.8:
            return [{"side": "buy", "price": clamp(ba), "qty": 1}]
        if u < 0.3:
            px_b = clamp(0.86 * ref)
            if u < 0.15 and cash - px_b >= 1800:
                return [{"side": "buy", "price": px_b, "qty": 1}]
            if can_sell:
                return [{"side": "sell", "price": clamp(1.14 * ref), "qty": 1}]
        return None


class AggressiveSignal(PolicyAgent):
    """공격: v̂ = 0.5·s + 0.5·(last or s). 최우선 분기 — 오차 한계(±8)에 근접한
    괴리(신호 대비 ±6 이상)는 즉시 공격. 그 외 앵커판 구조에서 기준을 v̂로,
    클램프를 매수 ≤ v̂−rng(1,3) / 매도 ≥ v̂+rng(1,3)으로 치환."""

    def decide(self, snap, ctx):
        rng = self.rng
        cash, shares = self.avail(snap["me"])
        recent = ctx["recent"]
        last = snap["ref_price"]
        s = self.signal
        v_hat = round(0.5 * s + 0.5 * (last if last is not None else s))
        bb, ba = snap["best_bid"], snap["best_ask"]
        # 최우선: 강한 정보 우위 즉시 공격
        if ba is not None and ba <= s - 6 and cash // ba >= 1:
            return [{"side": "buy", "price": clamp(ba), "qty": int(min(8, cash // ba))}]
        if bb is not None and bb >= s + 6 and shares > 0:
            return [{"side": "sell", "price": clamp(bb), "qty": int(min(8, shares))}]
        if rng.uniform(0, 1) < 0.15:
            return None
        b_m = rng.randint(1, 3)                  # 매수 상한 마진
        s_m = rng.randint(1, 3)                  # 매도 하한 마진
        buy_cap = v_hat - b_m
        sell_floor = v_hat + s_m
        trend = (recent[-1] - recent[0]) if len(recent) >= 2 else 0
        if ba is None and bb is None:
            px = min(buy_cap, clamp(v_hat - rng.randint(3, 6)))
            qty = min(8, cash // px) if px >= 1 else 0
            return [{"side": "buy", "price": clamp(px), "qty": int(qty)}] if qty >= 1 else None
        if ba is None and shares > 0:
            px = max(sell_floor, clamp(v_hat + rng.randint(5, 9)))
            return [{"side": "sell", "price": clamp(px), "qty": int(min(8, shares))}]
        if ((trend > 0 or last is None) and ba is not None and ba <= buy_cap
                and cash // ba >= 1 and rng.uniform(0, 1) < 0.6):
            return [{"side": "buy", "price": clamp(ba), "qty": int(min(8, cash // ba))}]
        if trend > 0 and ba is not None and ba <= buy_cap and cash // ba >= 1:
            return [{"side": "buy", "price": clamp(ba), "qty": int(min(8, cash // ba))}]
        if (trend >= 0 and shares >= 8 and ba is not None and ba - (bb or 0) >= 3
                and ba - 1 >= sell_floor):
            return [{"side": "sell", "price": clamp(ba - 1), "qty": 8}]
        if trend < 0 and bb is not None and bb >= sell_floor and shares > 0:
            return [{"side": "sell", "price": clamp(bb), "qty": int(min(8, shares))}]
        orders = []
        px_b = min(buy_cap, clamp((bb if bb is not None else v_hat) - rng.randint(0, 2)))
        if px_b >= 1 and cash // px_b >= 1:
            orders.append({"side": "buy", "price": clamp(px_b),
                           "qty": int(min(8, cash // px_b))})
        if shares > 0 and not snap["me"]["open_orders"] and rng.uniform(0, 1) < 0.5:
            px_s = max(sell_floor,
                       clamp((ba - 1) if ba is not None else v_hat + rng.randint(2, 5)))
            orders.append({"side": "sell", "price": clamp(px_s),
                           "qty": int(min(8, shares))})
        return orders or None


PERSONAS = {
    "momentum": (MomentumSignal, 2500, 20),
    "value": (ValueSignal, 2500, 20),
    "mm": (MMSignal, 2500, 30),
    "conservative": (ConservativeSignal, 2500, 20),
    "aggressive": (AggressiveSignal, 2500, 20),
}


def setup_run(run_seed, agents):
    """런별 V 추출과 사적 신호 배부 (공통 지식 구조: V~U[80,120], ε~U[-8,8])."""
    rng = random.Random(f"V-{run_seed}")
    v = rng.randint(80, 120)
    signals = {}
    for aid in sorted(agents):
        s = v + rng.randint(-8, 8)
        agents[aid].signal = s
        signals[aid] = s
    return {"V": v, "signals": signals}
