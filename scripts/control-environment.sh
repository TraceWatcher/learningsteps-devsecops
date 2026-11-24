#!/usr/bin/env bash
set -euo pipefail

: "${RG:?}" "${AKS:?}" "${POSTGRES:?}" "${VM:?}" "${AZURE_SUBSCRIPTION_ID:?}" "${ACTION:?}"
poll_timeout="${POLL_TIMEOUT_SECONDS:-600}"
poll_interval="${POLL_INTERVAL_SECONDS:-15}"

fail() {
  printf '::error::%s\n' "$1" >&2
  exit 1
}

[[ "$poll_timeout" =~ ^[1-9][0-9]{0,3}$ && "$poll_interval" =~ ^(0|[1-9][0-9]{0,3})$ ]] ||
  fail "Ungültige Polling-Konfiguration."
[[ "$POSTGRES" =~ ^[a-z0-9][a-z0-9-]{1,61}[a-z0-9]$ ]] ||
  fail "Ungültiger PostgreSQL-Servername."

azure() {
  timeout --kill-after=5s "${request_timeout:-60}s" az "$@" --subscription "$AZURE_SUBSCRIPTION_ID"
}

aks_state() {
  azure aks show -g "$RG" -n "$AKS" --query '{power:powerState.code,provisioning:provisioningState}' -o json |
    jq -er 'select((.power | type == "string") and (.provisioning | type == "string"))
      | if .provisioning == "Succeeded" then .power else .provisioning end'
}

pg_state() {
  azure postgres flexible-server show -g "$RG" -n "$POSTGRES" --query state -o tsv
}

vm_state() {
  # Query the VM subresource without expanding the VM document itself.
  local vm_id="/subscriptions/$AZURE_SUBSCRIPTION_ID/resourceGroups/$RG/providers/Microsoft.Compute/virtualMachines/$VM"
  azure rest --method get --url "https://management.azure.com$vm_id/instanceView?api-version=2025-11-01" \
    --query "statuses[?starts_with(code, 'PowerState/')].code | [0]" -o tsv
}

read_state() {
  local reader="$1" state
  state=$("$reader") || fail "Statusabfrage für $reader fehlgeschlagen (Exit-Code $?)."
  [[ -n "$state" && "$state" != None && "$state" != null ]] ||
    fail "Statusabfrage für $reader lieferte keinen Status."
  printf '%s\n' "$state"
}

wait_for_state() {
  local reader="$1" target="$2" state remaining delay request_timeout position=0
  shift 2
  # Azure reads may repeat the current state or skip intermediate states.
  # Regressions and states outside this operation's path fail immediately.
  local -a states=("$@" "$target")
  local deadline=$((SECONDS + poll_timeout))
  while (( (remaining = deadline - SECONDS) > 0 )); do
    request_timeout=$((remaining < 60 ? remaining : 60))
    state=$(read_state "$reader") || exit 1
    [[ "$state" != "$target" ]] || return 0

    while (( position < ${#states[@]} )) && [[ "$state" != "${states[position]}" ]]; do
      (( position += 1 ))
    done
    (( position < ${#states[@]} )) ||
      fail "$reader meldet unerwarteten Status $state beim Warten auf $target."

    remaining=$((deadline - SECONDS))
    delay=$((remaining < poll_interval ? remaining : poll_interval))
    if (( delay > 0 )); then
      sleep "$delay"
    fi
  done
  fail "Timeout für $reader beim Warten auf $target."
}

show_status() {
  local aks pg vm
  aks=$(read_state aks_state) || exit 1
  pg=$(read_state pg_state) || exit 1
  vm=$(read_state vm_state) || exit 1
  printf '=== LearningSteps Environment ===\nAKS:        %s\nPostgreSQL: %s\nVM:         %s\n' "$aks" "$pg" "$vm"
}

change_state() {
  local reader="$1" state="$2" from="$3" target="$4" intermediate="$5"
  shift 5
  [[ "$state" != "$target" ]] || return 0
  [[ "$state" == "$from" ]] || fail "Unerwarteter Status für $reader: $state."
  azure "$@" --no-wait -o none ||
    fail "Azure-Operation für $reader auf $target fehlgeschlagen (Exit-Code $?)."
  wait_for_state "$reader" "$target" "$from" "$intermediate"
}

case "$ACTION" in
  status)
    show_status
    ;;
  start|stop)
    if [[ "$ACTION" == stop && "${CONFIRM_STOP:-}" != STOP ]]; then
      fail "Zum Stoppen muss STOP bestätigt werden."
    fi

    # Verify that all reads work before changing the first resource.
    aks=$(read_state aks_state) || exit 1
    pg=$(read_state pg_state) || exit 1
    vm=$(read_state vm_state) || exit 1
    [[ "$aks" == Running || "$aks" == Stopped ]] || fail "Unerwarteter AKS-Status: $aks."
    [[ "$pg" == Ready || "$pg" == Stopped ]] || fail "Unerwarteter PostgreSQL-Status: $pg."

    if [[ "$ACTION" == start ]]; then
      change_state pg_state "$pg" Stopped Ready Starting postgres flexible-server start -g "$RG" -n "$POSTGRES"
      change_state aks_state "$aks" Stopped Running Starting aks start -g "$RG" -n "$AKS"
    else
      case "$vm" in
        PowerState/running|PowerState/stopped|PowerState/deallocating|PowerState/deallocated) ;;
        *) fail "Unerwarteter VM-Status: $vm." ;;
      esac
      change_state aks_state "$aks" Running Stopped Stopping aks stop -g "$RG" -n "$AKS"
      change_state pg_state "$pg" Ready Stopped Stopping postgres flexible-server stop -g "$RG" -n "$POSTGRES"
      if [[ "$vm" != PowerState/deallocated ]]; then
        if [[ "$vm" != PowerState/deallocating ]]; then
          azure vm deallocate -g "$RG" -n "$VM" --no-wait -o none ||
            fail "Deallokation der VM fehlgeschlagen (Exit-Code $?)."
        fi
        case "$vm" in
          PowerState/running)
            wait_for_state vm_state PowerState/deallocated \
              PowerState/running PowerState/stopping PowerState/stopped PowerState/deallocating
            ;;
          PowerState/stopped)
            wait_for_state vm_state PowerState/deallocated PowerState/stopped PowerState/deallocating
            ;;
          PowerState/deallocating)
            wait_for_state vm_state PowerState/deallocated PowerState/deallocating
            ;;
        esac
      fi
    fi
    show_status
    ;;
  *)
    fail "Unbekannte Aktion: $ACTION."
    ;;
esac
