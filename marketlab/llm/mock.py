"""모의 LLM 전송계층: 실제 LLM의 '통제 불가능한' 성질을 일부러 재현한다.

- 시드 불가능한 난수(os.urandom): 같은 프롬프트에도 매번 다른 응답
- 가변 지연: asyncio.sleep
- 간헐적 형식 위반(파싱 불가 텍스트)과 간헐적 초과 지연(어댑터 타임아웃 유발)

검증 대상은 판단 품질이 아니라 기록·재생 장치이므로 이것으로 충분하다 (M4 범위).
"""

import asyncio
import random
import re


class MockTransport:
    def __init__(self, junk_rate=0.1, slow_rate=0.05,
                 latency=(0.001, 0.01), slow_latency=1.0):
        self.rng = random.SystemRandom()
        self.junk_rate = junk_rate
        self.slow_rate = slow_rate
        self.latency = latency
        self.slow_latency = slow_latency

    async def __call__(self, req, model, params):
        if self.rng.random() < self.slow_rate:
            await asyncio.sleep(self.slow_latency)      # 어댑터 타임아웃을 넘긴다
        else:
            await asyncio.sleep(self.rng.uniform(*self.latency))
        if self.rng.random() < self.junk_rate:
            text = "Considering current market conditions, I would rather wait and see."
        else:
            m = re.search(r"REF=(\d+)", req["prompt"])
            ref = int(m.group(1)) if m else 100
            side = self.rng.choice(["BUY", "SELL"])
            qty = self.rng.randint(1, 4)
            price = max(1, ref + self.rng.randint(-6, 6))
            text = f"{side} {qty} @ {price}"
        words = len(req["prompt"].split()) + len(text.split())
        return {"text": text, "usage": {"total_tokens": words},
                "finish_reason": "stop"}
