# GHES Performance Testing

Performance testing toolkit for GitHub Enterprise Server (GHES) running on OpenShift Virtualization (OCP-V).

## Prerequisites

- Python 3.9+
- `bash`, `curl`, `jq`, `git` installed locally
- Network access to the GHES instance
- A GHES instance (3.x) with admin access

## 1. GHES Instance Setup

### Initial Configuration

1. Browse to the GHES management console:

   ```
   https://<GHES_IP>:8443/setup
   ```

2. Upload the license file, set the management console password, and complete the setup wizard.

3. Wait for all services to go green and the configuration run to finish.

### Create the First Admin User

1. Once GHES is fully configured, browse to:

   ```
   https://<GHES_IP>/join
   ```

2. Create a user account. The **first user** created is automatically promoted to **site admin**.

### Generate a Personal Access Token (PAT)

1. Log in to GHES with the admin user.
2. Go to **Settings → Developer settings → Personal access tokens → Tokens (classic)**.
3. Click **Generate new token (classic)**.
4. Select **all scopes** (the admin API requires broad permissions).
5. Copy the token (starts with `ghp_`).

## 2. Configure the Project

From the project root:

```bash
python3 configure.py \
  --hostname <GHES_IP> \
  --token <YOUR_TOKEN> \
  --org <ORG_NAME> \
  --repo <REPO_NAME> \
  -u <ADMIN_USERNAME> \
  --curl_custom_flags "--no-progress-meter --fail-with-body -k"
```

- The `-k` flag disables SSL certificate verification (required for self-signed certificates).
- `-u` sets the admin user that will own the org.
- `--org` and `--repo` can be any name you like (e.g., `load-test-org` and `loadtest-repo`).

Verify the configuration works:

```bash
bash pwr-get-octocat.sh
```

## 3. Build Test Prerequisites

Run the build script to create the org, repo, users, teams, issues, branches, and PRs:

```bash
bash build-all.sh
```

Expected output:
- Organization, team, and repo created
- Users `mona`, `hubot`, `mario`, `luigi` created and added to the org/team
- `docs/README.md`, `CODEOWNERS`, `requirements.txt` committed to the repo
- A `new_branch` created with a commit
- Issue #1 and PR #2 created
- Branch protection rules set on `main`

> **Note:** User creation may return `422` if users already exist from a previous run. This is harmless.

## 4. Install Python Dependencies

```bash
cd perf-test
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cd ..
```

## 5. Run Performance Tests

> **Important:** Run all tests from a regular terminal (not inside Cursor/IDE sandbox)
> so that Git operations have full filesystem access.

### Phase 1 — Baseline (smoke test)

Verify everything works end-to-end at low load.

```bash
python3 perf-test/perf-test-runner.py \
  --workload perf-test/perf-workload.yaml \
  --duration 60 --target-rpm 20 --workers 3
```

**What to look for:** 0% errors, actual RPM close to target, all script types appearing in the breakdown.

### Phase 2 — API Stress Test

Isolate API performance by using the API-only workload. Ramp up progressively.

```bash
# Step 1: 500 RPM
python3 perf-test/perf-test-runner.py \
  --workload perf-test/perf-workload-api.yaml \
  --duration 300 --target-rpm 500 --workers 15

# Step 2: 1,000 RPM
python3 perf-test/perf-test-runner.py \
  --workload perf-test/perf-workload-api.yaml \
  --duration 300 --target-rpm 1000 --workers 25

# Step 3: 1,500 RPM
python3 perf-test/perf-test-runner.py \
  --workload perf-test/perf-workload-api.yaml \
  --duration 300 --target-rpm 1500 --workers 35

# Step 4: 2,000 RPM (target ceiling)
python3 perf-test/perf-test-runner.py \
  --workload perf-test/perf-workload-api.yaml \
  --duration 300 --target-rpm 2000 --workers 45
```

### Phase 3 — Git Stress Test

Isolate Git performance using the Git-only workload. Git ops are heavier (~1–3s each), so they need more workers for the same RPM.

```bash
# Step 1: 200 RPM
python3 perf-test/perf-test-runner.py \
  --workload perf-test/perf-workload-git.yaml \
  --duration 300 --target-rpm 200 --workers 15

# Step 2: 500 RPM
python3 perf-test/perf-test-runner.py \
  --workload perf-test/perf-workload-git.yaml \
  --duration 300 --target-rpm 500 --workers 30

# Step 3: 1,000 RPM (target ceiling)
python3 perf-test/perf-test-runner.py \
  --workload perf-test/perf-workload-git.yaml \
  --duration 300 --target-rpm 1000 --workers 50
```

### Phase 4 — Combined (realistic mixed workload)

Once individual ceilings are known, run API + Git together to simulate real-world traffic.

```bash
# Mixed at 1,500 total RPM
python3 perf-test/perf-test-runner.py \
  --workload perf-test/perf-workload.yaml \
  --duration 600 --target-rpm 1500 --workers 40

# Mixed at 2,000 total RPM
python3 perf-test/perf-test-runner.py \
  --workload perf-test/perf-workload.yaml \
  --duration 600 --target-rpm 2000 --workers 50
```

### Interpreting Results

| Signal | Meaning |
|---|---|
| Error rate stays at 0% | GHES is handling it fine — push harder |
| p95 latency climbing sharply | Approaching saturation |
| Error rate > 5% | GHES is overloaded — back off |
| Actual RPM much lower than target | Client is the bottleneck (too many subprocesses) |

### CLI Overrides

All YAML settings can be overridden from the command line:

```bash
python3 perf-test/perf-test-runner.py \
  --workload perf-test/perf-workload.yaml \
  --duration 600 --target-rpm 120 --workers 10
```

## 6. Aggregate Results

Results are written as JSON-lines files to `perf-test/results/`.

```bash
# Summary to terminal
python3 perf-test/perf-test-aggregate.py perf-test/results/perf-*.jsonl

# Export as CSV
python3 perf-test/perf-test-aggregate.py perf-test/results/perf-*.jsonl \
  --csv perf-test/results/report.csv

# Markdown table (for pasting into GitHub issues/PRs)
python3 perf-test/perf-test-aggregate.py perf-test/results/perf-*.jsonl --markdown
```

## 7. Support Bundle Analysis

After a test run, download and parse the GHES support bundle to get **server-side metrics**
and compare them with the client-side results.

### Prerequisites — SSH key setup

The GHES appliance uses **SSH on port 122** for admin access. You must add your
public key before you can download a support bundle.

1. Copy your public key:

```bash
cat ~/.ssh/id_ed25519.pub   # or id_rsa.pub
```

2. Add it via the **Management Console** (`https://<GHES_HOST>:8443`):

   - Go to **Settings → SSH access** (under the Infrastructure section).
   - Paste your public key and save.
   - Click **Save settings** (a config run may be triggered).

3. Alternatively, if you already have SSH access to the VM (e.g. via OpenShift `virtctl`):

```bash
# From the VM console or virtctl ssh:
sudo ghe-ssh-admin-key add "$(cat /path/to/your/id_ed25519.pub)"
```

4. Verify connectivity:

```bash
ssh -p 122 admin@192.168.2.251 -- "echo ok"
```

> **Note**: The SSH user is always `admin` regardless of your GHES username.
> Authentication is **public key only** — no password.

### Download the bundle

Once SSH access is configured:

```bash
bash perf-test/fetch-support-bundle.sh
# or with an explicit host:
bash perf-test/fetch-support-bundle.sh 192.168.2.251
```

### Parse the bundle

Extract API timing (unicorn.log), Git transport (babeld.log), and load balancer (haproxy.log)
entries into JSONL format:

```bash
# Parse everything
python3 perf-test/parse-support-bundle.py perf-test/results/support-bundle-*.tgz

# Parse only entries within the test window
python3 perf-test/parse-support-bundle.py perf-test/results/support-bundle-*.tgz \
  --start 2026-02-17T13:00:00 --end 2026-02-17T13:10:00

# Parse only a specific log type
python3 perf-test/parse-support-bundle.py perf-test/results/support-bundle-*.tgz --log unicorn
```

### Compare client vs server

Feed both client and server JSONL files into the aggregator with `--compare`:

```bash
python3 perf-test/perf-test-aggregate.py \
  --compare perf-test/results/perf-*.jsonl \
  --server perf-test/results/server-*.jsonl
```

This shows a side-by-side table with latency from both perspectives and the delta between them.
The delta reveals **network overhead** (client latency − server latency = time spent on the wire).

## 8. Workload Configuration

Workload YAML files define which scripts to run and how often. Example:

```yaml
target_rpm: 60      # requests per minute
duration: 300       # seconds
workers: 5          # concurrent threads

scripts:
  - {script: list-repo.sh,               weight: 10}
  - {script: create-an-issue.sh,          weight: 5}
  - {script: perf-test/git-clone-repo.sh, weight: 5}
```

- **`script`** — path to any shell script in the project (relative to the project root).
- **`weight`** — controls how often a script is picked. Higher weight = more frequent.
- Weights don't need to sum to 100.

You can add any script from the project to the workload. See the root directory for the full list of available scripts.

## File Structure

```
perf-test/
├── README.md                    # This file
├── requirements.txt             # Python dependencies
├── perf-test-runner.py          # Main test orchestrator
├── perf-test-aggregate.py       # Results aggregator (client + server)
├── parse-support-bundle.py      # GHES support bundle → JSONL parser
├── fetch-support-bundle.sh      # Download support bundle via SSH
├── perf-workload.yaml           # Default balanced workload (API + Git)
├── perf-workload-api.yaml       # API-only workload
├── perf-workload-git.yaml       # Git-only workload
├── create-branch-and-pr.sh      # Composite: create branch + PR
├── git-clone-repo.sh            # Concurrency-safe git clone
├── git-clone-and-push.sh        # Concurrency-safe clone + push
├── git-fetch.sh                 # Concurrency-safe clone + fetch
├── git-pull.sh                  # Concurrency-safe clone + pull
├── results/                     # JSONL + bundle output files (git-ignored)
└── workdir/                     # Temporary git working dirs (git-ignored)
```
