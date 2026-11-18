
# Azure OpenAI account for LearningSteps
resource "azurerm_cognitive_account" "learningsteps_ai" {
  name                  = "oai-learningsteps-305c3ba6"
  location              = "westeurope"
  resource_group_name   = azurerm_resource_group.learningsteps.name
  kind                  = "OpenAI"
  sku_name              = "S0"
  custom_subdomain_name = "oai-learningsteps-305c3ba6"

  # Microsoft Entra ID only - disable API key authentication
  local_auth_enabled = false

  # Initial connectivity through the public endpoint.
  # Authentication is still required.
  public_network_access_enabled = true

  tags = {
    project     = "LearningSteps"
    environment = "dev"
    managed_by  = "terraform"
  }

  lifecycle {
    ignore_changes = [tags["created-on"]]
  }
}

# GPT-4.1-mini deployment
resource "azurerm_cognitive_deployment" "learningsteps_summary" {
  name                 = "learningsteps-summary"
  cognitive_account_id = azurerm_cognitive_account.learningsteps_ai.id

  model {
    format  = "OpenAI"
    name    = "gpt-4.1-mini"
    version = "2025-04-14"
  }

  sku {
    name     = "Standard"
    capacity = 1
  }
}

# Allow the existing AKS API identity to call the model
resource "azurerm_role_assignment" "api_openai_user" {
  scope                = azurerm_cognitive_account.learningsteps_ai.id
  role_definition_name = "Cognitive Services OpenAI User"

  principal_id   = azurerm_user_assigned_identity.learningsteps_api.principal_id
  principal_type = "ServicePrincipal"
}

# Non-secret deployment information
output "learningsteps_ai_endpoint" {
  value = azurerm_cognitive_account.learningsteps_ai.endpoint
}

output "learningsteps_ai_deployment" {
  value = azurerm_cognitive_deployment.learningsteps_summary.name
}
