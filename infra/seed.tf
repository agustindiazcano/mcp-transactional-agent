# --- Seed orders: one-shot `python -m scripts.seed_orders`, the sample orders the demo claims use ---
# Its own SA, even though migrate-sa has the same rights: each job's access is
# granted and revoked on its own, and the audit logs name the job that acted.
resource "google_service_account" "seed_orders" {
  account_id   = "seed-orders-sa"
  display_name = "Seed orders (one-shot sample data job)"
}

resource "google_project_iam_member" "seed_orders_sql_client" {
  project = var.project_id
  role    = "roles/cloudsql.client"
  member  = "serviceAccount:${google_service_account.seed_orders.email}"
}

resource "google_cloud_run_v2_job" "seed_orders" {
  name                = "seed-orders"
  location            = var.region
  deletion_protection = false # stateless: nothing is lost if Terraform replaces it

  template {
    task_count = 1

    template {
      service_account = google_service_account.seed_orders.email
      max_retries     = 0 # the script is idempotent, but a failure should be read, not retried blindly
      timeout         = "120s"

      containers {
        image   = "${var.region}-docker.pkg.dev/${var.project_id}/app-images/worker:813aa8a"
        command = ["python"]
        args    = ["-m", "scripts.seed_orders"]

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
    google_project_iam_member.seed_orders_sql_client,
    google_secret_manager_secret_iam_member.readers,
  ]
}
