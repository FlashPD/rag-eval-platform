variable "aws_region" {
  description = "AWS region for the deployment."
  type        = string
  default     = "us-east-1"
}

variable "project_name" {
  description = "Short name used to namespace resources."
  type        = string
  default     = "ragops"

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{1,20}$", var.project_name))
    error_message = "project_name must be 2-21 lowercase letters, numbers, or hyphens."
  }
}

variable "environment" {
  description = "Deployment environment name."
  type        = string
  default     = "production"

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{1,15}$", var.environment))
    error_message = "environment must be 2-16 lowercase letters, numbers, or hyphens."
  }
}

variable "vpc_cidr" {
  description = "IPv4 CIDR allocated to the ragops VPC."
  type        = string
  default     = "10.42.0.0/16"

  validation {
    condition     = can(cidrnetmask(var.vpc_cidr))
    error_message = "vpc_cidr must be a valid IPv4 CIDR."
  }
}

variable "nat_gateway_mode" {
  description = "NAT topology: none runs future ECS tasks in public subnets; single or per_az keeps them private."
  type        = string
  default     = "none"

  validation {
    condition     = contains(["none", "single", "per_az"], var.nat_gateway_mode)
    error_message = "nat_gateway_mode must be none, single, or per_az."
  }
}

variable "database_instance_class" {
  description = "RDS instance class; ARM burstable is the cost-conscious portfolio default."
  type        = string
  default     = "db.t4g.micro"
}

variable "database_allocated_storage_gib" {
  description = "Initial encrypted gp3 storage allocated to RDS."
  type        = number
  default     = 20

  validation {
    condition     = var.database_allocated_storage_gib >= 20
    error_message = "database_allocated_storage_gib must be at least 20."
  }
}

variable "database_max_storage_gib" {
  description = "RDS storage autoscaling ceiling."
  type        = number
  default     = 100

  validation {
    condition     = var.database_max_storage_gib >= var.database_allocated_storage_gib
    error_message = "database_max_storage_gib cannot be smaller than initial storage."
  }
}

variable "database_multi_az" {
  description = "Enable a standby RDS instance in another AZ."
  type        = bool
  default     = false
}

variable "database_deletion_protection" {
  description = "Protect RDS from deletion; disable for a destroyable portfolio environment."
  type        = bool
  default     = false
}

variable "database_skip_final_snapshot" {
  description = "Skip the final RDS snapshot on destroy. False is safer; true lowers teardown friction."
  type        = bool
  default     = true
}

variable "log_retention_days" {
  description = "CloudWatch log retention for ECS workloads."
  type        = number
  default     = 30
}
