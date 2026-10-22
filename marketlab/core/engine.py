"""MarketEngine: 명령 -> 이벤트 계산(process) -> apply.

설계안 §1~§2. 상태를 바꾸는 유일한 문. 매칭은 Mechanism에 위임하고,
정보 공개는 InfoPolicy에 위임한다. 엔진 자신은 검증(멱등·epoch·잔고)과
이벤트 발행 순서만 책임진다.
"""

import hashlib
import json
import random

from .state import new_state, apply_event


class MarketEngine:
    def __init__(self, mechanism, info_policy=None, seed=0):
        self.state = new_state()
        self.log = []
        self.mechanism = mechanism
        self.info_policy = info_policy
        # 메커니즘 내부의 명시적 무작위화(동일 가격 배급 셔플 등) 전용 난수원.
        # 이 난수는 '이벤트 계산'에만 쓰이고, 결과는 전부 이벤트로 기록되므로
        # 재생(replay)은 난수원 없이도 동일하다.
        self.rng = random.Random(seed)

    # ---- 이벤트 발행 (유일한 상태 변경 경로)

    def _emit(self, ev):
        ev["seq"] = self.state["seq"] + 1
        apply_event(self.state, ev)
        self.log.append(ev)
        return ev

    # ---- 수명주기

    def create_account(self, agent, cash, shares):
        self._emit({"type": "account_created", "agent": agent,
                    "cash": cash, "shares": shares})

    def bump_epoch(self):
        self._emit({"type": "epoch_bumped"})

    def advance_clock(self):
        """논리적 시간 1 진행. 라운드 경계 처리(일괄 경매 클리어링 등)는 메커니즘 몫."""
        self._emit({"type": "clock_advanced"})
        self.mechanism.on_clock(self)

    # ---- 명령

    def submit(self, oid, agent, side, price, qty, epoch):
        s = self.state
        if oid in s["orders"]:
            return self._emit({"type": "rejected", "reason": "duplicate", "oid": oid})
        if epoch != s["epoch"]:
            return self._emit({"type": "rejected", "reason": "stale_epoch", "oid": oid})
        if qty <= 0 or price <= 0:
            return self._emit({"type": "rejected", "reason": "bad_qty", "oid": oid})
        a = s["accounts"][agent]
        if side == "buy" and a["cash"] < price * qty:
            return self._emit({"type": "rejected", "reason": "insufficient", "oid": oid})
        if side == "sell" and a["shares"] < qty:
            return self._emit({"type": "rejected", "reason": "insufficient", "oid": oid})
        self._emit({"type": "accepted", "oid": oid, "agent": agent, "side": side,
                    "price": price, "qty": qty, "epoch": epoch})
        self.mechanism.on_order_accepted(self, oid)
        return None

    def cancel_replace(self, old_oid, new_oid, agent, side, price, qty, epoch):
        """원자적 취소·재호가 (M2의 이중 노출 레이스에 대한 엔진 차원 방어).

        의미론: 옛 주문이 '지금도 열려 있을 때만' 취소하고 새 주문을 수리한다.
        옛 주문이 이미 체결·취소·부재이면 새 주문 전체를 거부한다 — 판단 시점의
        노출 교체 의도가 집행 시점에 더 이상 성립하지 않기 때문이다. 단일
        직렬화 지점 덕분에 두 단계 사이에 다른 명령이 끼어들 수 없다.
        """
        s = self.state
        if epoch != s["epoch"]:
            return self._emit({"type": "rejected", "reason": "stale_epoch", "oid": new_oid})
        old = s["orders"].get(old_oid)
        if old is None or old["status"] != "open" or old["agent"] != agent:
            return self._emit({"type": "rejected", "reason": "replace_target_gone",
                               "oid": new_oid})
        self._emit({"type": "cancelled", "oid": old_oid})
        return self.submit(new_oid, agent, side, price, qty, epoch)

    def abstain(self, agent, reason):
        """타임아웃·판단 실패 등으로 이번 기회에 행동하지 않았음을 기록한다."""
        return self._emit({"type": "abstained", "agent": agent, "reason": reason})

    def cancel(self, oid, epoch):
        s = self.state
        if epoch != s["epoch"]:
            return self._emit({"type": "rejected", "reason": "stale_epoch", "oid": oid})
        o = s["orders"].get(oid)
        if o is None or o["status"] != "open":
            return self._emit({"type": "rejected", "reason": "unknown_cancel", "oid": oid})
        return self._emit({"type": "cancelled", "oid": oid})

    # ---- 읽기 (단일 문 원칙의 읽기 버전)

    def request_snapshot(self, agent):
        """InfoPolicy가 걸러 준 관측만 제공하고, 공개 사실을 이벤트로 남긴다."""
        snap = self.info_policy.view(self.state, agent)
        h = hashlib.sha256(
            json.dumps(snap, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        self._emit({"type": "info_published", "agent": agent,
                    "policy": self.info_policy.name, "content_hash": h})
        return snap
