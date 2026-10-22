"""반사실 실행기 (설계안 §7).

재현 패키지(도착 로그)에 외과수술을 가한 뒤 엔진의 '처리 경로'로 재구동한다.
이벤트 폴드 재생(core.replay)과 달리 매칭이 다시 계산되므로, "다른 조건이었다면
시장이 어떻게 됐을까"에 답한다. 도착 순서는 고정되므로 순서 효과가 통제된
반사실이다 (보고서 10.7).

M3 범위: 에이전트 절제(ablation) — "이 에이전트가 없었다면".
δ 재배정 반사실은 판단 로그(LLM 호출 로그)가 생기는 M4에서 추가된다.
"""

from marketlab.gateway.ingress import replay_record


def without_agent(record, agent_id):
    """도착 로그에서 한 에이전트의 모든 흔적(계좌·주문·취소·기권·관찰)을 제거한
    반사실 기록을 만든다. 나머지 참여자의 도착 순서는 그대로다."""
    owned = {e["oid"] for e in record["arrivals"]
             if e["k"] in ("sub", "rep") and e["agent"] == agent_id}
    kept = []
    for e in record["arrivals"]:
        k = e["k"]
        if k in ("acct", "sub", "rep", "abs", "snap") and e.get("agent") == agent_id:
            continue
        if k == "can" and e["oid"] in owned:
            continue
        kept.append(e)
    return {"meta": dict(record["meta"], counterfactual=f"without:{agent_id}"),
            "arrivals": kept, "final_hash": None}


def run_counterfactual(record, engine_factory):
    """수술된 기록을 처리 경로로 재구동해 엔진을 돌려준다."""
    return replay_record(record, engine_factory)


def redelay(record, decision_log, delay_model, engine_factory, seed=0):
    """δ 재배정 반사실 (설계안 §4): 기록된 '판단'은 그대로 두고 지연 가정만
    바꿔 도착 순서를 재구성한다. M4에서 판단 로그(호출 로그의 파싱 결과)가
    생기면서 가능해진 반사실 — '같은 응답들, 다른 속도의 세계'.

    record: 원 런의 재현 패키지 (계좌 초기화를 여기서 복원)
    decision_log: [{"t": 판단 시점, "agent": id, "dec": Decision}, ...]
    delay_model: (agent_id, rng) -> δ
    주의: 판단 속 replace 대상 oid는 원 런의 주문을 가리키므로, 새 타이밍에서
    대상이 없으면 replace_target_gone으로 거부된다 — 반사실에서도 판단은
    문자 그대로 집행된다는 의미론.
    """
    import random as _random

    from marketlab.gateway.ingress import Gateway

    eng = engine_factory(record["meta"])
    gw = Gateway(eng)
    for e in record["arrivals"]:
        if e["k"] == "acct":
            gw.create_account(e["agent"], e["cash"], e["shares"])
    rng = _random.Random(f"redelay-{seed}")
    sched = sorted(
        ((d["t"] + delay_model(d["agent"], rng), i, d)
         for i, d in enumerate(decision_log)),
        key=lambda x: (x[0], x[1]))
    tick = 0
    for t, i, d in sched:
        while tick < int(t):
            gw.clock()
            tick += 1
        aid, dec = d["agent"], d["dec"]
        for oid in dec.get("cancels", []):
            gw.cancel(oid, gw.epoch)
        for j, rep in enumerate(dec.get("replaces", [])):
            o = rep["order"]
            gw.cancel_replace(rep["old"], f"cf{i}-{aid}-x{j}", aid,
                              o["side"], o["price"], o["qty"], gw.epoch)
        for j, o in enumerate(dec.get("orders", [])):
            gw.submit(f"cf{i}-{aid}-{j}", aid, o["side"], o["price"],
                      o["qty"], gw.epoch)
    gw.clock()
    return eng
