# DataScribe — Demo & Reference Notes

A cheat-sheet for demoing DataScribe and answering the likely follow-up
questions. Everything here reflects what's actually in the repo.

---

## 1. What DataScribe is (one line)

Compares any two datasets — a **source** and a **target** (Snowflake tables,
CSV, or Excel) — and reports what matches, what differs (with field-level
old-vs-new detail), and what rows are missing on either side.

---

## 2. The three ways to use it

| Mode | Entry point | Who it's for |
|---|---|---|
| **Interactive UI** | `streamlit run ui/app.py` | Ad-hoc, non-technical users clicking through 5 steps |
| **Config + CLI (headless)** | `python -m core.job_runner <job.yaml>` | Repeatable, version-controlled, automatable reconciliations |
| **Programmatic API** | `from core.job_runner import run_job` | Embedding in other pipelines (Airflow, dbt, internal apps) |

All three call the **same engine** (`core/diff_engine.py` → `compare_datasets`).
The UI and CLI are just two front doors to the same logic — nothing is
duplicated.

### The 5-step UI flow
1. Choose source (upload file **or** Snowflake connection).
2. Choose target (same choice).
3. Column mapping — auto-suggested by name similarity; override + pick key column(s).
4. Optional column rules (tolerance, case-insensitive, date handling).
5. Run → summary metrics, expandable mismatch/missing tables, export to Excel.

### The config/CLI flow
A whole job is described once in a YAML file (`config/*.yaml`): source, target,
key columns, column mapping, rules. Then:
```
python -m core.job_runner config/example_job.yaml
python -m core.job_runner config/example_job.yaml --export report.xlsx
```
Prints the match/mismatch summary; `--export` also writes an Excel report.

---

## 3. Commands cheat-sheet (run from the project root)

```powershell
# UI (local)
streamlit run ui/app.py
.\.venv\Scripts\python.exe -m streamlit run ui/app.py     # if venv not activated

# Config-driven jobs
python -m core.job_runner config/example_job.yaml                       # lenient (2 matched)
python -m core.job_runner config/orders_strict_job.yaml                 # strict  (1 matched)
python -m core.job_runner config/example_job.yaml --export report.xlsx  # + Excel report
Invoke-Item report.xlsx                                                  # open the report

# Tests
pytest -q
```

**Gotcha:** `--export report.xlsx` is a *flag on the command*, not its own
command. It must ride on the end of the full `python -m core.job_runner <config>`
line. Running just `--export report.xlsx` errors ("Missing expression after
unary operator '--'").

### What `python -m` means
`-m core.job_runner` tells Python to find the module by its **dotted path**
(`job_runner` inside the `core` package) and run it. This is required (instead
of `python core/job_runner.py`) so that the internal `from core.config_schema
import ...` imports resolve. Must be run from the project root. Same mechanism
as `python -m pytest` and `python -m streamlit run ...`.

---

## 4. Column rules — there are FIVE (not 3)

Defined in `core/config_schema.py` (`ColumnRule`). Every rule is a
**relaxation** — it makes the comparison *more forgiving*. There is no
"strictness" rule because the default is already the strictest thing possible.

| Rule | What it does | Example |
|---|---|---|
| `tolerance` | absolute numeric allowance | `tolerance: 0.01` |
| `rel_tolerance` | relative (%) numeric allowance | `rel_tolerance: 0.001` |
| `case_insensitive` | ignore case + trim whitespace (strings) | `case_insensitive: true` |
| `date_only` | compare date, ignore time-of-day | `date_only: true` |
| `date_format` | normalize both sides to a strftime format first | `date_format: "%Y-%m-%d"` |

- Rules **combine** on a column (e.g. both `tolerance` and `rel_tolerance`).
- **No rule = exact equality** (the strict default, `NaN == NaN` counts as match).
- Not built yet but easy to add (~10-20 lines + a test each): trim-only,
  strip currency symbols/commas, null-equals-empty-string, round-to-N-decimals.

### What `tolerance` is
The max numeric difference allowed before two values count as a mismatch —
an absolute allowance. `|source - target| <= tolerance`.
- `100.00` vs `100.00` → match
- `250.50` vs `250.75` → mismatch (0.25 > 0.01)
Exists because the same value stores differently across systems (rounding,
float precision, currency). A small tolerance suppresses cosmetic noise so
only real breaks surface. `rel_tolerance` is the percentage version — use it
when acceptable drift scales with magnitude (e.g. values in the millions).

### Why `orders_strict_job.yaml` (no rules) is STRICTER than `example_job.yaml` (has rules)
Rules only loosen the comparison. No rules = exact match on everything = strictest.
- `orders_strict_job.yaml` (no rules): `Alice Smith` vs `ALICE SMITH` = mismatch → **1 matched**
- `example_job.yaml` (has `case_insensitive`): that pair now matches → **2 matched**
More rules = more forgiveness = fewer mismatches = less strict. Think of
`column_rules` as "tolerance/leniency settings," not "strictness settings."

---

## 5. The "scheduled job" question — be honest

**There is no scheduler built into DataScribe.** What exists is the headless
CLI/config runner (mode 2), which is *the piece you schedule* using tools the
company already has:
- Windows Task Scheduler / Linux cron calling `python -m core.job_runner ...`
- An Airflow / orchestrator DAG calling `run_job()`
- (Inside Snowflake) a Snowflake Task — would need the logic ported to a
  stored procedure; the current Python CLI doesn't auto-run there.

Correct framing: *"The engine already runs unattended from a config file with
one command — turning that into a nightly scheduled recon is a small wiring
step onto whatever scheduler you already use, not new product work."*

---

## 6. What runs when DEPLOYED (Streamlit Cloud or Streamlit-in-Snowflake)

- A Streamlit deployment hosts **only the UI** (`ui/app.py`). There is no
  terminal, no shell, no cron on that host — so the `python -m core.job_runner`
  CLI does **not** run there.
- BUT the engine (`compare_datasets`) is imported and used by the UI, so all
  reconciliation logic is fully alive in the deployed app.
- The config/CLI/scheduled path runs on a **different host** with a shell +
  scheduler: a laptop, build server, VM/EC2, Airflow worker.
- Nuance: `run_job()` is an importable *function*, so the deployed UI *could*
  run YAML jobs in-process (e.g. a "run a saved job" button). It's the
  command-line invocation + scheduling that need a separate host.

---

## 7. Deployment options — recommendation

| Option | SSO? | Infra to manage | Verdict |
|---|---|---|---|
| **Streamlit Community Cloud** | No (browser SSO can't work here) | None | Great for demo; not for company data |
| **Streamlit-in-Snowflake (SiS)** | **Yes, free** — inherits Snowsight SSO session | None (serverless in Snowflake) | **Recommended production path** |
| **EC2 / AWS** | You build it (ALB+OIDC/reverse proxy) | Full (patching, TLS, scaling) | Only if you must reach beyond Snowflake |

**Why SiS wins for a Snowflake recon tool:**
- SSO comes for free — runs inside Snowflake, reuses the user's already-SSO'd
  Snowsight session. No password fields, no IT identity-provider wiring.
- No servers for IT to own.
- Data never leaves Snowflake's security boundary (good for security/compliance).
- Already coded + tested in the repo (ambient-session detection, credential-free
  UI path, `snowflake.yml` / `sis/environment.yml` manifests). Deploy with
  `snow streamlit deploy` once granted a role with `CREATE STREAMLIT`.

**EC2 is the wrong sell here:** you'd rebuild SSO yourself and own uptime/patching.

### Why the hosted deployment broke before (for reference)
A root-level `environment.yml` (added for SiS) made Streamlit Cloud build a
conda env from that SiS-only package list instead of `requirements.txt` → app
failed to boot ("Error running app"). Fixed by moving it to `sis/environment.yml`
(Cloud ignores it there) and mapping it back via `snowflake.yml`. Also: an
errored Cloud app does NOT auto-redeploy on push — you must Reboot it from the
dashboard. Rule of thumb: keep platform-specific manifests OUT of the repo root.

---

## 8. SSO — how to talk about it

- **On the hosted free app:** SSO (browser login) **cannot work** — the login
  browser has to open on the machine running the app (Streamlit's server), not
  the viewer's laptop. Never try to demo SSO on the Cloud app; it will just spin
  and time out. Use password/key-pair on the hosted demo.
- **The User field for SSO** = your Snowflake login name, which for SSO accounts
  is almost always your **work email** (must match what the IdP/Okta/Azure AD
  knows you as). It's the `LOGIN_NAME` on your Snowflake user; `SELECT
  CURRENT_USER();` or Snowsight profile shows it.
- **The production answer:** deployed inside Snowflake (SiS), every user opens
  the app already logged in through the company's existing SSO — same session
  as Snowsight. No separate login, no infra. Already coded/tested; needs a
  deployment role to pilot.

---

## 9. Airflow / pipeline usage (Act 3 in the real world)

`run_job()` is an importable function returning a `ReconResult` — so a DAG
calls the engine directly and then **acts on the result** (the real value:
fail the pipeline / alert when breaks exceed a threshold).

Key pieces of a real DAG:
- **Schedule** = Airflow cron (`schedule="0 6 * * *"`) — this is the "scheduler."
- **Config-driven** = point tasks at `config/*.yaml`; add a table = add a YAML.
- **Credentials** = pulled from an Airflow Connection / secrets backend, set as
  the `SNOWFLAKE_*` env vars the connector reads. Never in the YAML or DAG.
- **Act on result** = read `result.summary` / `result.mismatched_count`; raise
  to fail the run (fires Airflow alerting/retries) or send Slack/email.
- **Audit trail** = `result.to_excel(path)` writes a dated report.
- **Prereq (honest):** DataScribe must be `pip install`-able on the Airflow
  workers — needs a minimal `pyproject.toml`/`setup.py` added to package it.

### Hero scenario: legacy DB → Snowflake migration
The strongest use case. Migrating hundreds of tables; the project lives or dies
on "does Snowflake match the old system?" Each recon = legacy CSV extract
(source of truth) vs Snowflake table (target).
- **Phase 1** — full-load validation after first bulk load. Tolerances are
  essential: migrated data always drifts on format (dates, decimals, whitespace,
  case), so rules separate real breaks from cosmetic noise.
- **Phase 2** — daily recon during dual-run; each run emits a dated Excel report
  as sign-off evidence.
- **Phase 3** — pre-cutover gate: cutover blocked unless recons are clean.
- **Scaling** = config-driven is the unlock. 300 tables = generate 300 YAMLs
  from the migration manifest, one per table. Airflow **dynamic task mapping**
  (`recon.expand(job_path=list_jobs())`) fans out one task per YAML.
- **After migration** — the same suite becomes a permanent daily data-quality
  gate on the ELT pipeline (loaded table vs source extract).

---

## 10. Known limitations (state these before a technical follow-up)

- **Cross-account Snowflake-to-Snowflake** isn't supported today — the connector
  reads one `SNOWFLAKE_*` env credential set, so both sides use the same account.
  Supported shapes: legacy-CSV vs Snowflake, and same-account table-vs-table
  (e.g. `STAGING.ORDERS` vs `PROD.ORDERS`). Cross-account needs a small schema
  change for per-source creds (~half a day).
- **SSO can't run on hosted Streamlit Cloud** (see §8) — SiS or local only.
- **No built-in scheduler** (see §5) — the CLI is schedule-*able*, not scheduled.
- **Duplicate keys** in either dataset raise an error — recon assumes unique keys.

---

## 11. Suggested demo flow

1. **Act 1 — UI (the wow):** hosted app, upload two CSV/Excel files, show
   auto-mapping, set a rule, Run, walk the metrics + field-level diffs, export Excel.
2. **Act 2 — live Snowflake:** same UI, Snowflake source with your personal
   creds, reconcile a real table. ("Not just spreadsheets.")
3. **Act 3 — config-driven & automatable (terminal, on your laptop):**
   - `python -m core.job_runner config/example_job.yaml` → 2 matched
   - `python -m core.job_runner config/orders_strict_job.yaml` → 1 matched
     ("Same data, same engine — I only changed rules in a text file, no code.")
   - open `config/snowflake_to_csv_job.yaml` → "drop this one command into a
     scheduler and it runs nightly, unattended."
4. **Close — production/SSO:** "Today it's on free hosting with my creds. For
   the company it deploys inside Snowflake — everyone opens it already logged in
   via our existing SSO. Already coded and tested; needs a deployment role to
   pilot. The ask: a role with `CREATE STREAMLIT` and a warehouse."

**Fallbacks:** hosted app asleep/broken → run UI locally (`streamlit run
ui/app.py`); Snowflake/VPN fails → skip Act 2, lean on Act 3 + CSV UI; never
demo SSO on the hosted app.
