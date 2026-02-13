#!/bin/bash
# git-clone-and-push.sh — Clone, create a branch, commit a file, push, clean up.
# Simulates a developer pushing code. Concurrency-safe (unique dir + branch per call).

. ./.gh-api-examples.conf

# Unique identifiers for this invocation
unique_id="$(date +%s)-$$-${RANDOM}"
workdir="perf-test/workdir/push-${unique_id}"
branch="perf-push-${unique_id}"
mkdir -p "$workdir"

# Strip "api." prefix for clone URL (needed for github.com; no-op for GHES IPs)
clone_host="${hostname/#api.github.com/github.com}"

# Build clone URL based on token type
TOKEN_PREFIX="${GITHUB_TOKEN:0:3}"
case ${TOKEN_PREFIX} in
    ghp|ghu) clone_url="https://${GITHUB_TOKEN}:x-oauth-basic@${clone_host}/${org}/${repo}.git" ;;
    ghs)     clone_url="https://x-access-token:${GITHUB_TOKEN}@${clone_host}/${org}/${repo}.git" ;;
    *)       echo "Unknown token type: ${TOKEN_PREFIX}" >&2; exit 1 ;;
esac

# All git commands use SSL verify off (self-signed certs)
GIT="git -c http.sslVerify=false"

# 1. Clone
$GIT clone --quiet "$clone_url" "$workdir/repo" 2>&1 || { rm -rf "$workdir"; exit 1; }

cd "$workdir/repo"

# 2. Create and switch to a new branch
$GIT checkout -b "$branch" --quiet 2>&1

# 3. Add a small file and commit
echo "perf-test push ${unique_id}" > "perf-${unique_id}.txt"
$GIT add . 2>&1
$GIT -c user.name="perf-test" -c user.email="perf@test" commit --quiet -m "perf-test: ${unique_id}" 2>&1

# 4. Push
$GIT push --quiet origin "$branch" 2>&1

exit_code=$?

# Always clean up
cd /
rm -rf "$workdir"

exit $exit_code
