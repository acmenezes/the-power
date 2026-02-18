# Running GHES Performance Tests on Kubernetes

Run the performance test runner as Kubernetes Jobs, distributing load across
multiple Pods. Each Pod runs `perf-test-runner.py` with its own worker pool,
writing JSONL results to a shared PersistentVolume.

## Prerequisites

- A Kubernetes cluster with access to the GHES appliance network
- `kubectl` configured for the target cluster
- `podman` (or `docker`) for building the container image
- A GHES personal access token with admin scope
- The GHES org/repo created by `build-all.sh` (run once from your laptop first)

## File Structure

```
perf-test/k8s/
├── .dockerignore
├── Dockerfile
├── entrypoint.sh
└── manifests/
    ├── kustomization.yaml
    ├── namespace.yaml
    ├── secret.yaml
    ├── pvc.yaml
    ├── job-api.yaml
    ├── job-git.yaml
    └── job-combined.yaml
```

## 1. Build the Container Image

Build from the **project root** (not from `k8s/`), because the scripts live
across the entire repo tree:

```bash
cd the-power/
podman build -f perf-test/k8s/Dockerfile -t ghes-perf-runner:latest .
```

## 2. Push to Your Registry

Tag and push to whatever registry your cluster can pull from:

```bash
podman tag ghes-perf-runner:latest your-registry.example.com/ghes-perf-runner:latest
podman push your-registry.example.com/ghes-perf-runner:latest
```

Then update the `image:` field in the Job manifests to match.

## 3. Deploy Base Resources

Apply the namespace, secret, and PVC:

```bash
kubectl apply -k perf-test/k8s/manifests/
```

This creates:
- **Namespace** `ghes-perf-test`
- **Secret** `ghes-credentials` (template — needs real values)
- **PVC** `perf-results` (5Gi, ReadWriteMany)

### Create the secret with real credentials

Either edit `secret.yaml` before applying, or create it imperatively:

```bash
kubectl -n ghes-perf-test create secret generic ghes-credentials \
  --from-literal=token='ghp_YOUR_TOKEN_HERE' \
  --from-literal=host='192.168.2.251'
```

## 4. Run a Test Phase

Apply the Job for the phase you want:

```bash
# Phase 1 — API only (5 Pods × 10 workers × 200 RPM = 1,000 RPM aggregate)
kubectl apply -f perf-test/k8s/manifests/job-api.yaml

# Phase 2 — Git only (5 Pods × 10 workers × 100 RPM = 500 RPM aggregate)
kubectl apply -f perf-test/k8s/manifests/job-git.yaml

# Phase 3 — Combined (5 Pods × 10 workers × 300 RPM = 1,500 RPM aggregate)
kubectl apply -f perf-test/k8s/manifests/job-combined.yaml
```

### Monitor progress

```bash
# Watch Pods
kubectl -n ghes-perf-test get pods -w

# Stream logs from a specific Job
kubectl -n ghes-perf-test logs -f job/ghes-perf-api

# Stream logs from a specific Pod
kubectl -n ghes-perf-test logs -f <pod-name>
```

## 5. Collect Results

Results are written to the shared PVC at `/results/`. Copy them out from any
completed Pod:

```bash
# List completed Pods
kubectl -n ghes-perf-test get pods -l ghes-perf/phase=api

# Copy results to your local machine
kubectl cp ghes-perf-test/<pod-name>:/results/ ./perf-test/results/
```

Or spin up a helper Pod to browse the PVC:

```bash
kubectl run results-reader -n ghes-perf-test --rm -it \
  --image=busybox -- sh -c 'ls -lh /results/'  \
  --overrides='{
    "spec": {
      "containers": [{
        "name": "r",
        "image": "busybox",
        "volumeMounts": [{"name": "results", "mountPath": "/results"}],
        "command": ["sh"]
      }],
      "volumes": [{
        "name": "results",
        "persistentVolumeClaim": {"claimName": "perf-results"}
      }]
    }
  }'
```

## 6. Aggregate Results

Combine the JSONL files from all Pods into a single report:

```bash
python3 perf-test/perf-test-aggregate.py perf-test/results/perf-api-*.jsonl --by-file
```

## 7. Clean Up

```bash
# Delete all Jobs (Pods are cleaned up automatically)
kubectl -n ghes-perf-test delete jobs --all

# Or delete the entire namespace
kubectl delete namespace ghes-perf-test
```

## Resource Sizing

Each Job is pre-configured with resource requests and limits based on our
laptop-based benchmarks. **No CPU limits** are set to prevent kernel throttling
from inflating latency measurements.

| Job | Pods | Workers/Pod | RPM/Pod | Aggregate RPM | CPU request | Memory request | Memory limit |
|-----|------|-------------|---------|---------------|-------------|----------------|--------------|
| API | 5 | 10 | 200 | 1,000 | 1 core | 512Mi | 1Gi |
| Git | 5 | 10 | 100 | 500 | 2 cores | 768Mi | 1.5Gi |
| Combined | 5 | 10 | 300 | 1,500 | 1.5 cores | 512Mi | 1Gi |

### Scaling up

To increase the aggregate RPM, you have two levers:

- **More Pods** — increase `parallelism` and `completions` in the Job spec
- **More workers per Pod** — increase `--workers` and `--target-rpm` in the command

For example, to reach 2,000 RPM with the API workload:
- 10 Pods × 10 workers × 200 RPM each, or
- 5 Pods × 20 workers × 400 RPM each (bump CPU request to 2 cores)

### Sizing guidelines

- **API workers**: ~50 MB RAM and ~0.1 CPU per worker (curl + jq)
- **Git workers**: ~75 MB RAM and ~0.2 CPU per worker (git clone/fetch/push)
- **Formula**: `memory_request = workers × per_worker_MB + 100 MB (overhead)`
- Set `memory_limit = 2 × memory_request` to absorb spikes without OOMKill
- Omit CPU limits entirely — only set CPU requests for scheduling

### Volumes

- **results** — PVC (`ReadWriteMany`) shared across all Pods for JSONL output
- **workdir** — `emptyDir` per Pod for Git clones (ephemeral, cleaned up with Pod)
- **tmp** — `emptyDir` per Pod for temporary JSON payloads used by curl scripts
