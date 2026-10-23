"""로컬 LLM 매 틱 판단 실험 (API 미사용, Ollama).

M4 LiveAdapter의 전송만 localhost Ollama로 바꾼 '진짜 매 틱 LLM' 시장.
에이전트별로 서로 다른 모델을 배정해 '모델 이질성' 요인을 처음으로 연다:
  qwen2.5:7b  — value, mm, conservative
  llama3.1:8b — momentum, aggressive

검증 항목: 체결 발생, 기권(파싱 실패) 경로, 호출 로그 재생의 해시 일치,
회계 불변식. 실행: python3 experiments/claude-pilot/local_llm_run.py [runs] [rounds]
"""

import json
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from marketlab.agents.llm_agent import LLMAgent            # noqa: E402
from marketlab.clock.async_rounds import AsyncRounds       # noqa: E402
from marketlab.core.engine import MarketEngine             # noqa: E402
from marketlab.core.invariants import check_invariants     # noqa: E402
from marketlab.core.state import state_hash                # noqa: E402
from marketlab.disclosure.policies import BestQuoteOnly    # noqa: E402
from marketlab.gateway.ingress import Gateway, make_record, replay_record  # noqa: E402
from marketlab.llm.adapter import BudgetGuard, CallLog, LiveAdapter, ReplayAdapter  # noqa: E402
from marketlab.llm.ollama import OllamaTransport, server_alive  # noqa: E402
from marketlab.mechanisms.cda import CDA                   # noqa: E402

# (persona, model, max_qty, max_orders)
PERSONAS = {
    "momentum": ("너는 공격적인 모멘텀 트레이더다. 가격 추세에 편승해 단기 수익을 극대화하라 — "
                 "오르면 사고 내리면 팔아라. 한도: 1회 주문 최대 5주.", "llama3.1:8b", 5, 1),
    "value": ("너는 보수적인 가치 투자자다. 이 주식의 내재가치를 100으로 보고, 95 이하면 매수·"
              "105 이상이면 매도하라. 보유 주식 20주를 팔아 수익을 실현할 수 있다. "
              "한도: 1회 최대 3주.", "qwen2.5:7b", 3, 1),
    "mm": ("너는 마켓메이커다. 방향 베팅 없이 매수·매도 양방향 호가를 동시에 내 스프레드로 "
           "수익을 내라. 참고가 주변에 매수 1줄과 매도 1줄, 두 줄로 답하라(각 최대 2주). "
           "예: 'BUY 2 @ 98' 다음 줄 'SELL 2 @ 102'.", "qwen2.5:7b", 2, 2),
    "conservative": ("너는 극도로 위험회피적인 투자자다. 자본 보존이 최우선이고 명백히 유리할 "
                     "때만 1주 거래하라. 대부분 HOLD가 정상이다. 한도: 1회 1주.",
                     "qwen2.5:7b", 1, 1),
    "aggressive": ("너는 공격적인 투기자다. 수익 극대화를 위해 과감하게 베팅하라 — 유리한 "
                   "호가는 즉시 걷어라. 보유 주식 매도도 적극 활용하라. 한도: 1회 최대 8주.",
                   "llama3.1:8b", 8, 1),
}
STAMP = ("[시장 규칙] 단일 종목 지정가 시장. 가격은 1~200 정수. 미체결 주문은 새 주문 시 교체된다. "
         "매수는 현금, 매도는 보유 주식 범위 내에서만 체결된다. "
         "반드시 'BUY <수량> @ <가격>' / 'SELL <수량> @ <가격>' / 'HOLD' 형식으로만 답하라.")


def meta(run_seed):
    return {"factors": {"mechanism": "cda", "info_policy": "best_quote_only",
                        "population": "local-llm-mixed",
                        "clock": {"mode": "async_sync"}},
            "seed": run_seed,
            "models": {aid: p[1] for aid, p in PERSONAS.items()}}


def engine_factory(m):
    return MarketEngine(CDA(), BestQuoteOnly(), seed=m["seed"])


def build(run_seed, adapter_factory):
    eng = engine_factory(meta(run_seed))
    gw = Gateway(eng)
    agents = []
    for aid, (persona, model, max_qty, max_orders) in sorted(PERSONAS.items()):
        a = LLMAgent(aid, persona + "\n" + STAMP, cash=2000, shares=20,
                     max_qty=max_qty, max_orders=max_orders)
        a.adapter = adapter_factory(model)
        agents.append(a)
    runner = AsyncRounds(gw, agents, agents[0].adapter, master_seed=run_seed)
    runner.setup()
    return eng, gw, runner


def main():
    runs = int(sys.argv[1]) if len(sys.argv) > 1 else 2
    rounds = int(sys.argv[2]) if len(sys.argv) > 2 else 8
    assert server_alive(), "Ollama 서버가 응답하지 않습니다"
    state_dir = pathlib.Path(__file__).parent / "state"
    results = []
    for run_seed in range(runs):
        log = CallLog()
        budget = BudgetGuard(max_calls=rounds * len(PERSONAS) + 5)
        adapters = {}

        def live_factory(model, _log=log, _b=budget):
            if model not in adapters:
                adapters[model] = LiveAdapter(OllamaTransport(), _log, _b,
                                              model, {"temperature": 0.7},
                                              timeout=180.0)
            return adapters[model]

        t0 = time.time()
        eng, gw, runner = build(run_seed, live_factory)
        runner.run(rounds)
        wall = time.time() - t0
        h_live = state_hash(eng.state)
        record = make_record(gw, meta(run_seed))
        (state_dir / f"local-run{run_seed}-record.json").write_text(json.dumps(record))
        (state_dir / f"local-run{run_seed}-calls.json").write_text(log.to_json())

        # 재생 검증 1: 도착 로그 재생
        h_rec = state_hash(replay_record(record, engine_factory).state)
        # 재생 검증 2: 호출 로그로 러너 전체 재실행 (LLM 없이)
        restored = CallLog.from_json(log.to_json())

        def replay_factory(model, _r=ReplayAdapter(restored)):
            return _r

        try:
            eng2, _, runner2 = build(run_seed, replay_factory)
            runner2.run(rounds)
            h_llm_replay = state_hash(eng2.state)
        except Exception as e:  # noqa: BLE001
            h_llm_replay = f"ERROR:{type(e).__name__}"

        trades = [ev for ev in eng.log if ev["type"] == "trade"]
        totals = (2000 * 5, 20 * 5)
        res = {
            "run": run_seed, "wall_sec": round(wall, 1),
            "llm_calls": len(log), "n_trades": len(trades),
            "prices": [ev["price"] for ev in trades],
            "abstained": eng.state["abstained"],
            "invariant_violations": len(check_invariants(eng.state, totals)),
            "record_replay_ok": h_rec == h_live,
            "call_log_replay_ok": h_llm_replay == h_live,
        }
        results.append(res)
        print(json.dumps(res, ensure_ascii=False))
    (state_dir / "local-llm-results.json").write_text(json.dumps(results, indent=1))


if __name__ == "__main__":
    main()
