"""Run a reconciliation job end-to-end from a config.

Usage from code:

    from core.job_runner import run_job
    result = run_job("config/example_job.yaml")

Or from the command line:

    python -m core.job_runner config/example_job.yaml --export report.xlsx
"""

from __future__ import annotations

import argparse
from pathlib import Path

from core.config_schema import ReconJobConfig, build_data_source, load_job
from core.diff_engine import ReconResult, compare_datasets


def run_job_config(job: ReconJobConfig) -> ReconResult:
    """Execute an already-validated job config."""
    source_df = build_data_source(job.source).fetch()
    target_df = build_data_source(job.target).fetch()
    return compare_datasets(
        source_df,
        target_df,
        key_columns=job.key_columns,
        column_mapping=job.column_mapping,
        column_rules=job.engine_rules(),
    )


def run_job(path: str | Path) -> ReconResult:
    """Load a job YAML and execute it."""
    return run_job_config(load_job(path))


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a reconciliation job from a YAML config.")
    parser.add_argument("job_file", help="Path to the job YAML file.")
    parser.add_argument("--export", help="Optional path to write an Excel report.")
    args = parser.parse_args()

    result = run_job(args.job_file)

    print(f"Job: {args.job_file}")
    for key, value in result.summary.items():
        print(f"  {key}: {value}")

    if args.export:
        result.to_excel(args.export)
        print(f"Report written to {args.export}")


if __name__ == "__main__":
    main()
