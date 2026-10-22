"""실험 관리자 (설계안 §7).

BehaviorSpace의 개념(요인 공간 위의 프로토콜)을 가져오되, NetLogo 실측이
확정한 요구를 구조로 해결한다:
  - 격리 자동화: 런 = 새 프로세스의 새 엔진. 워크스페이스 재사용이라는
    오염 원천 자체가 없다 (보고서 13.1 실험 4).
  - 시드 파생: run_seed = sha256(master, 요인 조합, 반복번호). 시각 기반
    시드의 충돌 가능성(보고서 5.2)을 원천 차단하고, 같은 조합·반복은
    어느 머신에서든 같은 시드를 받는다.
  - 런 산출물 = 재현 패키지: config + 도착 로그 + 최종 해시 + 메트릭.
"""

import hashlib
import itertools
import json
import os
from concurrent.futures import ProcessPoolExecutor

from marketlab.agents.rule import SpreadImprover
from marketlab.agents.zi import ZITrader
from marketlab.analysis.metrics import compute_metrics
from marketlab.clock.latency import LatencyRounds
from marketlab.clock.sync_rounds import SyncRounds
from marketlab.core.engine import MarketEngine
from marketlab.disclosure.policies import BestQuoteOnly, FullBook, TradesOnly
from marketlab.gateway.ingress import Gateway, make_record

MECHANISMS = {}
POLICIES = {"full_book": FullBook, "best_quote_only": BestQuoteOnly,
            "trades_only": TradesOnly}


def _mechanisms():
    # 늦은 임포트: 순환 의존 없이 레지스트리 유지
    if not MECHANISMS:
        from marketlab.mechanisms.cda import CDA
        from marketlab.mechanisms.call_auction import CallAuction
        MECHANISMS.update({"cda": CDA, "call_auction": CallAuction})
    return MECHANISMS


def derive_seed(master, key, rep):
    h = hashlib.sha256(f"{master}|{key}|{rep}".encode()).hexdigest()
    return int(h[:16], 16)


def expand_runs(config):
    """요인 공간 × 반복 → 런 명세 목록 (결정적 순서·결정적 시드)."""
    factors = config["factors"]
    names = sorted(factors)
    runs = []
    for values in itertools.product(*(factors[n] for n in names)):
        combo = dict(zip(names, values))
        combo_key = json.dumps(combo, sort_keys=True)
        short = hashlib.sha256(combo_key.encode()).hexdigest()[:8]
        for rep in range(config["repetitions"]):
            runs.append({
                "run_id": f"{config['name']}-{short}-r{rep}",
                "factors": combo, "rep": rep,
                "seed": derive_seed(config["master_seed"], combo_key, rep)})
    return runs


def build_population(pop_spec, run_seed):
    agents = []
    for g, group in enumerate(pop_spec):
        for i in range(group.get("count", 1)):
            aseed = derive_seed(run_seed, f"agent-{g}", i)
            if group["type"] == "zi":
                agents.append(ZITrader(
                    f"{group['role'][0]}{g}_{i}", group["role"],
                    list(group["values"]), group.get("pmin", 1),
                    group.get("pmax", 200), aseed, cash=group.get("cash")))
            elif group["type"] == "noise":
                from marketlab.agents.noise import NoiseTrader
                agents.append(NoiseTrader(
                    f"n{g}_{i}", cash=group.get("cash", 5000),
                    shares=group.get("shares", 20),
                    band=group.get("band", 10), seed=aseed))
            elif group["type"] == "spread":
                agents.append(SpreadImprover(
                    f"r{g}_{i}", cash=group.get("cash", 500),
                    shares=group.get("shares", 5)))
            else:
                raise ValueError("unknown agent type: " + group["type"])
    return agents


def engine_factory(meta):
    """재현 패키지 meta로 엔진을 복원한다 (replay_record용)."""
    f = meta["factors"]
    mech = _mechanisms()[f["mechanism"]]()
    policy = POLICIES[f.get("info_policy", "best_quote_only")]()
    return MarketEngine(mech, policy, seed=meta["seed"])


def _make_delay_model(spec):
    slow = spec.get("slow", {})

    def model(agent_id, rng):
        d = rng.uniform(spec["lo"], spec["hi"])
        return d + slow.get(agent_id, 0.0)
    return model


def execute_run(spec, out_dir=None):
    """런 하나를 처음부터 끝까지 실행한다. 병렬 시 각 워커 프로세스에서 호출."""
    f = spec["factors"]
    meta = {"factors": f, "seed": spec["seed"], "run_id": spec["run_id"]}
    eng = engine_factory(meta)
    gw = Gateway(eng)
    agents = build_population(f["population"], spec["seed"])
    clock = f["clock"]
    if clock["mode"] == "sync":
        runner = SyncRounds(gw, agents, master_seed=spec["seed"])
        runner.setup()
        runner.run(clock["rounds"])
    elif clock["mode"] == "latency":
        runner = LatencyRounds(gw, agents, _make_delay_model(clock["delay"]),
                               master_seed=spec["seed"])
        runner.setup()
        runner.run(clock["horizon"])
    else:
        raise ValueError("unknown clock mode: " + clock["mode"])

    record = make_record(gw, meta)
    result = {"run_id": spec["run_id"], "factors": f, "rep": spec["rep"],
              "seed": spec["seed"], "final_hash": record["final_hash"],
              "metrics": compute_metrics(eng.log)}
    if out_dir:
        rd = os.path.join(out_dir, spec["run_id"])
        os.makedirs(rd, exist_ok=True)
        with open(os.path.join(rd, "record.json"), "w") as fp:
            json.dump(record, fp)
        with open(os.path.join(rd, "result.json"), "w") as fp:
            json.dump(result, fp, indent=1)
    return result


def run_experiment(config, out_dir, max_workers=1):
    """실험 전체를 실행하고 manifest를 남긴다. max_workers>1이면 프로세스 병렬."""
    runs = expand_runs(config)
    os.makedirs(out_dir, exist_ok=True)
    if max_workers > 1:
        with ProcessPoolExecutor(max_workers=max_workers) as ex:
            results = list(ex.map(execute_run, runs, [out_dir] * len(runs)))
    else:
        results = [execute_run(spec, out_dir) for spec in runs]
    manifest = {"config": config, "results": results}
    with open(os.path.join(out_dir, "manifest.json"), "w") as fp:
        json.dump(manifest, fp, indent=1)
    return results
