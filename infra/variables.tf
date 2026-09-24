variable "project_id" {
  description = "GCP project that hosts every resource in this configuration."
  type        = string
  default     = "project-e0ad10c9-0b2f-4dc0-ac6"
}

variable "region" {
  description = "Default region for regional resources (Artifact Registry, Cloud Run, Cloud SQL)."
  type        = string
  default     = "us-central1"
}
variable "demo_up" {
  description = "Whole-demo switch. false stops Cloud SQL and scales the worker pools to 0, so only disk and images are billed; the services already scale to zero on their own."
  type        = bool
  default     = true
}

variable "github_repository_id" {
  description = "Numeric ID of the GitHub repo allowed to deploy (immutable, unlike its name)."
  type        = string
  default     = "1374005852" # agustindiazcano/mcp-transactional-agent
}

variable "github_owner_id" {
  description = "Numeric ID of the GitHub account that owns the repo."
  type        = string
  default     = "72924416" # agustindiazcano
}
