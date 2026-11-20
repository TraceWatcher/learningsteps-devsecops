# Temporary LearningSteps database maintenance VM

resource "azurerm_network_interface" "maintenance" {
  name                = "nic-learningsteps-maintenance"
  location            = azurerm_virtual_network.learningsteps.location
  resource_group_name = azurerm_resource_group.learningsteps.name

  ip_configuration {
    name                          = "internal"
    subnet_id                     = azurerm_subnet.maintenance.id
    private_ip_address_allocation = "Dynamic"
  }

  tags = {
    project     = "LearningSteps"
    environment = "maintenance"
  }

  lifecycle {
    ignore_changes = [
      tags["created-on"]
    ]
  }
}

resource "azurerm_linux_virtual_machine" "maintenance" {
  name                = "learningsteps-maintenance"
  resource_group_name = azurerm_resource_group.learningsteps.name
  location            = azurerm_virtual_network.learningsteps.location

  size           = "Standard_D2s_v6"
  admin_username = "maintenance"

  network_interface_ids = [
    azurerm_network_interface.maintenance.id
  ]

  disable_password_authentication = true

  admin_ssh_key {
    username   = "maintenance"
    public_key = file(pathexpand("~/.ssh/azure_cloud_lab_ed25519.pub"))
  }

  identity {
    type = "SystemAssigned"
  }

  os_disk {
    caching              = "ReadWrite"
    storage_account_type = "StandardSSD_LRS"
  }

  source_image_reference {
    publisher = "Canonical"
    offer     = "0001-com-ubuntu-server-jammy"
    sku       = "22_04-lts-gen2"
    version   = "latest"
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

# Read PostgreSQL password from the existing Key Vault.

resource "azurerm_role_assignment" "maintenance_keyvault" {
  scope                = azurerm_key_vault.learningsteps.id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = azurerm_linux_virtual_machine.maintenance.identity[0].principal_id
  principal_type       = "ServicePrincipal"
}

# Upload backup objects using Microsoft Entra authentication.

resource "azurerm_role_assignment" "maintenance_backup" {
  scope                = azurerm_storage_account.maintenance_backup.id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = azurerm_linux_virtual_machine.maintenance.identity[0].principal_id
  principal_type       = "ServicePrincipal"
}
