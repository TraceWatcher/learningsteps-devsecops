
# Virtual Network
resource "azurerm_virtual_network" "learningsteps" {
  name                = "vnet-learningsteps-weu"
  location            = var.workload_location
  resource_group_name = azurerm_resource_group.learningsteps.name
  address_space       = ["10.30.0.0/16"]

  tags = {
    project     = "LearningSteps"
    environment = "dev"
    managed_by  = "terraform"
  }

  lifecycle {
    ignore_changes = [tags["created-on"]]
  }
}

# AKS Subnet
resource "azurerm_subnet" "aks" {
  name                 = "snet-aks"
  resource_group_name  = azurerm_resource_group.learningsteps.name
  virtual_network_name = azurerm_virtual_network.learningsteps.name
  address_prefixes     = ["10.30.1.0/24"]
}

# PostgreSQL Subnet
resource "azurerm_subnet" "postgres" {
  name                 = "snet-postgres"
  resource_group_name  = azurerm_resource_group.learningsteps.name
  virtual_network_name = azurerm_virtual_network.learningsteps.name
  address_prefixes     = ["10.30.2.0/24"]

  delegation {
    name = "postgres-delegation"

    service_delegation {
      name = "Microsoft.DBforPostgreSQL/flexibleServers"

      actions = [
        "Microsoft.Network/virtualNetworks/subnets/join/action"
      ]
    }
  }
}

# Private DNS for PostgreSQL
resource "azurerm_private_dns_zone" "postgres" {
  name                = "learningsteps.postgres.database.azure.com"
  resource_group_name = azurerm_resource_group.learningsteps.name

  tags = {
    project     = "LearningSteps"
    environment = "dev"
    managed_by  = "terraform"
  }

  lifecycle {
    ignore_changes = [tags["created-on"]]
  }
}

# Link DNS zone to VNet
resource "azurerm_private_dns_zone_virtual_network_link" "postgres" {
  name                = "postgres-vnet-link"
  private_dns_zone_id = azurerm_private_dns_zone.postgres.id
  virtual_network_id  = azurerm_virtual_network.learningsteps.id

  registration_enabled = false

  tags = {
    project     = "LearningSteps"
    environment = "dev"
    managed_by  = "terraform"
  }

  lifecycle {
    ignore_changes = [tags["created-on"]]
  }
}