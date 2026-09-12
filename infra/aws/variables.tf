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

variable "adot_collector_image" {
  description = "Version-pinned AWS Distro for OpenTelemetry collector image used by ECS sidecars."
  type        = string
  default     = "public.ecr.aws/aws-observability/aws-otel-collector:v0.49.0"

  validation {
    condition = can(regex(
      "^public\\.ecr\\.aws/aws-observability/aws-otel-collector:v[0-9]+\\.[0-9]+\\.[0-9]+$",
      var.adot_collector_image,
    ))
    error_message = "adot_collector_image must use an explicit semantic-version tag from the AWS public ECR repository."
  }
}

variable "alarm_notification_email" {
  description = "Optional email address subscribed to production alarms. Confirmation is required before delivery."
  type        = string
  default     = ""

  validation {
    condition = (
      var.alarm_notification_email == "" ||
      can(regex("^[^[:space:]@]+@[^[:space:]@]+\\.[^[:space:]@]+$", var.alarm_notification_email))
    )
    error_message = "alarm_notification_email must be empty or a valid email address."
  }
}

variable "hourly_llm_cost_alarm_usd" {
  description = "Alarm when generated OpenTelemetry cost metrics exceed this amount in one hour."
  type        = number
  default     = 5

  validation {
    condition     = var.hourly_llm_cost_alarm_usd > 0
    error_message = "hourly_llm_cost_alarm_usd must be positive."
  }
}

variable "application_image_digest" {
  description = "Immutable sha256 digest deployed from the application ECR repository; null keeps services scaled to zero during initial provisioning."
  type        = string
  default     = null
  nullable    = true

  validation {
    condition = (
      var.application_image_digest == null ||
      can(regex("^sha256:[a-f0-9]{64}$", var.application_image_digest))
    )
    error_message = "application_image_digest must be null or a sha256 digest."
  }
}

variable "cpu_architecture" {
  description = "CPU architecture for application task definitions."
  type        = string
  default     = "X86_64"

  validation {
    condition     = contains(["X86_64", "ARM64"], var.cpu_architecture)
    error_message = "cpu_architecture must be X86_64 or ARM64."
  }
}

variable "api_cpu" {
  description = "Fargate CPU units allocated to each API task."
  type        = number
  default     = 1024
}

variable "api_memory_mib" {
  description = "Memory allocated to each API task."
  type        = number
  default     = 4096
}

variable "api_desired_count" {
  description = "API tasks to run after an image digest is configured."
  type        = number
  default     = 1

  validation {
    condition     = var.api_desired_count >= 0
    error_message = "api_desired_count cannot be negative."
  }
}

variable "worker_cpu" {
  description = "Fargate CPU units allocated to each evaluation worker or utility task."
  type        = number
  default     = 2048
}

variable "worker_memory_mib" {
  description = "Memory allocated to each evaluation worker or utility task."
  type        = number
  default     = 8192
}

variable "worker_desired_count" {
  description = "Worker tasks to run after an image digest is configured."
  type        = number
  default     = 1

  validation {
    condition     = var.worker_desired_count >= 0
    error_message = "worker_desired_count cannot be negative."
  }
}

variable "worker_use_spot" {
  description = "Run resumable evaluation workers on Fargate Spot capacity."
  type        = bool
  default     = true
}

variable "load_balancer_deletion_protection" {
  description = "Protect the application load balancer from accidental deletion."
  type        = bool
  default     = false
}

variable "load_balancer_certificate_arn" {
  description = "Validated ACM certificate ARN used by the public HTTPS listener."
  type        = string

  validation {
    condition = can(regex(
      "^arn:[a-z0-9-]+:acm:[a-z0-9-]+:[0-9]{12}:certificate/[a-f0-9-]+$",
      var.load_balancer_certificate_arn,
    ))
    error_message = "load_balancer_certificate_arn must be an ACM certificate ARN."
  }
}
