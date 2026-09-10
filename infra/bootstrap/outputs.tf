output "state_bucket_name" {
  description = "Bucket passed to infra/aws terraform init -backend-config."
  value       = aws_s3_bucket.terraform_state.id
}

output "state_key" {
  description = "Object key passed to infra/aws terraform init -backend-config."
  value       = "${var.project_name}/production/terraform.tfstate"
}

output "terraform_plan_role_arn" {
  description = "Role assumed by plans after infrastructure changes merge to dev."
  value       = aws_iam_role.terraform_plan.arn
}

output "terraform_apply_role_arn" {
  description = "Set as the repository variable AWS_TERRAFORM_APPLY_ROLE_ARN."
  value       = aws_iam_role.terraform_apply.arn
}
