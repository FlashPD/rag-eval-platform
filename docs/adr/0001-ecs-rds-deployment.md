# ADR 0001: Deploy on ECS Fargate with RDS PostgreSQL

- Status: accepted
- Date: 2026-09-11

## Context

The local platform already uses a containerized API, worker, PostgreSQL queue, pgvector retrieval,
and OpenTelemetry. The portfolio deployment should demonstrate production boundaries and automated
delivery without introducing an orchestration system that overwhelms the evaluation product itself.
It must also be inexpensive enough to create for a demo and destroy afterward.

## Decision

Deploy the API and evaluation worker as separate ECS Fargate services behind an Application Load
Balancer, with RDS PostgreSQL as their shared durable store. Use S3 for versioned artifacts, ECR for
immutable images, Secrets Manager for provider and database credentials, ADOT sidecars for X-Ray,
and CloudWatch for infrastructure metrics, logs, dashboards, and alarms. GitHub Actions authenticates
through a repository-and-environment-scoped OIDC role and runs Alembic as a one-off Fargate task.

Default demo networking avoids a NAT gateway by assigning public IPs to tasks in public subnets.
Their security group has no public ingress: only the ALB can reach API port 8000, while egress is
limited to HTTPS, VPC DNS, and RDS. A variable moves tasks into private subnets behind one NAT gateway
when the environment is kept online longer.

## Consequences

- The deployment mirrors local process boundaries and requires no Kubernetes control plane.
- API and worker deployments, scaling, health checks, and rollbacks are independently visible.
- RDS supports both pgvector data and durable queue semantics without adding another managed store.
- The public-subnet demo option reduces fixed cost but is not the preferred long-lived topology.
- S3 startup sync copies model and BM25 artifacts into each task's ephemeral storage. This is simple
  and reproducible, but increases cold-start time and duplicates bytes across tasks. EFS or native
  S3 artifact loading should be reconsidered if artifact size or service count grows materially.
- The first deployment may start services before the one-off migration finishes. API health remains
  available because startup is lazy; the workflow then migrates and explicitly rolls both services.
  Schema changes must therefore remain backward-compatible during rolling deployments.

## Alternatives considered

- EKS: rejected because cluster and platform operations add cost and complexity without improving
  the evaluation story at this scale.
- Lambda: rejected because local model loading, long evaluation jobs, and container size/runtime
  constraints are a poor fit.
- SQS: rejected for v1 because the existing leased PostgreSQL queue is tested and intentionally
  demonstrates durable work without duplicating the orchestration approach in `deep-research`.
- Always-private tasks with NAT: supported, but not the default because a mostly-idle portfolio
  environment should not pay the NAT gateway's fixed hourly cost.
