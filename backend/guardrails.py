"""Payment rules enforced in code, never by the LLM."""

MAX_PRICE = 250

# task_id -> True (granted) / False (rejected). One approval pays once.
approvals: dict[str, bool] = {}


class GuardrailError(Exception):
    pass


def check_payment(task_id: str, amount: float) -> None:
    if amount <= 0:
        raise GuardrailError("amount must be positive")
    if amount > MAX_PRICE:
        raise GuardrailError(f"${amount} is over the ${MAX_PRICE} limit")
    if approvals.get(task_id) is not True:
        raise GuardrailError(f"no approval for {task_id}")


def consume_approval(task_id: str) -> None:
    approvals.pop(task_id, None)
