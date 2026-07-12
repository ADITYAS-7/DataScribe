from pathlib import Path

import pandas as pd
import pytest

from core.diff_engine import ReconError, compare_datasets

SAMPLE_DIR = Path(__file__).parent / "sample_data"

COLUMN_MAPPING = {
    "order_id": "OrderID",
    "customer_name": "CustName",
    "amount": "Amt",
    "order_date": "OrderDate",
    "status": "Status",
}


@pytest.fixture
def orders():
    source_df = pd.read_csv(SAMPLE_DIR / "source_orders.csv")
    source_df["customer_name"] = source_df["customer_name"].str.strip()
    target_df = pd.read_csv(SAMPLE_DIR / "target_orders.csv")
    return source_df, target_df


def test_matched_and_missing_counts(orders):
    source_df, target_df = orders
    result = compare_datasets(
        source_df,
        target_df,
        key_columns=["order_id"],
        column_mapping=COLUMN_MAPPING,
        column_rules={
            "customer_name": {"case_insensitive": True},
            "amount": {"tolerance": 0.01},
            "order_date": {"date_only": True},
        },
    )

    # order 1: case-insensitive name + date_only -> matches
    # order 3: whitespace-trimmed name, exact amount, date_only -> matches
    assert result.matched_count == 2
    assert result.missing_in_target_count == 1
    assert result.missing_in_source_count == 1
    assert result.missing_in_target["order_id"].tolist() == [5]
    assert result.missing_in_source["order_id"].tolist() == [6]


def test_mismatch_detection_and_field_level_diff(orders):
    source_df, target_df = orders
    result = compare_datasets(
        source_df,
        target_df,
        key_columns=["order_id"],
        column_mapping=COLUMN_MAPPING,
        column_rules={
            "customer_name": {"case_insensitive": True},
            "amount": {"tolerance": 0.01},
            "order_date": {"date_only": True},
        },
    )

    mismatched = result.mismatched_rows.set_index("order_id")
    assert set(mismatched.index) == {2, 4}

    # order 2: amount differs by 0.25, over the 0.01 tolerance
    row2 = mismatched.loc[2]
    assert row2["differing_columns"] == ["amount"]
    assert row2["amount_source"] == 250.50
    assert row2["amount_target"] == 250.75

    # order 4: amount and status both differ
    row4 = mismatched.loc[4]
    assert set(row4["differing_columns"]) == {"amount", "status"}
    assert row4["status_source"] == "Shipped"
    assert row4["status_target"] == "Delivered"


def test_summary_dict_shape(orders):
    source_df, target_df = orders
    result = compare_datasets(
        source_df,
        target_df,
        key_columns=["order_id"],
        column_mapping=COLUMN_MAPPING,
        column_rules={
            "customer_name": {"case_insensitive": True},
            "amount": {"tolerance": 0.01},
            "order_date": {"date_only": True},
        },
    )
    assert result.summary == {
        "total_source_rows": 5,
        "total_target_rows": 5,
        "matched": 2,
        "mismatched": 2,
        "missing_in_target": 1,
        "missing_in_source": 1,
        "match_rate": 0.5,
    }


def test_no_rules_means_exact_match_required(orders):
    source_df, target_df = orders
    result = compare_datasets(
        source_df,
        target_df,
        key_columns=["order_id"],
        column_mapping=COLUMN_MAPPING,
    )
    # without case_insensitive/tolerance/date_only rules, order 1 and 3 also mismatch
    assert result.matched_count == 0
    assert result.mismatched_count == 4


def test_numeric_tolerance_widened_absorbs_small_diff(orders):
    source_df, target_df = orders
    result = compare_datasets(
        source_df,
        target_df,
        key_columns=["order_id"],
        column_mapping=COLUMN_MAPPING,
        column_rules={
            "customer_name": {"case_insensitive": True},
            "amount": {"tolerance": 5.0},
            "order_date": {"date_only": True},
            "status": {},
        },
    )
    mismatched = result.mismatched_rows.set_index("order_id")
    # order 2 (0.25 diff) now within tolerance; order 4 (5.0 diff exactly) within tolerance too,
    # but its status still differs
    assert set(mismatched.index) == {4}
    assert mismatched.loc[4]["differing_columns"] == ["status"]


def test_composite_key():
    source_df = pd.DataFrame(
        {
            "region": ["US", "US", "EU"],
            "sku": ["A1", "A2", "B1"],
            "qty": [10, 20, 30],
        }
    )
    target_df = pd.DataFrame(
        {
            "region": ["US", "US", "EU"],
            "sku": ["A1", "A2", "B1"],
            "qty": [10, 99, 30],
        }
    )
    result = compare_datasets(
        source_df,
        target_df,
        key_columns=["region", "sku"],
        column_mapping={"region": "region", "sku": "sku", "qty": "qty"},
    )
    assert result.matched_count == 2
    assert result.mismatched_count == 1
    assert result.mismatched_rows.iloc[0]["differing_columns"] == ["qty"]


def test_duplicate_keys_raise():
    source_df = pd.DataFrame({"id": [1, 1], "val": [1, 2]})
    target_df = pd.DataFrame({"id": [1], "val": [1]})
    with pytest.raises(ReconError, match="duplicate keys"):
        compare_datasets(
            source_df,
            target_df,
            key_columns=["id"],
            column_mapping={"id": "id", "val": "val"},
        )


def test_missing_column_mapping_raises():
    source_df = pd.DataFrame({"id": [1], "val": [1]})
    target_df = pd.DataFrame({"id": [1], "val": [1]})
    with pytest.raises(ReconError, match="missing source columns"):
        compare_datasets(
            source_df,
            target_df,
            key_columns=["id"],
            column_mapping={"id": "id", "does_not_exist": "val"},
        )
