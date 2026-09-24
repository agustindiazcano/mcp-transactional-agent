# --- CD: GitHub Actions deploys to Cloud Run through Workload Identity Federation ---
# GitHub signs a short-lived OIDC token per workflow run ("repo X, branch Y");
# Google checks it and hands out access for about an hour. No key is stored in GitHub.

# STS exchanges GitHub's token for a Google one. Enabled here, not by hand, so
# the dependency is visible in code; disabling it on destroy could break other users.
resource "google_project_service" "sts" {
  service            = "sts.googleapis.com"
  disable_on_destroy = false
}

resource "google_iam_workload_identity_pool" "github" {
  workload_identity_pool_id = "github"
  display_name              = "GitHub Actions"
  description               = "Identities from GitHub Actions workflow runs"

  depends_on = [google_project_service.sts]
}

resource "google_iam_workload_identity_pool_provider" "github" {
  workload_identity_pool_id          = google_iam_workload_identity_pool.github.workload_identity_pool_id
  workload_identity_pool_provider_id = "github-oidc"
  display_name                       = "GitHub OIDC"

  oidc {
    issuer_uri = "https://token.actions.githubusercontent.com"
  }

  # Claims from GitHub's token we can write rules against later.
  attribute_mapping = {
    "google.subject"                = "assertion.sub"
    "attribute.repository_id"       = "assertion.repository_id"
    "attribute.repository_owner_id" = "assertion.repository_owner_id"
    "attribute.ref"                 = "assertion.ref"
  }

  # Only this repo can even exchange a token. Numeric IDs, not names: a renamed
  # or re-created repo with the same name gets a new ID and is refused.
  attribute_condition = "assertion.repository_id == '${var.github_repository_id}' && assertion.repository_owner_id == '${var.github_owner_id}'"
}

# --- The deployer: the only identity GitHub Actions can become ---
resource "google_service_account" "github_deployer" {
  account_id   = "github-deployer-sa"
  display_name = "GitHub Actions deployer (CD)"
}

# Only workflow runs on this repo's main branch may impersonate it. The pool
# already refuses other repos; this narrows it to one branch.
resource "google_service_account_iam_member" "github_deployer_wif" {
  service_account_id = google_service_account.github_deployer.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.github.name}/attribute.ref/refs/heads/main"
}

# Push images to app-images only, not to any other repository.
resource "google_artifact_registry_repository_iam_member" "github_deployer_push" {
  repository = google_artifact_registry_repository.repo.name
  location   = var.region
  role       = "roles/artifactregistry.writer"
  member     = google_service_account.github_deployer.member
}

# Deploy new revisions of these five resources and nothing else in the project.
# The jobs (migrate, seed-orders, ingest-knowledge-base) stay manual.
resource "google_cloud_run_v2_service_iam_member" "github_deployer" {
  for_each = {
    gateway    = google_cloud_run_v2_service.gateway.name
    mcp_server = google_cloud_run_v2_service.mcp_server.name
    dashboard  = google_cloud_run_v2_service.dashboard.name
  }
  name     = each.value
  location = var.region
  role     = "roles/run.developer"
  member   = google_service_account.github_deployer.member
}

resource "google_cloud_run_v2_worker_pool_iam_member" "github_deployer" {
  for_each = {
    worker  = google_cloud_run_v2_worker_pool.worker.name
    sweeper = google_cloud_run_v2_worker_pool.sweeper.name
  }
  name     = each.value
  location = var.region
  role     = "roles/run.developer"
  member   = google_service_account.github_deployer.member
}

# Deploying a revision means "run this code as its service account", so Cloud
# Run checks the deployer may act as each runtime SA. Granted per SA, never
# project-wide (which would let it act as the default Compute SA, an Editor).
resource "google_service_account_iam_member" "github_deployer_act_as" {
  for_each = {
    gateway    = google_service_account.gateway.name
    mcp_server = google_service_account.mcp_server.name
    dashboard  = google_service_account.dashboard.name
    worker     = google_service_account.worker.name
    sweeper    = google_service_account.sweeper.name
  }
  service_account_id = each.value
  role               = "roles/iam.serviceAccountUser"
  member             = google_service_account.github_deployer.member
}

# `gcloud run worker-pools deploy` returns a long-running operation and polls it
# until the rollout finishes. Operations are a project-level resource, so the
# per-pool run.developer grant above doesn't cover them (the first CD run got a
# 403 on run.operations.get). A custom role with only that permission lets the
# deployer check an operation's status, and nothing else; roles/run.viewer would
# also let it read every Cloud Run resource's configuration.
resource "google_project_iam_custom_role" "run_operations_reader" {
  role_id     = "runOperationsReader"
  title       = "Cloud Run operations reader"
  description = "Read the status of Cloud Run long-running operations (CD polls worker-pool deploys)."
  permissions = ["run.operations.get"]
}

resource "google_project_iam_member" "github_deployer_run_operations" {
  project = var.project_id
  role    = google_project_iam_custom_role.run_operations_reader.id
  member  = google_service_account.github_deployer.member
}
