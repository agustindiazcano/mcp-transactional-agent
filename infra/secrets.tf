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