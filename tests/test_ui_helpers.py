from ui.helpers import suggest_mapping


def test_exact_match_after_normalization():
    suggestions = suggest_mapping(
        ["order_id", "customer_name", "amount"],
        ["OrderID", "CustName", "Amt"],
    )
    assert suggestions["order_id"] == "OrderID"


def test_fuzzy_match_picks_close_names():
    suggestions = suggest_mapping(
        ["customer_name", "order_date"],
        ["CustomerName", "OrderDate"],
    )
    assert suggestions == {
        "customer_name": "CustomerName",
        "order_date": "OrderDate",
    }


def test_no_target_column_used_twice():
    suggestions = suggest_mapping(["amount", "amount_usd"], ["Amount"])
    assert list(suggestions.values()).count("Amount") == 1


def test_unrelated_names_not_matched():
    suggestions = suggest_mapping(["order_id"], ["ZZTopRecords"])
    assert "order_id" not in suggestions
