#!/usr/bin/env bash
set +x
set -euo pipefail

repo="$1"
expected_id="${2:-}"
endpoint="repos/$repo/environments/production-operations"
api() {
  gh api --hostname github.com --method GET "$@" 2>/dev/null
}

environment=$(api "$endpoint") || {
  echo "ERROR: production-operations muss manuell angelegt und lesbar sein." >&2
  exit 2
}

# The sole named reviewer can approve their own run. Other administrators
# must not be able to bypass the approval.
if ! id=$(jq -er --arg expected "$expected_id" '
  select(.name == "production-operations")
  | select(.can_admins_bypass == false)
  | select(.deployment_branch_policy.protected_branches == false
      and .deployment_branch_policy.custom_branch_policies == true)
  | select([.protection_rules[] | select(.type == "branch_policy")] | length == 1)
  | select([.protection_rules[] | select(.type == "required_reviewers")] |
      length == 1 and (.[0] |
        .prevent_self_review == false and (.reviewers | type == "array" and length == 1
          and (.[0] | .type == "User" and .reviewer.id == 292215891
            and (.reviewer.login | ascii_downcase) == "tracewatcher"))))
  | .id | select(type == "number" and . > 0 and floor == .) | tostring
  | select($expected == "" or . == $expected)
' <<< "$environment" 2>/dev/null); then
  echo "ERROR: Environment-ID, Branch-Policy, Reviewer-Regel oder Administrator-Bypass für production-operations stimmt nicht." >&2
  exit 1
fi

branches=$(api "$endpoint/deployment-branch-policies?per_page=100") || {
  echo "ERROR: Die Branch-Regeln für production-operations sind nicht lesbar." >&2
  exit 2
}
jq -e '
  .total_count == 1 and (.branch_policies | length == 1)
  and .branch_policies[0].name == "main" and .branch_policies[0].type == "branch"
' <<< "$branches" >/dev/null 2>&1 || {
  echo "ERROR: production-operations benötigt genau eine Branch-Regel für main." >&2
  exit 1
}

printf '%s\n' "$id"
