# Dedicated identity for GitHub Actions releases
resource "azurerm_user_assigned_identity" "github_actions" {
  name                = "id-learningsteps-github"
  location            = var.workload_location
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

# Trust the GitHub production environment
resource "azurerm_federated_identity_credential" "github_actions" {
  name = "fic-learningsteps-github-production"

  user_assigned_identity_id = azurerm_user_assigned_identity.github_actions.id

  issuer = "https://token.actions.githubusercontent.com"

  subject = "repo:TraceWatcher@292215891/learningsteps-devsecops@1460727418:environment:production"

  audience = ["api://AzureADTokenExchange"]
}

# Allow GitHub Actions to push images to ACR
resource "azurerm_role_assignment" "github_acr_push" {
  scope                = azurerm_container_registry.learningsteps.id
  role_definition_name = "AcrPush"
  principal_id         = azurerm_user_assigned_identity.github_actions.principal_id
  principal_type       = "ServicePrincipal"
}

# Custom Azure role for AKS Run Command
resource "azurerm_role_definition" "github_aks_deployer" {
  name        = "LearningSteps AKS Command Deployer"
  scope       = azurerm_resource_group.learningsteps.id
  description = "Allows GitHub Actions to invoke commands on AKS"

  permissions {
    actions = [
      "Microsoft.ContainerService/managedClusters/read",
      "Microsoft.ContainerService/managedClusters/runCommand/action",
      "Microsoft.ContainerService/managedClusters/commandResults/read"
    ]

    not_actions = []
  }

  assignable_scopes = [
    azurerm_resource_group.learningsteps.id
  ]
}

# Assign the role only to our AKS cluster
resource "azurerm_role_assignment" "github_aks_deployer" {
  scope              = azurerm_kubernetes_cluster.learningsteps.id
  role_definition_id = azurerm_role_definition.github_aks_deployer.role_definition_resource_id
  principal_id       = azurerm_user_assigned_identity.github_actions.principal_id
  principal_type     = "ServicePrincipal"
}

# Non-secret identifiers for GitHub OIDC
output "github_actions_client_id" {
  value = azurerm_user_assigned_identity.github_actions.client_id
}

output "github_actions_tenant_id" {
  value = azurerm_user_assigned_identity.github_actions.tenant_id
}
