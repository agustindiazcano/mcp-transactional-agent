import pytest
from pydantic import ValidationError

from src.core.config import settings
from src.mcp_server.tools.schemas import ExecuteRefundArgs, ValidateFraudScoreArgs


def test_execute_refund_args_accepts_valid_payload():
    args = ExecuteRefundArgs(transaction_id="txn-1", amount=100.0, currency="USD")

    assert args.transaction_id == "txn-1"
    assert args.amount == 100.0


def test_execute_refund_args_defaults_currency_to_usd():
    args = ExecuteRefundArgs(transaction_id="txn-1", amount=100.0)

    assert args.currency == "USD"


def test_execute_refund_args_rejects_amount_above_max():
    with pytest.raises(ValidationError):
        ExecuteRefundArgs(
            transaction_id="txn-1",
            amount=settings.REFUND_MAX_AMOUNT + 1,
            currency="USD",
        )


def test_execute_refund_args_rejects_non_positive_amount():
    with pytest.raises(ValidationError):
        ExecuteRefundArgs(transaction_id="txn-1", amount=0, currency="USD")


def test_execute_refund_args_rejects_unknown_currency():
    with pytest.raises(ValidationError):
        ExecuteRefundArgs(transaction_id="txn-1", amount=100.0, currency="XYZ")


def test_execute_refund_args_rejects_unknown_fields():
    with pytest.raises(ValidationError):
        ExecuteRefundArgs(
            transaction_id="txn-1",
            amount=100.0,
            currency="USD",
            admin_override=True,
        )


def test_validate_fraud_score_args_rejects_unknown_fields():
    with pytest.raises(ValidationError):
        ValidateFraudScoreArgs(user_id="user-1", extra_field="nope")
