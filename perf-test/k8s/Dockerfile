# Dockerfile — Container image for GHES performance test runner.
#
# Build context is perf-test/ (not the full repo):
#   podman build -f perf-test/k8s/Dockerfile -t ghes-perf-runner:latest perf-test/
#
# perf-test/ is self-contained: scripts, test-data, runner, and workloads.

FROM python:3.12-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        bash \
        curl \
        git \
        jq \
        openssh-client \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir pyyaml

WORKDIR /app

# Copy the self-contained perf-test/ tree
COPY . .

# Create directories the runner and scripts expect
RUN mkdir -p results workdir tmp

# Entrypoint generates .gh-api-examples.conf from environment variables,
# then runs whatever command is passed (the perf-test-runner.py invocation).
COPY k8s/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
