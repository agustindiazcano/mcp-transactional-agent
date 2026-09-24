data "google_project" "this" {}

locals {
  # Cloud Run's predictable URL: <service>-<project-number>.<region>.run.app
  mcp_server_host = "mcp-server-${data.google_project.this.number}.${var.region}.run.app"
}

resource "google_cloud_run_v2_service" "mcp_server" {
  name                = "mcp-server"
  location            = var.region
  ingress             = "INGRESS_TRAFFIC_ALL"
  deletion_protection = false # stateless

  template {
    service_account = google_service_account.mcp_server.email

    scaling {
      min_instance_count = 0
      max_instance_count = 1 # an SSE stream and its POSTs must reach the same instance
    }

    containers {
      image = "${var.region}-docker.pkg.dev/${var.project_id}/app-images/mcp_server:17831b7"

      ports {
        container_port = 8080
      }

      env {
        name  = "MCP_ALLOWED_HOSTS"
        value = local.mcp_server_host
      }
      env {
        name  = "MCP_CLIENTS_FILE"
        value = "/secrets/mcp_clients.json" # the cloud registry, never the image's local-dev one
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

      # Same order Cloud Run stores them in; otherwise every plan shows a reorder diff.
      volume_mounts {
        name       = "mcp-clients"
        mount_path = "/secrets"
      }
      volume_mounts {
        name       = "cloudsql"
        mount_path = "/cloudsql"
      }
    }

    volumes {
      name = "mcp-clients"
      secret {
        secret = google_secret_manager_secret.manual["mcp-clients-json"].secret_id
        items {
          version = "latest"
          path    = "mcp_clients.json"
        }
      }
    }
    volumes {
      name = "cloudsql"
      cloud_sql_instance {
        instances = [google_sql_database_instance.main.connection_name]
      }
    }
  }

  depends_on = [google_secret_manager_secret_iam_member.readers]
}

# Public at the Cloud Run layer; the Phase 1.B boundary does the real auth.
resource "google_cloud_run_v2_service_iam_member" "mcp_server_public" {
  name     = google_cloud_run_v2_service.mcp_server.name
  location = var.region
  role     = "roles/run.invoker"
  member   = "allUsers"
}

resource "google_cloud_run_v2_service" "gateway" {
  name                = "gateway"
  location            = var.region
  ingress             = "INGRESS_TRAFFIC_ALL"
  deletion_protection = false # stateless

  template {
    service_account = google_service_account.gateway.email

    scaling {
      min_instance_count = 0
      max_instance_count = 2 # public and unauthenticated: caps what a flood of claims can cost
    }

    containers {
      image = "${var.region}-docker.pkg.dev/${var.project_id}/app-images/gateway:b0e7dbe"

      ports {
        container_port = 8000 # the gateway image listens on 8000, not Cloud Run's default 8080
      }

      env {
        name  = "MCP_SERVER_URL"
        value = "https://${local.mcp_server_host}/sse" # system-health ping; 401 = alive
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
      env {
        name = "RABBITMQ_URL"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.manual["rabbitmq-url"].secret_id
            version = "latest"
          }
        }
      }

      volume_mounts {
        name       = "cloudsql"
        mount_path = "/cloudsql"
      }
    }

    volumes {
      name = "cloudsql"
      cloud_sql_instance {
        instances = [google_sql_database_instance.main.connection_name]
      }
    }
  }

  depends_on = [google_secret_manager_secret_iam_member.readers]
}

# Public: the dashboard calls it from outside, and the login screen comes later.
resource "google_cloud_run_v2_service_iam_member" "gateway_public" {
  name     = google_cloud_run_v2_service.gateway.name
  location = var.region
  role     = "roles/run.invoker"
  member   = "allUsers"
}
# --- Consumers: worker pools, Cloud Run's resource for pull-based workloads
# (no HTTP port, no request-driven scaling). They pull from RabbitMQ.
locals {
  consumer_instance_count = var.demo_up ? 1 : 0 # 0 stops the pools and their billing
  consumer_image          = "${var.region}-docker.pkg.dev/${var.project_id}/app-images/worker:b0e7dbe"
}

resource "google_cloud_run_v2_worker_pool" "worker" {
  name                = "worker"
  location            = var.region
  deletion_protection = false # stateless

  scaling {
    scaling_mode          = "MANUAL"
    manual_instance_count = local.consumer_instance_count
  }

  template {
    service_account = google_service_account.worker.email

    containers {
      image = local.consumer_image

      resources {
        limits = { cpu = "1", memory = "512Mi" } # ~140 MiB in use locally
      }

      env {
        name  = "LLM_PROVIDER"
        value = "vertex" # Judge 1 + Supreme Court + embeddings on Vertex; Judge 2 + Prompt Guard on Groq
      }
      env {
        name  = "VERTEX_PROJECT"
        value = var.project_id
      }
      env {
        name  = "MCP_SERVER_URL"
        value = "https://${local.mcp_server_host}/sse" # the host in MCP_ALLOWED_HOSTS; the other URL gets 421
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
      env {
        name = "RABBITMQ_URL"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.manual["rabbitmq-url"].secret_id
            version = "latest"
          }
        }
      }
      env {
        name = "GROQ_API_KEY"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.manual["groq-api-key"].secret_id
            version = "latest"
          }
        }
      }
      env {
        name = "MCP_CLIENT_TOKEN"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.manual["mcp-client-token"].secret_id
            version = "latest"
          }
        }
      }

      volume_mounts {
        name       = "cloudsql"
        mount_path = "/cloudsql"
      }
    }

    volumes {
      name = "cloudsql"
      cloud_sql_instance {
        instances = [google_sql_database_instance.main.connection_name]
      }
    }
  }

  depends_on = [google_secret_manager_secret_iam_member.readers]
}

resource "google_cloud_run_v2_worker_pool" "sweeper" {
  name                = "sweeper"
  location            = var.region
  deletion_protection = false # stateless

  scaling {
    scaling_mode          = "MANUAL"
    manual_instance_count = local.consumer_instance_count
  }

  template {
    service_account = google_service_account.sweeper.email

    containers {
      image   = local.consumer_image
      command = ["python", "-m", "src.worker.recovery_sweeper"] # same image as the worker, as in compose

      resources {
        limits = { cpu = "1", memory = "512Mi" }
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
      env {
        name = "RABBITMQ_URL"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.manual["rabbitmq-url"].secret_id
            version = "latest"
          }
        }
      }

      volume_mounts {
        name       = "cloudsql"
        mount_path = "/cloudsql"
      }
    }

    volumes {
      name = "cloudsql"
      cloud_sql_instance {
        instances = [google_sql_database_instance.main.connection_name]
      }
    }
  }

  depends_on = [google_secret_manager_secret_iam_member.readers]
}

# --- Dashboard: read-only Streamlit UI; talks only to the gateway's HTTP API.
resource "google_cloud_run_v2_service" "dashboard" {
  name                = "dashboard"
  location            = var.region
  ingress             = "INGRESS_TRAFFIC_ALL"
  deletion_protection = false # stateless

  template {
    service_account  = google_service_account.dashboard.email
    session_affinity = true # Streamlit keeps a websocket per browser session

    scaling {
      min_instance_count = 0
      max_instance_count = 1
    }

    containers {
      image = "${var.region}-docker.pkg.dev/${var.project_id}/app-images/dashboard:b0e7dbe"

      ports {
        container_port = 8501 # Streamlit's port in the dashboard image
      }

      env {
        name  = "GATEWAY_URL"
        value = "https://gateway-${data.google_project.this.number}.${var.region}.run.app"
      }
    }
  }
}

# Public for now; the login screen comes later.
resource "google_cloud_run_v2_service_iam_member" "dashboard_public" {
  name     = google_cloud_run_v2_service.dashboard.name
  location = var.region
  role     = "roles/run.invoker"
  member   = "allUsers"
}
