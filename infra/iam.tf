resource "google_service_account" "worker" {
  account_id   = "worker-sa"
  display_name = "Worker (RabbitMQ consumer, judges, refunds)"
}

resource "google_project_iam_member" "worker" {
  for_each = toset([
    "roles/aiplatform.user",
    "roles/secretmanager.secretAccessor",
    "roles/cloudsql.client",
  ])

  project = var.project_id
  role    = each.value
  member  = "serviceAccount:${google_service_account.worker.email}"
}

moved {
  from = google_project_iam_member.worker_vertex
  to   = google_project_iam_member.worker["roles/aiplatform.user"]
}