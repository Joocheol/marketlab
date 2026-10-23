"""로컬 LLM 본 실험: 모델 이질성 비교 (API 미사용).

조건 3개 × 20런 × 20라운드, 매 라운드 5에이전트가 실제 LLM 판단(총 6,000호출):
  qwen  — 5개 페르소나 전부 qwen2.5:7b
  llama — 전부 llama3.1:8b
  mixed — momentum·aggressive=llama3.1:8b, value·mm·conservative=qwen2.5:7b

같은 페르소나 프롬프트·같은 시장(CDA, 최우선 호가 공개, 종료 비고지)에서
기반 모델만 바꾼다. 측정: 시장 지표(체결·가격·변동성) + 모델별 행동 지표
(파싱 실패=기권율, 위험한도 클립율, HOLD율, 호출 지연) + 페르소나 손익.

실행: python3 experiments/claude-pilot/local_llm_experiment.py [runs] [rounds]
산출: state/local-exp/ (런별 record·call log, gitignore), local-exp-summary.json
"""

import json
import pathlib
import statistics
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
from marketlab.llm.adapter import BudgetGuard, CallLog, LiveAdapter  # noqa: E402
from marketlab.llm.ollama import OllamaTransport, server_alive  # noqa: E402
from marketlab.mechanisms.cda import CDA                   # noqa: E402

QWEN, LLAMA = "qwen2.5:7b", "llama3.1:8b"

PERSONAS = {
    "momentum": ("너는 공격적인 모멘텀 트레이더다. 가격 추세에 편승해 단기 수익을 극대화하라 — "
                 "오르면 사고 내리면 팔아라. 한도: 1회 주문 최대 5주.", 5, 1),
    "value": ("너는 보수적인 가치 투자자다. 이 주식의 내재가치를 100으로 보고, 95 이하면 매수·"
              "105 이상이면 매도하라. 보유 주식 20주를 팔아 수익을 실현할 수 있다. "
              "한도: 1회 최대 3주.", 3, 1),
    "mm": ("너는 마켓메이커다. 방향 베팅 없이 매수·매도 양방향 호가를 동시에 내 스프레드로 "
           "수익을 내라. 참고가 주변에 매수 1줄과 매도 1줄, 두 줄로 답하라(각 최대 2주). "
           "예: 'BUY 2 @ 98' 다음 줄 'SELL 2 @ 102'.", 2, 2),
    "conservative": ("너는 극도로 위험회피적인 투자자다. 자본 보존이 최우선이고 명백히 유리할 "
                     "때만 1주 거래하라. 대부분 HOLD가 정상이다. 한도: 1회 1주.", 1, 1),
    "aggressive": ("너는 공격적인 투기자다. 수익 극대화를 위해 과감하게 베팅하라 — 유리한 "
                   "호가는 즉시 걷어라. 보유 주식 매도도 적극 활용하라. 한도: 1회 최대 8주.",
                   8, 1),
}
STAMP = ("[시장 규칙] 단일 종목 지정가 시장. 가격은 1~200 정수. 미체결 주문은 새 주문 시 교체된다. "
         "매수는 현금, 매도는 보유 주식 범위 내에서만 체결된다. "
         "반드시 'BUY <수량> @ <가격>' / 'SELL <수량> @ <가격>' / 'HOLD' 형식으로만 답하라.")

CONDITIONS = {
    "qwen": {aid: QWEN for aid in PERSONAS},
    "llama": {aid: LLAMA for aid in PERSONAS},
    "mixed": {"momentum": LLAMA, "aggressive": LLAMA,
              "value": QWEN, "mm": QWEN, "conservative": QWEN},
}
CASH0, SH0 = 2000, 20


def engine_factory(m):
    return MarketEngine(CDA(), BestQuoteOnly(), seed=m["seed"])


def run_one(condition, run_seed, rounds, out_dir):
    model_map = CONDITIONS[condition]
    meta = {"factors": {"mechanism": "cda", "condition": condition},
            "seed": run_seed, "models": model_map}
    log = CallLog()
    budget = BudgetGuard(max_calls=rounds * len(PERSONAS) + 5)
    adapters = {}

    def adapter_for(model):
        if model not in adapters:
            adapters[model] = LiveAdapter(OllamaTransport(), log, budget, model,
                                          {"temperature": 0.7}, timeout=180.0)
        return adapters[model]

    eng = engine_factory(meta)
    gw = Gateway(eng)
    agents = []
    for aid, (persona, max_qty, max_orders) in sorted(PERSONAS.items()):
        a = LLMAgent(aid, persona + "\n" + STAMP, cash=CASH0, shares=SH0,
                     max_qty=max_qty, max_orders=max_orders)
        a.adapter = adapter_for(model_map[aid])
        agents.append(a)
    runner = AsyncRounds(gw, agents, agents[0].adapter, master_seed=run_seed)
    runner.setup()
    t0 = time.time()
    runner.run(rounds)
    wall = time.time() - t0

    record = make_record(gw, meta)
    (out_dir / f"{condition}-r{run_seed}-record.json").write_text(json.dumps(record))
    (out_dir / f"{condition}-r{run_seed}-calls.json").write_text(log.to_json())

    trades = [ev for ev in eng.log if ev["type"] == "trade"]
    prices = [ev["price"] for ev in trades]
    abstains = {}
    for e in gw.arrivals:
        if e["k"] == "abs":
            abstains[e["agent"]] = abstains.get(e["agent"], 0) + 1
    holds = {}
    for d in runner.decision_log:
        if not d["dec"].get("orders") and not d["dec"].get("replaces"):
            holds[d["agent"]] = holds.get(d["agent"], 0) + 1
    lat = {}
    for e in log.entries:
        lat.setdefault(e["model"], []).append(e.get("latency", 0))
    row = {"condition": condition, "run": run_seed, "wall_sec": round(wall, 1),
           "llm_calls": len(log), "n_trades": len(trades),
           "volume": sum(ev["qty"] for ev in trades),
           "last_price": prices[-1] if prices else None,
           "mean_price": statistics.mean(prices) if prices else None,
           "price_sd": statistics.stdev(prices) if len(prices) > 1 else None,
           "abstains": abstains, "holds": holds,
           "clips": {a.agent_id: a.n_clipped for a in agents},
           "latency_mean": {m: statistics.mean(v) for m, v in lat.items()},
           "violations": len(check_invariants(eng.state, (CASH0 * 5, SH0 * 5))),
           }
    mark = prices[-1] if prices else 100
    for aid in PERSONAS:
        acc = eng.state["accounts"][aid]
        cash = acc["cash"] + acc["res_cash"]
        sh = acc["shares"] + acc["res_shares"]
        row[f"pnl100_{aid}"] = (cash + sh * 100) - (CASH0 + SH0 * 100)
        row[f"pnlL_{aid}"] = (cash + sh * mark) - (CASH0 + SH0 * mark)
    # 첫 런만 도착 로그 재생 검증
    if run_seed == 0:
        row["record_replay_ok"] = (
            state_hash(replay_record(record, engine_factory).state)
            == state_hash(eng.state))
    return row


def main():
    runs = int(sys.argv[1]) if len(sys.argv) > 1 else 20
    rounds = int(sys.argv[2]) if len(sys.argv) > 2 else 20
    assert server_alive(), "Ollama 서버가 응답하지 않습니다"
    out_dir = pathlib.Path(__file__).parent / "state" / "local-exp"
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for condition in CONDITIONS:
        for run_seed in range(runs):
            row = run_one(condition, run_seed, rounds, out_dir)
            rows.append(row)
            print(json.dumps({k: row[k] for k in
                              ("condition", "run", "wall_sec", "n_trades",
                               "mean_price")}, ensure_ascii=False), flush=True)
    (pathlib.Path(__file__).parent / "local-exp-rows.json").write_text(
        json.dumps(rows, indent=1))
    print("DONE", len(rows), "runs")


if __name__ == "__main__":
    main()
