# Temporary subnet for LearningSteps database maintenance.
# No VM or public IP is created in this step.

resource "azurerm_subnet" "maintenance" {
  name                 = "snet-maintenance"
  resource_group_name  = azurerm_resource_group.learningsteps.name
  virtual_network_name = azurerm_virtual_network.learningsteps.name

  address_prefixes = ["10.30.4.0/27"]
}

# NSG dedicated to the temporary maintenance subnet.
resource "azurerm_network_security_group" "maintenance" {
  name                = "nsg-learningsteps-maintenance"
  location            = azurerm_virtual_network.learningsteps.location
  resource_group_name = azurerm_resource_group.learningsteps.name

  security_rule {
    name                       = "DenyAllInbound"
    priority                   = 100
    direction                  = "Inbound"
    access                     = "Deny"
    protocol                   = "*"
    source_port_range          = "*"
    destination_port_range     = "*"
    source_address_prefix      = "*"
    destination_address_prefix = "*"
  }

  tags = {
    project     = "LearningSteps"
    environment = "maintenance"
    managed_by  = "terraform"
  }

  lifecycle {
    ignore_changes = [
      tags["created-on"]
    ]
  }
}

# Attach the NSG to the maintenance subnet.
resource "azurerm_subnet_network_security_group_association" "maintenance" {
  subnet_id                 = azurerm_subnet.maintenance.id
  network_security_group_id = azurerm_network_security_group.maintenance.id
}
