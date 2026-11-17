
terraform {
  backend "azurerm" {
    resource_group_name  = "rg-learningsteps-tfstate"
    storage_account_name = "stlearningsteps6f83874f"
    container_name       = "tfstate"
    key                  = "learningsteps.terraform.tfstate"

    use_cli          = true
    use_azuread_auth = true
  }
}
