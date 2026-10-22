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

RESPONSE_RE = re.compile(r"^\s*(BUY|SELL)\s+(\d+)\s*@\s*(\d+)\s*$", re.IGNORECASE)


class LLMAgent(AgentBase):
    def __init__(self, agent_id, persona, cash, shares):
        super().__init__(agent_id)
        self.persona = persona
        self.template_hash = hashlib.sha256(persona.encode()).hexdigest()[:16]
        self._cash, self._shares = cash, shares

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
            f"[지시] 다음 한 줄 형식으로만 답하라: "
            f"'BUY <수량> @ <가격>' 또는 'SELL <수량> @ <가격>' 또는 'HOLD'")

    def parse(self, text, snapshot):
        """응답 텍스트 -> Decision. 해석 불가면 None (기권으로 기록된다)."""
        if text.strip().upper() == "HOLD":
            return {"cancels": [], "orders": [], "replaces": []}
        m = RESPONSE_RE.match(text)
        if not m:
            return None
        side = m.group(1).lower()
        qty, price = int(m.group(2)), int(m.group(3))
        order = {"side": side, "price": price, "qty": qty}
        open_orders = list(snapshot["me"]["open_orders"].keys())
        if open_orders:
            # 노출 교체는 원자적으로: 판단 시점에 열려 있던 가장 오래된 주문 대상
            return {"cancels": [], "orders": [],
                    "replaces": [{"old": sorted(open_orders)[0], "order": order}]}
        return {"cancels": [], "orders": [order], "replaces": []}

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
