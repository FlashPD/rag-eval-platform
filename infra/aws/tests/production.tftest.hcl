mock_provider "aws" {
  mock_data "aws_iam_policy_document" {
    defaults = {
      json = "{\"Version\":\"2012-10-17\",\"Statement\":[]}"
    }
  }
}

override_data {
  target = data.aws_availability_zones.available
  values = { names = ["us-east-1a", "us-east-1b"] }
}

override_data {
  target = data.aws_caller_identity.current
  values = { account_id = "123456789012" }
}

override_data {
  target = data.aws_partition.current
  values = { partition = "aws" }
}

override_data {
  target = data.aws_ecr_repository.app
  values = {
    name           = "ragops"
    repository_url = "123456789012.dkr.ecr.us-east-1.amazonaws.com/ragops"
  }
}

override_data {
  target = data.aws_ecr_image.app
  values = { image_digest = "sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef" }
}

run "cost_aware_secure_defaults" {
  command = plan

  variables {
    image_tag             = "0123456789abcdef0123456789abcdef01234567"
    allowed_ingress_cidrs = ["203.0.113.10/32"]
  }

  assert {
    condition     = aws_db_instance.main.publicly_accessible == false
    error_message = "RDS must never be publicly accessible."
  }

  assert {
    condition     = aws_db_instance.main.manage_master_user_password == true
    error_message = "RDS must keep its password in its AWS-managed secret."
  }

  assert {
    condition     = length(aws_nat_gateway.main) == 0
    error_message = "The cost-aware demo default must not provision a NAT gateway."
  }

  assert {
    condition     = aws_lb.api.drop_invalid_header_fields == true
    error_message = "The public ALB must reject invalid headers."
  }

  assert {
    condition     = aws_ecs_task_definition.api.runtime_platform[0].cpu_architecture == "X86_64"
    error_message = "The task architecture must match the deployment workflow image build."
  }
}

run "private_tls_topology" {
  command = plan

  variables {
    image_tag             = "fedcba9876543210fedcba9876543210fedcba98"
    allowed_ingress_cidrs = ["198.51.100.20/32"]
    enable_nat_gateway    = true
    certificate_arn       = "arn:aws:acm:us-east-1:123456789012:certificate/00000000-0000-0000-0000-000000000000"
  }

  assert {
    condition     = length(aws_nat_gateway.main) == 1
    error_message = "Private mode must provide controlled outbound access through NAT."
  }

  assert {
    condition     = aws_ecs_service.api.network_configuration[0].assign_public_ip == false
    error_message = "Private-mode ECS tasks must not receive public IPs."
  }

  assert {
    condition     = length(aws_lb_listener.https) == 1 && length(aws_lb_listener.http_redirect) == 1
    error_message = "A certificate must enable HTTPS and redirect HTTP."
  }
}
