# --- Migrate: one-shot `alembic upgrade head`, the cloud twin of compose's `migrate` service ---
resource "google_service_account" "migrate" {
  account_id   = "migrate-sa"
  display_name = "Migrate (one-shot Alembic job)"
}

resource "google_project_iam_member" "migrate_sql_client" {
  project = var.project_id
  role    = "roles/cloudsql.client"
  member  = "serviceAccount:${google_service_account.migrate.email}"
}

# Granted on this one secret, not project-wide: migrate-sa can read database-url and nothing else.
resource "google_secret_manager_secret_iam_member" "migrate_database_url" {
  secret_id = google_secret_manager_secret.database_url.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.migrate.email}"
}

resource "google_cloud_run_v2_job" "migrate" {
  name                = "migrate"
  location            = var.region
  deletion_protection = false # stateless: nothing is lost if Terraform replaces it

  template {
    task_count = 1

    template {
      service_account = google_service_account.migrate.email
      max_retries     = 0 # a failed migration should stop and be read, not retried blindly
      timeout         = "300s"

      containers {
        image   = "${var.region}-docker.pkg.dev/${var.project_id}/app-images/worker:b0e7dbe"
        command = ["alembic"]
        args    = ["upgrade", "head"]

        env {
          name = "DATABASE_URL"
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.database_url.secret_id
              version = "latest"
            }
          }
        }

        volume_mounts {
          name       = "cloudsql"
          mount_path = "/cloudsql" # where the ?host=/cloudsql/... in DATABASE_URL points
        }
      }

      volumes {
        name = "cloudsql"
        cloud_sql_instance {
          instances = [google_sql_database_instance.main.connection_name]
        }
      }
    }
  }

  # Cloud Run checks the SA can read the secret when the job is created, so grant access first.
  depends_on = [
    google_project_iam_member.migrate_sql_client,
    google_secret_manager_secret_iam_member.migrate_database_url,
  ]
}