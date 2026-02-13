#!/bin/bash
# git-clone-repo.sh — Clone the configured repo into a unique temp dir, then clean up.
# Simulates a developer cloning a repository. Concurrency-safe (unique dir per call).

. ./.gh-api-examples.conf

# Unique work directory to avoid collisions across concurrent workers
workdir="perf-test/workdir/clone-$(date +%s)-$$-${RANDOM}"
mkdir -p "$workdir"

# Strip "api." prefix for clone URL (needed for github.com; no-op for GHES IPs)
clone_host="${hostname/#api.github.com/github.com}"

# Build clone URL based on token type (same logic as clone-default-repo.sh)
TOKEN_PREFIX="${GITHUB_TOKEN:0:3}"
case ${TOKEN_PREFIX} in
    ghp|ghu) clone_url="https://${GITHUB_TOKEN}:x-oauth-basic@${clone_host}/${org}/${repo}.git" ;;
    ghs)     clone_url="https://x-access-token:${GITHUB_TOKEN}@${clone_host}/${org}/${repo}.git" ;;
    *)       echo "Unknown token type: ${TOKEN_PREFIX}" >&2; exit 1 ;;
esac

# Clone (disable SSL verify for self-signed certs)
git -c http.sslVerify=false clone --quiet "$clone_url" "$workdir/repo" 2>&1

exit_code=$?

# Always clean up
rm -rf "$workdir"

exit $exit_code
