# SECURITY TEST ONLY
# Intentionally insecure configuration.
# Never apply this Terraform resource.

resource "azurerm_network_security_group" "security_gate_test" {
  name                = "nsg-security-gate-test"
  location            = "westeurope"
  resource_group_name = "rg-learningsteps-devsecops"

  security_rule {
    name                       = "allow-ssh-from-internet"
    priority                   = 100
    direction                  = "Inbound"
    access                     = "Allow"
    protocol                   = "Tcp"
    source_port_range          = "*"
    destination_port_range     = "22"
    source_address_prefix      = "*"
    destination_address_prefix = "*"
  }
}
