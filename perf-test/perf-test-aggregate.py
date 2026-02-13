#!/usr/bin/env python3
"""
perf-test-aggregate.py — Read one or more JSON-lines result files produced by
perf-test-runner.py, compute summary statistics, and optionally write CSV or
markdown output.

Usage:
    python3 perf-test/perf-test-aggregate.py perf-test/results/*.jsonl
    python3 perf-test/perf-test-aggregate.py perf-test/results/*.jsonl --csv perf-test/results/report.csv
    python3 perf-test/perf-test-aggregate.py perf-test/results/*.jsonl --markdown
"""

import sys
import os
import json
import csv
import argparse
import statistics
from datetime import datetime
from collections import defaultdict


def percentile(sorted_data, p):
    """Linear interpolation percentile on pre-sorted list."""
    if not sorted_data:
        return 0.0
    k = (len(sorted_data) - 1) * (p / 100)
    f = int(k)
    c = min(f + 1, len(sorted_data) - 1)
    return sorted_data[f] + (k - f) * (sorted_data[c] - sorted_data[f])


def is_error(entry):
    """True if the entry represents a failure."""
    if entry.get("error"):
        return True
    code = entry.get("exit_code")
    return code is not None and code != 0


def entry_label(entry):
    """Label for grouping — the script name."""
    return entry.get("script", "unknown")


def load_jsonl_files(paths):
    """Read all JSONL files. Returns list of (entry, source_file) tuples."""
    rows = []
    for filepath in paths:
        with open(filepath) as f:
            for lineno, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append((json.loads(line), os.path.basename(filepath)))
                except json.JSONDecodeError as e:
                    print(f"  WARN: {filepath}:{lineno} — bad JSON: {e}", file=sys.stderr)
    return rows


def compute_stats(entries):
    """Compute summary stats for a list of log entries."""
    total = len(entries)
    errors = sum(1 for e in entries if is_error(e))
    durations = sorted(e["duration_ms"] for e in entries if not is_error(e))

    # Time span for RPM
    timestamps = []
    for e in entries:
        ts = e.get("timestamp")
        if ts:
            try:
                timestamps.append(datetime.fromisoformat(ts.replace("Z", "+00:00")))
            except ValueError:
                pass
    span_s = (max(timestamps) - min(timestamps)).total_seconds() if len(timestamps) >= 2 else 0
    rpm = (total / span_s) * 60 if span_s > 0 else 0

    return {
        "total": total, "errors": errors,
        "error_pct": (errors / total * 100) if total else 0,
        "rpm": round(rpm, 1),
        "avg_ms": round(statistics.mean(durations), 1) if durations else 0,
        "p50_ms": round(percentile(durations, 50), 1),
        "p95_ms": round(percentile(durations, 95), 1),
        "p99_ms": round(percentile(durations, 99), 1),
        "min_ms": round(durations[0], 1) if durations else 0,
        "max_ms": round(durations[-1], 1) if durations else 0,
    }


FIELDS = ["total", "errors", "error_pct", "rpm", "avg_ms", "p50_ms", "p95_ms", "p99_ms", "min_ms", "max_ms"]
HEADERS = ["Total", "Errors", "Err %", "RPM", "Avg ms", "p50 ms", "p95 ms", "p99 ms", "Min ms", "Max ms"]


def print_table(title, rows_dict, label_header="Script"):
    """Print a formatted ASCII table to stderr."""
    print(f"\n  {title}", file=sys.stderr)
    hdr = f"  {label_header:<40}"
    for h in HEADERS:
        hdr += f" {h:>8}"
    print(hdr, file=sys.stderr)
    print(f"  {'-'*40} " + " ".join("-" * 8 for _ in HEADERS), file=sys.stderr)
    for label, stats in rows_dict.items():
        row = f"  {label:<40}"
        for field in FIELDS:
            val = stats[field]
            if field == "error_pct":
                row += f" {val:>7.1f}%"
            elif isinstance(val, float):
                row += f" {val:>8.1f}"
            else:
                row += f" {val:>8}"
        print(row, file=sys.stderr)
    print(file=sys.stderr)


def print_markdown(label_header, rows_dict):
    """Print a GitHub-flavored markdown table to stdout."""
    headers = [label_header] + HEADERS
    print("| " + " | ".join(headers) + " |")
    print("| " + " | ".join("---" for _ in headers) + " |")
    for label, stats in rows_dict.items():
        vals = [label]
        for field in FIELDS:
            v = stats[field]
            vals.append(f"{v:.1f}%" if field == "error_pct" else f"{v:.1f}" if isinstance(v, float) else str(v))
        print("| " + " | ".join(vals) + " |")
    print()


def main():
    parser = argparse.ArgumentParser(description="Aggregate perf-test results.")
    parser.add_argument("files", nargs="+", help=".jsonl result files")
    parser.add_argument("--csv", dest="csv_path", default=None, help="Write CSV report")
    parser.add_argument("--markdown", action="store_true", help="Print markdown table to stdout")
    parser.add_argument("--by-file", dest="by_file", action="store_true", help="Group by source file")
    args = parser.parse_args()

    rows = load_jsonl_files(args.files)
    if not rows:
        print("  No data found.", file=sys.stderr)
        sys.exit(1)

    print(f"\n  Loaded {len(rows)} entries from {len(args.files)} file(s).", file=sys.stderr)

    # Group entries
    all_entries = [e for e, _ in rows]
    by_label = defaultdict(list)
    by_file = defaultdict(list)
    for entry, source in rows:
        by_label[entry_label(entry)].append(entry)
        by_file[source].append(entry)

    # Overall
    overall = compute_stats(all_entries)
    print(f"\n{'='*70}", file=sys.stderr)
    print(f"  AGGREGATED RESULTS", file=sys.stderr)
    print(f"{'='*70}", file=sys.stderr)
    for key, label in [("total","Total ops/reqs"), ("errors","Errors"), ("rpm","Throughput"),
                        ("avg_ms","Avg latency"), ("p50_ms","p50 latency"),
                        ("p95_ms","p95 latency"), ("p99_ms","p99 latency"),
                        ("min_ms","Min latency"), ("max_ms","Max latency")]:
        val = overall[key]
        if key == "errors":
            print(f"  {label:<16}: {val} ({overall['error_pct']:.1f}%)", file=sys.stderr)
        elif key == "rpm":
            print(f"  {label:<16}: {val:.1f} req/min", file=sys.stderr)
        elif isinstance(val, float):
            print(f"  {label:<16}: {val:.1f} ms", file=sys.stderr)
        else:
            print(f"  {label:<16}: {val}", file=sys.stderr)
    print(f"{'='*70}", file=sys.stderr)

    # Per-script
    label_stats = {k: compute_stats(v) for k, v in sorted(by_label.items())}
    print_table("By Script", label_stats)

    # Per-file (optional)
    if args.by_file:
        file_stats = {k: compute_stats(v) for k, v in sorted(by_file.items())}
        print_table("By Source File", file_stats, label_header="File")

    # CSV
    if args.csv_path:
        os.makedirs(os.path.dirname(args.csv_path) or ".", exist_ok=True)
        with open(args.csv_path, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["Script"] + HEADERS)
            for label, stats in label_stats.items():
                w.writerow([label] + [stats[field] for field in FIELDS])
        print(f"\n  CSV → {args.csv_path}", file=sys.stderr)

    # Markdown
    if args.markdown:
        print("\n## Overall\n")
        print_markdown("Metric", {"Summary": overall})
        print("## By Script\n")
        print_markdown("Script", label_stats)


if __name__ == "__main__":
    main()
