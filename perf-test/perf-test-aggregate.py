#!/usr/bin/env python3
"""
perf-test-aggregate.py — Read one or more JSON-lines result files produced by
perf-test-runner.py or parse-support-bundle.py, compute summary statistics,
and optionally write CSV or markdown output.

Usage:
    python3 perf-test/perf-test-aggregate.py perf-test/results/*.jsonl
    python3 perf-test/perf-test-aggregate.py perf-test/results/*.jsonl --csv perf-test/results/report.csv
    python3 perf-test/perf-test-aggregate.py perf-test/results/*.jsonl --markdown

    # Compare client-side (perf-test) with server-side (support bundle):
    python3 perf-test/perf-test-aggregate.py --compare perf-test/results/perf-*.jsonl --server perf-test/results/server-*.jsonl
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
    durations = sorted(
        e["duration_ms"] for e in entries
        if "duration_ms" in e and not is_error(e)
    )

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
    # Size the label column to fit the longest label (minimum 40 chars)
    col_w = max(40, max((len(k) for k in rows_dict), default=40))
    print(f"\n  {title}", file=sys.stderr)
    hdr = f"  {label_header:<{col_w}}"
    for h in HEADERS:
        hdr += f" {h:>8}"
    print(hdr, file=sys.stderr)
    print(f"  {'-'*col_w} " + " ".join("-" * 8 for _ in HEADERS), file=sys.stderr)
    for label, stats in rows_dict.items():
        row = f"  {label:<{col_w}}"
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


def print_compare(client_stats, server_stats):
    """Print a side-by-side client vs server comparison table."""
    COMPARE_FIELDS = ["total", "errors", "error_pct", "rpm", "avg_ms", "p50_ms", "p95_ms", "p99_ms"]
    COMPARE_LABELS = ["Total", "Errors", "Err %", "RPM", "Avg ms", "p50 ms", "p95 ms", "p99 ms"]

    print(f"\n{'='*70}", file=sys.stderr)
    print(f"  CLIENT vs SERVER COMPARISON", file=sys.stderr)
    print(f"{'='*70}", file=sys.stderr)
    print(f"  {'Metric':<16} {'Client':>12} {'Server':>12} {'Delta':>12}", file=sys.stderr)
    print(f"  {'-'*16} {'-'*12} {'-'*12} {'-'*12}", file=sys.stderr)

    for field, label in zip(COMPARE_FIELDS, COMPARE_LABELS):
        cv = client_stats[field]
        sv = server_stats[field]

        if field == "error_pct":
            c_str = f"{cv:.1f}%"
            s_str = f"{sv:.1f}%"
            d_str = f"{sv - cv:+.1f}%"
        elif isinstance(cv, float):
            c_str = f"{cv:.1f}"
            s_str = f"{sv:.1f}"
            delta = sv - cv
            if field in ("avg_ms", "p50_ms", "p95_ms", "p99_ms") and cv > 0:
                # For latency: client > server means network overhead
                d_str = f"{delta:+.1f} ms"
            else:
                d_str = f"{delta:+.1f}"
        else:
            c_str = str(cv)
            s_str = str(sv)
            d_str = str(sv - cv)

        print(f"  {label:<16} {c_str:>12} {s_str:>12} {d_str:>12}", file=sys.stderr)

    # Highlight the network overhead (client p50 - server p50)
    net_overhead = client_stats["p50_ms"] - server_stats["p50_ms"]
    if net_overhead > 0 and server_stats["p50_ms"] > 0:
        print(f"\n  Network overhead (client p50 − server p50): ~{net_overhead:.0f} ms", file=sys.stderr)
    print(f"{'='*70}\n", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description="Aggregate perf-test results.")
    parser.add_argument("files", nargs="*", help=".jsonl result files (client-side)")
    parser.add_argument("--csv", dest="csv_path", default=None, help="Write CSV report")
    parser.add_argument("--markdown", action="store_true", help="Print markdown table to stdout")
    parser.add_argument("--by-file", dest="by_file", action="store_true", help="Group by source file")
    parser.add_argument("--compare", action="store_true", help="Compare client vs server stats")
    parser.add_argument("--server", nargs="+", default=[], help="Server-side .jsonl files (from parse-support-bundle.py)")
    args = parser.parse_args()

    # If --compare mode, merge files lists but track which is which
    if args.compare and args.server:
        all_files = (args.files or []) + args.server
        server_basenames = {os.path.basename(f) for f in args.server}
    else:
        all_files = args.files or []
        server_basenames = set()

    if not all_files:
        parser.print_help()
        sys.exit(1)

    rows = load_jsonl_files(all_files)
    if not rows:
        print("  No data found.", file=sys.stderr)
        sys.exit(1)

    print(f"\n  Loaded {len(rows)} entries from {len(all_files)} file(s).", file=sys.stderr)

    # Group entries
    all_entries = [e for e, _ in rows]
    by_label = defaultdict(list)
    by_file = defaultdict(list)
    for entry, source in rows:
        by_label[entry_label(entry)].append(entry)
        by_file[source].append(entry)

    # Client vs server split (for --compare mode)
    if args.compare and server_basenames:
        client_entries = [e for e, src in rows if src not in server_basenames]
        server_entries = [e for e, src in rows if src in server_basenames]
        if client_entries and server_entries:
            print_compare(compute_stats(client_entries), compute_stats(server_entries))

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

    # Per-file (optional, or automatic in --compare mode)
    if args.by_file or (args.compare and server_basenames):
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
            # Overall summary as the last row
            w.writerow(["OVERALL"] + [overall[field] for field in FIELDS])
        print(f"\n  CSV → {args.csv_path}", file=sys.stderr)

    # Markdown
    if args.markdown:
        print("\n## Overall\n")
        print_markdown("Overall", {"All scripts": overall})
        print("## By Script\n")
        print_markdown("Script", label_stats)


if __name__ == "__main__":
    main()
