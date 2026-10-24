"""무앵커 × 매 틱 LLM 버블 실험 (구조화 출력, 긴 지평).

연구 원점 질문("LLM 시장은 버블을 만드는가")에 대한 첫 정면 실험.
청산가치 고지 없음 — 가치 투자자 페르소나만 '내재가치 100' 신념을 갖는
무앵커 체제(클론 정책 실험에서 +8% 내생 랠리·자유 표류를 만든 구조).
JSON 스키마 강제로 형식 축 제거, 지평 60라운드(종료 비고지).

조건: llama-b(전원 llama3.1:8b, 가장 활동적) / qwen14-b(전원 qwen2.5:14b,
가장 유능) / mix14-b(모멘텀·공격=llama8, 가치·MM·보수=qwen14 — 능력 비대칭).

실행: python3 experiments/claude-pilot/local_llm_bubble.py [runs] [rounds] [conds]
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

LLAMA, QWEN14 = "llama3.1:8b", "qwen2.5:14b"

PERSONAS = {
    "momentum": ("너는 공격적인 모멘텀 트레이더다. 가격 추세에 편승해 단기 수익을 극대화하라 — "
                 "오르면 사고 내리면 팔아라. 한도: 1회 주문 최대 5주.", 5, 1),
    "value": ("너는 보수적인 가치 투자자다. 이 주식의 내재가치를 100으로 보고, 95 이하면 매수·"
              "105 이상이면 매도하라. 보유 주식을 팔아 수익을 실현할 수 있다. "
              "한도: 1회 최대 3주.", 3, 1),
    "mm": ("너는 마켓메이커다. 방향 베팅 없이 매수·매도 양방향 호가를 동시에 내 스프레드로 "
           "수익을 내라(각 최대 2주).", 2, 2),
    "conservative": ("너는 극도로 위험회피적인 투자자다. 자본 보존이 최우선이고 명백히 유리할 "
                     "때만 1주 거래하라. 거래하지 않는 라운드가 많아도 정상이다.", 1, 1),
    "aggressive": ("너는 공격적인 투기자다. 수익 극대화를 위해 과감하게 베팅하라 — 유리한 "
                   "호가는 즉시 걷고, 고점이라 판단하면 미련 없이 팔아라. 한도: 1회 최대 8주.",
                   8, 1),
}
STAMP = ("[시장 규칙] 단일 종목 지정가 시장. 가격은 1~200 정수. 초기 참고가는 100 부근으로 "
         "알려져 있을 뿐, 자산의 객관적 가치는 공표된 바 없다. 미체결 주문은 새 주문 시 "
         "교체된다. 매수는 현금, 매도는 보유 주식 범위 내에서만 체결된다. JSON으로만 답하라.")

CONDITIONS = {
    "llama-b": {aid: LLAMA for aid in PERSONAS},
    "qwen14-b": {aid: QWEN14 for aid in PERSONAS},
    "mix14-b": {"momentum": LLAMA, "aggressive": LLAMA,
                "value": QWEN14, "mm": QWEN14, "conservative": QWEN14},
}
CASH0, SH0 = 3000, 20


def order_schema(max_orders):
    return {"type": "object", "required": ["orders"], "properties": {
        "orders": {"type": "array", "maxItems": max_orders, "items": {
            "type": "object", "required": ["side", "price", "qty"],
            "properties": {"side": {"type": "string", "enum": ["buy", "sell"]},
                           "price": {"type": "integer"},
                           "qty": {"type": "integer"}}}}}}


def engine_factory(m):
    return MarketEngine(CDA(), BestQuoteOnly(), seed=m["seed"])


def run_one(condition, run_seed, rounds, out_dir):
    model_map = CONDITIONS[condition]
    meta = {"factors": {"mechanism": "cda", "condition": condition,
                        "structure": "no-anchor", "structured_output": True},
            "seed": run_seed, "models": model_map}
    log = CallLog()
    budget = BudgetGuard(max_calls=rounds * len(PERSONAS) + 5)
    adapters = {}

    def adapter_for(model, max_orders):
        key = (model, max_orders)
        if key not in adapters:
            adapters[key] = LiveAdapter(
                OllamaTransport(), log, budget, model,
                {"temperature": 0.7, "format": order_schema(max_orders)},
                timeout=180.0)
        return adapters[key]

    eng = engine_factory(meta)
    gw = Gateway(eng)
    agents = []
    for aid, (persona, max_qty, max_orders) in sorted(PERSONAS.items()):
        a = LLMAgent(aid, persona + "\n" + STAMP, cash=CASH0, shares=SH0,
                     max_qty=max_qty, max_orders=max_orders, structured=True)
        a.adapter = adapter_for(model_map[aid], max_orders)
        agents.append(a)
    runner = AsyncRounds(gw, agents, agents[0].adapter, master_seed=run_seed)
    runner.setup()

    # 라운드별 가격 경로를 틱 경계에서 수집 (버블 지표용)
    path, seen, last = [], 0, None
    t0 = time.time()
    import asyncio

    async def run_with_path():
        nonlocal seen, last
        for r in range(rounds):
            if not await runner._round(r):
                break
            for ev in eng.log[seen:]:
                if ev["type"] == "trade":
                    last = ev["price"]
            seen = len(eng.log)
            path.append(last)
    asyncio.run(run_with_path())
    wall = time.time() - t0

    record = make_record(gw, meta)
    (out_dir / f"bub-{condition}-r{run_seed}-record.json").write_text(json.dumps(record))
    (out_dir / f"bub-{condition}-r{run_seed}-calls.json").write_text(log.to_json())

    trades = [ev for ev in eng.log if ev["type"] == "trade"]
    prices = [p for p in path if p is not None]
    row = {"condition": condition, "run": run_seed, "wall_sec": round(wall, 1),
           "n_trades": len(trades), "volume": sum(ev["qty"] for ev in trades),
           "path": path,
           "last_price": prices[-1] if prices else None,
           "max_price": max(prices) if prices else None,
           "min_price": min(prices) if prices else None,
           "rounds_above_105": sum(1 for p in prices if p > 105),
           "rounds_below_95": sum(1 for p in prices if p < 95),
           "clips": sum(a.n_clipped for a in agents),
           "abstains": eng.state["abstained"],
           "violations": len(check_invariants(eng.state, (CASH0 * 5, SH0 * 5)))}
    mark = prices[-1] if prices else 100
    for aid in PERSONAS:
        acc = eng.state["accounts"][aid]
        cash = acc["cash"] + acc["res_cash"]
        sh = acc["shares"] + acc["res_shares"]
        row[f"pnl100_{aid}"] = (cash + sh * 100) - (CASH0 + SH0 * 100)
        row[f"pnlL_{aid}"] = (cash + sh * mark) - (CASH0 + SH0 * mark)
    if run_seed == 0:
        row["record_replay_ok"] = (
            state_hash(replay_record(record, engine_factory).state)
            == state_hash(eng.state))
    return row


def main():
    runs = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    rounds = int(sys.argv[2]) if len(sys.argv) > 2 else 60
    only = sys.argv[3].split(",") if len(sys.argv) > 3 else list(CONDITIONS)
    assert server_alive(), "Ollama 서버가 응답하지 않습니다"
    out_dir = pathlib.Path(__file__).parent / "state" / "local-exp"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_rows = pathlib.Path(__file__).parent / "local-bubble-rows.json"
    rows = []
    if out_rows.exists():
        rows = json.loads(out_rows.read_text())
    done = {(r["condition"], r["run"]) for r in rows if len(r["path"]) >= rounds}
    rows = [r for r in rows if len(r["path"]) >= rounds]   # 짧은 스모크 행 제거
    for condition in only:
        for run_seed in range(runs):
            if (condition, run_seed) in done:
                continue                          # 이어달리기: 기존 런 보존
            row = run_one(condition, run_seed, rounds, out_dir)
            rows.append(row)
            print(json.dumps({k: row[k] for k in
                              ("condition", "run", "n_trades", "last_price",
                               "max_price", "min_price", "wall_sec")},
                             ensure_ascii=False), flush=True)
    out_rows.write_text(json.dumps(rows, indent=1))
    print("DONE", len(rows), "rows")


if __name__ == "__main__":
    main()
