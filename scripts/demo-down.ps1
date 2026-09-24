# Turn the cloud demo off: stops Cloud SQL (data kept) and scales the worker
# pools to 0. The HTTP services already scale to zero on their own.
# Terraform shows the plan and asks "yes" before changing anything.
# Claims sent while down wait in the CloudAMQP queue until demo-up.
$ErrorActionPreference = "Stop"
terraform -chdir="$PSScriptRoot\..\infra" apply -var demo_up=false
