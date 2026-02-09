#!/bin/sh

# shellcheck disable=SC2154,SC3040

set -euo pipefail

apk add --no-cache jq

aws_account_id=$(echo "$secrets" | jq -r .aws_account_id)
aws_access_key_id=$(echo "$secrets" | jq -r .aws_access_key_id)
aws_secret_access_key=$(echo "$secrets" | jq -r .aws_secret_access_key)

domain=$(echo "$secrets" | jq -r .domain)
ecr_repository=$(echo "$secrets" | jq -r .ecr_repository)

lambda_timeout=$(echo "$secrets" | jq -r .lambda_timeout)

github_app_client_id=$(echo "$secrets" | jq -r .github_app_client_id)
aws_secret_name=$(echo "$secrets" | jq -r .aws_secret_name)
github_org=$(echo "$secrets" | jq -r .github_org)

source_bucket=$(echo "$secrets" | jq -r .source_bucket)
source_key=$(echo "$secrets" | jq -r .source_key)
batch_size=$(echo "$secrets" | jq -r .batch_size)
schedule=$(echo "$secrets" | jq -r .schedule)

export AWS_ACCESS_KEY_ID="$aws_access_key_id"
export AWS_SECRET_ACCESS_KEY="$aws_secret_access_key"

git config --global url."https://x-access-token:$github_access_token@github.com/".insteadOf "https://github.com/"

if [ "${env}" != "prod" ]; then
	env="dev"
fi

echo "${env}"

cd resource-repo/terraform/batch

terraform init -backend-config=env/"${env}"/backend-"${env}".tfbackend -reconfigure

# The following terraform-apply may need to change if the environment variables change

terraform apply \
	-var "aws_account_id=$aws_account_id" \
	-var "aws_access_key_id=$aws_access_key_id" \
	-var "aws_secret_access_key=$aws_secret_access_key" \
	-var "domain=$domain" \
	-var "ecr_repository=$ecr_repository" \
	-var "github_app_client_id=$github_app_client_id" \
	-var "aws_secret_name=$aws_secret_name" \
	-var "github_org=$github_org" \
	-var "source_bucket=$source_bucket" \
	-var "source_key=$source_key" \
	-var "batch_size=$batch_size" \
	-var "schedule=$schedule" \
	-var "container_ver=${tag}" \
	-auto-approve
