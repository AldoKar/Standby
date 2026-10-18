"""Spending mandate and policy engine.

Every money decision is made here, in code. The LLM never decides on a spend
and never sees card data.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone


@dataclass
class Mandate:
    instruction: str
    budget_usd: float
    ask_over_usd: float
    allowed_mcc: list[str]
    token_id: str
    expires_at: datetime

    @classmethod
    def from_dict(cls, d: dict) -> "Mandate":
        return cls(
            instruction=d["instruction"],
            budget_usd=float(d["budget_usd"]),
            ask_over_usd=float(d["ask_over_usd"]),
            allowed_mcc=list(d["allowed_mcc"]),
            token_id=d["token_id"],
            expires_at=datetime.now(timezone.utc) + timedelta(hours=d.get("expires_hours", 48)),
        )

    def allows_mcc(self, mcc: str) -> bool:
        code = int(mcc)
        for rule in self.allowed_mcc:
            if "-" in rule:
                lo, hi = (int(x) for x in rule.split("-"))
                if lo <= code <= hi:
                    return True
            elif code == int(rule):
                return True
        return False

    def as_dict(self) -> dict:
        return {
            "instruction": self.instruction,
            "budget_usd": self.budget_usd,
            "ask_over_usd": self.ask_over_usd,
            "allowed_mcc": self.allowed_mcc,
            "token_id": self.token_id,
            "expires_at": self.expires_at.isoformat(),
            "label": "Simulated, modeled on Visa Intelligent Commerce and Trusted Agent Protocol",
        }


@dataclass
class Ledger:
    spends: list[dict] = field(default_factory=list)
    refunds: list[dict] = field(default_factory=list)
    consents: list[dict] = field(default_factory=list)
    denied: list[dict] = field(default_factory=list)

    def spent(self) -> float:
        return round(sum(s["amount"] for s in self.spends), 2)

    def remaining(self, m: Mandate) -> float:
        return round(m.budget_usd - self.spent(), 2)

    def view(self, m: Mandate) -> dict:
        refunded = round(sum(r["amount"] for r in self.refunds), 2)
        return {
            "mandate": m.as_dict(),
            "spent_usd": self.spent(),
            "remaining_usd": self.remaining(m),
            "refunds_pending_usd": refunded,
            "net_cost_usd": round(self.spent() - refunded, 2),
            "spends": self.spends,
            "refunds": self.refunds,
            "consents": self.consents,
            "denied": self.denied,
        }


def check_spend(m: Mandate, ledger: Ledger, amount: float, mcc: str, fee_allowance: float = 0) -> tuple[str, str]:
    """Return (decision, reason). decision is allow, ask or deny."""
    if datetime.now(timezone.utc) > m.expires_at:
        return "deny", "mandate expired; confirm on phone"
    if not m.allows_mcc(mcc):
        return "deny", f"merchant category {mcc} is not in the mandate; confirm on phone"
    left = ledger.remaining(m)
    if amount > left:
        return "deny", f"${amount:g} > ${left:g} left; deny, confirm on phone"
    if amount <= m.ask_over_usd:
        return "allow", f"${amount:g} is within the ${m.ask_over_usd:g} ask limit; allowed silently"
    if fee_allowance and amount <= fee_allowance:
        return "allow", f"${amount:g} is within the ${fee_allowance:g} fee allowance set at booking"
    return "ask", f"${amount:g} > ${m.ask_over_usd:g} ask limit; ask the wearer"


def rank_options(options: list[dict], m: Mandate, ledger: Ledger, deadline: dict) -> list[dict]:
    """Filter options deterministically and mark one as the pick."""
    left = ledger.remaining(m)
    ranked = []
    for o in options:
        o = dict(o)
        if o["day"] != "today" or o["arrives"] > deadline["arrive_by"]:
            o["verdict"], o["reason"] = "rejected", f"arrives {o['day']}, misses {deadline['label']}"
        elif o["price_usd"] > left:
            o["verdict"], o["reason"] = "rejected", f"${o['price_usd']} is over the ${left:g} budget"
        else:
            o["verdict"], o["reason"] = "ok", f"arrives {o['arrives']} tonight, ${o['price_usd']} fits the budget"
        ranked.append(o)
    ok = [o for o in ranked if o["verdict"] == "ok"]
    if ok:
        min(ok, key=lambda o: (o["arrives"], o["price_usd"]))["verdict"] = "pick"
    return ranked


def arrival_eta(arrives: str, travel_minutes: int) -> str:
    h, mnt = (int(x) for x in arrives.split(":"))
    total = h * 60 + mnt + travel_minutes
    return f"{(total // 60) % 24:02d}:{total % 60:02d}"
