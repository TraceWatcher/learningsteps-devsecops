
resource "azurerm_user_assigned_identity" "aks" {
  name                = "id-learningsteps-aks"
  resource_group_name = azurerm_resource_group.learningsteps.name
  location            = var.workload_location

  lifecycle {
    ignore_changes = [
      tags["created-on"]
    ]
  }
}

resource "azurerm_role_assignment" "aks_network" {
  scope                = azurerm_subnet.aks.id
  role_definition_name = "Network Contributor"
  principal_id         = azurerm_user_assigned_identity.aks.principal_id
}

resource "azurerm_kubernetes_cluster" "learningsteps" {
  node_provisioning_profile {
    mode = "Manual"
  }
  name                = "aks-learningsteps"
  location            = var.workload_location
  resource_group_name = azurerm_resource_group.learningsteps.name
  dns_prefix          = "learningsteps"

  sku_tier = "Free"

  default_node_pool {
    name            = "system"
    node_count      = 2
    vm_size         = var.aks_node_vm_size
    vnet_subnet_id  = azurerm_subnet.aks.id
    os_disk_size_gb = 64

    upgrade_settings {
      max_surge                     = "10%"
      drain_timeout_in_minutes      = 0
      node_soak_duration_in_minutes = 0
    }
  }

  lifecycle {
    ignore_changes = [
      tags["created-on"]
    ]
  }

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.aks.id]
  }

  network_profile {
    network_plugin      = "azure"
    network_plugin_mode = "overlay"
    network_policy      = "cilium"
    network_data_plane  = "cilium"

    pod_cidr       = "10.244.0.0/16"
    service_cidr   = "10.31.0.0/16"
    dns_service_ip = "10.31.0.10"

    load_balancer_sku = "standard"
  }

  oidc_issuer_enabled       = true
  workload_identity_enabled = true

  key_vault_secrets_provider {
    secret_rotation_enabled = true
  }

  tags = {
    project     = "LearningSteps"
    environment = "dev"
    managed_by  = "terraform"
  }

  depends_on = [
    azurerm_role_assignment.aks_network
  ]
}

# Allow AKS kubelet identity to pull images from ACR
resource "azurerm_role_assignment" "aks_acr_pull" {
  scope                = azurerm_container_registry.learningsteps.id
  role_definition_name = "AcrPull"

  principal_id = azurerm_kubernetes_cluster.learningsteps.kubelet_identity[0].object_id

  principal_type = "ServicePrincipal"
}
