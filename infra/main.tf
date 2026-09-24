resource "google_artifact_registry_repository" "repo" {
  location      = var.region
  repository_id = "app-images"
  description   = "Docker repository for our application images"
  format        = "DOCKER"
}