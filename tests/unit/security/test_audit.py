from src.mcp_server.security.audit import mask_pii


def test_mask_pii_masks_known_pii_keys():
    arguments = {"user_id": "user-123", "amount": 50.0}

    masked = mask_pii(arguments)

    assert masked["user_id"] == "***MASKED***"
    assert masked["amount"] == 50.0


def test_mask_pii_is_case_insensitive_on_keys():
    arguments = {"User_Id": "user-123"}

    masked = mask_pii(arguments)

    assert masked["User_Id"] == "***MASKED***"


def test_mask_pii_leaves_non_pii_keys_untouched():
    arguments = {"transaction_id": "txn-1", "currency": "USD"}

    masked = mask_pii(arguments)

    assert masked == arguments


def test_mask_pii_preserves_all_keys():
    arguments = {"user_id": "user-1", "transaction_id": "txn-1"}

    masked = mask_pii(arguments)

    assert set(masked.keys()) == set(arguments.keys())
