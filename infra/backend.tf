terraform {
  backend "gcs" {
    bucket = "project-e0ad10c9-0b2f-4dc0-ac6-tfstate"
    prefix = "terraform/state"
  }
}