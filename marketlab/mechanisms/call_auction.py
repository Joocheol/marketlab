"""일괄 경매(call auction): 수집 후 라운드 경계에서 단일 가격 클리어링.

동시 정보 모형의 구현체 (설계안 §3). 모든 규칙을 결정론적으로 명세한다:
  클리어링 가격: ① 체결량 V(p)=min(D(p),S(p)) 최대화
                ② 동률이면 초과수요 |D(p)-S(p)| 최소화
                ③ 그래도 동률이면 기준가(ref_price)에 가장 가까운 값
                   (등거리면 낮은 쪽; 기준가 없으면 후보들의 하위 중앙값)
  배급(rationing): 가격 우선. 같은 가격 안에서는 엔진 시드에서 파생된 셔플
                   (같은 라운드 제출은 관념상 동시이므로 도착 순서 특권을 주지 않음).
미체결·부분체결 주문은 다음 라운드로 이월된다.
"""


class CallAuction:
    name = "call_auction"

    def on_order_accepted(self, engine, oid):
        pass  # 수집 단계: 주문은 호가장에 쉬기만 한다 (교차 허용)

    def on_clock(self, engine):
        s = engine.state
        orders = s["orders"]
        bids = [orders[oid] | {"oid": oid} for oid in s["bids"]]
        asks = [orders[oid] | {"oid": oid} for oid in s["asks"]]

        # 후보 = 지정가들 + 기준가. 기준가를 후보에 넣는 이유: 체결량 최대
        # 구간이 폭을 가질 때(V가 준오목이라 구간 내부도 최대 체결량 유지)
        # 구간 안의 기준가 자체가 선택될 수 있어야 한다 (거래소 관행과 일치).
        candidates = {o["price"] for o in bids} | {o["price"] for o in asks}
        if s["ref_price"] is not None and candidates:
            candidates.add(s["ref_price"])
        candidates = sorted(candidates)
        best, volume = None, 0
        if candidates:
            def D(p): return sum(o["remaining"] for o in bids if o["price"] >= p)
            def S(p): return sum(o["remaining"] for o in asks if o["price"] <= p)
            scored = [(p, min(D(p), S(p)), abs(D(p) - S(p))) for p in candidates]
            volume = max(v for _, v, _ in scored)
            if volume > 0:
                tied = [(p, imb) for p, v, imb in scored if v == volume]
                min_imb = min(imb for _, imb in tied)
                tied = [p for p, imb in tied if imb == min_imb]
                if len(tied) == 1:
                    best = tied[0]
                elif s["ref_price"] is not None:
                    best = min(tied, key=lambda p: (abs(p - s["ref_price"]), p))
                else:
                    best = tied[(len(tied) - 1) // 2]  # 하위 중앙값

        engine._emit({"type": "auction_cleared", "tick": s["tick"],
                      "price": best, "volume": volume})
        if best is None:
            return

        buy_q = self._ranked(engine, [o for o in bids if o["price"] >= best], desc=True)
        sell_q = self._ranked(engine, [o for o in asks if o["price"] <= best], desc=False)
        need, bi, si = volume, 0, 0
        while need > 0:
            b_oid, s_oid = buy_q[bi], sell_q[si]
            q = min(orders[b_oid]["remaining"], orders[s_oid]["remaining"], need)
            engine._emit({"type": "trade", "buy_oid": b_oid, "sell_oid": s_oid,
                          "price": best, "qty": q})
            need -= q
            if orders[b_oid]["remaining"] == 0:
                bi += 1
            if orders[s_oid]["remaining"] == 0:
                si += 1

    def _ranked(self, engine, order_dicts, desc):
        """가격 우선 + 동일 가격 내 시드 셔플로 배급 순서를 정한다."""
        groups = {}
        for o in order_dicts:
            groups.setdefault(o["price"], []).append(o["oid"])
        ranked = []
        for price in sorted(groups, reverse=desc):
            group = sorted(groups[price],
                           key=lambda oid: engine.state["orders"][oid]["seq"])
            engine.rng.shuffle(group)
            ranked.extend(group)
        return ranked
