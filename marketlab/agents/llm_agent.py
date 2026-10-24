"""LLM 에이전트 (설계안 §5·§6).

- 프롬프트는 InfoPolicy 스냅샷 + 자기 계좌 + 페르소나 템플릿에서만 만들어진다
  (정보 통제 = 실험 요인). 템플릿 해시는 런 설정의 일부.
- 응답 파싱은 어댑터 밖(에이전트 소속). 파싱 실패·타임아웃은 기권으로 기록.
- 미체결 주문이 있는데 새 주문을 원하면 단순 '취소+재제출'이 아니라 Decision의
  replaces 항목을 쓴다 → 러너가 엔진의 원자적 cancel-replace로 집행해
  이중 노출 레이스(M2 발견)를 구조적으로 차단한다.
"""

import hashlib
import re

from .base import AgentBase

# 후행 구두점·공백은 허용하되 형식 자체는 고정 (실제 LLM 출력의 자연 변이 흡수)
RESPONSE_RE = re.compile(r"^\s*(BUY|SELL)\s+(\d+)\s*@\s*(\d+)\s*[.!]?\s*$",
                         re.IGNORECASE)


class LLMAgent(AgentBase):
    def __init__(self, agent_id, persona, cash, shares, max_qty=None,
                 max_orders=1, structured=False):
        super().__init__(agent_id)
        self.persona = persona
        self.template_hash = hashlib.sha256(persona.encode()).hexdigest()[:16]
        self._cash, self._shares = cash, shares
        self.max_qty = max_qty          # 브로커 강제 한도 (초과 주문은 클립)
        self.max_orders = max_orders    # 마켓메이커는 2 (매수·매도 각 1)
        self.structured = structured    # JSON 스키마 강제 모드 (형식 축 제거)
        self.n_clipped = 0

    def endowment(self):
        return (self._cash, self._shares)

    def build_prompt(self, snapshot, round_no):
        me = snapshot["me"]
        ref = snapshot.get("ref_price") or 100
        bb = snapshot.get("best_bid")
        ba = snapshot.get("best_ask")
        return (
            f"{self.persona}\n"
            f"[시장] round={round_no} REF={ref} best_bid={bb} best_ask={ba}\n"
            f"[계좌] cash={me['cash']} shares={me['shares']} "
            f"open_orders={len(me['open_orders'])}\n"
            + (f"[지시] JSON으로만 답하라: {{\"orders\": [{{\"side\": \"buy|sell\", "
               f"\"price\": 정수, \"qty\": 정수}}]}} — 거래하지 않으려면 빈 배열."
               if self.structured else
               f"[지시] 다음 한 줄 형식으로만 답하라: "
               f"'BUY <수량> @ <가격>' 또는 'SELL <수량> @ <가격>' 또는 'HOLD'"))

    def _finish(self, orders, snapshot):
        """주문 목록에 브로커 한도 클립을 적용하고 교체/신규/취소로 변환."""
        for o in orders:
            if self.max_qty is not None and o["qty"] > self.max_qty:
                o["qty"] = self.max_qty
                self.n_clipped += 1
        open_orders = sorted(snapshot["me"]["open_orders"].keys())
        replaces = [{"old": old, "order": o}
                    for old, o in zip(open_orders, orders)]
        rest = orders[len(replaces):]
        return {"cancels": open_orders[len(orders):], "orders": rest,
                "replaces": replaces}

    def parse(self, text, snapshot):
        """응답 텍스트 -> Decision. 해석 불가면 None (기권으로 기록된다)."""
        if self.structured:
            import json as _json
            try:
                data = _json.loads(text)
                orders = []
                for o in list(data.get("orders", []))[:self.max_orders]:
                    side = str(o["side"]).lower()
                    price, qty = int(o["price"]), int(o["qty"])
                    if side in ("buy", "sell") and qty >= 1 and 1 <= price <= 200:
                        orders.append({"side": side, "price": price, "qty": qty})
                if not orders:
                    return {"cancels": [], "orders": [], "replaces": []}  # HOLD
                return self._finish(orders, snapshot)
            except (ValueError, KeyError, TypeError):
                return None
        lines = [ln for ln in text.strip().splitlines() if ln.strip()]
        if not lines:
            return None
        if lines[0].upper().rstrip(".!").strip() == "HOLD":
            return {"cancels": [], "orders": [], "replaces": []}
        orders = []
        for ln in lines[:self.max_orders]:
            m = RESPONSE_RE.match(ln)
            if not m:
                break
            orders.append({"side": m.group(1).lower(),
                           "price": int(m.group(3)), "qty": int(m.group(2))})
        if not orders:
            return None
        return self._finish(orders, snapshot)

    async def acall(self, adapter, snapshot, round_no, epoch):
        """어댑터 호출 + 파싱. (decision, 기권사유) 반환. BudgetExhausted는 전파."""
        from marketlab.llm.adapter import BudgetExhausted, LLMError, LLMTimeout
        prompt = self.build_prompt(snapshot, round_no)
        req = {"call_id": f"{self.agent_id}-r{round_no}", "epoch": epoch,
               "prompt": prompt}
        try:
            resp = await adapter.call(req)
        except BudgetExhausted:
            raise
        except LLMTimeout:
            return None, "timeout"
        except LLMError as e:
            return None, f"llm_error:{type(e).__name__}"
        dec = self.parse(resp["text"], snapshot)
        return (dec, None) if dec is not None else (None, "parse_error")

    def decide(self, snapshot, ctx):
        raise NotImplementedError("LLMAgent는 AsyncRounds 러너로만 구동한다")
