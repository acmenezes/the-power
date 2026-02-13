#!/usr/bin/env python3
"""
perf-test-runner.py — Run any project script at a target rate and record the numbers.

Picks scripts from a YAML workload file, runs them concurrently via subprocess,
measures wall-clock time, and writes results to a JSON-lines file.

Usage:
    python3 perf-test/perf-test-runner.py --workload perf-test/perf-workload.yaml
    python3 perf-test/perf-test-runner.py --workload perf-test/perf-workload.yaml --target-rpm 100 --duration 60
"""

import sys
import os
import json
import time
import random
import argparse
import threading
import statistics
import subprocess
import concurrent.futures
from datetime import datetime, timezone
from pathlib import Path

import yaml

# Project root: one level up from perf-test/
PROJECT_ROOT = Path(__file__).resolve().parent.parent


def load_workload(filepath):
    """Read the YAML workload file."""
    with open(filepath) as f:
        return yaml.safe_load(f)


def run_script(script_path, timeout=60):
    """Run a shell script from the project root. Returns (exit_code, duration_ms, error)."""
    start = time.time()
    try:
        result = subprocess.run(
            ["bash", script_path],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        duration_ms = (time.time() - start) * 1000
        error = result.stderr.strip()[-200:] if result.returncode != 0 else None
        return result.returncode, duration_ms, error
    except subprocess.TimeoutExpired:
        return -1, (time.time() - start) * 1000, "timeout"
    except Exception as e:
        return -1, (time.time() - start) * 1000, str(e)


def percentile(sorted_data, p):
    """Linear-interpolation percentile on a pre-sorted list."""
    if not sorted_data:
        return 0.0
    k = (len(sorted_data) - 1) * (p / 100)
    f = int(k)
    c = min(f + 1, len(sorted_data) - 1)
    return sorted_data[f] + (k - f) * (sorted_data[c] - sorted_data[f])


class LoadDriver:
    """Drives script execution at a target requests-per-minute rate."""

    def __init__(self, scripts, target_rpm, duration, workers, output_file):
        self.items = list(scripts)
        self.weights = [s["weight"] for s in self.items]
        self.target_rpm = target_rpm
        self.duration = duration
        self.workers = workers
        self.output_file = output_file

        self.lock = threading.Lock()
        self.results = []
        self.stop_event = threading.Event()
        self.interval = 60.0 / target_rpm  # seconds between requests

    def _pick(self):
        return random.choices(self.items, weights=self.weights, k=1)[0]

    def _sleep(self, seconds):
        """Interruptible sleep in 100ms ticks for prompt shutdown."""
        end = time.time() + seconds
        while time.time() < end and not self.stop_event.is_set():
            time.sleep(min(0.1, max(0, end - time.time())))

    def _worker(self):
        """Pick a script, run it, record the result, pace, repeat."""
        while not self.stop_event.is_set():
            script = self._pick()
            exit_code, duration_ms, error = run_script(script["script"])

            entry = {
                "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
                "script": script["script"],
                "duration_ms": round(duration_ms, 2),
                "exit_code": exit_code,
                "error": error,
            }
            with self.lock:
                self.results.append(entry)

            # Spread target RPM evenly across workers, with jitter
            self._sleep(self.interval * self.workers * random.uniform(0.8, 1.2))

    def _reporter(self, start_time):
        """Print live stats every 10 seconds."""
        last_count = 0
        while not self.stop_event.is_set():
            self._sleep(10)
            with self.lock:
                total = len(self.results)
                errors = sum(1 for r in self.results if r["exit_code"] != 0)
                durations = [r["duration_ms"] for r in self.results if r["exit_code"] == 0]
            elapsed = time.time() - start_time
            recent = total - last_count
            last_count = total
            avg = statistics.mean(durations) if durations else 0
            print(
                f"  [{elapsed:>6.0f}s] ops: {total:>6}  |  rpm: {total / elapsed * 60:>7.1f}"
                f"  |  last10s: {recent:>4}  |  errors: {errors:>4}  |  avg_ms: {avg:>8.1f}",
                file=sys.stderr,
            )

    def run(self):
        """Start workers, wait for duration, write results, print summary."""
        print(f"\n{'='*70}", file=sys.stderr)
        print(f"  GHES Performance Test", file=sys.stderr)
        print(f"  Target: {self.target_rpm} ops/min  |  Duration: {self.duration}s  |  Workers: {self.workers}", file=sys.stderr)
        print(f"  Scripts: {len(self.items)}  |  Output: {self.output_file}", file=sys.stderr)
        print(f"{'='*70}\n", file=sys.stderr)

        start_time = time.time()

        threading.Thread(target=self._reporter, args=(start_time,), daemon=True).start()

        with concurrent.futures.ThreadPoolExecutor(max_workers=self.workers) as pool:
            futures = [pool.submit(self._worker) for _ in range(self.workers)]
            try:
                time.sleep(self.duration)
            except KeyboardInterrupt:
                print("\n  Interrupted — stopping...", file=sys.stderr)
            self.stop_event.set()
            concurrent.futures.wait(futures, timeout=15)

        elapsed = time.time() - start_time

        # Write JSONL results
        os.makedirs(os.path.dirname(self.output_file) or ".", exist_ok=True)
        with open(self.output_file, "w") as f:
            for entry in self.results:
                f.write(json.dumps(entry) + "\n")

        self._print_summary(elapsed)

    def _print_summary(self, elapsed):
        total = len(self.results)
        errors = sum(1 for r in self.results if r["exit_code"] != 0)
        durations = sorted(r["duration_ms"] for r in self.results if r["exit_code"] == 0)
        rpm = (total / elapsed) * 60 if elapsed > 0 else 0

        print(f"\n{'='*70}", file=sys.stderr)
        print(f"  RESULTS", file=sys.stderr)
        print(f"{'='*70}", file=sys.stderr)
        print(f"  Duration     : {elapsed:.1f}s", file=sys.stderr)
        print(f"  Total ops    : {total}", file=sys.stderr)
        print(f"  Errors       : {errors} ({errors / total * 100 if total else 0:.1f}%)", file=sys.stderr)
        print(f"  Actual RPM   : {rpm:.1f}", file=sys.stderr)
        print(f"  Avg latency  : {statistics.mean(durations) if durations else 0:.1f} ms", file=sys.stderr)
        print(f"  p50 latency  : {percentile(durations, 50):.1f} ms", file=sys.stderr)
        print(f"  p95 latency  : {percentile(durations, 95):.1f} ms", file=sys.stderr)
        print(f"  p99 latency  : {percentile(durations, 99):.1f} ms", file=sys.stderr)
        print(f"  Min latency  : {(durations[0] if durations else 0):.1f} ms", file=sys.stderr)
        print(f"  Max latency  : {(durations[-1] if durations else 0):.1f} ms", file=sys.stderr)
        print(f"{'='*70}", file=sys.stderr)
        print(f"  Results → {self.output_file}", file=sys.stderr)
        print(f"{'='*70}\n", file=sys.stderr)

        # Per-script breakdown
        by_script = {}
        for r in self.results:
            name = r["script"]
            by_script.setdefault(name, {"count": 0, "errors": 0, "durations": []})
            by_script[name]["count"] += 1
            if r["exit_code"] != 0:
                by_script[name]["errors"] += 1
            else:
                by_script[name]["durations"].append(r["duration_ms"])

        print(f"  {'Script':<45} {'Count':>6} {'Err':>5} {'Avg ms':>8} {'p95 ms':>8}", file=sys.stderr)
        print(f"  {'-'*45} {'-'*6} {'-'*5} {'-'*8} {'-'*8}", file=sys.stderr)
        for name, data in sorted(by_script.items()):
            d = sorted(data["durations"])
            avg = statistics.mean(d) if d else 0
            p95 = percentile(d, 95)
            print(f"  {name:<45} {data['count']:>6} {data['errors']:>5} {avg:>8.1f} {p95:>8.1f}", file=sys.stderr)
        print(file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description="Run project scripts as a performance test.")
    parser.add_argument("--workload", required=True, help="Path to YAML workload file")
    parser.add_argument("--target-rpm", type=int, dest="target_rpm", default=None)
    parser.add_argument("--duration", type=int, default=None)
    parser.add_argument("--workers", type=int, default=None)
    parser.add_argument("--output", default=None, help="Output JSONL file")
    args = parser.parse_args()

    workload = load_workload(args.workload)

    # CLI flags override YAML values
    target_rpm = args.target_rpm or workload.get("target_rpm", 60)
    duration = args.duration or workload.get("duration", 300)
    workers = args.workers or workload.get("workers", 10)

    # Validate scripts exist on disk
    for s in workload["scripts"]:
        path = PROJECT_ROOT / s["script"]
        if not path.is_file():
            print(f"  ERROR: script not found: {path}", file=sys.stderr)
            sys.exit(1)

    # Output file
    if args.output:
        output_file = args.output
    else:
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        output_file = str(Path(__file__).parent / "results" / f"perf-{ts}.jsonl")

    LoadDriver(workload["scripts"], target_rpm, duration, workers, output_file).run()


if __name__ == "__main__":
    main()
