"""LLM 어댑터 3모드 + 호출 로그 + 예산 가드 (설계안 §6).

세 어댑터가 같은 인터페이스(async call(req) -> resp)를 공유한다:
  LiveAdapter   — 전송계층(transport)을 통해 실제/모의 LLM을 호출하고 전 과정을
                  호출 로그에 기록. 실제 HTTP 전송은 승인 전까지 차단 게이트
                  (disabled_transport)가 기본값.
  ReplayAdapter — 호출 로그의 기록만 돌려준다. 미기록 호출은 오류(ReplayMiss):
                  재현이 깨졌음을 침묵시키지 않는다. 프롬프트 해시가 다르면
                  ReplayDivergence: 프롬프트 구성 로직이 달라졌다는 뜻이다.
  CacheAdapter  — 기록에 있으면 재생, 없으면 live 후 기록 (실험 이어돌리기).

호출 로그 항목 = 재현의 완전조건: call_id(멱등 키), epoch, 모델·파라미터,
프롬프트 전문과 해시, 응답 전문, 토큰 사용량, 종료 사유, 지연, 오류.
타임아웃도 '기록되는 결과'다 — 재생 시 같은 타임아웃이 재연된다.
"""

import asyncio
import hashlib
import json
import time


class LLMError(Exception):
    pass


class LLMTimeout(LLMError):
    pass


class LiveCallsDisabled(LLMError):
    pass


class BudgetExhausted(LLMError):
    pass


class ReplayMiss(LLMError):
    pass


class ReplayDivergence(LLMError):
    pass


def prompt_hash(prompt):
    return hashlib.sha256(prompt.encode()).hexdigest()


class CallLog:
    def __init__(self, entries=None):
        self.entries = []
        self._by_id = {}
        for e in entries or []:
            self.append(e)

    def append(self, entry):
        self.entries.append(entry)
        self._by_id[entry["call_id"]] = entry

    def get(self, call_id):
        return self._by_id.get(call_id)

    def __len__(self):
        return len(self.entries)

    def to_json(self):
        return json.dumps(self.entries, sort_keys=True)

    @classmethod
    def from_json(cls, text):
        return cls(json.loads(text))


class BudgetGuard:
    """호출 수·토큰·비용 상한. 초과 시 다음 호출 전에 BudgetExhausted —
    런은 '예산 소진'으로 정상 종료되고 부분 기록도 재생 가능하다."""

    def __init__(self, max_calls=None, max_tokens=None, max_cost=None,
                 price_per_1k_tokens=0.0):
        self.max_calls, self.max_tokens, self.max_cost = max_calls, max_tokens, max_cost
        self.price_per_1k = price_per_1k_tokens
        self.calls = 0
        self.tokens = 0
        self.cost = 0.0

    def reserve(self):
        """호출 '시작 시점'에 슬롯을 예약한다. 검사와 소비를 분리하면 병렬
        발사된 호출들이 모두 검사를 통과한 뒤 상한을 초과하는 경합이 생긴다
        (M4 테스트가 검출) — 예약이 곧 소비 확정이다."""
        if ((self.max_calls is not None and self.calls >= self.max_calls)
                or (self.max_tokens is not None and self.tokens >= self.max_tokens)
                or (self.max_cost is not None and self.cost >= self.max_cost)):
            raise BudgetExhausted(
                f"budget exhausted: calls={self.calls} tokens={self.tokens} "
                f"cost={self.cost:.4f}")
        self.calls += 1

    def consume(self, usage):
        t = (usage or {}).get("total_tokens", 0)
        self.tokens += t
        self.cost += t / 1000.0 * self.price_per_1k


async def disabled_transport(req, model, params):
    raise LiveCallsDisabled(
        "실제 LLM API 호출은 비용 승인 후에만 활성화됩니다 (설계안 §10-E).")


class LiveAdapter:
    def __init__(self, transport, call_log, budget, model, params=None,
                 timeout=10.0):
        self.transport = transport
        self.log = call_log
        self.budget = budget
        self.model = model
        self.params = params or {}
        self.timeout = timeout

    async def call(self, req):
        self.budget.reserve()
        base = {"call_id": req["call_id"], "epoch": req["epoch"],
                "model": self.model, "params": self.params,
                "prompt": req["prompt"], "prompt_hash": prompt_hash(req["prompt"])}
        t0 = time.monotonic()
        try:
            raw = await asyncio.wait_for(
                self.transport(req, self.model, self.params), self.timeout)
        except asyncio.TimeoutError:
            self.log.append(base | {"error": "timeout",
                                    "latency": time.monotonic() - t0})
            raise LLMTimeout(req["call_id"])
        entry = base | {"text": raw["text"], "usage": raw.get("usage"),
                        "finish_reason": raw.get("finish_reason", "stop"),
                        "latency": time.monotonic() - t0}
        self.log.append(entry)
        self.budget.consume(raw.get("usage"))
        return {"call_id": req["call_id"], "text": raw["text"]}


class ReplayAdapter:
    def __init__(self, call_log):
        self.log = call_log

    async def call(self, req):
        e = self.log.get(req["call_id"])
        if e is None:
            raise ReplayMiss(f"no recorded response for {req['call_id']}")
        if e["prompt_hash"] != prompt_hash(req["prompt"]):
            raise ReplayDivergence(
                f"prompt for {req['call_id']} differs from the recorded one")
        if e.get("error") == "timeout":
            raise LLMTimeout(req["call_id"])
        if e.get("error"):
            raise LLMError(e["error"])
        return {"call_id": req["call_id"], "text": e["text"]}


class CacheAdapter:
    def __init__(self, call_log, live_adapter):
        self.replay = ReplayAdapter(call_log)
        self.live = live_adapter
        self.log = call_log

    async def call(self, req):
        if self.log.get(req["call_id"]) is not None:
            return await self.replay.call(req)   # 해시 불일치면 그대로 오류
        return await self.live.call(req)
