variable "aws_region" {
  description = "AWS region that stores Terraform state and hosts the application."
  type        = string
  default     = "us-east-1"
}

variable "project_name" {
  description = "Short name used to namespace bootstrap resources."
  type        = string
  default     = "ragops"

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{1,20}$", var.project_name))
    error_message = "project_name must be 2-21 lowercase letters, numbers, or hyphens."
  }
}

variable "github_repository" {
  description = "GitHub repository allowed to request AWS credentials, in owner/name form."
  type        = string
  default     = "FlashPD/rag-eval-platform"

  validation {
    condition     = can(regex("^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", var.github_repository))
    error_message = "github_repository must use owner/name form."
  }
}

variable "github_deployment_environment" {
  description = "Protected GitHub environment allowed to assume the apply role."
  type        = string
  default     = "production"
}

variable "create_github_oidc_provider" {
  description = "Create GitHub's account-wide OIDC provider; disable if the account already has it."
  type        = bool
  default     = true
}
