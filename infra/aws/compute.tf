locals {
  application_image = var.application_image_digest == null ? (
    "${aws_ecr_repository.application.repository_url}:bootstrap"
    ) : (
    "${aws_ecr_repository.application.repository_url}@${var.application_image_digest}"
  )

  application_environment = concat(
    [
      { name = "AWS_REGION", value = var.aws_region },
      { name = "RAGOPS_ENVIRONMENT", value = var.environment },
      { name = "RAGOPS_DATABASE_HOST", value = aws_db_instance.this.address },
      { name = "RAGOPS_DATABASE_PORT", value = tostring(aws_db_instance.this.port) },
      { name = "RAGOPS_DATABASE_NAME", value = aws_db_instance.this.db_name },
      { name = "RAGOPS_DATABASE_REQUIRE_SSL", value = "true" },
      { name = "RAGOPS_CONFIGURATION_DIRECTORY", value = "/app/config" },
      { name = "RAGOPS_ARTIFACT_DIRECTORY", value = "/app/artifacts" },
      { name = "RAGOPS_ARTIFACT_BUCKET", value = aws_s3_bucket.artifacts.id },
      { name = "RAGOPS_MODEL_CACHE_DIRECTORY", value = "/app/artifacts/models" },
      { name = "RAGOPS_OTLP_ENDPOINT", value = "http://127.0.0.1:4318" },
      { name = "RAGOPS_TELEMETRY_SERVICE_NAME", value = local.name_prefix },
      {
        name  = "OTEL_RESOURCE_ATTRIBUTES"
        value = "deployment.environment.name=${var.environment}"
      },
    ],
    var.application_image_digest == null ? [] : [
      { name = "RAGOPS_IMAGE_DIGEST", value = var.application_image_digest },
    ],
  )

  database_secrets = [
    {
      name      = "RAGOPS_DATABASE_USER"
      valueFrom = "${aws_db_instance.this.master_user_secret[0].secret_arn}:username::"
    },
    {
      name      = "RAGOPS_DATABASE_PASSWORD"
      valueFrom = "${aws_db_instance.this.master_user_secret[0].secret_arn}:password::"
    },
  ]

  application_secrets = concat(local.database_secrets, [
    {
      name      = "RAGOPS_API_KEY_HASHES"
      valueFrom = aws_secretsmanager_secret.api_key_hashes.arn
    },
    {
      name      = "RAGOPS_OPENAI_API_KEY"
      valueFrom = aws_secretsmanager_secret.openai_api_key.arn
    },
  ])

  container_mount_points = [
    {
      sourceVolume  = "artifacts"
      containerPath = "/app/artifacts"
      readOnly      = false
    },
    {
      sourceVolume  = "reports"
      containerPath = "/app/evals/runs"
      readOnly      = false
    },
    {
      sourceVolume  = "scratch"
      containerPath = "/tmp"
      readOnly      = false
    },
  ]

  container_security = {
    readonlyRootFilesystem = true
    user                   = "10001:10001"
    linuxParameters = {
      initProcessEnabled = true
      capabilities = {
        drop = ["ALL"]
      }
    }
  }

  adot_config = file("${path.module}/otel-collector.yaml")

  adot_container = {
    name              = "aws-otel-collector"
    image             = var.adot_collector_image
    essential         = true
    cpu               = 0
    memoryReservation = 256
    command           = ["--config=env:AOT_CONFIG_CONTENT"]
    environment = [
      { name = "AOT_CONFIG_CONTENT", value = local.adot_config },
      { name = "AWS_REGION", value = var.aws_region },
      { name = "AWS_DEFAULT_REGION", value = var.aws_region },
      {
        name  = "RAGOPS_METRICS_LOG_GROUP"
        value = aws_cloudwatch_log_group.application_metrics.name
      },
    ]
    readonlyRootFilesystem = true
    linuxParameters = {
      initProcessEnabled = true
      capabilities = {
        drop = ["ALL"]
      }
    }
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.workload["otel"].name
        awslogs-region        = var.aws_region
        awslogs-stream-prefix = "ecs"
        mode                  = "non-blocking"
        max-buffer-size       = "25m"
      }
    }
  }

  api_desired_count    = var.application_image_digest == null ? 0 : var.api_desired_count
  worker_desired_count = var.application_image_digest == null ? 0 : var.worker_desired_count
}

resource "aws_ecs_cluster" "this" {
  name = local.name_prefix

  setting {
    name  = "containerInsights"
    value = "enhanced"
  }
}

resource "aws_ecs_cluster_capacity_providers" "this" {
  cluster_name       = aws_ecs_cluster.this.name
  capacity_providers = ["FARGATE", "FARGATE_SPOT"]

  default_capacity_provider_strategy {
    capacity_provider = "FARGATE"
    weight            = 1
  }
}

# Public reachability is intentional for the portfolio API; security groups
# restrict the ALB to web ingress and tasks accept traffic only from this ALB.
#trivy:ignore:AVD-AWS-0053
resource "aws_lb" "api" {
  name                       = substr("${local.name_prefix}-api", 0, 32)
  internal                   = false
  load_balancer_type         = "application"
  security_groups            = [aws_security_group.load_balancer.id]
  subnets                    = [for subnet in aws_subnet.public : subnet.id]
  drop_invalid_header_fields = true
  enable_deletion_protection = var.load_balancer_deletion_protection
  idle_timeout               = 60
}

resource "aws_lb_target_group" "api" {
  name                 = substr("${local.name_prefix}-api", 0, 32)
  port                 = 8000
  protocol             = "HTTP"
  target_type          = "ip"
  vpc_id               = aws_vpc.this.id
  deregistration_delay = 30

  health_check {
    enabled             = true
    healthy_threshold   = 2
    interval            = 30
    matcher             = "200"
    path                = "/readyz"
    port                = "traffic-port"
    protocol            = "HTTP"
    timeout             = 5
    unhealthy_threshold = 3
  }
}

resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.api.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type = "redirect"

    redirect {
      port        = "443"
      protocol    = "HTTPS"
      status_code = "HTTP_301"
    }
  }
}

resource "aws_lb_listener" "https" {
  load_balancer_arn = aws_lb.api.arn
  port              = 443
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  certificate_arn   = var.load_balancer_certificate_arn

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.api.arn
  }
}

resource "aws_ecs_task_definition" "api" {
  family                   = "${local.name_prefix}-api"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = tostring(var.api_cpu)
  memory                   = tostring(var.api_memory_mib)
  execution_role_arn       = aws_iam_role.task_execution.arn
  task_role_arn            = aws_iam_role.application_task.arn

  runtime_platform {
    cpu_architecture        = var.cpu_architecture
    operating_system_family = "LINUX"
  }

  dynamic "volume" {
    for_each = toset(["artifacts", "reports", "scratch"])
    content {
      name = volume.value
    }
  }

  container_definitions = jsonencode([
    merge(local.container_security, {
      name        = "api"
      image       = local.application_image
      essential   = true
      command     = ["python", "-m", "uvicorn", "ragops.api:app", "--host", "0.0.0.0", "--port", "8000"]
      environment = local.application_environment
      secrets     = local.application_secrets
      mountPoints = local.container_mount_points
      dependsOn = [{
        containerName = "aws-otel-collector"
        condition     = "START"
      }]
      portMappings = [{
        name          = "http"
        containerPort = 8000
        hostPort      = 8000
        protocol      = "tcp"
        appProtocol   = "http"
      }]
      healthCheck = {
        command = [
          "CMD-SHELL",
          "python -c \"import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=2)\"",
        ]
        interval    = 30
        retries     = 3
        startPeriod = 120
        timeout     = 5
      }
      stopTimeout = 30
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = aws_cloudwatch_log_group.workload["api"].name
          awslogs-region        = var.aws_region
          awslogs-stream-prefix = "ecs"
          mode                  = "non-blocking"
          max-buffer-size       = "25m"
        }
      }
    }),
    local.adot_container,
  ])
}

resource "aws_ecs_task_definition" "worker" {
  family                   = "${local.name_prefix}-worker"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = tostring(var.worker_cpu)
  memory                   = tostring(var.worker_memory_mib)
  execution_role_arn       = aws_iam_role.task_execution.arn
  task_role_arn            = aws_iam_role.application_task.arn

  runtime_platform {
    cpu_architecture        = var.cpu_architecture
    operating_system_family = "LINUX"
  }

  dynamic "volume" {
    for_each = toset(["artifacts", "reports", "scratch"])
    content {
      name = volume.value
    }
  }

  container_definitions = jsonencode([
    merge(local.container_security, {
      name        = "worker"
      image       = local.application_image
      essential   = true
      command     = ["ragops", "worker"]
      environment = local.application_environment
      secrets     = local.application_secrets
      mountPoints = local.container_mount_points
      dependsOn = [{
        containerName = "aws-otel-collector"
        condition     = "START"
      }]
      stopTimeout = 120
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = aws_cloudwatch_log_group.workload["worker"].name
          awslogs-region        = var.aws_region
          awslogs-stream-prefix = "ecs"
          mode                  = "non-blocking"
          max-buffer-size       = "25m"
        }
      }
    }),
    local.adot_container,
  ])
}

resource "aws_ecs_task_definition" "migration" {
  family                   = "${local.name_prefix}-migration"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = "512"
  memory                   = "1024"
  execution_role_arn       = aws_iam_role.task_execution.arn

  runtime_platform {
    cpu_architecture        = var.cpu_architecture
    operating_system_family = "LINUX"
  }

  volume {
    name = "scratch"
  }

  container_definitions = jsonencode([
    merge(local.container_security, {
      name        = "migration"
      image       = local.application_image
      essential   = true
      command     = ["python", "-m", "alembic", "upgrade", "head"]
      environment = local.application_environment
      secrets     = local.database_secrets
      mountPoints = [{
        sourceVolume  = "scratch"
        containerPath = "/tmp"
        readOnly      = false
      }]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = aws_cloudwatch_log_group.workload["migration"].name
          awslogs-region        = var.aws_region
          awslogs-stream-prefix = "ecs"
          mode                  = "non-blocking"
          max-buffer-size       = "25m"
        }
      }
    }),
  ])
}

# This task is invoked with ECS command overrides for ingestion, report
# generation, or other administrative CLI operations. It is never a service.
resource "aws_ecs_task_definition" "utility" {
  family                   = "${local.name_prefix}-utility"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = tostring(var.worker_cpu)
  memory                   = tostring(var.worker_memory_mib)
  execution_role_arn       = aws_iam_role.task_execution.arn
  task_role_arn            = aws_iam_role.application_task.arn

  runtime_platform {
    cpu_architecture        = var.cpu_architecture
    operating_system_family = "LINUX"
  }

  dynamic "volume" {
    for_each = toset(["artifacts", "reports", "scratch"])
    content {
      name = volume.value
    }
  }

  container_definitions = jsonencode([
    merge(local.container_security, {
      name        = "utility"
      image       = local.application_image
      essential   = true
      command     = ["ragops", "--version"]
      environment = local.application_environment
      secrets     = local.application_secrets
      mountPoints = local.container_mount_points
      stopTimeout = 120
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = aws_cloudwatch_log_group.workload["utility"].name
          awslogs-region        = var.aws_region
          awslogs-stream-prefix = "ecs"
          mode                  = "non-blocking"
          max-buffer-size       = "25m"
        }
      }
    }),
  ])
}

resource "aws_ecs_service" "api" {
  name                              = "${local.name_prefix}-api"
  cluster                           = aws_ecs_cluster.this.id
  task_definition                   = aws_ecs_task_definition.api.arn
  desired_count                     = local.api_desired_count
  health_check_grace_period_seconds = 180
  enable_ecs_managed_tags           = true
  propagate_tags                    = "SERVICE"
  wait_for_steady_state             = true

  capacity_provider_strategy {
    capacity_provider = "FARGATE"
    weight            = 1
  }

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  network_configuration {
    assign_public_ip = var.nat_gateway_mode == "none"
    security_groups  = [aws_security_group.application.id]
    subnets = var.nat_gateway_mode == "none" ? (
      [for subnet in aws_subnet.public : subnet.id]
    ) : [for subnet in aws_subnet.private : subnet.id]
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.api.arn
    container_name   = "api"
    container_port   = 8000
  }

  depends_on = [
    aws_ecs_cluster_capacity_providers.this,
    aws_lb_listener.http,
    aws_lb_listener.https,
  ]
}

resource "aws_ecs_service" "worker" {
  name                    = "${local.name_prefix}-worker"
  cluster                 = aws_ecs_cluster.this.id
  task_definition         = aws_ecs_task_definition.worker.arn
  desired_count           = local.worker_desired_count
  enable_ecs_managed_tags = true
  propagate_tags          = "SERVICE"
  wait_for_steady_state   = true

  capacity_provider_strategy {
    capacity_provider = var.worker_use_spot ? "FARGATE_SPOT" : "FARGATE"
    weight            = 1
  }

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  network_configuration {
    assign_public_ip = var.nat_gateway_mode == "none"
    security_groups  = [aws_security_group.application.id]
    subnets = var.nat_gateway_mode == "none" ? (
      [for subnet in aws_subnet.public : subnet.id]
    ) : [for subnet in aws_subnet.private : subnet.id]
  }

  depends_on = [aws_ecs_cluster_capacity_providers.this]
}
