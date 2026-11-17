
# Identity used only by the LearningSteps application
resource "azurerm_user_assigned_identity" "learningsteps_api" {
  name                = "id-learningsteps-api"
  resource_group_name = azurerm_resource_group.learningsteps.name
  location            = var.workload_location

  lifecycle {
    ignore_changes = [tags["created-on"]]
  }
}

# Allow reading secrets from our Key Vault
resource "azurerm_role_assignment" "api_keyvault_reader" {
  scope                = azurerm_key_vault.learningsteps.id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = azurerm_user_assigned_identity.learningsteps_api.principal_id
  principal_type       = "ServicePrincipal"
}

# Trust a specific Kubernetes ServiceAccount

resource "azurerm_federated_identity_credential" "learningsteps_api" {
  name = "fic-learningsteps-api"

  user_assigned_identity_id = azurerm_user_assigned_identity.learningsteps_api.id

  issuer  = azurerm_kubernetes_cluster.learningsteps.oidc_issuer_url
  subject = "system:serviceaccount:learningsteps:learningsteps-api"

  audience = ["api://AzureADTokenExchange"]
}


output "learningsteps_api_client_id" {
  value = azurerm_user_assigned_identity.learningsteps_api.client_id
}

output "keyvault_tenant_id" {
  value = data.azurerm_client_config.current.tenant_id
}
