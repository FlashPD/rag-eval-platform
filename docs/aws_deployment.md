# AWS deployment

Phase 3 deploys ragops to ECS on Fargate with private RDS PostgreSQL, versioned S3 artifacts, ECR,
Secrets Manager, CloudWatch, and X-Ray. Infrastructure is split into two Terraform roots:

- `infra/bootstrap` creates the versioned state bucket and the GitHub OIDC plan/apply roles.
- `infra/aws` creates application infrastructure and uses the bootstrap bucket as an S3 backend
  with native lockfiles.

The split prevents the stack from trying to create the bucket and role needed to manage its own
state. Bootstrap state stays local and contains no application secrets; store its state securely.

## Security and cost choices

- RDS is always private, encrypted, backed up for seven days, and uses an RDS-managed master
  password in Secrets Manager. Terraform stores the secret ARN, never the password value.
- The artifact and state buckets block all public access, use encryption and versioning, and retain
  recoverable object history.
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

Create a protected GitHub environment named `production`, require a reviewer, and set these
repository variables from the bootstrap outputs:

| Repository variable | Bootstrap output |
|---|---|
| `AWS_TERRAFORM_STATE_BUCKET` | `state_bucket_name` |
| `AWS_TERRAFORM_STATE_KEY` | `state_key` |
| `AWS_TERRAFORM_PLAN_ROLE_ARN` | `terraform_plan_role_arn` |
| `AWS_TERRAFORM_APPLY_ROLE_ARN` | `terraform_apply_role_arn` |

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
protected environment.

After the first apply, populate the empty provider secret without putting it in Terraform or shell
history:

```bash
aws secretsmanager put-secret-value \
  --secret-id "$(terraform -chdir=infra/aws output -raw openai_api_key_secret_arn)" \
  --secret-string file://openai-secret.txt
```

The local file must contain only the API key and should be deleted securely afterward. ECS task
definitions are the next Phase 3 slice; they will consume this secret and the RDS-managed JSON
secret by ARN.

## Teardown

The application stack is designed to be removed when idle:

```bash
terraform -chdir=infra/aws destroy
```

The destroyable default skips the final RDS snapshot. Set `database_skip_final_snapshot = false`
for a persistent environment that needs a recovery point; retained snapshots continue to incur
storage charges. The bootstrap state bucket has `prevent_destroy`; retain it for future
recreations.
