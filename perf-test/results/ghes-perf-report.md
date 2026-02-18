# GHES Performance Test Results

## 64 vCPU & 128 GB RAM VM — GHES 3.19 on OCP Virt

All tests ran against a single GHES 3.19 appliance. The test client is a MacBook (14 cores, 48 GB RAM) running shell scripts via a Python orchestrator that paces requests to a target RPM.

---

## Phase 2 — API Stress Test

**Workload:** 9 API scripts (reads + writes). No Git operations.

**Scripts:** list-repo, list-repository-issues, list-pull-requests, list-org-repos, get-repository-content, search-issues-and-pull-requests, create-an-issue, create-issue-comment, create-branch-and-pr.

| Step | Target RPM | Workers | Actual RPM | Avg Latency | p95 Latency | Errors |
|------|-----------|---------|-----------|-------------|-------------|--------|
| 1 | 500 | 10 | 499.6 | 371 ms | 790 ms | 1.3% |
| 2 | 1,000 | 20 | 973.0 | 596 ms | 1,780 ms | 5.1% |
| 3 | 1,500 | 30 | 1,349.7 | 922 ms | 3,153 ms | 6.0% |
| 4 | 2,000 | 45 | 1,583.1 | 1,098 ms | 3,845 ms | 8.3% |

**Observations:**

- API ceiling at ~1,580 RPM. Pushing beyond 1,500 RPM target yields diminishing returns.
- Errors are concentrated in `create-issue-comment.sh` which triggers GHES secondary rate limiting (HTTP 403) when creating comments on the same issue at high frequency. This is abuse-detection by design, not a server capacity issue.
- API reads (`get-repository-content`, `list-org-repos`) stay fast (~250–370 ms) even at peak load.
- `create-branch-and-pr.sh` is the heaviest API script (~4s avg at Step 4) as it involves 4 chained API calls.

---

## Phase 3 — Git Stress Test

**Workload:** 4 Git-over-HTTPS scripts. No REST API operations.

**Scripts:** git-fetch (weight 15), git-pull (weight 10), git-clone-repo (weight 10), git-clone-and-push (weight 5).

| Step | Target RPM | Workers | Actual RPM | Avg Latency | p95 Latency | Errors |
|------|-----------|---------|-----------|-------------|-------------|--------|
| 1 | 200 | 15 | 200.5 | 784 ms | 1,090 ms | 0% |
| 2 | 500 | 30 | 502.5 | 860 ms | 1,187 ms | 0% |
| 3 | 1,000 | 50 | 959.7 | 2,560 ms | 3,545 ms | 0% |

**Per-script breakdown at Step 3 (1,000 RPM):**

| Script | Count | Avg ms | p95 ms |
|--------|-------|--------|--------|
| git-fetch | 1,825 | 2,962 | 3,619 |
| git-pull | 1,189 | 2,597 | 3,128 |
| git-clone-repo | 1,199 | 1,605 | 1,994 |
| git-clone-and-push | 612 | 3,162 | 3,840 |

**Observations:**

- Zero errors across all three steps — the Git transport layer is more resilient than the API under load.
- Git ceiling at ~960 RPM. 50 workers could not reach 1,000 RPM because each operation takes 2.5s+.
- Latency jumped 3x from Step 2 to Step 3 (860 ms → 2,560 ms), indicating saturation.
- `git-clone-and-push` (write path) is the heaviest operation at 3.2s avg.
- Each client-side Git op generates ~6–7 HTTP requests on the server (auth challenge, info/refs, pack negotiation, transfer). At 960 RPM client-side, the server sees ~6,000+ HTTP requests/min from Git alone.

---

## Phase 4 — Combined Workload (API + Git)

**Workload:** All 13 scripts running simultaneously — realistic mixed traffic.

**Duration:** 10 minutes per step (vs 5 min in earlier phases).

| Step | Target RPM | Workers | Actual RPM | Avg Latency | p95 Latency | Errors |
|------|-----------|---------|-----------|-------------|-------------|--------|
| 1 | 1,500 | 40 | 1,350.7 | 1,200 ms | 2,710 ms | 9.4%* |
| 2 | 2,000 | 50 | 1,482.9 | 1,621 ms | 3,602 ms | 8.9%* |

*\*Errors are entirely from create-issue-comment.sh (secondary rate limit, HTTP 403). Excluding that script: 0.1% actual error rate.*

**Per-script comparison (Step 1 → Step 2):**

| Script | Type | Step 1 Avg | Step 2 Avg | Change |
|--------|------|-----------|-----------|--------|
| get-repository-content | API read | 278 ms | 305 ms | +10% |
| list-pull-requests | API read | 744 ms | 884 ms | +19% |
| create-an-issue | API write | 1,092 ms | 1,270 ms | +16% |
| git-clone-repo | Git read | 1,132 ms | 1,706 ms | +51% |
| git-fetch | Git read | 1,970 ms | 3,079 ms | +56% |
| git-clone-and-push | Git write | 2,314 ms | 3,415 ms | +48% |

**Observations:**

- Combined ceiling at ~1,480 RPM. Adding Git ops alongside API traffic reduces throughput vs API-only (1,580 RPM).
- Git operations took the biggest latency hit (+50%) when competing with API traffic. API reads barely moved (+10–19%).
- The server was stable over 10 minutes — no crashes, no timeouts, no progressive degradation.
- RPM slowly drifted from ~1,535 down to ~1,480 in Step 2, suggesting the server accumulated some back-pressure over time.

---

## Summary — GHES Capacity on 64 vCPU / 128 GB RAM

| Workload | Comfortable RPM | Hard Ceiling RPM |
|----------|----------------|-----------------|
| API only | ~1,000 (p95 < 2s) | ~1,580 |
| Git only | ~500 (p95 < 1.2s) | ~960 |
| Combined (API + Git) | ~1,350 | ~1,480 |

**Note:** `create-issue-comment.sh` triggers GHES secondary rate limiting (HTTP 403) when posting comments to the same issue at high concurrency. This is intentional abuse-detection and not a server capacity failure. All error metrics above are inflated by this single script.
