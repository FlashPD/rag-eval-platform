resource "aws_cloudwatch_log_group" "workload" {
  for_each = toset(["api", "worker", "migration", "utility", "otel"])

  name              = "/ecs/${local.name_prefix}/${each.key}"
  retention_in_days = var.log_retention_days
}

resource "aws_cloudwatch_log_group" "application_metrics" {
  name              = "/aws/metrics/${local.name_prefix}"
  retention_in_days = var.log_retention_days
}

# Alarm payloads contain no customer data or secrets. The AWS-managed SNS key
# avoids a broader customer-key policy for the CloudWatch and SNS services.
#trivy:ignore:AVD-AWS-0136
resource "aws_sns_topic" "operations" {
  name              = "${local.name_prefix}-operations"
  kms_master_key_id = "alias/aws/sns"
}

resource "aws_sns_topic_subscription" "operations_email" {
  count = var.alarm_notification_email == "" ? 0 : 1

  topic_arn = aws_sns_topic.operations.arn
  protocol  = "email"
  endpoint  = var.alarm_notification_email
}

resource "aws_cloudwatch_metric_alarm" "api_error_rate" {
  alarm_name          = "${local.name_prefix}-api-error-rate"
  alarm_description   = "The API target 5xx rate exceeded five percent with at least five requests."
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 1
  threshold           = 5
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.operations.arn]
  ok_actions          = [aws_sns_topic.operations.arn]

  metric_query {
    id          = "error_rate"
    expression  = "IF(requests >= 5, 100 * errors / requests, 0)"
    label       = "API target 5xx rate"
    return_data = true
  }

  metric_query {
    id          = "errors"
    return_data = false

    metric {
      namespace   = "AWS/ApplicationELB"
      metric_name = "HTTPCode_Target_5XX_Count"
      dimensions  = { LoadBalancer = aws_lb.api.arn_suffix }
      period      = 300
      stat        = "Sum"
    }
  }

  metric_query {
    id          = "requests"
    return_data = false

    metric {
      namespace   = "AWS/ApplicationELB"
      metric_name = "RequestCount"
      dimensions  = { LoadBalancer = aws_lb.api.arn_suffix }
      period      = 300
      stat        = "Sum"
    }
  }
}

resource "aws_cloudwatch_metric_alarm" "api_p95_latency" {
  alarm_name          = "${local.name_prefix}-api-p95-latency"
  alarm_description   = "The ALB target response p95 exceeded the eight-second answer objective."
  namespace           = "AWS/ApplicationELB"
  metric_name         = "TargetResponseTime"
  dimensions          = { LoadBalancer = aws_lb.api.arn_suffix }
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  period              = 300
  extended_statistic  = "p95"
  threshold           = 8
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.operations.arn]
  ok_actions          = [aws_sns_topic.operations.arn]
}

resource "aws_cloudwatch_metric_alarm" "service_cpu" {
  for_each = {
    api    = aws_ecs_service.api.name
    worker = aws_ecs_service.worker.name
  }

  alarm_name        = "${local.name_prefix}-${each.key}-cpu"
  alarm_description = "${each.key} CPU utilization remained above 85 percent for fifteen minutes."
  namespace         = "AWS/ECS"
  metric_name       = "CPUUtilization"
  dimensions = {
    ClusterName = aws_ecs_cluster.this.name
    ServiceName = each.value
  }
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 3
  period              = 300
  statistic           = "Average"
  threshold           = 85
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.operations.arn]
  ok_actions          = [aws_sns_topic.operations.arn]
}

resource "aws_cloudwatch_metric_alarm" "database_free_storage" {
  alarm_name          = "${local.name_prefix}-database-free-storage"
  alarm_description   = "RDS free storage fell below 2 GiB."
  namespace           = "AWS/RDS"
  metric_name         = "FreeStorageSpace"
  dimensions          = { DBInstanceIdentifier = aws_db_instance.this.identifier }
  comparison_operator = "LessThanThreshold"
  evaluation_periods  = 2
  period              = 300
  statistic           = "Average"
  threshold           = 2 * 1024 * 1024 * 1024
  treat_missing_data  = "breaching"
  alarm_actions       = [aws_sns_topic.operations.arn]
  ok_actions          = [aws_sns_topic.operations.arn]
}

resource "aws_cloudwatch_metric_alarm" "hourly_llm_cost" {
  alarm_name          = "${local.name_prefix}-hourly-llm-cost"
  alarm_description   = "Incremental generator and judge cost exceeded the configured hourly budget."
  namespace           = "RagOps"
  metric_name         = "ragops.llm.cost"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  period              = 3600
  statistic           = "Sum"
  threshold           = var.hourly_llm_cost_alarm_usd
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.operations.arn]
  ok_actions          = [aws_sns_topic.operations.arn]
}

resource "aws_cloudwatch_dashboard" "service" {
  dashboard_name = "${local.name_prefix}-service"
  dashboard_body = jsonencode({
    widgets = [
      {
        type   = "text"
        x      = 0
        y      = 0
        width  = 24
        height = 2
        properties = {
          markdown = "# ragops production\nALB health, ECS saturation, RDS capacity, and application OpenTelemetry signals."
        }
      },
      {
        type   = "metric"
        x      = 0
        y      = 2
        width  = 12
        height = 6
        properties = {
          title  = "API traffic and target errors"
          region = var.aws_region
          view   = "timeSeries"
          period = 300
          metrics = [
            ["AWS/ApplicationELB", "RequestCount", "LoadBalancer", aws_lb.api.arn_suffix, { stat = "Sum" }],
            ["AWS/ApplicationELB", "HTTPCode_Target_5XX_Count", "LoadBalancer", aws_lb.api.arn_suffix, { stat = "Sum" }],
          ]
        }
      },
      {
        type   = "metric"
        x      = 12
        y      = 2
        width  = 12
        height = 6
        properties = {
          title  = "API latency and healthy targets"
          region = var.aws_region
          view   = "timeSeries"
          period = 300
          metrics = [
            ["AWS/ApplicationELB", "TargetResponseTime", "LoadBalancer", aws_lb.api.arn_suffix, { stat = "p95" }],
            ["AWS/ApplicationELB", "HealthyHostCount", "LoadBalancer", aws_lb.api.arn_suffix, "TargetGroup", aws_lb_target_group.api.arn_suffix, { stat = "Minimum", yAxis = "right" }],
          ]
        }
      },
      {
        type   = "metric"
        x      = 0
        y      = 8
        width  = 12
        height = 6
        properties = {
          title  = "ECS CPU utilization"
          region = var.aws_region
          view   = "timeSeries"
          period = 300
          metrics = [
            ["AWS/ECS", "CPUUtilization", "ClusterName", aws_ecs_cluster.this.name, "ServiceName", aws_ecs_service.api.name, { stat = "Average", label = "API" }],
            ["AWS/ECS", "CPUUtilization", "ClusterName", aws_ecs_cluster.this.name, "ServiceName", aws_ecs_service.worker.name, { stat = "Average", label = "Worker" }],
          ]
        }
      },
      {
        type   = "metric"
        x      = 12
        y      = 8
        width  = 12
        height = 6
        properties = {
          title  = "ECS memory utilization"
          region = var.aws_region
          view   = "timeSeries"
          period = 300
          metrics = [
            ["AWS/ECS", "MemoryUtilization", "ClusterName", aws_ecs_cluster.this.name, "ServiceName", aws_ecs_service.api.name, { stat = "Average", label = "API" }],
            ["AWS/ECS", "MemoryUtilization", "ClusterName", aws_ecs_cluster.this.name, "ServiceName", aws_ecs_service.worker.name, { stat = "Average", label = "Worker" }],
          ]
        }
      },
      {
        type   = "metric"
        x      = 0
        y      = 14
        width  = 12
        height = 6
        properties = {
          title  = "RDS utilization"
          region = var.aws_region
          view   = "timeSeries"
          period = 300
          metrics = [
            ["AWS/RDS", "CPUUtilization", "DBInstanceIdentifier", aws_db_instance.this.identifier, { stat = "Average" }],
            ["AWS/RDS", "DatabaseConnections", "DBInstanceIdentifier", aws_db_instance.this.identifier, { stat = "Average", yAxis = "right" }],
          ]
        }
      },
      {
        type   = "metric"
        x      = 12
        y      = 14
        width  = 12
        height = 6
        properties = {
          title  = "Application telemetry"
          region = var.aws_region
          view   = "timeSeries"
          period = 300
          metrics = [
            ["RagOps", "ragops.http.server.duration", "service.name", local.name_prefix, { stat = "p95", label = "HTTP p95" }],
            ["RagOps", "ragops.retrieval.stage.duration", "service.name", local.name_prefix, { stat = "p95", label = "Retrieval-stage p95", yAxis = "right" }],
          ]
        }
      },
      {
        type   = "log"
        x      = 0
        y      = 20
        width  = 24
        height = 6
        properties = {
          title  = "Recent application errors"
          region = var.aws_region
          view   = "table"
          query = join(" | ", [
            "SOURCE '${aws_cloudwatch_log_group.workload["api"].name}' SOURCE '${aws_cloudwatch_log_group.workload["worker"].name}'",
            "fields @timestamp, @logStream, @message",
            "filter @message like /ERROR|Exception|Traceback/",
            "sort @timestamp desc",
            "limit 50",
          ])
        }
      },
    ]
  })
}
