resource "aws_iam_policy" "secrets_access" {
  name        = "${var.domain}-${var.service_subdomain}-secrets-access"
  description = "Policy to allow access to Secrets Manager for GitHub Repository Scraper"
  policy      = data.aws_iam_policy_document.secrets_policy.json
}

resource "aws_iam_policy" "s3_access" {
  name        = "${var.domain}-${var.service_subdomain}-s3-access"
  description = "Policy to allow access to S3 for GitHub Repository Scraper"
  policy      = data.aws_iam_policy_document.s3_policy.json
}

module "batch_eventbridge" {
  source = "git::https://github.com/ONS-Innovation/keh-scheduled-batch-tf-module.git?ref=v1.1.0"

  aws_account_id        = var.aws_account_id
  aws_access_key_id     = var.aws_access_key_id
  aws_secret_access_key = var.aws_secret_access_key
  environment          = var.domain
  service_name         = var.service_subdomain
  region              = var.region
  project_tag         = var.project_tag
  team_owner_tag      = var.team_owner_tag
  business_owner_tag  = var.business_owner_tag
  ecr_repository_name = var.ecr_repository
  container_ver       = var.container_ver
  schedule           = var.schedule
  private_subnet_ids = data.terraform_remote_state.vpc.outputs.private_subnets
  vpc_id = data.terraform_remote_state.vpc.outputs.vpc_id

  service_environment_variables = [
    {
      name  = "SOURCE_BUCKET"
      value = var.source_bucket
    },
    {
      name  = "SOURCE_KEY"
      value = var.source_key
    },
    {
      name  = "GITHUB_APP_CLIENT_ID"
      value = var.github_app_client_id
    },
    {
      name  = "AWS_SECRET_NAME"
      value = var.aws_secret_name
    },
    {
      name  = "GITHUB_ORG"
      value = var.github_org
    },
    {
      name  = "BATCH_SIZE"
      value = tostring(var.batch_size)
    },
    {
      name  = "ENVIRONMENT"
      value = "production"
    }
  ]
}

# Attach policies to the batch job role
resource "aws_iam_role_policy_attachment" "secrets_policy_attachment" {
  role       = split("/", module.batch_eventbridge.batch_job_role_arn)[1]
  policy_arn = aws_iam_policy.secrets_access.arn
}

resource "aws_iam_role_policy_attachment" "s3_policy_attachment" {
  role       = split("/", module.batch_eventbridge.batch_job_role_arn)[1]
  policy_arn = aws_iam_policy.s3_access.arn
}

# IAM User Group
resource "aws_iam_group" "group" {
  name = "${var.domain}-${var.service_subdomain}-user-group"
  path = "/"
}

# Attach S3 policy to group
resource "aws_iam_group_policy_attachment" "group_s3_access_attachment" {
  group      = aws_iam_group.group.name
  policy_arn = aws_iam_policy.s3_access.arn
}

# Attach Secrets Manager policy to group
resource "aws_iam_group_policy_attachment" "group_secrets_attachment" {
  group      = aws_iam_group.group.name
  policy_arn = aws_iam_policy.secrets_access.arn
}

# IAM User
resource "aws_iam_user" "user" {
  name = "${var.domain}-${var.service_subdomain}"
  path = "/"
}

# Assign IAM User to group
resource "aws_iam_user_group_membership" "user_group_attach" {
  user = aws_iam_user.user.name

  groups = [
    aws_iam_group.group.name
  ]
}

# IAM Key Rotation Module
module "iam_key_rotation" {
  source = "git::https://github.com/ONS-Innovation/keh-aws-iam-key-rotation.git?ref=v0.1.0"

  iam_username          = aws_iam_user.user.name
  access_key_secret_arn = aws_secretsmanager_secret.access_key.arn
  secret_key_secret_arn = aws_secretsmanager_secret.secret_key.arn
  rotation_in_days      = 90
}
