# Turn the cloud demo on: starts Cloud SQL and scales the worker pools to 1.
# Terraform shows the plan and asks "yes" before changing anything.
# Cloud SQL takes ~1-3 min to start; claims queued meanwhile are processed after.
$ErrorActionPreference = "Stop"
terraform -chdir="$PSScriptRoot\..\infra" apply -var demo_up=true
