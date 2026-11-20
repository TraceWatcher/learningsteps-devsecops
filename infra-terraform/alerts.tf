resource "azurerm_monitor_scheduled_query_rules_alert_v2" "api_availability" {
  name                = "alert-learningsteps-api-availability"
  resource_group_name = azurerm_resource_group.learningsteps.name
  location            = azurerm_log_analytics_workspace.learningsteps.location

  scopes = [
    azurerm_log_analytics_workspace.learningsteps.id
  ]

  description = "Detect missing LearningSteps API containers or AKS inventory telemetry."

  severity             = 2
  enabled              = false
  evaluation_frequency = "PT5M"
  window_duration      = "PT15M"

  auto_mitigation_enabled = true

  criteria {
    query = <<-KQL
      KubePodInventory
      | where TimeGenerated > ago(10m)
      | summarize arg_max(TimeGenerated, *) by PodUid, ContainerName
      | summarize
          InventoryContainers = count(),
          RunningAPI = countif(
              Namespace == "learningsteps"
              and Name startswith "learningsteps-api-"
              and ContainerStatus == "running"
          )
      | extend AlertValue = case(
          InventoryContainers == 0, 2,
          RunningAPI == 0, 1,
          0
      )
      | project AlertValue
    KQL

    time_aggregation_method = "Maximum"
    metric_measure_column   = "AlertValue"
    operator                = "GreaterThan"
    threshold               = 0
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