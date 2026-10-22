"""에이전트 인터페이스 (설계안 §5).

판단은 순수 함수에 가깝다: 스냅샷(InfoPolicy가 걸러 준 것)과 자기 상태를 보고
Decision을 반환할 뿐, 시장 상태는 건드리지 못한다. 부작용(주문 제출)은
스케줄러가 게이트웨이를 통해 수행한다. None 반환 = 기권.

Decision = {"cancels": [oid, ...], "orders": [{"side","price","qty"}, ...]}
"""


class AgentBase:
    def __init__(self, agent_id):
        self.agent_id = agent_id

    def endowment(self):
        """(cash, shares) 초기 자산."""
        raise NotImplementedError

    def decide(self, snapshot, ctx):
        """Decision 또는 None(기권)을 반환. ctx: {"round": int}."""
        raise NotImplementedError
