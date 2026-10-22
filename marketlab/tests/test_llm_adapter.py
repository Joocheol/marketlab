"""어댑터 계층 단위 테스트: 호출 로그·예산 가드·재생 오류 의미론·라이브 게이트."""

import asyncio
import unittest

from marketlab.llm.adapter import (BudgetExhausted, BudgetGuard, CallLog,
                                   CacheAdapter, LiveAdapter, LiveCallsDisabled,
                                   LLMTimeout, ReplayAdapter, ReplayDivergence,
                                   ReplayMiss, disabled_transport, prompt_hash)


def run(coro):
    return asyncio.run(coro)


async def ok_transport(req, model, params):
    return {"text": "BUY 1 @ 100", "usage": {"total_tokens": 10},
            "finish_reason": "stop"}


async def slow_transport(req, model, params):
    await asyncio.sleep(0.2)
    return {"text": "late", "usage": {"total_tokens": 1}}


def req(cid="c1", prompt="p"):
    return {"call_id": cid, "epoch": 0, "prompt": prompt}


class AdapterUnitTests(unittest.TestCase):

    def test_call_log_json_roundtrip(self):
        log = CallLog()
        log.append({"call_id": "a", "prompt_hash": "x", "text": "t"})
        log2 = CallLog.from_json(log.to_json())
        self.assertEqual(log2.get("a")["text"], "t")

    def test_budget_guard_counts_and_cost(self):
        g = BudgetGuard(max_calls=2, price_per_1k_tokens=3.0)
        g.reserve(); g.consume({"total_tokens": 500})
        g.reserve(); g.consume({"total_tokens": 500})
        self.assertAlmostEqual(g.cost, 3.0)
        with self.assertRaises(BudgetExhausted):
            g.reserve()                            # 예약 = 소비 확정 (경합 차단)

    def test_live_adapter_records_and_times_out(self):
        log = CallLog()
        live = LiveAdapter(slow_transport, log, BudgetGuard(), "mock-model",
                           timeout=0.01)
        with self.assertRaises(LLMTimeout):
            run(live.call(req()))
        self.assertEqual(log.get("c1")["error"], "timeout")
        # 재생도 같은 타임아웃을 재연한다
        with self.assertRaises(LLMTimeout):
            run(ReplayAdapter(log).call(req()))

    def test_replay_miss_and_divergence(self):
        log = CallLog()
        live = LiveAdapter(ok_transport, log, BudgetGuard(), "mock-model")
        run(live.call(req("c1", "prompt-A")))
        rep = ReplayAdapter(log)
        self.assertEqual(run(rep.call(req("c1", "prompt-A")))["text"],
                         "BUY 1 @ 100")
        with self.assertRaises(ReplayMiss):
            run(rep.call(req("c2", "prompt-A")))
        with self.assertRaises(ReplayDivergence):
            run(rep.call(req("c1", "prompt-B")))   # 프롬프트 구성 변경 탐지

    def test_cache_uses_recorded_before_live(self):
        log = CallLog()
        run(LiveAdapter(ok_transport, log, BudgetGuard(), "m").call(req("c1")))
        # live 쪽이 '차단된 전송'이어도, 기록이 있으면 닿지 않는다
        gated = LiveAdapter(disabled_transport, log, BudgetGuard(), "m")
        cache = CacheAdapter(log, gated)
        self.assertEqual(run(cache.call(req("c1")))["text"], "BUY 1 @ 100")
        with self.assertRaises(LiveCallsDisabled):
            run(cache.call(req("c9")))             # 미기록 호출만 live로 간다

    def test_default_live_transport_is_gated(self):
        live = LiveAdapter(disabled_transport, CallLog(), BudgetGuard(), "real")
        with self.assertRaises(LiveCallsDisabled):
            run(live.call(req()))


if __name__ == "__main__":
    unittest.main()
