resource "google_secret_manager_secret" "database_url" {
  secret_id = "database-url"

  replication {
    auto {}
  }
}

resource "google_secret_manager_secret_version" "database_url" {
  secret = google_secret_manager_secret.database_url.id
  secret_data = join("", [
    "postgresql+asyncpg://${google_sql_user.app.name}:${random_password.db_app.result}",
    "@/${google_sql_database.app.name}",
    "?host=/cloudsql/${google_sql_database_instance.main.connection_name}",
  ])
}

# External secrets: Terraform owns the container, the value is added by hand
# with gcloud (7c), so it never enters the Terraform state.
locals {
  manual_secrets = toset([
    "rabbitmq-url",     # created by hand in step 5, imported below
    "groq-api-key",     # worker: Judge 2 + Prompt Guard
    "mcp-client-token", # worker: bearer token for the MCP server
    "mcp-clients-json", # mcp_server: client registry (token hash + allowed tools)
  ])
}

resource "google_secret_manager_secret" "manual" {
  for_each  = local.manual_secrets
  secret_id = each.value

  replication {
    auto {}
  }
}

# rabbitmq-url already exists: adopt it instead of creating it again.
import {
  to = google_secret_manager_secret.manual["rabbitmq-url"]
  id = "projects/${var.project_id}/secrets/rabbitmq-url"
}