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
