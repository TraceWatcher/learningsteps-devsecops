# Dedicated subnet for private endpoints
resource "azurerm_subnet" "private_endpoints" {
  name                 = "snet-private-endpoints"
  resource_group_name  = azurerm_resource_group.learningsteps.name
  virtual_network_name = azurerm_virtual_network.learningsteps.name
  address_prefixes     = ["10.30.3.0/24"]
}

# Private DNS for Azure Key Vault
resource "azurerm_private_dns_zone" "keyvault" {
  name                = "privatelink.vaultcore.azure.net"
  resource_group_name = azurerm_resource_group.learningsteps.name

  lifecycle {
    ignore_changes = [tags["created-on"]]
  }
}

# Connect DNS zone to AKS virtual network
resource "azurerm_private_dns_zone_virtual_network_link" "keyvault" {
  name                 = "keyvault-vnet-link"
  private_dns_zone_id  = azurerm_private_dns_zone.keyvault.id
  virtual_network_id   = azurerm_virtual_network.learningsteps.id
  registration_enabled = false

  lifecycle {
    ignore_changes = [tags["created-on"]]
  }
}

# Private endpoint for Key Vault
resource "azurerm_private_endpoint" "keyvault" {
  name                = "pe-learningsteps-keyvault"
  location            = var.workload_location
  resource_group_name = azurerm_resource_group.learningsteps.name
  subnet_id           = azurerm_subnet.private_endpoints.id

  private_service_connection {
    name                           = "psc-learningsteps-keyvault"
    private_connection_resource_id = azurerm_key_vault.learningsteps.id
    subresource_names              = ["vault"]
    is_manual_connection           = false
  }

  private_dns_zone_group {
    name                 = "keyvault-dns-group"
    private_dns_zone_ids = [azurerm_private_dns_zone.keyvault.id]
  }

  lifecycle {
    ignore_changes = [tags["created-on"]]
  }
}
