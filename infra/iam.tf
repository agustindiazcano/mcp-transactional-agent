resource "google_service_account" "worker" {
  account_id   = "worker-sa"
  display_name = "Worker (RabbitMQ consumer, judges, refunds)"
}

resource "google_project_iam_member" "worker" {
  for_each = toset([
    "roles/aiplatform.user",
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

# --- Gateway: publishes claims to the broker, reads transactions from the DB ---
resource "google_service_account" "gateway" {
  account_id   = "gateway-sa"
  display_name = "Gateway (FastAPI ingestion and read API)"
}

resource "google_project_iam_member" "gateway" {
  for_each = toset([
    "roles/cloudsql.client",
  ])

  project = var.project_id
  role    = each.value
  member  = "serviceAccount:${google_service_account.gateway.email}"
}

# --- MCP server: runs the tools, writes refunds and audit rows to the DB ---
resource "google_service_account" "mcp_server" {
  account_id   = "mcp-server-sa"
  display_name = "MCP server (tool boundary)"
}

resource "google_project_iam_member" "mcp_server" {
  for_each = toset([
    "roles/cloudsql.client",
  ])

  project = var.project_id
  role    = each.value
  member  = "serviceAccount:${google_service_account.mcp_server.email}"
}

# --- Dashboard: only calls the gateway over HTTP, so it gets no roles at all.
# It still needs its own SA: without one, Cloud Run would run it as the
# default Compute SA, which has Editor on the whole project.
resource "google_service_account" "dashboard" {
  account_id   = "dashboard-sa"
  display_name = "Dashboard (Streamlit, read-only)"
}

# --- Sweeper: requeues PROCESSING rows abandoned by a crashed worker ---
resource "google_service_account" "sweeper" {
  account_id   = "sweeper-sa"
  display_name = "Recovery Sweeper (requeues abandoned transactions)"
}

resource "google_project_iam_member" "sweeper_sql_client" {
  project = var.project_id
  role    = "roles/cloudsql.client"
  member  = "serviceAccount:${google_service_account.sweeper.email}"
}