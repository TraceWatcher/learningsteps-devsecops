resource "azurerm_user_assigned_identity" "github_operations" {
  name                = "id-learningsteps-github-operations"
  location            = var.workload_location
  resource_group_name = azurerm_resource_group.learningsteps.name

  tags = {
    project    = "LearningSteps"
    managed_by = "terraform"
  }

  lifecycle {
    ignore_changes = [tags["created-on"]]
  }
}

resource "azurerm_federated_identity_credential" "github_operations" {
  name                      = "fic-learningsteps-github-production-operations"
  user_assigned_identity_id = azurerm_user_assigned_identity.github_operations.id
  issuer                    = "https://token.actions.githubusercontent.com"
  subject                   = "repo:TraceWatcher@292215891/learningsteps-devsecops@1460727418:environment:production-operations"
  audience                  = ["api://AzureADTokenExchange"]
}

resource "azurerm_role_definition" "github_operations" {
  name              = "LearningSteps Environment Operator"
  scope             = azurerm_resource_group.learningsteps.id
  assignable_scopes = [azurerm_resource_group.learningsteps.id]
  description       = "Read and change power state of the LearningSteps environment resources"

  permissions {
    actions = [
      "Microsoft.ContainerService/managedClusters/read",
      "Microsoft.ContainerService/managedClusters/start/action",
      "Microsoft.ContainerService/managedClusters/stop/action",
      "Microsoft.DBforPostgreSQL/flexibleServers/read",
      "Microsoft.DBforPostgreSQL/flexibleServers/start/action",
      "Microsoft.DBforPostgreSQL/flexibleServers/stop/action",
      "Microsoft.Compute/virtualMachines/instanceView/read",
      "Microsoft.Compute/virtualMachines/deallocate/action",
    ]
  }
}

resource "azurerm_role_assignment" "github_operations" {
  for_each = {
    aks         = azurerm_kubernetes_cluster.learningsteps.id
    postgres    = azurerm_postgresql_flexible_server.learningsteps.id
    maintenance = azurerm_linux_virtual_machine.maintenance.id
  }

  scope              = each.value
  role_definition_id = azurerm_role_definition.github_operations.role_definition_resource_id
  principal_id       = azurerm_user_assigned_identity.github_operations.principal_id
  principal_type     = "ServicePrincipal"
}

output "github_operations_client_id" {
  value = azurerm_user_assigned_identity.github_operations.client_id
}

output "github_operations_tenant_id" {
  value = azurerm_user_assigned_identity.github_operations.tenant_id
}

output "github_operations_postgres_server_name" {
  value = azurerm_postgresql_flexible_server.learningsteps.name
}
