# Temporary backup storage for the LearningSteps migration.

# Private Endpoint only; public network access is disabled.
# Trusted Azure Services bypass is intentionally not enabled.
# Security exception: AVD-AZU-0010 (review if architecture changes).
#trivy:ignore:AVD-AZU-0010
resource "azurerm_storage_account" "maintenance_backup" {
  name                     = "stlstepsbackup305c3ba6"
  resource_group_name      = azurerm_resource_group.learningsteps.name
  location                 = azurerm_virtual_network.learningsteps.location
  account_tier             = "Standard"
  account_replication_type = "LRS"
  account_kind             = "StorageV2"
  access_tier              = "Hot"

  min_tls_version                 = "TLS1_2"
  https_traffic_only_enabled      = true
  public_network_access           = "Disabled"
  allow_nested_items_to_be_public = false
  shared_access_key_enabled       = false
  default_to_oauth_authentication = true
  local_user_enabled              = false

  network_rules {
    default_action = "Deny"
    bypass         = ["None"]
  }

  blob_properties {
    delete_retention_policy {
      days = 7
    }

    container_delete_retention_policy {
      days = 7
    }
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

# Private DNS for Azure Blob Storage.

resource "azurerm_private_dns_zone" "maintenance_blob" {
  name                = "privatelink.blob.core.windows.net"
  resource_group_name = azurerm_resource_group.learningsteps.name

  lifecycle {
    ignore_changes = [
      tags["created-on"]
    ]
  }
}

resource "azurerm_private_dns_zone_virtual_network_link" "maintenance_blob" {
  name                 = "maintenance-blob-vnet-link"
  private_dns_zone_id  = azurerm_private_dns_zone.maintenance_blob.id
  virtual_network_id   = azurerm_virtual_network.learningsteps.id
  registration_enabled = false

  lifecycle {
    ignore_changes = [
      tags["created-on"]
    ]
  }
}

# Private Endpoint in the existing private-endpoints subnet.

resource "azurerm_private_endpoint" "maintenance_blob" {
  name                = "pe-learningsteps-backup"
  location            = azurerm_virtual_network.learningsteps.location
  resource_group_name = azurerm_resource_group.learningsteps.name
  subnet_id           = azurerm_subnet.private_endpoints.id

  private_service_connection {
    name                           = "psc-learningsteps-backup"
    private_connection_resource_id = azurerm_storage_account.maintenance_backup.id
    subresource_names              = ["blob"]
    is_manual_connection           = false
  }

  private_dns_zone_group {
    name = "backup-blob-dns-group"
    private_dns_zone_ids = [
      azurerm_private_dns_zone.maintenance_blob.id
    ]
  }

  lifecycle {
    ignore_changes = [
      tags["created-on"]
    ]
  }
}
