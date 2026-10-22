"""InfoPolicy: 누가 무엇을 보는가 (설계안 §3).

에이전트는 엔진 상태를 직접 읽지 못하고, 정책이 만들어 준 스냅샷만 받는다.
자기 계좌와 자기 주문은 모든 정책에서 보인다(자기 정보까지 숨기는 것은
별도 연구 가정이므로 여기서는 배제).
"""


def _own(state, agent):
    a = state["accounts"][agent]
    own_orders = {oid: {"side": o["side"], "price": o["price"],
                        "remaining": o["remaining"]}
                  for oid, o in state["orders"].items()
                  if o["agent"] == agent and o["status"] == "open"}
    return {"cash": a["cash"], "res_cash": a["res_cash"],
            "shares": a["shares"], "res_shares": a["res_shares"],
            "open_orders": own_orders}


def _best(state, side_book):
    book = state[side_book]
    return state["orders"][book[0]]["price"] if book else None


def _levels(state, side_book, depth):
    levels = {}
    for oid in state[side_book]:
        o = state["orders"][oid]
        levels[o["price"]] = levels.get(o["price"], 0) + o["remaining"]
    reverse = side_book == "bids"
    return [[p, levels[p]] for p in sorted(levels, reverse=reverse)[:depth]]


class FullBook:
    """호가장 전체(가격 수준별 집계)."""
    name = "full_book"

    def __init__(self, depth=10):
        self.depth = depth

    def view(self, state, agent):
        return {"policy": self.name, "tick": state["tick"],
                "ref_price": state["ref_price"],
                "bids": _levels(state, "bids", self.depth),
                "asks": _levels(state, "asks", self.depth),
                "me": _own(state, agent)}


class BestQuoteOnly:
    """최우선 호가만."""
    name = "best_quote_only"

    def view(self, state, agent):
        return {"policy": self.name, "tick": state["tick"],
                "ref_price": state["ref_price"],
                "best_bid": _best(state, "bids"),
                "best_ask": _best(state, "asks"),
                "me": _own(state, agent)}


class TradesOnly:
    """직전 체결가만 (호가 비공개)."""
    name = "trades_only"

    def view(self, state, agent):
        return {"policy": self.name, "tick": state["tick"],
                "ref_price": state["ref_price"],
                "me": _own(state, agent)}
