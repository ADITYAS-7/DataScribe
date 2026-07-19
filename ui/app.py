"""Streamlit UI for Data Scribe.

Run from the project root:

    streamlit run ui/app.py

Flow: pick source -> pick target -> map columns & keys -> set rules -> run.
Fetched DataFrames live in st.session_state; Snowflake passwords are used
only to open the connection and are never stored or logged.
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

# Make project-root imports work when launched as `streamlit run ui/app.py`.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from connectors.file_connector import FileDataSource  # noqa: E402
from connectors.snowflake_connector import SnowflakeDataSource  # noqa: E402
from core.diff_engine import ReconError, compare_datasets  # noqa: E402
from ui.helpers import normalize_column_name, suggest_mapping  # noqa: E402

LOGO_LIGHT_PATH = PROJECT_ROOT / "assets" / "datascribe-lockup.png"
LOGO_DARK_PATH = PROJECT_ROOT / "assets" / "datascribe-lockup-dark.png"

st.set_page_config(page_title="Data Scribe", page_icon=str(LOGO_LIGHT_PATH), layout="wide")


def _in_sis() -> bool:
    """True when running inside Streamlit in Snowflake — the viewer already
    has an authenticated Snowflake session (their own SSO'd Snowsight
    login), so the Snowflake picker doesn't need a credentials form at all."""
    try:
        from snowflake.snowpark.context import get_active_session

        get_active_session()
        return True
    except Exception:
        return False


IN_SIS = _in_sis()

UNMAPPED = "— not mapped —"


# Streamlit doesn't allow changing theme.base at runtime ("cannot be set on
# the fly"), so the toggle works by injecting a CSS palette that overrides
# the active theme in both directions. Session state (uploaded data, wizard
# progress) survives the switch because nothing reloads.
_PALETTES = {
    "light": {
        "bg": "#ffffff",
        "bg2": "#f0f2f6",
        "text": "#31333f",
        "muted": "#6e7387",
        "border": "#d5d9e0",
        # st.dataframe draws on a canvas whose colors come from Streamlit's
        # native theme (always light); in dark mode we recolor it with a
        # CSS invert filter tuned so white lands near the dark palette.
        "df_filter": "none",
    },
    "dark": {
        "bg": "#0e1117",
        "bg2": "#262730",
        "text": "#fafafa",
        "muted": "#a3a8b8",
        "border": "#3d4051",
        "df_filter": "invert(0.86) hue-rotate(180deg)",
    },
}


def _inject_theme_css() -> None:
    p = _PALETTES["dark" if st.session_state.get("dark_mode") else "light"]
    st.markdown(
        f"""
        <style>
        .stApp, [data-testid="stHeader"] {{
            background-color: {p["bg"]};
            color: {p["text"]};
        }}
        section[data-testid="stSidebar"],
        [data-testid="stSidebarContent"] {{
            background-color: {p["bg2"]} !important;
        }}
        h1, h2, h3, h4, h5, h6,
        [data-testid="stWidgetLabel"] p,
        [data-testid="stMetricValue"],
        [data-testid="stMetricLabel"] p,
        [data-testid="stMarkdownContainer"] p,
        [data-testid="stExpander"] summary p,
        .stRadio label p, .stCheckbox label p, .stToggle label p {{
            color: {p["text"]} !important;
        }}
        [data-testid="stCaptionContainer"] p {{
            color: {p["muted"]} !important;
        }}
        [data-testid="stMarkdownContainer"] p.ds-muted {{
            color: {p["muted"]} !important;
        }}
        /* Tooltip boxes keep a white background in both themes, so their
           text must stay dark regardless of the toggle. */
        [data-testid="stTooltipContent"] p,
        [data-baseweb="tooltip"] p {{
            color: #31333f !important;
        }}
        [data-baseweb="input"] input, [data-baseweb="textarea"] textarea,
        [data-baseweb="input"], [data-baseweb="textarea"],
        [data-baseweb="select"] > div,
        [data-testid="stTextInputRootElement"],
        [data-testid="stTextAreaRootElement"],
        [data-testid="stNumberInputContainer"] {{
            background-color: {p["bg2"]} !important;
            color: {p["text"]} !important;
            border-color: {p["border"]} !important;
        }}
        [data-testid="stTextInputRootElement"] input,
        [data-testid="stTextAreaRootElement"] textarea,
        [data-testid="stNumberInputContainer"] input,
        [data-testid="stNumberInputContainer"] button {{
            background-color: transparent !important;
            color: {p["text"]} !important;
        }}
        [data-baseweb="menu"], [data-baseweb="popover"] > div {{
            background-color: {p["bg2"]} !important;
        }}
        [data-baseweb="menu"] li {{
            color: {p["text"]} !important;
        }}
        /* Streamlit >=1.59 renders select/multiselect with react-aria,
           not BaseWeb. */
        .react-aria-ComboBox [role="group"],
        [data-testid="stMultiSelect"] [role="group"],
        .react-aria-Group {{
            background-color: {p["bg2"]} !important;
            color: {p["text"]} !important;
            border-color: {p["border"]} !important;
        }}
        input[role="combobox"] {{
            color: {p["text"]} !important;
        }}
        div[role="listbox"], .react-aria-Popover, .react-aria-ListBox {{
            background-color: {p["bg2"]} !important;
            color: {p["text"]} !important;
        }}
        div[role="option"] {{
            color: {p["text"]} !important;
        }}
        /* Uploaded-file chip in the file uploader */
        [data-testid="stFileChip"] {{
            background-color: {p["bg2"]} !important;
            color: {p["text"]} !important;
            border-color: {p["border"]} !important;
        }}
        [data-testid="stFileChip"] div, [data-testid="stFileChip"] small,
        [data-testid="stFileChip"] svg {{
            color: {p["text"]} !important;
            fill: {p["text"]} !important;
        }}
        .stButton button, .stFormSubmitButton button:not([kind="primary"]),
        .stDownloadButton button,
        [data-testid="stFileUploaderDropzone"] button {{
            background-color: {p["bg2"]} !important;
            color: {p["text"]} !important;
            border-color: {p["border"]} !important;
        }}
        [data-testid="stFileUploaderDropzone"] {{
            background-color: {p["bg2"]};
            color: {p["text"]};
        }}
        [data-testid="stFileUploaderDropzone"] span,
        [data-testid="stFileUploaderDropzone"] small {{
            color: {p["muted"]} !important;
        }}
        [data-testid="stForm"],
        [data-testid="stVerticalBlockBorderWrapper"],
        [data-testid="stExpander"] details {{
            border-color: {p["border"]} !important;
        }}
        [data-testid="stExpander"] summary,
        [data-testid="stExpander"] summary:hover {{
            background-color: {p["bg2"]} !important;
            color: {p["text"]} !important;
        }}
        [data-testid="stExpanderDetails"] {{
            background-color: transparent !important;
        }}
        /* Chrome autofill paints its own white background; the inset
           box-shadow trick is the only way to override it. */
        input:-webkit-autofill,
        input:-webkit-autofill:hover,
        input:-webkit-autofill:focus {{
            -webkit-box-shadow: 0 0 0 1000px {p["bg2"]} inset !important;
            -webkit-text-fill-color: {p["text"]} !important;
            caret-color: {p["text"]};
        }}
        [data-testid="stDataFrame"] canvas {{
            filter: {p["df_filter"]};
        }}
        [data-testid="stElementToolbar"],
        [data-testid="stElementToolbar"] button {{
            background-color: {p["bg2"]} !important;
            color: {p["text"]} !important;
        }}
        /* Sidebar controls: replace Streamlit's arrow icons (hardcoded dark,
           invisible on the dark theme) with a theme-colored cross to close
           and hamburger to open. */
        [data-testid="stSidebarCollapseButton"] button svg,
        [data-testid="stSidebarCollapseButton"] button span,
        [data-testid="stExpandSidebarButton"] svg,
        [data-testid="stExpandSidebarButton"] span {{
            display: none !important;
        }}
        [data-testid="stSidebarCollapseButton"] button::before {{
            content: "\\2715";  /* ✕ */
            color: {p["text"]} !important;
            font-size: 1.05rem;
            line-height: 1;
        }}
        [data-testid="stExpandSidebarButton"]::before {{
            content: "\\2630";  /* ☰ */
            color: {p["text"]} !important;
            font-size: 1.25rem;
            line-height: 1;
        }}
        hr {{
            border-color: {p["border"]};
            background-color: {p["border"]};
        }}
        [data-testid="stMarkdownContainer"] code {{
            background-color: {p["bg2"]};
            color: {p["text"]};
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def _init_dark_mode() -> None:
    """Seed the toggle from the theme the browser is currently rendering,
    so the first paint matches the user's system preference."""
    if "dark_mode" not in st.session_state:
        theme = getattr(st.context, "theme", None)
        st.session_state.dark_mode = getattr(theme, "type", None) == "dark"


def _active_logo() -> str:
    return str(LOGO_DARK_PATH if st.session_state.get("dark_mode") else LOGO_LIGHT_PATH)


def render_sidebar() -> None:
    with st.sidebar:
        st.image(_active_logo(), width=180)
        st.caption("Source → Target reconciliation wizard")
        st.toggle("Dark mode", key="dark_mode")
        st.divider()

        steps = [
            ("Source loaded", st.session_state.get("source_df") is not None),
            ("Target loaded", st.session_state.get("target_df") is not None),
            ("Comparison run", "result" in st.session_state),
        ]
        for label, done in steps:
            if done:
                st.markdown(f":green[✓] {label}")
            else:
                st.markdown(
                    f"<p class='ds-muted'>– {label}</p>",
                    unsafe_allow_html=True,
                )

        st.divider()
        if st.button("Start over", width="stretch"):
            st.session_state.clear()
            st.rerun()


def _fetch_snowflake(form_values: dict) -> pd.DataFrame:
    source = SnowflakeDataSource(
        table=form_values["table"] or None,
        query=form_values["query"] or None,
        account=form_values["account"] or None,
        user=form_values["user"] or None,
        password=form_values["password"] or None,
        private_key_path=form_values["key_path"] or None,
        authenticator=form_values.get("authenticator") or None,
        warehouse=form_values["warehouse"] or None,
        database=form_values["database"] or None,
        schema=form_values["schema"] or None,
        role=form_values["role"] or None,
    )
    return source.fetch()


def _fetch_snowflake_sis(side: str, table: str, query: str) -> pd.DataFrame:
    """SiS path: reuses the ambient Snowpark session (no credentials)."""
    source = SnowflakeDataSource(
        table=table or None,
        query=query or None,
        warehouse=st.session_state.get(f"{side}_sf_wh") or None,
        database=st.session_state.get(f"{side}_sf_db") or None,
        schema=st.session_state.get(f"{side}_sf_schema") or None,
        role=st.session_state.get(f"{side}_sf_role") or None,
    )
    return source.fetch()


def dataset_picker(side: str) -> pd.DataFrame | None:
    """Render the source/target picker for one side; return the fetched df."""
    state_key = f"{side}_df"
    label_key = f"{side}_label"

    kind = st.radio(
        f"{side.capitalize()} type",
        ["Upload File", "Snowflake"],
        key=f"{side}_kind",
        horizontal=True,
    )

    if kind == "Upload File":
        uploaded = st.file_uploader(
            f"Drop a CSV or Excel file for the {side}",
            type=["csv", "txt", "tsv", "xlsx", "xls", "xlsm"],
            key=f"{side}_upload",
        )
        if uploaded is not None:
            sheet = 0
            if Path(uploaded.name).suffix.lower() in (".xlsx", ".xls", ".xlsm"):
                sheet_input = st.text_input(
                    "Sheet name (blank = first sheet)", key=f"{side}_sheet"
                )
                sheet = sheet_input or 0
            try:
                df = FileDataSource(uploaded, sheet_name=sheet).fetch()
                st.session_state[state_key] = df
                st.session_state[label_key] = uploaded.name
            except Exception as exc:
                st.error(f"Could not read file: {exc}")

    elif IN_SIS:  # Snowflake, running inside Streamlit in Snowflake
        st.caption(
            "Running inside Snowflake — using your logged-in session, "
            "no credentials needed."
        )
        with st.form(f"{side}_snowflake_form"):
            table = st.text_input("Table name", key=f"{side}_sf_table")
            query = st.text_area(
                "…or custom SQL query (leave table blank)", key=f"{side}_sf_query"
            )
            with st.expander("Advanced (optional overrides)"):
                st.caption("Blank fields fall back to your session's defaults.")
                col1, col2 = st.columns(2)
                with col1:
                    st.text_input("Warehouse", key=f"{side}_sf_wh")
                    st.text_input("Database", key=f"{side}_sf_db")
                with col2:
                    st.text_input("Schema", key=f"{side}_sf_schema")
                    st.text_input("Role", key=f"{side}_sf_role")
            submitted = st.form_submit_button(f"Fetch {side}")

        if submitted:
            try:
                with st.spinner("Fetching from Snowflake…"):
                    df = _fetch_snowflake_sis(side, table, query)
                st.session_state[state_key] = df
                st.session_state[label_key] = table or "custom query"
            except Exception as exc:
                st.error(f"Snowflake fetch failed: {exc}")

    else:  # Snowflake, running outside Snowflake (local dev, Streamlit Cloud, ...)
        if side == "target" and st.session_state.get("source_kind") == "Snowflake":
            if st.button(
                "Auto-fill from source connection",
                key=f"{side}_sf_autofill",
                help="Copy the connection details (including the authentication "
                "method) and table name from the source Snowflake connection.",
            ):
                for field in (
                    "auth_method",
                    "account",
                    "user",
                    "password",
                    "key",
                    "wh",
                    "db",
                    "schema",
                    "role",
                    "table",
                ):
                    src_val = st.session_state.get(f"source_sf_{field}")
                    if src_val is not None:
                        st.session_state[f"target_sf_{field}"] = src_val

        auth_method = st.radio(
            "Authentication",
            ["SSO (browser login)", "Password", "Key pair"],
            key=f"{side}_sf_auth_method",
            horizontal=True,
            help="SSO opens your company's identity provider (Okta, Azure AD, ...) "
            "in a browser window — no password is entered in this app.",
        )

        with st.form(f"{side}_snowflake_form"):
            st.caption(
                "Blank fields fall back to environment variables / .env "
                "(see .env.example). Credentials are never stored."
            )
            password = ""
            key_path = ""
            col1, col2 = st.columns(2)
            with col1:
                account = st.text_input("Account", key=f"{side}_sf_account")
                user = st.text_input("User", key=f"{side}_sf_user")
                if auth_method == "Password":
                    password = st.text_input(
                        "Password", type="password", key=f"{side}_sf_password"
                    )
                elif auth_method == "Key pair":
                    key_path = st.text_input(
                        "Private key path", key=f"{side}_sf_key"
                    )
                else:
                    st.caption(
                        "A browser window will open for your workplace SSO "
                        "login when you connect."
                    )
            with col2:
                warehouse = st.text_input("Warehouse", key=f"{side}_sf_wh")
                database = st.text_input("Database", key=f"{side}_sf_db")
                schema = st.text_input("Schema", key=f"{side}_sf_schema")
                role = st.text_input("Role", key=f"{side}_sf_role")

            table = st.text_input("Table name", key=f"{side}_sf_table")
            query = st.text_area(
                "…or custom SQL query (leave table blank)", key=f"{side}_sf_query"
            )
            submitted = st.form_submit_button(f"Connect & fetch {side}")

        if submitted:
            try:
                spinner_msg = (
                    "Waiting for SSO login in your browser…"
                    if auth_method == "SSO (browser login)"
                    else "Fetching from Snowflake…"
                )
                with st.spinner(spinner_msg):
                    df = _fetch_snowflake(
                        {
                            "account": account,
                            "user": user,
                            "password": password,
                            "key_path": key_path,
                            "authenticator": (
                                "externalbrowser"
                                if auth_method == "SSO (browser login)"
                                else ""
                            ),
                            "warehouse": warehouse,
                            "database": database,
                            "schema": schema,
                            "role": role,
                            "table": table,
                            "query": query,
                        }
                    )
                st.session_state[state_key] = df
                st.session_state[label_key] = table or "custom query"
            except Exception as exc:
                st.error(f"Snowflake fetch failed: {exc}")

    df = st.session_state.get(state_key)
    if df is not None:
        with st.container(border=True):
            c1, c2, c3 = st.columns([3, 1, 1])
            c1.markdown(f":green[✓] **{st.session_state.get(label_key, '?')}**")
            c2.metric("Rows", f"{len(df):,}")
            c3.metric("Columns", f"{len(df.columns):,}")
            with st.expander(f"Preview {side} (first 20 rows)"):
                st.dataframe(df.head(20), width="stretch")
    return df


def rules_editor(
    mapping: dict[str, str], key_columns: list[str], source_df: pd.DataFrame
) -> dict[str, dict]:
    """Render per-column rule widgets; return engine-format rules."""
    rules: dict[str, dict] = {}
    compare_cols = [c for c in mapping if c not in key_columns]
    if not compare_cols:
        st.info("No non-key columns mapped — nothing to set rules for.")
        return rules

    for col in compare_cols:
        dtype = source_df[col].dtype
        is_numeric = pd.api.types.is_numeric_dtype(dtype)
        is_datetime = pd.api.types.is_datetime64_any_dtype(dtype)

        with st.expander(f"Rules for `{col}` → `{mapping[col]}` ({dtype})"):
            rule: dict = {}
            if is_numeric:
                tol = st.number_input(
                    "Absolute tolerance (0 = exact)",
                    min_value=0.0,
                    value=0.0,
                    step=0.01,
                    format="%.4f",
                    key=f"rule_tol_{col}",
                )
                if tol > 0:
                    rule["tolerance"] = tol
            elif is_datetime:
                if st.checkbox("Compare date only (ignore time)", key=f"rule_date_{col}"):
                    rule["date_only"] = True
            else:
                if st.checkbox(
                    "Case-insensitive compare (also trims whitespace)",
                    key=f"rule_ci_{col}",
                ):
                    rule["case_insensitive"] = True
                if st.checkbox(
                    "Treat as dates (compare date only)", key=f"rule_asdate_{col}"
                ):
                    rule["date_only"] = True
            if rule:
                rules[col] = rule
    return rules


def render_results() -> None:
    result = st.session_state["result"]
    s = result.summary

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Matched", f"{s['matched']:,}")
    m2.metric("Mismatched", f"{s['mismatched']:,}")
    m3.metric("Missing in target", f"{s['missing_in_target']:,}")
    m4.metric("Missing in source", f"{s['missing_in_source']:,}")

    if s["match_rate"] is not None:
        rate = s["match_rate"]
        color = "green" if rate >= 0.99 else "orange" if rate >= 0.9 else "red"
        st.progress(rate, text=f"Match rate: {rate:.1%}")
        st.badge(f"{rate:.1%} match rate", color=color)

    st.divider()

    tab_mismatch, tab_target, tab_source = st.tabs(
        [
            f"Mismatched ({s['mismatched']:,})",
            f"Missing in target ({s['missing_in_target']:,})",
            f"Missing in source ({s['missing_in_source']:,})",
        ]
    )

    with tab_mismatch:
        if len(result.mismatched_rows):
            display = result.mismatched_rows.copy()
            display["differing_columns"] = display["differing_columns"].apply(", ".join)
            st.dataframe(display, width="stretch")
        else:
            st.write("No rows.")

    with tab_target:
        if len(result.missing_in_target):
            st.dataframe(result.missing_in_target, width="stretch")
        else:
            st.write("No rows.")

    with tab_source:
        if len(result.missing_in_source):
            st.dataframe(result.missing_in_source, width="stretch")
        else:
            st.write("No rows.")

    st.divider()

    buffer = io.BytesIO()
    export = result.mismatched_rows.copy()
    export["differing_columns"] = export["differing_columns"].apply(", ".join)
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        pd.DataFrame([s]).to_excel(writer, sheet_name="Summary", index=False)
        export.to_excel(writer, sheet_name="Mismatches", index=False)
        result.missing_in_target.to_excel(writer, sheet_name="Missing In Target", index=False)
        result.missing_in_source.to_excel(writer, sheet_name="Missing In Source", index=False)
    st.download_button(
        "Export full report to Excel",
        data=buffer.getvalue(),
        file_name="recon_report.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------

_init_dark_mode()
_inject_theme_css()
render_sidebar()

st.image(_active_logo(), width=280)
st.caption("Compare a source dataset against a target and report matches, mismatches, and missing rows.")
st.divider()

st.header("Step 1 · Source dataset")
source_df = dataset_picker("source")

st.divider()
st.header("Step 2 · Target dataset")
target_df = dataset_picker("target")

if source_df is None or target_df is None:
    st.info("Load both a source and a target dataset to continue.")
    st.stop()

st.divider()
st.header("Step 3 · Column mapping & keys")

source_cols = list(source_df.columns)
target_cols = list(target_df.columns)
suggested = suggest_mapping(source_cols, target_cols)

st.caption(
    "Each source column is auto-matched to a target column by name similarity. "
    "Override below, or set a column to “not mapped” to exclude it."
)

mapping: dict[str, str] = {}
map_cols = st.columns(3)
for i, src in enumerate(source_cols):
    options = [UNMAPPED] + target_cols
    default = suggested.get(src, UNMAPPED)
    with map_cols[i % 3]:
        choice = st.selectbox(
            f"`{src}` →",
            options,
            index=options.index(default),
            key=f"map_{src}",
        )
    if choice != UNMAPPED:
        mapping[src] = choice

# Reject many-to-one mappings early.
reverse: dict[str, list[str]] = {}
for src, tgt in mapping.items():
    reverse.setdefault(tgt, []).append(src)
collisions = {t: srcs for t, srcs in reverse.items() if len(srcs) > 1}
if collisions:
    st.error(f"Multiple source columns map to the same target column: {collisions}")
    st.stop()

if not mapping:
    st.warning("Map at least one column to continue.")
    st.stop()

key_columns = st.multiselect(
    "Key column(s) — must uniquely identify a row (composite keys supported)",
    options=list(mapping.keys()),
    default=[c for c in mapping if normalize_column_name(c).endswith("id")][:1],
)
if not key_columns:
    st.warning("Pick at least one key column to continue.")
    st.stop()

st.divider()
st.header("Step 4 · Column rules (optional)")
rules = rules_editor(mapping, key_columns, source_df)

st.divider()
st.header("Step 5 · Run comparison")
if st.button("Run comparison", type="primary"):
    try:
        with st.spinner("Comparing…"):
            st.session_state["result"] = compare_datasets(
                source_df,
                target_df,
                key_columns=key_columns,
                column_mapping=mapping,
                column_rules=rules,
            )
        st.toast("Comparison complete.")
    except ReconError as exc:
        st.session_state.pop("result", None)
        st.error(str(exc))

if "result" in st.session_state:
    st.divider()
    render_results()
