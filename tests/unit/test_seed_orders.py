"""The sample orders must be loadable as-is: every one a valid order the
gateway and the MCP boundary would accept a full refund for."""
from scripts.seed_orders import SAMPLE_ORDERS
from src.core.config import settings
from src.core.currency import Currency


def test_sample_order_ids_are_unique() -> None:
    ids = [order["order_id"] for order in SAMPLE_ORDERS]

    assert len(ids) == len(set(ids))


def test_sample_orders_are_refundable_within_limits() -> None:
    for order in SAMPLE_ORDERS:
        assert 0 < order["amount"] <= settings.REFUND_MAX_AMOUNT, order
        assert order["currency"] in {c.value for c in Currency}, order
        assert order["user_id"], order


def test_dashboard_default_user_has_orders() -> None:
    """The dashboard form defaults to user-1, so a demo works out of the box."""
    assert any(order["user_id"] == "user-1" for order in SAMPLE_ORDERS)
