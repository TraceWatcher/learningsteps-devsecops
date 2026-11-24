#!/usr/bin/env bash
set +x
set -euo pipefail

RG="rg-learningsteps-devsecops"
IDENTITY="id-learningsteps-github"
REPO="TraceWatcher/learningsteps-devsecops"
ENVIRONMENT="production"
ACR="acrlearningstepsbff17e9a"
AKS="aks-learningsteps"
FIC="fic-learningsteps-github-production"
AKS_ROLE="LearningSteps AKS Command Deployer"
ACR_PUSH_ROLE_ID="8311e382-0749-4cb8-b61a-304f252e45ec"
VARIABLES="repos/$REPO/environments/$ENVIRONMENT/variables"
UUID='\A[0-9a-fA-F]{8}(-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}\z'

fail() {
  printf 'ERROR: %s\n' "$1" >&2
  exit 2
}

drift() {
  printf 'ABWEICHUNG: %s\n' "$1" >&2
  exit 1
}

trap 'fail "Technischer Fehler in Skriptzeile $LINENO."' ERR

check=false
case "$#:${1:-}" in
  0:) ;;
  1:--check) check=true ;;
  *) fail "Aufruf: $0 [--check]" ;;
esac

for command in az gh jq; do
  command -v "$command" >/dev/null || fail "$command fehlt."
done

# CLI-Fehler kontextbezogen melden. Rohdaten können sensible Werte enthalten.
read_cli() {
  local description="$1"
  shift
  "$@" 2>/dev/null || fail "$description fehlgeschlagen. Anmeldung und Leseberechtigungen prüfen."
}

github_get() {
  gh api --hostname github.com --method GET "$@"
}

require_json() {
  local description="$1" data="$2"
  shift 2
  jq -e "$@" <<< "$data" >/dev/null 2>&1 ||
    fail "$description ist ungültig oder unvollständig."
}

ACCOUNT=$(read_cli "Azure-Kontoabfrage" az account show -o json)
require_json "Azure-Kontoantwort" "$ACCOUNT" --arg uuid "$UUID" \
  '(.id | test($uuid)) and (.tenantId | test($uuid))'
SUBSCRIPTION_ID=$(jq -r '.id' <<< "$ACCOUNT")
ACTIVE_TENANT=$(jq -r '.tenantId' <<< "$ACCOUNT")
RG_ID="/subscriptions/$SUBSCRIPTION_ID/resourceGroups/$RG"

IDENTITY_JSON=$(read_cli "Abfrage der Managed Identity" az identity show \
  --subscription "$SUBSCRIPTION_ID" --resource-group "$RG" --name "$IDENTITY" -o json)
require_json "Antwort der Managed Identity" "$IDENTITY_JSON" --arg uuid "$UUID" '
  (.clientId | test($uuid)) and (.tenantId | test($uuid))
  and (.principalId | test($uuid)) and (.id | type == "string" and length > 0)'
CLIENT_ID=$(jq -r '.clientId' <<< "$IDENTITY_JSON")
TENANT_ID=$(jq -r '.tenantId' <<< "$IDENTITY_JSON")
PRINCIPAL_ID=$(jq -r '.principalId | ascii_downcase' <<< "$IDENTITY_JSON")
IDENTITY_ID=$(jq -r '.id' <<< "$IDENTITY_JSON")
EXPECTED_ID="$RG_ID/providers/Microsoft.ManagedIdentity/userAssignedIdentities/$IDENTITY"
[[ "${IDENTITY_ID,,}" == "${EXPECTED_ID,,}" ]] || drift "Azure Identity hat einen unerwarteten Ressourcen-Scope."
[[ "${TENANT_ID,,}" == "${ACTIVE_TENANT,,}" ]] || drift "Azure Identity und Azure-Konto verwenden unterschiedliche Tenants."

# Alle Seiten prüfen, damit eine fehlende Variable eindeutig erkannt wird.
GH_VARS=$(read_cli "Abfrage der GitHub-Environment-Variablen" \
  github_get "$VARIABLES?per_page=100" --paginate)
require_json "Antwort der GitHub-Environment-Variablen" "$GH_VARS" -s '
  length > 0 and
  all(.[]; (.total_count | type == "number" and . >= 0)
    and (.variables | type == "array")
    and all(.variables[]; (.name | type == "string") and (.value | type == "string"))) and
  (.[0].total_count as $total |
    all(.[]; .total_count == $total) and
    ([.[].variables[].name] | length == $total and (unique | length == $total)))'
get_var() {
  jq -sr --arg name "$1" --arg uuid "$UUID" '
    .[].variables[] | select(.name == $name) | .value | select(test($uuid))
  ' <<< "$GH_VARS"
}

OLD_CLIENT_ID=$(get_var AZURE_CLIENT_ID)
GH_TENANT=$(get_var AZURE_TENANT_ID)
GH_SUBSCRIPTION=$(get_var AZURE_SUBSCRIPTION_ID)
[[ "${GH_TENANT,,}" == "${TENANT_ID,,}" ]] || drift "GitHub AZURE_TENANT_ID fehlt oder weicht ab."
[[ "${GH_SUBSCRIPTION,,}" == "${SUBSCRIPTION_ID,,}" ]] || drift "GitHub AZURE_SUBSCRIPTION_ID fehlt oder weicht ab."

REPO_INFO=$(read_cli "Abfrage der GitHub-Repository-Daten" github_get "repos/$REPO")
require_json "GitHub-Repository-Antwort" "$REPO_INFO" '
  def github_id: type == "number" and . > 0 and floor == .;
  (.id | github_id) and (.owner.id | github_id) and
  (.name | type == "string" and length > 0) and
  (.owner.login | type == "string" and length > 0) and
  (.created_at | fromdateiso8601 | type == "number")'
REPO_SUBJECT=$(jq -r '"\(.owner.login)@\(.owner.id)/\(.name)@\(.id)"' <<< "$REPO_INFO")
REPO_CREATED_AT=$(jq -r '.created_at' <<< "$REPO_INFO")
EXPECTED_SUBJECT="repo:$REPO_SUBJECT:environment:$ENVIRONMENT"
OIDC=$(read_cli "Abfrage der GitHub-OIDC-Konfiguration" \
  github_get "repos/$REPO/actions/oidc/customization/sub" -H "X-GitHub-Api-Version: 2026-03-10")
require_json "GitHub-OIDC-Antwort" "$OIDC" '
  (.use_default | type == "boolean") and
  ((has("use_immutable_subject") | not) or (.use_immutable_subject | type == "boolean")) and
  (.use_default or (.include_claim_keys | type == "array" and all(.[]; type == "string")))'
jq -e '.use_default or .include_claim_keys == ["repo", "context"]' <<< "$OIDC" >/dev/null ||
  drift "GitHub-OIDC-Template ergibt nicht das erwartete Environment-Subject."
# GitHub dokumentiert das ID-basierte Standardformat für nach dem 15. Juli
# 2026 erstellte Repositories. Bei älteren ist ein bestätigtes Opt-in nötig.
case "$(jq -r '.use_immutable_subject' <<< "$OIDC")" in
  false) drift "Das ID-basierte GitHub-OIDC-Subject ist deaktiviert." ;;
  null)
    [[ "${REPO_CREATED_AT:0:10}" > "2026-07-15" ]] ||
      fail "Das ID-basierte GitHub-OIDC-Subject ist anhand der API-Antwort nicht nachweisbar."
    ;;
esac

FICS=$(read_cli "Abfrage der Federated Credentials" az identity federated-credential list \
  --subscription "$SUBSCRIPTION_ID" --resource-group "$RG" --identity-name "$IDENTITY" -o json)
require_json "Antwort der Federated Credentials" "$FICS" '
  type == "array" and all(.[]; (.name | type == "string")
    and (.issuer | type == "string") and (.subject | type == "string")
    and (.audiences | type == "array" and all(.[]; type == "string")))'
jq -e --arg name "$FIC" --arg subject "$EXPECTED_SUBJECT" '
  [.[] | select(.name == $name)] |
  length == 1 and all(.[];
    .issuer == "https://token.actions.githubusercontent.com"
    and .subject == $subject
    and .audiences == ["api://AzureADTokenExchange"])
' <<< "$FICS" >/dev/null ||
  drift "Federated Credential für production fehlt oder weicht bei Issuer, Subject oder Audience ab."

ACR_JSON=$(read_cli "Abfrage der Release-Registry" az acr show \
  --subscription "$SUBSCRIPTION_ID" --resource-group "$RG" --name "$ACR" -o json)
AKS_JSON=$(read_cli "Abfrage des AKS-Clusters" az aks show \
  --subscription "$SUBSCRIPTION_ID" --resource-group "$RG" --name "$AKS" -o json)
require_json "ACR-Antwort" "$ACR_JSON" '
  (.id | type == "string" and length > 0) and (.roleAssignmentMode | type == "string" and length > 0)'
require_json "AKS-Antwort" "$AKS_JSON" '(.id | type == "string" and length > 0)'
ACR_ID=$(jq -r '.id' <<< "$ACR_JSON")
AKS_ID=$(jq -r '.id' <<< "$AKS_JSON")
[[ "${ACR_ID,,}" == "${RG_ID,,}/providers/microsoft.containerregistry/registries/${ACR,,}" ]] ||
  drift "ACR hat einen unerwarteten Ressourcen-Scope."
[[ "${AKS_ID,,}" == "${RG_ID,,}/providers/microsoft.containerservice/managedclusters/${AKS,,}" ]] ||
  drift "AKS hat einen unerwarteten Ressourcen-Scope."
ACR_MODE=$(jq -r '.roleAssignmentMode | ascii_downcase' <<< "$ACR_JSON")
[[ "$ACR_MODE" == legacyregistrypermissions ]] ||
  drift "Der ACR-Rollenzuweisungsmodus unterstützt das vorgesehene AcrPush nicht."

AKS_ROLES=$(read_cli "Abfrage der AKS-Rollendefinition" az role definition list \
  --subscription "$SUBSCRIPTION_ID" --scope "$RG_ID" --name "$AKS_ROLE" -o json)
require_json "Antwort der AKS-Rollendefinition" "$AKS_ROLES" --arg uuid "$UUID" '
  def patterns: type == "array" and all(.[]; test("\\A[A-Za-z0-9_./*-]+\\z"));
  type == "array" and all(.[];
    (.name | test($uuid)) and (.roleName | type == "string") and (.roleType | type == "string")
    and (.permissions | type == "array" and all(.[]; (.actions | patterns) and (.notActions | patterns))))'
jq -e --arg role "$AKS_ROLE" '
  length == 1 and .[0].roleName == $role and .[0].roleType == "CustomRole"
' <<< "$AKS_ROLES" >/dev/null || drift "Erwartete AKS-Custom-Rolle fehlt oder ist nicht eindeutig."
AKS_ROLE_ID=$(jq -r '.[0].name' <<< "$AKS_ROLES")

# Azure-Aktionsnamen sind case-insensitive. Nur * ist als Wildcard zulässig.
# NotActions ziehen Rechte innerhalb desselben Berechtigungsblocks ab.
allows_action() {
  local action="${1,,}" block pattern actions not_actions
  local -a allowed excluded
  while IFS= read -r block; do
    actions=$(jq -r '.actions | join(" ") | ascii_downcase' <<< "$block") ||
      fail "Actions der AKS-Custom-Rolle konnten nicht ausgewertet werden."
    not_actions=$(jq -r '.notActions | join(" ") | ascii_downcase' <<< "$block") ||
      fail "NotActions der AKS-Custom-Rolle konnten nicht ausgewertet werden."
    read -r -a allowed <<< "$actions"
    read -r -a excluded <<< "$not_actions"
    for pattern in "${excluded[@]}"; do
      [[ "$action" == $pattern ]] && continue 2
    done
    for pattern in "${allowed[@]}"; do
      [[ "$action" == $pattern ]] && return 0
    done
  done <<< "$AKS_PERMISSIONS"
  return 1
}

AKS_PERMISSIONS=$(jq -c '.[0].permissions[]' <<< "$AKS_ROLES")
[[ -n "$AKS_PERMISSIONS" ]] || drift "Die AKS-Custom-Rolle hat keine Berechtigungen."
for action in \
  Microsoft.ContainerService/managedClusters/read \
  Microsoft.ContainerService/managedClusters/runCommand/action \
  Microsoft.ContainerService/managedClusters/commandResults/read; do
  allows_action "$action" || drift "Die AKS-Custom-Rolle erlaubt $action nicht."
done

# Aus vorhandenen Zuweisungen allein lässt sich kein vollständiges Urteil
# über effektiven Zugriff ableiten (z. B. Gruppen, Conditions, Deny Assignments).
check_assignment() {
  local label="$1" scope="$2" role_id="$3" assignments result
  assignments=$(read_cli "Abfrage der $label-Rollenzuweisungen" az role assignment list \
    --subscription "$SUBSCRIPTION_ID" --scope "$scope" --include-inherited \
    --assignee-object-id "$PRINCIPAL_ID" --fill-principal-name false \
    --fill-role-definition-name false -o json) || exit 2
  require_json "Antwort der $label-Rollenzuweisungen" "$assignments" --arg uuid "$UUID" '
    def role_id:
      startswith("/") and (ascii_downcase | split("/") |
        .[-4:-1] == ["providers", "microsoft.authorization", "roledefinitions"] and (last | test($uuid)));
    type == "array" and all(.[]; (.principalId | test($uuid))
      and (.roleDefinitionId | role_id)
      and (.scope | type == "string" and startswith("/"))
      and (.condition | type == "null" or type == "string"))'
  result=$(jq -r --arg scope "${scope,,}" --arg role "${role_id,,}" --arg principal "$PRINCIPAL_ID" '
    [.[] | select((.principalId | ascii_downcase) == $principal)
      | {scope: (.scope | ascii_downcase), role: (.roleDefinitionId | split("/") | last | ascii_downcase),
         unconditional: (.condition == null or .condition == "")}] as $assignments |
    if any($assignments[]; .scope == $scope and .role == $role and .unconditional)
      then "direct"
    else
      [$assignments[] | .scope as $parent | select($parent != $scope and
        ($parent == "/" or ($scope | startswith($parent + "/"))
          or ($parent | test("^/providers/microsoft[.]management/managementgroups/[^/]+$"))))] as $parents |
      if any($parents[]; .role == $role and .unconditional) then "inherited-role"
      elif ($parents | length > 0) then "inherited-other"
      else "missing" end
    end
  ' <<< "$assignments") || fail "Die $label-Rollenzuweisungen konnten nicht ausgewertet werden."
  case "$result" in
    direct) printf 'PASS: %s direkt am Ressourcen-Scope zugewiesen.\n' "$label"; return 0 ;;
    inherited-role) printf 'HINWEIS: %s ist als geerbte Zuweisung sichtbar.\n' "$label" ;;
    inherited-other) printf 'HINWEIS: Für %s sind andere oder bedingte geerbte Zuweisungen sichtbar.\n' "$label" ;;
  esac
  printf 'ABWEICHUNG: %s fehlt als unbedingte direkte Zuweisung am Ressourcen-Scope.\n' "$label" >&2
  return 1
}

rbac_valid=true
check_assignment AcrPush "$ACR_ID" "$ACR_PUSH_ROLE_ID" || rbac_valid=false
check_assignment "$AKS_ROLE" "$AKS_ID" "$AKS_ROLE_ID" || rbac_valid=false
[[ "$rbac_valid" == true ]] || exit 1

if [[ "${OLD_CLIENT_ID,,}" == "${CLIENT_ID,,}" ]]; then
  echo "PASS: GitHub AZURE_CLIENT_ID ist bereits aktuell."
  exit 0
fi
if [[ "$check" == true ]]; then
  drift "GitHub AZURE_CLIENT_ID fehlt oder muss aktualisiert werden."
fi

gh variable set AZURE_CLIENT_ID --repo "github.com/$REPO" --env "$ENVIRONMENT" \
  --body "$CLIENT_ID" >/dev/null 2>&1 ||
  fail "GitHub AZURE_CLIENT_ID konnte nicht bestätigt geschrieben werden. Aktuellen Wert mit --check prüfen."

SAVED_VAR=$(github_get "$VARIABLES/AZURE_CLIENT_ID" 2>/dev/null) ||
  fail "Rücklesen von AZURE_CLIENT_ID nach dem Schreibversuch fehlgeschlagen."
require_json "GitHub-Rückleseantwort nach dem Schreibversuch" "$SAVED_VAR" --arg uuid "$UUID" '
  .name == "AZURE_CLIENT_ID" and (.value | test($uuid))'
SAVED_CLIENT_ID=$(jq -r '.value' <<< "$SAVED_VAR")
[[ "${SAVED_CLIENT_ID,,}" == "${CLIENT_ID,,}" ]] ||
  fail "Rücklesewert von AZURE_CLIENT_ID weicht nach dem Schreibversuch ab."

echo "PASS: GitHub AZURE_CLIENT_ID aktualisiert und verifiziert."
