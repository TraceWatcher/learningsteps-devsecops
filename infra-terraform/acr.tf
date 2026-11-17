resource "azurerm_container_registry" "learningsteps" {
  name                = var.acr_name
  resource_group_name = azurerm_resource_group.learningsteps.name
  location            = azurerm_resource_group.learningsteps.location

  sku           = "Basic"
  admin_enabled = false

  tags = {
    project     = "LearningSteps"
    environment = "dev"
    managed_by  = "terraform"
  }

  lifecycle {
    ignore_changes = [
      tags["created-on"]
    ]
  }
}