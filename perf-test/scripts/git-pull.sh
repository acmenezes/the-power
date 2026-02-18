#!/bin/bash
# git-pull.sh — Clone the repo then pull (simulates a developer syncing their checkout).
# Concurrency-safe (unique dir per call).

. ./.gh-api-examples.conf

# Unique work directory
workdir="workdir/pull-$(date +%s)-$$-${RANDOM}"
mkdir -p "$workdir"

# Strip "api." prefix for clone URL
clone_host="${hostname/#api.github.com/github.com}"

# Build clone URL based on token type
TOKEN_PREFIX="${GITHUB_TOKEN:0:3}"
case ${TOKEN_PREFIX} in
    ghp|ghu) clone_url="https://${GITHUB_TOKEN}:x-oauth-basic@${clone_host}/${org}/${repo}.git" ;;
    ghs)     clone_url="https://x-access-token:${GITHUB_TOKEN}@${clone_host}/${org}/${repo}.git" ;;
    *)       echo "Unknown token type: ${TOKEN_PREFIX}" >&2; exit 1 ;;
esac

GIT="git -c http.sslVerify=false"

# Clone first (setup), then pull (the actual operation)
$GIT clone --quiet "$clone_url" "$workdir/repo" 2>&1 || { rm -rf "$workdir"; exit 1; }

cd "$workdir/repo"
$GIT pull --quiet origin ${base_branch} 2>&1

exit_code=$?

# Clean up
cd /
rm -rf "$workdir"

exit $exit_code
