resource "aws_cloudwatch_log_group" "workload" {
  for_each = toset(["api", "worker", "migration", "utility"])

  name              = "/ecs/${local.name_prefix}/${each.key}"
  retention_in_days = var.log_retention_days
}
