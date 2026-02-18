# Makefile — Build, push, deploy, and manage GHES performance test Jobs.
#
# Usage:
#   make build push setup           # Build image, push, create namespace + secret + PVC
#   make run-api                    # Run Phase 1 (API only)
#   make run-git                    # Run Phase 2 (Git only)
#   make run-combined               # Run Phase 3 (Combined)
#   make logs-api                   # Stream logs from the API Job
#   make results                    # Copy results from PVC to local machine
#   make clean                      # Delete all Jobs
#   make teardown                   # Delete the entire namespace

# ── Configuration ──────────────────────────────────────────────────────────────
IMAGE       ?= quay.io/acmenezes/ghes-perf-runner
TAG         ?= latest
NAMESPACE   ?= ghes-perf-test
GHES_HOST   ?= 192.168.2.251
GHES_TOKEN  ?= $(shell cat ../../token.txt 2>/dev/null || echo "REPLACE_ME")

MANIFESTS   := manifests
PROJECT_ROOT := $(shell cd ../.. && pwd)
PERF_DIR     := $(PROJECT_ROOT)/perf-test

# ── Image ──────────────────────────────────────────────────────────────────────
.PHONY: build push

build:
	podman build -f Dockerfile -t $(IMAGE):$(TAG) $(PERF_DIR)

push:
	podman push $(IMAGE):$(TAG)

# ── Cluster setup ──────────────────────────────────────────────────────────────
.PHONY: setup namespace secret pvc

setup: namespace secret pvc
	@echo "  ✓ Namespace, secret, and PVC ready in $(NAMESPACE)"

namespace:
	kubectl apply -f $(MANIFESTS)/namespace.yaml

secret:
	@kubectl -n $(NAMESPACE) get secret ghes-credentials >/dev/null 2>&1 || \
		kubectl -n $(NAMESPACE) create secret generic ghes-credentials \
			--from-literal=token='$(GHES_TOKEN)' \
			--from-literal=host='$(GHES_HOST)'

pvc:
	kubectl apply -f $(MANIFESTS)/pvc.yaml

# ── Run Jobs ───────────────────────────────────────────────────────────────────
.PHONY: run-api run-git run-combined

run-api:
	kubectl apply -f $(MANIFESTS)/job-api.yaml
	@echo "  ✓ API Job started — run 'make logs-api' to follow"

run-git:
	kubectl apply -f $(MANIFESTS)/job-git.yaml
	@echo "  ✓ Git Job started — run 'make logs-git' to follow"

run-combined:
	kubectl apply -f $(MANIFESTS)/job-combined.yaml
	@echo "  ✓ Combined Job started — run 'make logs-combined' to follow"

# ── Logs ───────────────────────────────────────────────────────────────────────
.PHONY: logs-api logs-git logs-combined pods

logs-api:
	kubectl -n $(NAMESPACE) logs -f job/ghes-perf-api --all-containers --prefix

logs-git:
	kubectl -n $(NAMESPACE) logs -f job/ghes-perf-git --all-containers --prefix

logs-combined:
	kubectl -n $(NAMESPACE) logs -f job/ghes-perf-combined --all-containers --prefix

pods:
	kubectl -n $(NAMESPACE) get pods -o wide

# ── Results ────────────────────────────────────────────────────────────────────
.PHONY: results

results:
	@mkdir -p $(PERF_DIR)/results
	@POD=$$(kubectl -n $(NAMESPACE) get pods -l app.kubernetes.io/name=ghes-perf-test \
		--field-selector=status.phase=Succeeded -o jsonpath='{.items[0].metadata.name}' 2>/dev/null); \
	if [ -z "$$POD" ]; then \
		echo "  No completed Pods found. Wait for a Job to finish."; exit 1; \
	fi; \
	echo "  Copying results from $$POD:/results/ ..."; \
	kubectl cp $(NAMESPACE)/$$POD:/results/ $(PERF_DIR)/results/; \
	echo "  ✓ Results saved to $(PERF_DIR)/results/"

# ── Cleanup ────────────────────────────────────────────────────────────────────
.PHONY: clean clean-api clean-git clean-combined teardown

clean:
	kubectl -n $(NAMESPACE) delete jobs --all --ignore-not-found
	@echo "  ✓ All Jobs deleted"

clean-api:
	kubectl -n $(NAMESPACE) delete job ghes-perf-api --ignore-not-found

clean-git:
	kubectl -n $(NAMESPACE) delete job ghes-perf-git --ignore-not-found

clean-combined:
	kubectl -n $(NAMESPACE) delete job ghes-perf-combined --ignore-not-found

teardown:
	kubectl delete namespace $(NAMESPACE) --ignore-not-found
	@echo "  ✓ Namespace $(NAMESPACE) deleted"

# ── Help ───────────────────────────────────────────────────────────────────────
.PHONY: help

help:
	@echo ""
	@echo "  GHES Performance Test — Kubernetes Targets"
	@echo ""
	@echo "  Image:"
	@echo "    make build                Build container image"
	@echo "    make push                 Push to $(IMAGE)"
	@echo ""
	@echo "  Setup:"
	@echo "    make setup                Create namespace + secret + PVC"
	@echo "    make secret               Create secret (reads token.txt or GHES_TOKEN)"
	@echo ""
	@echo "  Run:"
	@echo "    make run-api              Phase 1 — API stress test"
	@echo "    make run-git              Phase 2 — Git stress test"
	@echo "    make run-combined         Phase 3 — Combined workload"
	@echo ""
	@echo "  Monitor:"
	@echo "    make pods                 List Pods"
	@echo "    make logs-api             Stream API Job logs"
	@echo "    make logs-git             Stream Git Job logs"
	@echo "    make logs-combined        Stream Combined Job logs"
	@echo ""
	@echo "  Results:"
	@echo "    make results              Copy JSONL from PVC to local results/"
	@echo ""
	@echo "  Cleanup:"
	@echo "    make clean                Delete all Jobs"
	@echo "    make clean-api            Delete API Job only"
	@echo "    make teardown             Delete entire namespace"
	@echo ""
	@echo "  Override defaults:"
	@echo "    make setup GHES_HOST=10.0.0.1 GHES_TOKEN=ghp_xxx"
	@echo "    make build IMAGE=my-registry.io/runner TAG=v2"
	@echo ""
