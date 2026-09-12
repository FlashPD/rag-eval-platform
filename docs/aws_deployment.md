# AWS deployment

Phase 3 deploys ragops to ECS on Fargate with private RDS PostgreSQL, versioned S3 artifacts, ECR,
Secrets Manager, CloudWatch, and X-Ray. Infrastructure is split into two Terraform roots:

- `infra/bootstrap` creates the versioned state bucket and the GitHub OIDC plan/apply roles.
- `infra/aws` creates application infrastructure and uses the bootstrap bucket as an S3 backend
  with native lockfiles.

The split prevents the stack from trying to create the bucket and role needed to manage its own
state. Bootstrap state stays local and contains no application secrets; store its state securely.

Before applying the application stack, provision and validate an ACM certificate in the deployment
region and set `load_balancer_certificate_arn` in `terraform.tfvars`. Create a DNS alias for the
load balancer after apply. The HTTP listener redirects to HTTPS and the API is served only through
the TLS listener.

## Security and cost choices

- RDS is always private, encrypted, backed up for seven days, and uses an RDS-managed master
  password in Secrets Manager. Terraform stores the secret ARN, never the password value.
- The artifact and state buckets block all public access, use encryption and versioning, and retain
  recoverable object history.
- The alarm topic uses the AWS-managed SNS KMS key. Alarm payloads contain no customer data or
  secrets, so a broader customer-key policy for CloudWatch and SNS is not justified here.
- Pull requests receive no AWS credentials. After review, pushes to protected `dev` can assume a
  read-only plan role. Applies use the protected `production` GitHub environment, whose OIDC
  subject is distinct and should require manual approval.
- `nat_gateway_mode = "none"` is the destroyable portfolio default. ECS tasks will run in public
  subnets with restrictive security groups while RDS remains private. `single` keeps tasks private
  with one NAT gateway; `per_az` removes that single-AZ egress dependency at higher hourly cost.
- RDS deletion protection and Multi-AZ are configurable. Enable both for a persistent environment;
  leave them off when the environment must be inexpensive to destroy and recreate.

## Bootstrap once

Authenticate locally with an AWS administrator role, then:

```bash
terraform -chdir=infra/bootstrap init
terraform -chdir=infra/bootstrap apply \
  -var='github_repository=FlashPD/rag-eval-platform'
terraform -chdir=infra/bootstrap output
```

If the AWS account already has `token.actions.githubusercontent.com` configured as an IAM OIDC
provider, add `-var='create_github_oidc_provider=false'`.

Create a protected GitHub environment named `production`, require a reviewer, restrict deployment
branches to protected `dev`, and set these repository variables from the bootstrap outputs:

| Repository variable | Bootstrap output |
|---|---|
| `AWS_TERRAFORM_STATE_BUCKET` | `state_bucket_name` |
| `AWS_TERRAFORM_STATE_KEY` | `state_key` |
| `AWS_TERRAFORM_PLAN_ROLE_ARN` | `terraform_plan_role_arn` |
| `AWS_TERRAFORM_APPLY_ROLE_ARN` | `terraform_apply_role_arn` |

Also set `AWS_ACM_CERTIFICATE_ARN` to the validated certificate ARN. Unlike the four bootstrap
outputs, this value comes from the certificate you provisioned for the public API hostname.
Optionally set `AWS_ALARM_NOTIFICATION_EMAIL`; AWS sends a confirmation request before that address
receives alarm and recovery notifications.

The trust policies bind the plan role to this repository's `dev` branch and the apply role to the
protected environment. No AWS access keys are stored in GitHub.

## Plan and apply

For a local plan, initialize the partial backend with the bucket printed above:

```bash
terraform -chdir=infra/aws init \
  -backend-config='bucket=YOUR_STATE_BUCKET' \
  -backend-config='key=ragops/production/terraform.tfstate' \
  -backend-config='region=us-east-1'
terraform -chdir=infra/aws plan
```

Pull requests that touch `infra/**` run credential-free formatting, initialization, validation,
and Trivy scanning. Once reviewed changes merge to protected `dev`, the workflow runs an AWS-backed
plan. Use the **AWS infrastructure** workflow's manual dispatch to plan or apply through the
protected environment. The workflow carries the currently deployed image digest and desired counts
forward from Terraform state, so an infrastructure-only apply cannot replace a live release—or a
failed migration's safe zero-count state—with default values.

After the first apply, populate the empty provider and API-authentication secrets without putting
plaintext credentials in Terraform or shell history:

```bash
aws secretsmanager put-secret-value \
  --secret-id "$(terraform -chdir=infra/aws output -raw openai_api_key_secret_arn)" \
  --secret-string file://openai-secret.txt

openssl rand -base64 32 > ragops-api-key.txt
python -c 'import hashlib,json,sys; key=sys.stdin.read().strip(); print(json.dumps([hashlib.sha256(key.encode()).hexdigest()]))' \
  < ragops-api-key.txt > api-key-hashes.json
aws secretsmanager put-secret-value \
  --secret-id "$(terraform -chdir=infra/aws output -raw api_key_hashes_secret_arn)" \
  --secret-string file://api-key-hashes.json
```

The provider file must contain only the OpenAI key and should be deleted securely afterward. Store
the generated ragops plaintext key in a password manager before deleting the local files; clients
send that value in the `X-API-Key` header. ECS receives only the JSON array of hashes, and the API
checks every configured digest with constant-time comparison. The release workflow refuses to
start services until both secrets have values and the authentication secret has the expected shape.

Run the **Deploy AWS release** workflow from protected `dev` after the initial infrastructure
apply and secret population. It assumes the environment-scoped apply role, resolves the
Terraform-created ECR repository, builds `linux/amd64`, fails on high or critical Trivy findings,
and pushes the commit SHA as an immutable tag. It then resolves the registry digest, stages the new
task definitions with both services at zero, requires the one-off migration container to exit zero,
and only then scales the services. The workflow finishes by waiting for stable ECS services and a
healthy ALB target. Infrastructure applies and releases share one concurrency group so they cannot
race on the same state. If migration or rollout fails and an older release exists, a final recovery
step restores its digest and service counts. A failed first release remains safely scaled to zero.

## ECS runtime

The application stack defines an ECS cluster, public Application Load Balancer, API and worker
services, and one-off migration and utility task definitions. Task containers run as UID 10001,
drop Linux capabilities, use read-only root filesystems with explicit scratch/artifact mounts, and
write logs to workload-specific CloudWatch log groups. API tasks use regular Fargate capacity;
resumable workers use Fargate Spot by default.

API and worker tasks each include the version-pinned AWS Distro for OpenTelemetry collector as an
essential sidecar. Application traces and metrics use OTLP/HTTP over the task-local network; the
collector exports traces to X-Ray and low-cardinality `RagOps` metrics to CloudWatch. Terraform also
creates a CloudWatch service dashboard, alarms for target 5xx rate, p95 latency, ECS CPU, RDS
free storage, and hourly LLM cost, plus an SNS operations topic. Collector configuration is checked
in at `infra/aws/otel-collector.yaml`, and the sidecar runs with a read-only root filesystem.

RDS host metadata is injected as ordinary environment configuration. The RDS-managed JSON secret's
`username` and `password` keys are injected directly by ECS, so neither credential enters Terraform
state or an image. The task execution role can read only the RDS, API-hash, and OpenAI secrets,
while the task role is limited to the artifact bucket, its KMS key, and the CloudWatch/X-Ray
telemetry APIs.

The initial apply uses a placeholder image reference and forces both services to zero tasks. After
an image has been pushed to ECR, register its immutable digest without starting services:

```bash
terraform -chdir=infra/aws apply \
  -var='application_image_digest=sha256:YOUR_ECR_DIGEST' \
  -var='api_desired_count=0' \
  -var='worker_desired_count=0'
```

Run the migration task with the network configuration exported by Terraform, wait for it to stop,
and require container exit code zero before scaling either service. The release workflow automates
these AWS CLI steps; the underlying values are available as
`ecs_cluster_name`, `migration_task_definition_arn`, and `ecs_network_configuration_json` outputs.

After a successful migration, start the services:

```bash
terraform -chdir=infra/aws apply \
  -var='application_image_digest=sha256:YOUR_ECR_DIGEST'
```

Use the utility task definition with an ECS command override for one-off operations such as
`ragops ingest --dataset scifact` or `ragops eval report RUN_ID`. It receives the same database and
artifact configuration as the services, and completed ingestion/report artifacts are published to
the private S3 bucket before the task exits.

## Teardown

The application stack is designed to be removed when idle:

```bash
terraform -chdir=infra/aws destroy
```

The destroyable default skips the final RDS snapshot. Set `database_skip_final_snapshot = false`
for a persistent environment that needs a recovery point; retained snapshots continue to incur
storage charges. The bootstrap state bucket has `prevent_destroy`; retain it for future
recreations.
