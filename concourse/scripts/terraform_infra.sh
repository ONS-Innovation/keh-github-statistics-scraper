#!/bin/sh

# shellcheck disable=SC2154,SC3040

set -euo pipefail

apk add --no-cache jq

domain=$(echo "$secrets" | jq -r .domain)
ecr_repository=$(echo "$secrets" | jq -r .ecr_repository)

github_client_id_secret_name=$(echo "$secrets" | jq -r .github_client_id_secret_name)
github_private_key_secret_name=$(echo "$secrets" | jq -r .github_private_key_secret_name)
github_org=$(echo "$secrets" | jq -r .github_org)

alert_secret_name=$(echo "$secrets" | jq -r .alert_secret_name)

source_bucket=$(echo "$secrets" | jq -r .source_bucket)
source_key=$(echo "$secrets" | jq -r .source_key)
batch_size=$(echo "$secrets" | jq -r .batch_size)
schedule=$(echo "$secrets" | jq -r .schedule)

git config --global url."https://x-access-token:$github_access_token@github.com/".insteadOf "https://github.com/"

if [ "${env}" != "prod" ]; then
	env="dev"
fi

echo "${env}"

cd resource-repo/terraform/batch

terraform init -backend-config=env/"${env}"/backend-"${env}".tfbackend -reconfigure

# The following terraform-apply may need to change if the environment variables change

terraform apply \
	-var "domain=$domain" \
	-var "ecr_repository=$ecr_repository" \
	-var "github_client_id_secret_name=$github_client_id_secret_name" \
	-var "github_private_key_secret_name=$github_private_key_secret_name" \
	-var "github_org=$github_org" \
	-var "alert_secret_name=$alert_secret_name" \
	-var "source_bucket=$source_bucket" \
	-var "source_key=$source_key" \
	-var "batch_size=$batch_size" \
	-var "schedule=$schedule" \
	-var "container_ver=${tag}" \
	-auto-approve
