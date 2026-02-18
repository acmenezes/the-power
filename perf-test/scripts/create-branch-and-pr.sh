#!/bin/bash
# create-branch-and-pr.sh — Composite: creates a unique branch, then opens a PR from it.
# Designed for perf-test-runner.py — works as a single atomic operation.

. ./.gh-api-examples.conf

# 1. Generate a unique branch name (timestamp + PID avoids collisions under concurrency)
branch_name="perf-${branch_name}-$(date +%s)-$$"
json_branch=tmp/create-branch-${branch_name}.json

# 2. Get the SHA of the base branch
sha=$(curl --silent ${curl_custom_flags} \
     -H "Authorization: Bearer ${GITHUB_TOKEN}" \
     "${GITHUB_API_BASE_URL}/repos/${org}/${repo}/git/refs/heads/${base_branch}" \
     | jq -r '.object.sha')

# 3. Create the branch
jq -n --arg ref "refs/heads/${branch_name}" --arg sha "$sha" \
   '{ref: $ref, sha: $sha}' > "$json_branch"

curl ${curl_custom_flags} \
     -H "Accept: application/vnd.github.v3+json" \
     -H "Authorization: Bearer ${GITHUB_TOKEN}" \
     "${GITHUB_API_BASE_URL}/repos/${org}/${repo}/git/refs" --data @"$json_branch"

# 4. Add a small commit so the branch differs from base (required to open a PR)
json_commit=tmp/create-commit-${branch_name}.json
timestamp=$(date +%s)
content=$(echo "perf-test commit ${timestamp}" | base64)
jq -n \
  --arg message "perf-test: ${branch_name}" \
  --arg content "$content" \
  --arg branch "$branch_name" \
  '{message: $message, content: $content, branch: $branch}' > "$json_commit"

curl ${curl_custom_flags} \
     -X PUT \
     -H "Accept: application/vnd.github.v3+json" \
     -H "Authorization: Bearer ${GITHUB_TOKEN}" \
     "${GITHUB_API_BASE_URL}/repos/${org}/${repo}/contents/perf-test/${branch_name}.txt" --data @"$json_commit"

# 5. Create a PR from that branch → base
json_pr=tmp/create-pr-${branch_name}.json
jq -n \
  --arg title "Perf-test PR: ${branch_name}" \
  --arg body "Automated PR created by perf-test-runner." \
  --arg head "${branch_name}" \
  --arg base "${base_branch}" \
  '{title: $title, body: $body, head: $head, base: $base}' > "$json_pr"

curl ${curl_custom_flags} \
     -H "Accept: application/vnd.github.v3+json" \
     -H "Authorization: Bearer ${GITHUB_TOKEN}" \
     "${GITHUB_API_BASE_URL}/repos/${org}/${repo}/pulls" --data @"$json_pr"
