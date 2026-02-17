#!/bin/bash
# fetch-support-bundle.sh — Download a GHES support bundle for analysis.
#
# Usage:
#   bash perf-test/fetch-support-bundle.sh                     # uses config defaults
#   bash perf-test/fetch-support-bundle.sh 192.168.2.251       # explicit host
#
# Requires SSH access to the GHES appliance (port 122).
# See: https://docs.github.com/en/enterprise-server@3.19/support/contacting-github-support/providing-data-to-github-support

set -euo pipefail

. ./.gh-api-examples.conf

GHES_HOST="${1:-$hostname}"
SSH_KEY="perf-test/credentials/ghes-admin"
SSH_OPTS="-i ${SSH_KEY} -o StrictHostKeyChecking=no -p 122"
LOCAL_FILE="perf-test/results/support-bundle-$(date +%Y%m%d-%H%M%S).tgz"

mkdir -p perf-test/results

echo ""
echo "  Generating and downloading bundle from ${GHES_HOST}..."
echo "  (this may take a few minutes)"
echo ""
ssh ${SSH_OPTS} admin@"${GHES_HOST}" -- 'ghe-support-bundle -o' > "${LOCAL_FILE}" 2>/dev/null

SIZE=$(du -h "${LOCAL_FILE}" | cut -f1)
echo "  ✓ Saved: ${LOCAL_FILE} (${SIZE})"
echo ""
echo "  Next: python3 perf-test/parse-support-bundle.py ${LOCAL_FILE}"
echo ""
