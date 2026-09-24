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
variable "consumer_instance_count" {
  description = "Instances per consumer worker pool (worker, sweeper). 0 pauses them and stops their billing."
  type        = number
  default     = 1
}
