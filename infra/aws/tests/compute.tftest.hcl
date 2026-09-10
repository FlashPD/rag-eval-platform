mock_provider "aws" {
  mock_data "aws_availability_zones" {
    defaults = {
      names = ["us-east-1a", "us-east-1b"]
    }
  }

  mock_data "aws_caller_identity" {
    defaults = {
      account_id = "123456789012"
    }
  }

  mock_data "aws_partition" {
    defaults = {
      partition = "aws"
    }
  }

  mock_data "aws_iam_policy_document" {
    defaults = {
      json = "{\"Version\":\"2012-10-17\",\"Statement\":[]}"
    }
  }

  mock_resource "aws_db_instance" {
    defaults = {
      address = "ragops.example.us-east-1.rds.amazonaws.com"
      port    = 5432
      db_name = "ragops"
      master_user_secret = [{
        kms_key_id    = "arn:aws:kms:us-east-1:123456789012:key/database"
        secret_arn    = "arn:aws:secretsmanager:us-east-1:123456789012:secret:database"
        secret_status = "active"
      }]
    }
  }

  mock_resource "aws_ecr_repository" {
    defaults = {
      repository_url = "123456789012.dkr.ecr.us-east-1.amazonaws.com/ragops-production"
    }
  }

  mock_resource "aws_s3_bucket" {
    defaults = {
      id = "ragops-production-artifacts"
    }
  }

  mock_resource "aws_secretsmanager_secret" {
    defaults = {
      arn = "arn:aws:secretsmanager:us-east-1:123456789012:secret:openai"
    }
  }

  mock_resource "aws_cloudwatch_log_group" {
    defaults = {
      name = "/ecs/ragops-production/workload"
    }
  }

  mock_resource "aws_iam_role" {
    defaults = {
      arn = "arn:aws:iam::123456789012:role/ragops-task"
    }
  }

  mock_resource "aws_lb" {
    defaults = {
      arn      = "arn:aws:elasticloadbalancing:us-east-1:123456789012:loadbalancer/app/ragops/1234567890123456"
      dns_name = "ragops.us-east-1.elb.amazonaws.com"
    }
  }

  mock_resource "aws_lb_target_group" {
    defaults = {
      arn = "arn:aws:elasticloadbalancing:us-east-1:123456789012:targetgroup/ragops/1234567890123456"
    }
  }

  mock_resource "aws_ecs_cluster" {
    defaults = {
      id   = "arn:aws:ecs:us-east-1:123456789012:cluster/ragops-production"
      name = "ragops-production"
    }
  }

  mock_resource "aws_ecs_task_definition" {
    defaults = {
      arn = "arn:aws:ecs:us-east-1:123456789012:task-definition/ragops:1"
    }
  }
}

run "initial_provisioning_is_scaled_to_zero" {
  command = apply

  variables {
    load_balancer_certificate_arn = "arn:aws:acm:us-east-1:123456789012:certificate/00000000-0000-0000-0000-000000000000"
  }

  assert {
    condition     = aws_ecs_service.api.desired_count == 0
    error_message = "The API must not start before an immutable image digest is available."
  }

  assert {
    condition     = aws_ecs_service.worker.desired_count == 0
    error_message = "The worker must not start before an immutable image digest is available."
  }

  assert {
    condition = (
      jsondecode(aws_ecs_task_definition.api.container_definitions)[0].image ==
      "123456789012.dkr.ecr.us-east-1.amazonaws.com/ragops-production:bootstrap"
    )
    error_message = "Initial task definitions should use the non-running bootstrap image tag."
  }
}

run "immutable_image_configures_runtime_contracts" {
  command = apply

  variables {
    application_image_digest      = "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    load_balancer_certificate_arn = "arn:aws:acm:us-east-1:123456789012:certificate/00000000-0000-0000-0000-000000000000"
  }

  assert {
    condition     = aws_ecs_service.api.desired_count == 1
    error_message = "The API should start after an image digest is configured."
  }

  assert {
    condition     = aws_ecs_service.worker.desired_count == 1
    error_message = "The worker should start after an image digest is configured."
  }

  assert {
    condition = (
      jsondecode(aws_ecs_task_definition.api.container_definitions)[0].image ==
      "123456789012.dkr.ecr.us-east-1.amazonaws.com/ragops-production@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    )
    error_message = "Task definitions must deploy the immutable ECR digest."
  }

  assert {
    condition = contains(
      jsondecode(aws_ecs_task_definition.api.container_definitions)[0].environment,
      { name = "RAGOPS_ARTIFACT_BUCKET", value = "ragops-production-artifacts" },
    )
    error_message = "The API task must receive its S3 artifact bucket."
  }

  assert {
    condition = contains(
      jsondecode(aws_ecs_task_definition.api.container_definitions)[0].secrets,
      {
        name      = "RAGOPS_DATABASE_PASSWORD"
        valueFrom = "arn:aws:secretsmanager:us-east-1:123456789012:secret:database:password::"
      },
    )
    error_message = "The API task must select the password from the RDS JSON secret."
  }

  assert {
    condition     = aws_lb_target_group.api.target_type == "ip"
    error_message = "Fargate targets must use the ALB ip target type."
  }

  assert {
    condition     = aws_lb_listener.https.protocol == "HTTPS"
    error_message = "The public API listener must terminate TLS."
  }

  assert {
    condition     = one(aws_lb_listener.http.default_action).type == "redirect"
    error_message = "The plaintext listener must only redirect to HTTPS."
  }
}
