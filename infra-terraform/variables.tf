
variable "subscription_id" {
  description = "Azure Subscription ID"
  type        = string
}

variable "location" {
  description = "Azure Region"
  type        = string
  default     = "germanywestcentral"
}

variable "resource_group_name" {
  description = "Resource Group for LearningSteps"
  type        = string
  default     = "rg-learningsteps-devsecops"
}

variable "acr_name" {
  description = "Globally unique Azure Container Registry name"
  type        = string
}

variable "postgres_server_name" {
  description = "Globally unique PostgreSQL Flexible Server name"
  type        = string
}

variable "db_admin_password" {
  description = "PostgreSQL administrator password"
  type        = string
  sensitive   = true
}

variable "workload_location" {
  description = "Azure region for AKS and PostgreSQL"
  type        = string
  default     = "westeurope"
}

variable "keyvault_name" {
  description = "Globally unique Azure Key Vault name"
  type        = string
}

variable "aks_node_vm_size" {
  description = "VM size for the AKS system node pool"
  type        = string
}