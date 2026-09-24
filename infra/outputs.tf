# Values the deploy workflow needs. Neither is a secret: both are useless
# without a GitHub token from this repo's main branch.
output "github_wif_provider" {
  description = "Workload Identity provider for google-github-actions/auth."
  value       = google_iam_workload_identity_pool_provider.github.name
}

output "github_deployer_email" {
  description = "Service account the deploy workflow impersonates."
  value       = google_service_account.github_deployer.email
}
