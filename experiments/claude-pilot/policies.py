"""클로드 클론 5개가 스스로 작성한 정책 명세의 충실한 이식 (2026-10-22).

각 클래스의 주석에 클론이 보낸 명세 원문의 요지를 보존했고, 전문은
state/policy-specs.md 참조. 구현 원칙:
  - 가용 자원 = 현금+예약현금 / 주식+예약주식 (새 주문이 기존 미체결을
    교체하면서 예약이 풀리는 것을 반영 — 클론들의 NOTES 요구)
  - 가격은 1~200 정수 클램프, 수량 ≥1 아니면 HOLD
  - HOLD는 기존 대기주문 유지, 새 주문은 기존 주문을 원자적으로 교체
"""

import random
import statistics


def clamp(p):
    return max(1, min(200, int(round(p))))


class PolicyAgent:
    def __init__(self, agent_id, cash, shares, seed):
        self.agent_id = agent_id
        self._cash, self._shares = cash, shares
        self.rng = random.Random(seed)

    def endowment(self):
        return (self._cash, self._shares)

    @staticmethod
    def avail(me):
        return (me["cash"] + me["res_cash"], me["shares"] + me["res_shares"])


class MomentumPolicy(PolicyAgent):
    """모멘텀 클론 명세: 가격 미형성 시 70%로 참고가 부근 소량 매수 탐색;
    15% 확률적 불참; 상승 추세면 호가 수취/추격 매수(≤5주, 주식≤50, 현금≥300),
    하락 추세면 대칭 매도; 횡보면 HOLD."""

    def decide(self, snap, ctx):
        rng = self.rng
        cash, shares = self.avail(snap["me"])
        last = snap["ref_price"]
        recent = ctx["recent"]
        ref = last if last is not None else 100
        trend = (recent[-1] - recent[0]) if len(recent) >= 2 else 0
        ba, bb = snap["best_ask"], snap["best_bid"]
        if last is None:
            # AMEND(검수): 매도호가가 ref+5 이내면 40% 확률로 스프레드를 건너 수취
            if ba is not None and ba <= ref + 5 and rng.uniform(0, 1) < 0.4:
                qty = rng.randint(1, 2)
                if cash - ba * qty >= 300 and shares + qty <= 50:
                    return [{"side": "buy", "price": clamp(ba), "qty": qty}]
            if rng.uniform(0, 1) < 0.7:
                qty = rng.randint(1, 2)
                px = clamp(ref + rng.randint(-1, 0))
                if cash - px * qty >= 300 and shares + qty <= 50:
                    return [{"side": "buy", "price": px, "qty": qty}]
            return None
        if rng.uniform(0, 1) < 0.15:
            return None
        if trend > 0:
            px = ba if (ba is not None and ba - last <= 3) else clamp(last + rng.randint(1, 2))
            qty = min(5, 50 - shares, (cash - 300) // px)
            if qty >= 1:
                return [{"side": "buy", "price": clamp(px), "qty": int(qty)}]
            return None
        if trend < 0:
            px = bb if (bb is not None and last - bb <= 3) else clamp(last - rng.randint(1, 2))
            qty = min(5, shares)
            if qty >= 1:
                return [{"side": "sell", "price": clamp(px), "qty": int(qty)}]
            return None
        # AMEND(검수): 횡보여도 10% 확률로 best_ask가 last+2 이내면 1주 수취
        if (rng.uniform(0, 1) < 0.1 and ba is not None and ba <= last + 2
                and cash - ba >= 300 and shares + 1 <= 50):
            return [{"side": "buy", "price": clamp(ba), "qty": 1}]
        return None


class ValuePolicy(PolicyAgent):
    """가치 클론 명세: 내재가치 100, qty=rng(1,3); 매도호가≥105면 즉시 매도,
    매수호가≤95면 즉시 매수(보유≤40); 50% 확률로 대기주문 갱신(105+j 매도 /
    95-j 매수); 그 외 HOLD."""

    def decide(self, snap, ctx):
        rng = self.rng
        cash, shares = self.avail(snap["me"])
        bb, ba = snap["best_bid"], snap["best_ask"]
        qty = rng.randint(1, 3)
        can_buy = shares + qty <= 40 and cash >= 95 * qty
        can_sell = shares - qty >= 0
        if bb is not None and bb >= 105 and can_sell:
            return [{"side": "sell", "price": clamp(bb), "qty": qty}]
        if ba is not None and ba <= 95 and can_buy:
            return [{"side": "buy", "price": clamp(ba), "qty": qty}]
        if rng.uniform(0, 1) < 0.5:
            if can_sell and (bb is None or bb > 100):
                return [{"side": "sell", "price": clamp(105 + rng.randint(0, 3)), "qty": qty}]
            if can_buy and (bb is None or bb <= 100):
                return [{"side": "buy", "price": clamp(95 - rng.randint(0, 3)), "qty": qty}]
        return None


class MMPolicy(PolicyAgent):
    """MM 클론 명세: ref=직전가(없으면 중간가, 없으면 100)+드리프트 보정 절반;
    호가폭 jitter {1,2,3}; 재고 치우침 skew=(재고-30)/10으로 호가 전체 이동;
    교차(테이커) 금지; 재고 >45면 매도만, <15면 매수만, 아니면 양방향 2주."""

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.just_took = False

    def decide(self, snap, ctx):
        rng = self.rng
        cash, shares = self.avail(snap["me"])
        recent = ctx["recent"]
        bb, ba = snap["best_bid"], snap["best_ask"]
        last = snap["ref_price"]
        # AMEND(검수): 15% 확률 + 스프레드≤4 + 재고 20~40 + 직전 라운드 비테이커일 때,
        # 무작위 한 쪽만 상대 최우선 호가에 1주 테이커 주문 (직후 라운드는 메이커 복귀)
        if not self.just_took:
            if (rng.uniform(0, 1) < 0.15 and bb is not None and ba is not None
                    and ba - bb <= 4 and 20 <= shares <= 40):
                side = rng.choice(["buy", "sell"])
                if side == "buy" and cash >= ba:
                    self.just_took = True
                    return [{"side": "buy", "price": clamp(ba), "qty": 1}]
                if side == "sell" and shares >= 1:
                    self.just_took = True
                    return [{"side": "sell", "price": clamp(bb), "qty": 1}]
        self.just_took = False
        if last is not None:
            ref = last
        elif bb is not None and ba is not None:
            ref = (bb + ba) / 2
        else:
            ref = 100
        if len(recent) >= 3:
            drift = max(-2, min(2, statistics.mean(recent[-3:]) - ref))
        else:
            drift = 0
        ref = round(ref + 0.5 * drift)
        half = rng.choice([1, 2, 3])
        skew = round((shares - 30) / 10)
        bid = clamp(ref - half - skew)
        ask = clamp(ref + half - skew)
        if ba is not None and bid >= ba:
            bid = clamp(ba - 1)
        if bb is not None and ask <= bb:
            ask = clamp(bb + 1)
        if ask <= bid:
            ask = clamp(bid + 1)
        qty = 2
        if shares > 45:
            orders = [{"side": "sell", "price": ask, "qty": qty}]
        elif shares < 15:
            orders = [{"side": "buy", "price": bid, "qty": qty}] if cash >= bid * qty else []
        else:
            orders = []
            if cash >= bid * qty:
                orders.append({"side": "buy", "price": bid, "qty": qty})
            if shares >= qty:
                orders.append({"side": "sell", "price": ask, "qty": qty})
        return orders or None


class ConservativePolicy(PolicyAgent):
    """보수 클론 명세: ref=최근 체결가 중앙값; 명백히 유리(매도호가≤0.9ref 매수 /
    매수호가≥1.1ref 매도)할 때만 1주, 80% 참여; ref 변화 3% 미만이면 기존 주문
    유지; 주문 없을 때 30% 확률로 깊은 지정가(0.88ref 매수 15% / 1.12ref 매도);
    매수 후 현금 ≥1800 유지."""

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.prev_ref = None

    def decide(self, snap, ctx):
        rng = self.rng
        cash, shares = self.avail(snap["me"])
        recent = ctx["recent"]
        last = snap["ref_price"]
        ref = statistics.median(recent) if recent else (last if last is not None else 100)
        u = rng.uniform(0, 1)
        has_open = bool(snap["me"]["open_orders"])
        small_move = (self.prev_ref is not None and self.prev_ref > 0
                      and abs(ref - self.prev_ref) / self.prev_ref < 0.03)
        self.prev_ref = ref
        bb, ba = snap["best_bid"], snap["best_ask"]

        def can_buy(price):
            return cash - price >= 1800

        can_sell = shares >= 1
        if has_open and small_move:
            return None
        if can_sell and bb is not None and bb >= 1.10 * ref and u < 0.8:
            return [{"side": "sell", "price": clamp(bb), "qty": 1}]
        if ba is not None and ba <= 0.90 * ref and can_buy(ba) and u < 0.8:
            return [{"side": "buy", "price": clamp(ba), "qty": 1}]
        if not has_open and u < 0.3:
            px_b = clamp(0.88 * ref)
            if u < 0.15 and can_buy(px_b):
                return [{"side": "buy", "price": px_b, "qty": 1}]
            if can_sell:
                return [{"side": "sell", "price": clamp(1.12 * ref), "qty": 1}]
        return None


class AggressivePolicy(PolicyAgent):
    """공격 클론 명세(분기 순서 보존): 15% 관망; 호가 전무→저가 매수벽 선점;
    매도 공백→유일한 매도벽(ref+5~9); 상승+매도호가≤1.08ref→즉시 걷기(≤8주);
    스프레드≥3이고 보유≥8→최우선 매도(ask-1); 하락→매수호가에 축소;
    그 외 현금 있으면 bid 아래 재매집 대기."""

    def decide(self, snap, ctx):
        rng = self.rng
        cash, shares = self.avail(snap["me"])
        recent = ctx["recent"]
        last = snap["ref_price"]
        ref = last if last is not None else 100
        trend = (recent[-1] - recent[0]) if len(recent) >= 2 else 0
        if rng.uniform(0, 1) < 0.15:
            return None
        bb, ba = snap["best_bid"], snap["best_ask"]
        if ba is None and bb is None:
            px = clamp(ref - rng.randint(3, 6))
            qty = min(8, cash // px)
            return [{"side": "buy", "price": px, "qty": int(qty)}] if qty >= 1 else None
        if ba is None and shares > 0:
            px = clamp(ref + rng.randint(5, 9))
            return [{"side": "sell", "price": px, "qty": int(min(8, shares))}]
        # AMEND(검수): 첫 체결 전에도 걷기 — (trend>0 or last 없음)이고
        # best_ask ≤ 1.03*ref면 60% 확률로 즉시 수취
        if ((trend > 0 or last is None) and ba is not None and ba <= ref * 1.03
                and cash // ba >= 1 and rng.uniform(0, 1) < 0.6):
            return [{"side": "buy", "price": clamp(ba), "qty": int(min(8, cash // ba))}]
        if trend > 0 and ba is not None:
            qty = min(8, cash // ba)
            if qty >= 1 and ba <= ref * 1.08:
                return [{"side": "buy", "price": clamp(ba), "qty": int(qty)}]
        if trend >= 0 and shares >= 8 and ba is not None and ba - (bb or 0) >= 3:
            return [{"side": "sell", "price": clamp(ba - 1), "qty": 8}]
        if trend < 0 and bb is not None and shares > 0:
            return [{"side": "sell", "price": clamp(bb), "qty": int(min(8, shares))}]
        px = clamp((bb if bb is not None else ref) - rng.randint(1, 4))
        if cash > ref and cash // px >= 1:
            return [{"side": "buy", "price": px, "qty": int(min(8, cash // px))}]
        return None


PERSONAS = {
    "momentum": (MomentumPolicy, 2500, 20),
    "value": (ValuePolicy, 2500, 20),
    "mm": (MMPolicy, 2500, 30),
    "conservative": (ConservativePolicy, 2500, 20),
    "aggressive": (AggressivePolicy, 2500, 20),
}
