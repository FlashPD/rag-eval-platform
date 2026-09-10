data "aws_availability_zones" "available" {
  state = "available"
}

data "aws_caller_identity" "current" {}

data "aws_partition" "current" {}

locals {
  name_prefix        = "${var.project_name}-${var.environment}"
  availability_zones = slice(data.aws_availability_zones.available.names, 0, 2)
  nat_gateway_count  = var.nat_gateway_mode == "none" ? 0 : (var.nat_gateway_mode == "single" ? 1 : 2)

  common_tags = {
    Environment = var.environment
    ManagedBy   = "terraform"
    Project     = var.project_name
  }

  artifact_bucket_name = lower(
    "${local.name_prefix}-${data.aws_caller_identity.current.account_id}-${var.aws_region}-artifacts"
  )
}
