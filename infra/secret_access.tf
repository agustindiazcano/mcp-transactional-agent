# Who can read which secret. Per-secret grants replace the old project-wide
# secretAccessor: each service account reads only the secrets it uses.
locals {
  secret_ids = merge(
    { "database-url" = google_secret_manager_secret.database_url.id },
    { for name, s in google_secret_manager_secret.manual : name => s.id },
  )

  secret_readers = {
    worker      = { member = google_service_account.worker.member, secrets = ["database-url", "rabbitmq-url", "groq-api-key", "mcp-client-token"] }
    gateway     = { member = google_service_account.gateway.member, secrets = ["database-url", "rabbitmq-url"] }
    mcp_server  = { member = google_service_account.mcp_server.member, secrets = ["database-url", "mcp-clients-json"] }
    sweeper     = { member = google_service_account.sweeper.member, secrets = ["database-url", "rabbitmq-url"] }
    seed_orders = { member = google_service_account.seed_orders.member, secrets = ["database-url"] }
    ingest_kb   = { member = google_service_account.ingest_kb.member, secrets = ["database-url"] }
  }

  # One entry per (account, secret) pair, e.g. "worker/groq-api-key".
  secret_grants = merge([
    for sa, cfg in local.secret_readers : {
      for secret in cfg.secrets : "${sa}/${secret}" => { member = cfg.member, secret = secret }
    }
  ]...)
}

resource "google_secret_manager_secret_iam_member" "readers" {
  for_each  = local.secret_grants
  secret_id = local.secret_ids[each.value.secret]
  role      = "roles/secretmanager.secretAccessor"
  member    = each.value.member
}