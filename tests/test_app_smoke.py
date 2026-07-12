"""End-to-end smoke test of the Streamlit wizard using streamlit.testing.

AppTest can't drive the file uploader, so we pre-seed the fetched
DataFrames into session_state (exactly what the uploader would produce)
and verify the rest of the wizard: auto-mapping, key selection, running
the comparison, and results in session_state.
"""

from pathlib import Path

import pandas as pd
from streamlit.testing.v1 import AppTest

PROJECT_ROOT = Path(__file__).parent.parent
SAMPLE_DIR = Path(__file__).parent / "sample_data"


def _make_app() -> AppTest:
    at = AppTest.from_file(str(PROJECT_ROOT / "ui" / "app.py"), default_timeout=30)
    source_df = pd.read_csv(SAMPLE_DIR / "source_orders.csv")
    source_df["customer_name"] = source_df["customer_name"].str.strip()
    target_df = pd.read_csv(SAMPLE_DIR / "target_orders.csv")
    at.session_state["source_df"] = source_df
    at.session_state["source_label"] = "source_orders.csv"
    at.session_state["target_df"] = target_df
    at.session_state["target_label"] = "target_orders.csv"
    return at


def test_wizard_renders_without_errors():
    at = _make_app().run()
    assert not at.exception
    # auto-mapping should have matched order_id -> OrderID by normalization
    assert at.selectbox(key="map_order_id").value == "OrderID"
    # key column defaulted to the *_id column
    assert at.multiselect[0].value == ["order_id"]


def test_run_comparison_produces_result():
    at = _make_app().run()
    run_buttons = [b for b in at.button if "Run comparison" in b.label]
    assert run_buttons, "Run comparison button not rendered"
    at = run_buttons[0].click().run()
    assert not at.exception

    result = at.session_state["result"]
    # exact-equality defaults (no rules toggled): orders 2 and 4 mismatch on
    # amount/status; 1 and 3 also mismatch (case/date format differences)
    assert result.summary["missing_in_target"] == 1
    assert result.summary["missing_in_source"] == 1
    assert result.summary["matched"] + result.summary["mismatched"] == 4
