output "artifact_bucket_name" {
  description = "Versioned private bucket used for BM25 indexes, datasets, reports, and labels."
  value       = aws_s3_bucket.artifacts.id
}

output "ecr_repository_url" {
  description = "Push the ragops application image to this repository."
  value       = aws_ecr_repository.application.repository_url
}

output "database_endpoint" {
  description = "Private RDS endpoint consumed by future ECS task definitions."
  value       = aws_db_instance.this.address
}

output "database_master_secret_arn" {
  description = "RDS-managed JSON secret; its value is never read into Terraform state."
  value       = aws_db_instance.this.master_user_secret[0].secret_arn
}

output "openai_api_key_secret_arn" {
  description = "Populate this secret out of band before enabling answer generation."
  value       = aws_secretsmanager_secret.openai_api_key.arn
}

output "application_subnet_ids" {
  description = "Subnet IDs for ECS; public when NAT is disabled, private otherwise."
  value = var.nat_gateway_mode == "none" ? (
    [for subnet in aws_subnet.public : subnet.id]
  ) : [for subnet in aws_subnet.private : subnet.id]
}

output "application_assign_public_ip" {
  description = "Whether future Fargate tasks need public IPs for provider/model access."
  value       = var.nat_gateway_mode == "none"
}

output "application_security_group_id" {
  value = aws_security_group.application.id
}

output "load_balancer_security_group_id" {
  value = aws_security_group.load_balancer.id
}

output "task_execution_role_arn" {
  value = aws_iam_role.task_execution.arn
}

output "application_task_role_arn" {
  value = aws_iam_role.application_task.arn
}
