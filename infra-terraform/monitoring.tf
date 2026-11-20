resource "azurerm_log_analytics_workspace" "learningsteps" {
  name                = "log-learningsteps"
  location            = "westeurope"
  resource_group_name = azurerm_resource_group.learningsteps.name

  sku               = "PerGB2018"
  retention_in_days = 30
  daily_quota_gb    = 0.1

  tags = {
    project     = "LearningSteps"
    environment = "monitoring"
    managed_by  = "terraform"
  }

  lifecycle {
    ignore_changes = [tags["created-on"]]
  }
}

output "learningsteps_log_analytics_workspace_id" {
  value = azurerm_log_analytics_workspace.learningsteps.id
}

# Azure Monitor – Container Insights
# Data Collection Rule (DCR)

resource "azurerm_monitor_data_collection_rule" "aks_monitoring" {
  name                = "MSCI-${azurerm_kubernetes_cluster.learningsteps.name}"
  resource_group_name = azurerm_kubernetes_cluster.learningsteps.resource_group_name
  location            = azurerm_log_analytics_workspace.learningsteps.location

  description = "Container Insights monitoring for LearningSteps AKS"

  destinations {
    log_analytics {
      workspace_resource_id = azurerm_log_analytics_workspace.learningsteps.id
      name                  = "learningsteps-logs"
    }
  }

  data_flow {
    streams = [
      "Microsoft-ContainerLogV2",
      "Microsoft-KubePodInventory",
      "Microsoft-InsightsMetrics"
    ]

    destinations = ["learningsteps-logs"]
  }

  data_sources {
    extension {
      name           = "ContainerInsightsExtension"
      extension_name = "ContainerInsights"

      streams = [
        "Microsoft-ContainerLogV2",
        "Microsoft-KubePodInventory",
        "Microsoft-InsightsMetrics"
      ]

      extension_json = jsonencode({
        dataCollectionSettings = {
          interval               = "1m"
          namespaceFilteringMode = "Off"
          namespaces             = []
          enableContainerLogV2   = true
        }
      })
    }
  }

  tags = {
    environment = "dev"
    managed_by  = "terraform"
    project     = "LearningSteps"
  }

  lifecycle {
    ignore_changes = [
      tags["created-on"]
    ]
  }
}

# DCR Association – AKS mit Datensammlungsregel verbinden

resource "azurerm_monitor_data_collection_rule_association" "aks_monitoring" {
  name                    = "ContainerInsightsExtension"
  target_resource_id      = azurerm_kubernetes_cluster.learningsteps.id
  data_collection_rule_id = azurerm_monitor_data_collection_rule.aks_monitoring.id

  description = "Connect LearningSteps AKS to Container Insights DCR"
}