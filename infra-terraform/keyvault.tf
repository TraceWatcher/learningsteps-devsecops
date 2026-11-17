
data "azurerm_client_config" "current" {}

resource "azurerm_key_vault" "learningsteps" {
  name                = var.keyvault_name
  location            = var.workload_location
  resource_group_name = azurerm_resource_group.learningsteps.name

  tenant_id = data.azurerm_client_config.current.tenant_id
  sku_name  = "standard"

  rbac_authorization_enabled = true

  soft_delete_retention_days = 7
  purge_protection_enabled   = false

  # Disable public access to the Key Vault
  public_network_access_enabled = false

  # Deny unmatched network traffic
  network_acls {
    default_action = "Deny"
    bypass         = "None"
  }


  tags = {
    project     = "LearningSteps"
    environment = "dev"
    managed_by  = "terraform"
  }

  lifecycle {
    ignore_changes = [tags["created-on"]]
  }
}
