# Secrets Manager resources for IAM user access keys

resource "aws_secretsmanager_secret" "access_key" {
  name        = "${var.domain}-${var.service_subdomain}-access-key"
  description = "Access Key ID for github statistics scraper IAM user"
}

resource "aws_secretsmanager_secret" "secret_key" {
  name        = "${var.domain}-${var.service_subdomain}-secret-key"
  description = "Secret Access Key for github stastics scraper IAM user"
}
