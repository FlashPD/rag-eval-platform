# Zero-AWS-cost portfolio mode

Portfolio mode runs retrieval evaluations on a GitHub-hosted runner and commits only the generated
Markdown and JSON reports to a pull-request branch. It requests no AWS credentials, creates no AWS
resources, requires no domain, and does not call OpenAI.

This is the safe default. AWS infrastructure and release workflows remain disabled while the
repository variable `PORTFOLIO_MODE` is unset or set to `true`. Full AWS deployment requires the
deliberate value `PORTFOLIO_MODE=false`.

GitHub Actions usage may count against the repository owner's included minutes for private
repositories. The workflow itself creates zero AWS or model-provider cost.

## One-time GitHub setup

GitHub only displays a manually dispatched workflow after its workflow file exists on the default
branch. This repository's default branch is `main`, so first merge the portfolio-mode changes from
`dev` into `main`.

Then open the repository on GitHub and complete these steps:

1. Go to **Settings → Secrets and variables → Actions → Variables**.
2. Create a repository variable named `PORTFOLIO_MODE` with value `true`.
3. Go to **Settings → Actions → General → Workflow permissions**.
4. Select **Read and write permissions**.
5. Enable **Allow GitHub Actions to create and approve pull requests**, if that option is
   available, and save.

The workflow can still generate and push a report branch if repository policy prevents automatic
pull-request creation. Its summary will show the branch name so the pull request can be opened
manually.

## Generate a report

1. Open the repository's **Actions** tab.
2. Select **Publish portfolio evaluation**.
3. Choose **Run workflow** and use the `dev` branch.
4. Start with the `scifact` dataset and sample size `50`.
5. Wait for the workflow to finish. The first run is slower because it downloads models, ingests
   the dataset, and creates a reusable GitHub Actions cache.
6. Open the pull request created by the workflow and inspect `report.md` and `report.json`.
7. Merge the pull request into `dev` when the values look correct.

The committed files live under `evals/runs/<run-id>/`. They render directly on GitHub and remain
available after the temporary PostgreSQL service and runner have been deleted.

Use sample size `full` only when you want a headline-quality result. A 50-query run is the quicker
and cheaper validation path.

## Cost and safety behavior

| Workflow or resource | Portfolio-mode behavior |
|---|---|
| **Publish portfolio evaluation** | Uses GitHub runner and temporary PostgreSQL only |
| **AWS infrastructure** → `portfolio` | Validates Terraform, then creates nothing |
| **AWS infrastructure** → `plan` or `apply` | Refused unless `PORTFOLIO_MODE=false` |
| **Deploy AWS release** | Skipped unless `PORTFOLIO_MODE=false` |
| Scheduled answer evaluation | Disabled; manual runs remain possible |
| Domain, ACM, ALB, RDS, ECS, S3, KMS | Not required or created |
| OpenAI | Not called by the portfolio workflow |

AWS Billing Budgets are still recommended before any future full deployment. A budget alerts on
spend but does not stop resources automatically.

## Opt in to the full AWS deployment later

Only when the production-style AWS demonstration is wanted, change the repository variable to:

```text
PORTFOLIO_MODE=false
```

Then follow [AWS deployment](aws_deployment.md). That path creates resources with hourly or monthly
charges and requires a real domain plus an issued ACM certificate. Set the variable back to `true`
after destroying the application stack.
