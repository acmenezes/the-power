#!/usr/bin/env python3
"""
parse-support-bundle.py — Extract performance-relevant entries from a GHES
support bundle and write them as JSONL (same format as perf-test-runner.py).

This lets you feed both client-side and server-side data into
perf-test-aggregate.py for side-by-side comparison.

Usage:
    # Parse everything in the bundle
    python3 perf-test/parse-support-bundle.py perf-test/results/support-bundle.tgz

    # Parse only entries within a time window (ISO 8601)
    python3 perf-test/parse-support-bundle.py support-bundle.tgz \
        --start 2026-02-17T13:00:00 --end 2026-02-17T13:10:00

    # Parse an already-extracted directory
    python3 perf-test/parse-support-bundle.py /tmp/extracted-bundle/

Parsed logs:
    - unicorn.log    → API request timing  (method + path + duration + status)
    - babeld.log     → Git operation timing (program + repo + duration)
    - haproxy.log    → Load balancer timing (frontend → backend latency)

Output: JSONL to perf-test/results/server-<timestamp>.jsonl
"""

import sys
import os
import re
import json
import gzip
import tarfile
import argparse
import tempfile
import shutil
from datetime import datetime, timezone
from pathlib import Path


# ─── Key-value log parser (used by unicorn.log and babeld.log) ───────────────

KV_PATTERN = re.compile(
    r'(\w+)='
    r'(?:'
    r'"([^"]*)"'     # quoted value
    r'|'
    r'(\S+)'         # unquoted value
    r')'
)


def parse_kv_line(line):
    """Parse a key=value or key="value" log line into a dict."""
    result = {}
    for match in KV_PATTERN.finditer(line):
        key = match.group(1)
        result[key] = match.group(2) if match.group(2) is not None else match.group(3)
    return result


# ─── Haproxy log parser ─────────────────────────────────────────────────────

HAPROXY_PATTERN = re.compile(
    r'(?P<datetime>\d+/\w+/\d+:\d+:\d+:\d+\.\d+)\]'  # [dd/Mon/yyyy:HH:MM:SS.sss]
    r'\s+\S+'                                           # frontend
    r'\s+\S+'                                           # backend/server
    r'\s+(?P<Tq>\d+)/(?P<Tw>\d+)/(?P<Tc>\d+)/(?P<Tr>\d+)/(?P<Tt>\d+)'  # timers
    r'\s+(?P<status>\d+)'                               # status code
    r'.*?"(?P<method>\w+)\s+(?P<path>\S+)'              # HTTP method + path
)

HAPROXY_DATE_FMT = "%d/%b/%Y:%H:%M:%S"


def parse_haproxy_line(line):
    """Parse a haproxy log line. Returns dict or None."""
    m = HAPROXY_PATTERN.search(line)
    if not m:
        return None
    dt_str = m.group("datetime").split(".")[0]  # drop milliseconds for strptime
    try:
        ts = datetime.strptime(dt_str, HAPROXY_DATE_FMT).replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    return {
        "timestamp": ts,
        "method": m.group("method"),
        "path": m.group("path"),
        "status": int(m.group("status")),
        "duration_ms": int(m.group("Tt")),  # Tt = total time in ms
    }


# ─── Time window filter ─────────────────────────────────────────────────────

def parse_timestamp(ts_str):
    """Best-effort ISO 8601 timestamp → datetime (UTC)."""
    if not ts_str:
        return None
    ts_str = ts_str.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(ts_str).astimezone(timezone.utc)
    except ValueError:
        return None


def in_window(ts, start, end):
    """True if ts is within [start, end]. None bounds are open."""
    if ts is None:
        return True  # can't filter without a timestamp — include it
    if start and ts < start:
        return False
    if end and ts > end:
        return False
    return True


# ─── Log file processors ────────────────────────────────────────────────────

def process_unicorn(lines, start, end):
    """Parse unicorn.log (Rails HTTP requests) → list of JSONL dicts."""
    entries = []
    for line in lines:
        kv = parse_kv_line(line)
        if not kv.get("path") or not kv.get("duration"):
            continue

        ts = parse_timestamp(kv.get("now"))
        if not in_window(ts, start, end):
            continue

        status = int(kv.get("status", 0))
        duration_s = float(kv.get("duration", 0))
        is_err = status >= 400

        entries.append({
            "timestamp": ts.strftime("%Y-%m-%dT%H:%M:%S.%fZ") if ts else None,
            "script": f"{kv.get('method', '?')} {kv['path']}",
            "duration_ms": round(duration_s * 1000, 2),
            "exit_code": 0 if not is_err else status,
            "error": f"HTTP {status}" if is_err else None,
            # Extra server-side fields (ignored by aggregator, useful for deep dives)
            "db_ms": round(float(kv.get("db", 0)) * 1000, 2),
            "view_ms": round(float(kv.get("view", 0)) * 1000, 2),
            "controller": kv.get("controller"),
        })
    return entries


def process_babeld(lines, start, end):
    """Parse babeld.log (Git transport) → list of JSONL dicts."""
    entries = []
    for line in lines:
        kv = parse_kv_line(line)
        program = kv.get("program") or kv.get("msg")
        if not program:
            continue

        ts = parse_timestamp(kv.get("now"))
        if not in_window(ts, start, end):
            continue

        # duration can be in seconds (duration) or milliseconds (duration_ms)
        dur_ms = float(kv.get("duration_ms", 0))
        if not dur_ms and kv.get("duration"):
            dur_ms = float(kv["duration"]) * 1000

        repo = kv.get("repo_name", kv.get("repo", "unknown"))

        entries.append({
            "timestamp": ts.strftime("%Y-%m-%dT%H:%M:%S.%fZ") if ts else None,
            "script": f"git {program} ({repo})",
            "duration_ms": round(dur_ms, 2),
            "exit_code": 0,
            "error": None,
        })
    return entries


def process_haproxy(lines, start, end):
    """Parse haproxy.log (load balancer) → list of JSONL dicts."""
    entries = []
    for line in lines:
        parsed = parse_haproxy_line(line)
        if not parsed:
            continue

        ts = parsed["timestamp"]
        if not in_window(ts, start, end):
            continue

        is_err = parsed["status"] >= 400
        entries.append({
            "timestamp": ts.strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
            "script": f"{parsed['method']} {parsed['path']}",
            "duration_ms": parsed["duration_ms"],
            "exit_code": 0 if not is_err else parsed["status"],
            "error": f"HTTP {parsed['status']}" if is_err else None,
        })
    return entries


# ─── File discovery and reading ──────────────────────────────────────────────

LOG_PROCESSORS = {
    "unicorn.log": process_unicorn,
    "babeld.log": process_babeld,
    "haproxy.log": process_haproxy,
}


def read_log_file(path):
    """Read a log file (plain or gzipped) and return lines."""
    if path.endswith(".gz"):
        with gzip.open(path, "rt", errors="replace") as f:
            return f.readlines()
    else:
        with open(path, "r", errors="replace") as f:
            return f.readlines()


def find_log_files(root_dir):
    """Walk the extracted bundle and find known log files."""
    found = {}
    for dirpath, _, filenames in os.walk(root_dir):
        for fname in filenames:
            base = fname.replace(".gz", "").replace(".1", "").replace(".2", "")
            if base in LOG_PROCESSORS:
                key = base
                if key not in found:
                    found[key] = []
                found[key].append(os.path.join(dirpath, fname))
    return found


# ─── Main ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Parse GHES support bundle → JSONL.")
    parser.add_argument("bundle", help="Path to .tgz bundle or extracted directory")
    parser.add_argument("--start", default=None, help="Start time filter (ISO 8601)")
    parser.add_argument("--end", default=None, help="End time filter (ISO 8601)")
    parser.add_argument("-o", "--output", default=None, help="Output JSONL path")
    parser.add_argument("--log", choices=["unicorn", "babeld", "haproxy", "all"],
                        default="all", help="Which log to parse (default: all)")
    args = parser.parse_args()

    start = parse_timestamp(args.start)
    end = parse_timestamp(args.end)

    # Determine if input is a .tgz or a directory
    bundle_path = args.bundle
    tmp_dir = None

    if os.path.isdir(bundle_path):
        root_dir = bundle_path
    elif tarfile.is_tarfile(bundle_path):
        tmp_dir = tempfile.mkdtemp(prefix="ghes-bundle-")
        print(f"  Extracting {bundle_path} → {tmp_dir}...", file=sys.stderr)
        with tarfile.open(bundle_path, "r:gz") as tar:
            tar.extractall(tmp_dir)
        root_dir = tmp_dir
    else:
        print(f"  ERROR: {bundle_path} is not a .tgz file or directory.", file=sys.stderr)
        sys.exit(1)

    try:
        # Find log files
        log_files = find_log_files(root_dir)
        if not log_files:
            print("  No recognized log files found in the bundle.", file=sys.stderr)
            sys.exit(1)

        print(f"\n  Found log files:", file=sys.stderr)
        for name, paths in sorted(log_files.items()):
            print(f"    {name}: {len(paths)} file(s)", file=sys.stderr)

        # Process each log type
        all_entries = []
        for log_name, paths in sorted(log_files.items()):
            base_name = log_name.replace(".log", "")
            if args.log != "all" and args.log != base_name:
                continue

            processor = LOG_PROCESSORS[log_name]
            count = 0
            for path in sorted(paths):
                lines = read_log_file(path)
                entries = processor(lines, start, end)
                all_entries.extend(entries)
                count += len(entries)
            print(f"    {log_name}: {count} entries parsed", file=sys.stderr)

        if not all_entries:
            print("\n  No entries matched the filters.", file=sys.stderr)
            sys.exit(1)

        # Sort by timestamp
        all_entries.sort(key=lambda e: e.get("timestamp") or "")

        # Write output
        output_path = args.output
        if not output_path:
            ts = datetime.now().strftime("%Y%m%d-%H%M%S")
            output_path = f"perf-test/results/server-{ts}.jsonl"
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

        with open(output_path, "w") as f:
            for entry in all_entries:
                f.write(json.dumps(entry) + "\n")

        print(f"\n  ✓ {len(all_entries)} entries → {output_path}", file=sys.stderr)
        window_str = ""
        if start:
            window_str += f" from {start.isoformat()}"
        if end:
            window_str += f" to {end.isoformat()}"
        if window_str:
            print(f"    Time window:{window_str}", file=sys.stderr)

        print(f"\n  Next step — compare with client results:", file=sys.stderr)
        print(f"    python3 perf-test/perf-test-aggregate.py perf-test/results/perf-*.jsonl {output_path} --by-file", file=sys.stderr)
        print("", file=sys.stderr)

    finally:
        # Clean up temp directory
        if tmp_dir:
            shutil.rmtree(tmp_dir, ignore_errors=True)


if __name__ == "__main__":
    main()
