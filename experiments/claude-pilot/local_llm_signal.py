"""신호 구조 × 로컬 LLM: 실제 LLM 판단 하의 가격발견 실험 (API 미사용).

매 런 V~U[80,120] 추출, 에이전트별 사적 신호 s=V+U[-8,8]를 프롬프트에 주입.
조건 3개(qwen/llama/혼성) × 20런 × 20라운드. **같은 run_seed는 조건과 무관하게
같은 V·같은 신호**를 받으므로 조건 간 짝지은 비교가 가능하다.

질문: ① 소형 LLM 시장이 분산된 사적 정보를 가격으로 집계하는가
(클론 정책 기준선: |종가-V|=1.89 ≈ 5신호 평균 1.96) ② 모델별 차이는?

실행: python3 experiments/claude-pilot/local_llm_signal.py [runs] [rounds]
"""

import json
import pathlib
import random
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

QWEN, LLAMA, QWEN14 = "qwen2.5:7b", "llama3.1:8b", "qwen2.5:14b"

PERSONAS = {
    "momentum": ("너는 공격적인 모멘텀 트레이더다. 가격 추세와 네 신호를 함께 활용해 "
                 "단기 수익을 극대화하라. 한도: 1회 주문 최대 5주.", 5, 1),
    "value": ("너는 보수적인 가치 투자자다. 네 사적 신호를 청산가치의 추정 근거로 삼아 "
              "충분히 저평가된 가격에 사고 충분히 고평가된 가격에 팔아라. "
              "한도: 1회 최대 3주.", 3, 1),
    "mm": ("너는 마켓메이커다. 방향 베팅 없이 매수·매도 양방향 호가로 스프레드 수익을 "
           "내되, 정보 우위자에게 당하지 않게 호가 중심과 폭을 신중히 정하라. "
           "매수 1줄·매도 1줄 두 줄로 답하라(각 최대 2주).", 2, 2),
    "conservative": ("너는 극도로 위험회피적인 투자자다. 자본 보존이 최우선이고, 네 신호 "
                     "기준으로 명백히 유리할 때만 1주 거래하라. 대부분 HOLD가 정상이다.",
                     1, 1),
    "aggressive": ("너는 공격적인 투기자다. 네 신호와 시장가의 괴리에서 기회를 포착해 "
                   "과감히 베팅하라. 한도: 1회 최대 8주.", 8, 1),
}
BASE_STAMP = ("[시장 규칙] 단일 종목 지정가 시장. 가격은 1~200 정수. 미체결 주문은 새 주문 시 "
              "교체된다. 매수는 현금, 매도는 보유 주식 범위 내에서만 체결된다. "
              "반드시 'BUY <수량> @ <가격>' / 'SELL <수량> @ <가격>' / 'HOLD' 형식으로만 답하라.")

CONDITIONS = {
    "qwen": {aid: QWEN for aid in PERSONAS},
    "llama": {aid: LLAMA for aid in PERSONAS},
    "mixed": {"momentum": LLAMA, "aggressive": LLAMA,
              "value": QWEN, "mm": QWEN, "conservative": QWEN},
    "qwen14": {aid: QWEN14 for aid in PERSONAS},   # 판별 조건: 같은 계열, 2배 크기
}
CASH0, SH0 = 3000, 20          # V 상한 120에서도 매수 여력이 있도록 현금 확대


def draw_signals(run_seed):
    rng = random.Random(f"V-{run_seed}")       # 조건 간 공유 (짝지은 설계)
    v = rng.randint(80, 120)
    return v, {aid: v + rng.randint(-8, 8) for aid in sorted(PERSONAS)}


def engine_factory(m):
    return MarketEngine(CDA(), BestQuoteOnly(), seed=m["seed"])


def run_one(condition, run_seed, rounds, out_dir):
    model_map = CONDITIONS[condition]
    v, signals = draw_signals(run_seed)
    meta = {"factors": {"mechanism": "cda", "condition": condition,
                        "structure": "signal"},
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
        info = (f"[자산 정보] 이 자산은 알 수 없는 시점에 주당 V로 청산된다. V는 80~120 "
                f"사이에서 정해졌고 아무도 모른다. 너의 사적 신호: {signals[aid]} "
                f"(V±최대 8, 무편향). 다른 참가자 4명도 각자 독립적인 신호를 가진다. "
                f"이 구조는 모두가 안다.")
        a = LLMAgent(aid, persona + "\n" + info + "\n" + BASE_STAMP,
                     cash=CASH0, shares=SH0, max_qty=max_qty,
                     max_orders=max_orders)
        a.adapter = adapter_for(model_map[aid])
        agents.append(a)
    runner = AsyncRounds(gw, agents, agents[0].adapter, master_seed=run_seed)
    runner.setup()
    t0 = time.time()
    runner.run(rounds)
    wall = time.time() - t0

    record = make_record(gw, meta)
    (out_dir / f"sig-{condition}-r{run_seed}-record.json").write_text(json.dumps(record))
    (out_dir / f"sig-{condition}-r{run_seed}-calls.json").write_text(log.to_json())

    trades = [ev for ev in eng.log if ev["type"] == "trade"]
    prices = [ev["price"] for ev in trades]
    row = {"condition": condition, "run": run_seed, "V": v, "signals": signals,
           "wall_sec": round(wall, 1), "llm_calls": len(log),
           "n_trades": len(trades), "volume": sum(ev["qty"] for ev in trades),
           "last_price": prices[-1] if prices else None,
           "mean_price": statistics.mean(prices) if prices else None,
           "abstains": eng.state["abstained"],
           "clips": sum(a.n_clipped for a in agents),
           "violations": len(check_invariants(eng.state, (CASH0 * 5, SH0 * 5)))}
    mark = v                                   # 손익은 참 청산가치 기준
    for aid in PERSONAS:
        acc = eng.state["accounts"][aid]
        cash = acc["cash"] + acc["res_cash"]
        sh = acc["shares"] + acc["res_shares"]
        row[f"pnlV_{aid}"] = (cash + sh * mark) - (CASH0 + SH0 * mark)
    if run_seed == 0:
        row["record_replay_ok"] = (
            state_hash(replay_record(record, engine_factory).state)
            == state_hash(eng.state))
    return row


def main():
    runs = int(sys.argv[1]) if len(sys.argv) > 1 else 20
    rounds = int(sys.argv[2]) if len(sys.argv) > 2 else 20
    only = sys.argv[3].split(",") if len(sys.argv) > 3 else list(CONDITIONS)
    assert server_alive(), "Ollama 서버가 응답하지 않습니다"
    out_dir = pathlib.Path(__file__).parent / "state" / "local-exp"
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    out_rows = pathlib.Path(__file__).parent / "local-signal-rows.json"
    if out_rows.exists():
        rows = [r for r in json.loads(out_rows.read_text())
                if r["condition"] not in only]   # 기존 조건 결과 보존, 재실행 조건만 교체
    for condition in only:
        for run_seed in range(runs):
            row = run_one(condition, run_seed, rounds, out_dir)
            rows.append(row)
            print(json.dumps({k: row[k] for k in
                              ("condition", "run", "V", "n_trades",
                               "last_price", "wall_sec")},
                             ensure_ascii=False), flush=True)
    out_rows.write_text(json.dumps(rows, indent=1))
    print("DONE", len(rows), "runs")


if __name__ == "__main__":
    main()
