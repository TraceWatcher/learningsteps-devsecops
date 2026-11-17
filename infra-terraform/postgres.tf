
resource "azurerm_postgresql_flexible_server" "learningsteps" {
  name                = var.postgres_server_name
  resource_group_name = azurerm_resource_group.learningsteps.name
  location            = var.workload_location

  version = "16"

  administrator_login    = "lsadmin"
  administrator_password = var.db_admin_password

  delegated_subnet_id = azurerm_subnet.postgres.id
  private_dns_zone_id = azurerm_private_dns_zone.postgres.id

  public_network_access_enabled = false

  sku_name              = "B_Standard_B1ms"
  storage_mb            = 32768
  backup_retention_days = 7

  tags = {
    project     = "LearningSteps"
    environment = "dev"
    managed_by  = "terraform"
  }

  lifecycle {
    ignore_changes = [
      tags["created-on"],
      zone
    ]
  }

  depends_on = [
    azurerm_private_dns_zone_virtual_network_link.postgres
  ]
}

resource "azurerm_postgresql_flexible_server_database" "learningsteps" {
  name      = "learning_journal"
  server_id = azurerm_postgresql_flexible_server.learningsteps.id

  charset   = "UTF8"
  collation = "en_US.utf8"
}
