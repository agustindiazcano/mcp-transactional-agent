resource "google_sql_database_instance" "main" {
  name             = "agentic-pg"
  database_version = "POSTGRES_16" # same major version as local (pgvector/pgvector:pg16)
  region           = var.region

  settings {
    edition           = "ENTERPRISE"  # PG16+ defaults to Enterprise Plus, which can't use shared-core tiers
    tier              = "db-f1-micro" # smallest shared-core tier, ~$8/month while running
    availability_type = "ZONAL"       # no standby replica (that would double the cost)
    disk_type         = "PD_HDD"
    disk_size         = 10
    disk_autoresize   = false

    ip_configuration {
      ipv4_enabled = true             # public IP, but with no authorized_networks...
      ssl_mode     = "ENCRYPTED_ONLY" # ...and unencrypted connections refused
    }

    backup_configuration {
      enabled = false # demo data: rebuildable with Alembic + seed scripts
    }
  }

  deletion_protection = true # Terraform refuses to destroy it until you flip this
}

resource "google_sql_database" "app" {
  name     = "agentic_engine" # same name as local, so only the URL changes
  instance = google_sql_database_instance.main.name
}

resource "random_password" "db_app" {
  length  = 32
  special = false # letters and digits only: safe inside DATABASE_URL without escaping
}

resource "google_sql_user" "app" {
  name     = "app"
  instance = google_sql_database_instance.main.name
  password = random_password.db_app.result
}