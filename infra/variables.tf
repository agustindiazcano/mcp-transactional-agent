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
