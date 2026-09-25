import pytest

from tests.performance.chaos_idempotency import (
    Outcome,
    build_submission_plan,
    orders_for_plan,
)


def test_plan_has_the_requested_number_of_duplicates() -> None:
    plan = build_submission_plan("run", total=200, dup_rate=0.10, seed=1)

    assert len(plan) == 200
    assert sum(c.is_duplicate for c in plan) == 20
    assert len({c.request_id for c in plan}) == 180


def test_every_duplicate_follows_its_original_with_the_same_body() -> None:
    plan = build_submission_plan("run", total=300, dup_rate=0.25, seed=7)

    first_seen: dict[str, int] = {}
    for position, claim in enumerate(plan):
        if claim.is_duplicate:
            original = plan[first_seen[claim.request_id]]
            assert first_seen[claim.request_id] < position
            assert claim.body == original.body
        else:
            assert claim.request_id not in first_seen
            first_seen[claim.request_id] = position


def test_plan_claims_are_executable_and_tagged_with_the_run() -> None:
    plan = build_submission_plan("chaos-1", total=10, dup_rate=0.0, seed=0)

    for claim in plan:
        assert claim.request_id.startswith("chaos-1-")
        assert claim.body["order_id"] and claim.body["amount"] > 0


def test_plan_is_reproducible_for_a_seed() -> None:
    a = build_submission_plan("r", total=100, dup_rate=0.1, seed=3)
    b = build_submission_plan("r", total=100, dup_rate=0.1, seed=3)

    assert [c.request_id for c in a] == [c.request_id for c in b]


@pytest.mark.parametrize("total, dup_rate", [(0, 0.1), (10, 1.0), (10, -0.1)])
def test_plan_rejects_invalid_arguments(total: int, dup_rate: float) -> None:
    with pytest.raises(ValueError):
        build_submission_plan("r", total=total, dup_rate=dup_rate, seed=0)


def _outcome(**overrides: int) -> Outcome:
    values = {
        "accepted_unique": 10,
        "missing": 0,
        "stuck_processing": 0,
        "refund_rows": 10,
        "refunded_request_ids": 10,
        "completed_without_refund": 0,
        "refund_without_completed": 0,
        "already_executed_replays": 0,
    }
    values.update(overrides)
    return Outcome(status_counts={"COMPLETED": 10}, **values)


def test_clean_outcome_passes() -> None:
    assert _outcome().failures() == []


def test_double_refund_fails_the_run() -> None:
    outcome = _outcome(refund_rows=11)

    assert outcome.double_refunds == 1
    assert outcome.failures() == ["1 double refund(s)"]


def test_missing_and_stuck_claims_count_as_lost() -> None:
    outcome = _outcome(missing=3, stuck_processing=2)

    assert outcome.lost == 5
    assert len(outcome.failures()) == 2


def test_replays_absorbed_by_idempotency_are_not_failures() -> None:
    assert _outcome(already_executed_replays=4).failures() == []


def test_every_claim_has_a_matching_order_to_pass_the_evidence_check() -> None:
    """Part B checks each refund against its order before the judges, so the
    run seeds one order per unique claim: same user, amount and currency."""
    plan = build_submission_plan("chaos-1", total=20, dup_rate=0.25, seed=3)

    orders = orders_for_plan(plan)

    unique = {c.request_id: c.body for c in plan}
    assert len(orders) == len(unique)
    by_id = {o["order_id"]: o for o in orders}
    for body in unique.values():
        order = by_id[body["order_id"]]
        assert order["user_id"] == body["user_id"]
        assert order["amount"] == body["amount"]
        assert order["currency"] == body["currency"]
