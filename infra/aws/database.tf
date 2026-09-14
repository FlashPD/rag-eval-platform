resource "aws_db_subnet_group" "this" {
  name       = local.name_prefix
  subnet_ids = [for subnet in aws_subnet.private : subnet.id]

  tags = { Name = local.name_prefix }
}

resource "aws_db_parameter_group" "this" {
  name   = "${local.name_prefix}-postgres16"
  family = "postgres16"

  parameter {
    name  = "log_min_duration_statement"
    value = "1000"
  }
}

resource "aws_db_instance" "this" {
  identifier = local.name_prefix

  engine         = "postgres"
  engine_version = "16"
  instance_class = var.database_instance_class

  allocated_storage     = var.database_allocated_storage_gib
  max_allocated_storage = var.database_max_storage_gib
  storage_type          = "gp3"
  storage_encrypted     = true

  db_name                     = "ragops"
  username                    = "ragops_admin"
  manage_master_user_password = true
  port                        = 5432

  db_subnet_group_name   = aws_db_subnet_group.this.name
  parameter_group_name   = aws_db_parameter_group.this.name
  vpc_security_group_ids = [aws_security_group.database.id]
  publicly_accessible    = false
  multi_az               = var.database_multi_az

  backup_retention_period    = 7
  backup_window              = "03:00-04:00"
  maintenance_window         = "sun:04:00-sun:05:00"
  auto_minor_version_upgrade = true
  apply_immediately          = true
  copy_tags_to_snapshot      = true
  deletion_protection        = var.database_deletion_protection
  skip_final_snapshot        = var.database_skip_final_snapshot
  final_snapshot_identifier  = var.database_skip_final_snapshot ? null : "${local.name_prefix}-final"

  performance_insights_enabled = false

  lifecycle {
    precondition {
      condition     = !var.database_deletion_protection || !var.database_skip_final_snapshot
      error_message = "A deletion-protected database must retain a final snapshot."
    }
  }
}
