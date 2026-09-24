# --- Ingest knowledge base: one-shot `python -m scripts.ingest_knowledge_base` ---
# Chunks docs/policies/refund_policy.md (shipped in the worker image), embeds it
# on Vertex and writes it to knowledge_base. Re-running replaces the document's
# chunks instead of duplicating them, so a failed run can simply be re-executed.
resource "google_service_account" "ingest_kb" {
  account_id   = "ingest-kb-sa"
  display_name = "Ingest knowledge base (one-shot RAG ingestion job)"
}

resource "google_project_iam_member" "ingest_kb" {
  for_each = toset([
    "roles/aiplatform.user", # Vertex embeddings
    "roles/cloudsql.client",
  ])

  project = var.project_id
  role    = each.value
  member  = "serviceAccount:${google_service_account.ingest_kb.email}"
}

resource "google_cloud_run_v2_job" "ingest_kb" {
  name                = "ingest-knowledge-base"
  location            = var.region
  deletion_protection = false # stateless: nothing is lost if Terraform replaces it

  template {
    task_count = 1

    template {
      service_account = google_service_account.ingest_kb.email
      max_retries     = 0 # a failure should be read, not retried blindly (each run costs embedding calls)
      timeout         = "300s"

      containers {
        # 76a4ae5: first commit whose ingestion replaces chunks instead of duplicating them.
        image   = "${var.region}-docker.pkg.dev/${var.project_id}/app-images/worker:76a4ae5"
        command = ["python"]
        args    = ["-m", "scripts.ingest_knowledge_base"]

        env {
          name  = "LLM_PROVIDER"
          value = "vertex" # embeddings on Vertex through the service account, no API key
        }
        env {
          name  = "VERTEX_PROJECT"
          value = var.project_id # no gcloud config inside the container to resolve it from
        }
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
    google_project_iam_member.ingest_kb,
    google_secret_manager_secret_iam_member.readers,
  ]
}
