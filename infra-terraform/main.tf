resource "azurerm_resource_group" "learningsteps" {
  name     = var.resource_group_name
  location = var.location

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