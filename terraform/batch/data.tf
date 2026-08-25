data "aws_caller_identity" "current" {}

locals {
  aws_account_id = data.aws_caller_identity.current.account_id
}

data "aws_iam_policy_document" "secrets_policy" {
  statement {
    effect = "Allow"
    actions = [
      "secretsmanager:GetSecretValue"
    ]
    resources = [
      "arn:aws:secretsmanager:${var.region}:${local.aws_account_id}:secret:${var.aws_secret_name}-*"
    ]
  }
}

data "aws_iam_policy_document" "s3_policy" {
  statement {
    effect = "Allow"
    actions = [
      "s3:PutObject",
      "s3:GetObject",
      "s3:ListBucket"
    ]
    resources = [
      "arn:aws:s3:::${var.source_bucket}",
      "arn:aws:s3:::${var.source_bucket}/*"
    ]
  }
}

data "terraform_remote_state" "vpc" {
  backend = "s3"

  config = {
    bucket = "${var.domain}-tf-state"
    key    = "${var.domain}-ecs-infra/terraform.tfstate"
    region = "eu-west-2"
  }
}