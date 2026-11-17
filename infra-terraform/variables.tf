
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