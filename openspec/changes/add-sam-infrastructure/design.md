## Context

The application is a FastAPI service that calls Athena and S3. It must run as a single Lambda function fronted by API Gateway, with all infrastructure managed declaratively. The previous `vex-query-layer` change drafted an `sam-infrastructure` spec; this change ships the actual `template.yaml` and `samconfig.toml`.

Existing constraints driving this design:
- Lambda runtime: Python 3.12 (matches local dev).
- App entry point: `handler = Mangum(app)` in `app/main.py` (delivered by `add-athena-query-routes`).
- Athena query polling cap: 60 seconds (set in `athena.py`); Lambda timeout must exceed this.
- Bucket name `vex-data`, Glue DB `vex_data`, Athena workgroup `vex-data-wg`, output prefix `s3://vex-data/athena-results/` — already referenced throughout `app/config.py` and `query_rule.md`.

## Goals / Non-Goals

**Goals:**
- One SAM stack creates every resource — no manual console setup.
- Lambda starts on cold-start fast enough for a usable API (target < 3s cold start).
- IAM scoped to the resources the app actually uses (no `Resource: "*"` for S3 or `*` action sets where avoidable).
- `sam deploy` after the first run is fully non-interactive.
- Environment variables are injected at the Globals level so every (future) function inherits the same config without duplication.

**Non-Goals:**
- VPC / private subnets — the Lambda is public-facing via API Gateway and does not need VPC access.
- Custom domain / TLS certificate — clients can call the raw `*.execute-api.amazonaws.com` URL for now.
- Provisioned concurrency / reserved concurrency — pay-per-invoke is fine at current expected volume.
- Authentication / authorization on the API — out of scope; queries are read-only and the data is public VEX results.
- CI/CD pipeline — `sam deploy` runs manually for now.

## Decisions

### 1. AWS SAM (Serverless Application Model), not plain CloudFormation or CDK

SAM is a thin layer over CloudFormation that adds `AWS::Serverless::Function` and `AWS::Serverless::HttpApi`, which collapse 5-10 lines of CFN each.

**Why:** The project is small, single-function, and Python — SAM's conveniences (auto-zip, easy local testing via `sam local`) are exactly the right fit. CDK would add a TypeScript build step; raw CFN would be more verbose.

### 2. Single Lambda function handling all routes via Mangum

The whole FastAPI app is wrapped by `Mangum` and routed from a single `Path: /{proxy+}` catch-all in API Gateway.

**Why:** Routes share imports (`boto3`, `pydantic`, `query_builder`) — splitting per-route would mean duplicating layers or zips. Cold start is dominated by the import graph, and one warm container can serve all routes.

### 3. Bucket name is a hard literal `vex-data`, not parameterized

`AWS::S3::Bucket` `Properties.BucketName: vex-data`. The `S3_BUCKET` env var is also literal `vex-data`.

**Why:** The codebase (DDLs, partition paths, search docs) all reference `vex-data` by name. Parameterizing it would force every developer to remember a different name and would invalidate seeded data. The trade-off: a second deploy of this stack to a different account requires renaming first.

### 4. Lambda timeout = 90s, memory = 512 MB

Athena polling caps at 60s, plus ~25s headroom for connection setup, result fetch, and Mangum overhead.

**Why:** Cheaper than 1024 MB; 512 MB gets ~0.3 vCPU which is enough for the SQL builder and result marshaling. We can bump if profiling shows it.

### 5. IAM policy structure

Inline policies on a single role:
- **S3**: `s3:GetObject`, `s3:PutObject`, `s3:ListBucket` scoped to `arn:aws:s3:::vex-data` and `arn:aws:s3:::vex-data/*`.
- **Athena**: `athena:StartQueryExecution`, `athena:GetQueryExecution`, `athena:GetQueryResults`, `athena:StopQueryExecution` scoped to the `vex-data-wg` workgroup ARN.
- **Glue**: `glue:GetTable`, `glue:GetTables`, `glue:GetDatabase`, `glue:CreateTable`, `glue:UpdateTable` scoped to the `vex_data` database and its tables.
- **CloudWatch Logs**: via the managed `AWSLambdaBasicExecutionRole` policy.

**Why:** "Least privilege" is the spec; this is the minimum surface for the routes that exist today (`/query/create-tables` needs Glue DDL; `/query/execute` needs Athena query + S3 read for results staging).

### 6. `samconfig.toml` schema

```toml
version = 0.1

[default.global.parameters]
stack_name = "vex-data"

[default.deploy.parameters]
region = "us-east-1"
resolve_s3 = true
capabilities = "CAPABILITY_IAM"
confirm_changeset = false
disable_rollback = false
parameter_overrides = "RobotEventsApiKey=\"<filled-on-first-deploy>\""
```

`resolve_s3 = true` lets SAM manage the deploy artifact bucket automatically (no need for a pre-created bucket).

### 7. Parameters vs hardcoded values

- **Parameter** (`RobotEventsApiKey`): secret value, NoEcho, filled on first `sam deploy --guided` and persisted in `samconfig.toml`.
- **Parameter** (`AthenaDatabase`, default `vex_data`): user-overridable but rarely changed.
- **Hardcoded** (`BucketName: vex-data`, `WorkGroupName: vex-data-wg`): see Decision 3.

## Risks / Trade-offs

- **Bucket name collision** → `vex-data` may already be taken globally. Mitigation: if first `sam deploy` fails on bucket creation, owner can rename in `template.yaml` and search-replace `S3_BUCKET` / partition path references. Documented in deploy notes.
- **Glue database name collision within account** → less likely; `vex_data` is project-specific. Mitigation: same as above — rename `AthenaDatabase` parameter if needed.
- **`CAPABILITY_IAM` required** → `sam deploy` will fail without `--capabilities CAPABILITY_IAM`; this is persisted in `samconfig.toml` so subsequent deploys work, but the first `--guided` flow must accept it.
- **No rollback on failure mid-stack** → If e.g. the Athena workgroup creation fails after the S3 bucket is created, CFN rolls the whole stack back by default. Acceptable for greenfield deploys.
- **Lambda zip size** → boto3 is ~50 MB; with our deps the zip should be under the 250 MB unzipped limit, but if it grows we'll move to a container image (`PackageType: Image`).
- **Athena cost** → unbounded if a user sends an expensive query. Mitigation deferred (`selectTop` cap of 1000 in the builder is the current control); future work: scan-bytes limit in workgroup config.
