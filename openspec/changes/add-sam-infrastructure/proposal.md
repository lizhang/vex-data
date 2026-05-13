## Why

The query layer (builder + Athena execution + FastAPI routes) is implemented and runs locally under uvicorn, but there is no way to deploy it. AWS infrastructure (S3 bucket, Athena workgroup, Glue database, IAM role, Lambda function, HTTP API Gateway) must be provisioned, and the Python app must be packaged for Lambda. This change adds the SAM template and config that turn `sam deploy` into a one-command deploy of the entire stack.

## What Changes

- Add `template.yaml` — AWS SAM CloudFormation template that defines:
  - `VexDataBucket` (`AWS::S3::Bucket`, name `vex-data`, versioning enabled)
  - `AthenaWorkgroup` (`AWS::Athena::WorkGroup`, name `vex-data-wg`, output to `s3://vex-data/athena-results/`)
  - `GlueDatabase` (`AWS::Glue::Database`, name `vex_data`)
  - `AppRole` (`AWS::IAM::Role`, least-privilege: S3 on vex-data bucket only, Athena + Glue scoped to workgroup/db)
  - `VexDataFunction` (`AWS::Serverless::Function`, Python 3.12, handler `app.main.handler`, 90s timeout, 512 MB memory)
  - `VexDataApi` (`AWS::Serverless::HttpApi`, catch-all route → Lambda)
- Add `samconfig.toml` — persists `stack_name`, `region`, deploy bucket, and parameter overrides so subsequent `sam deploy` calls run non-interactively.
- Add `mangum` to `requirements.txt` if not already present (the Mangum handler is wired by the `add-athena-query-routes` change, but the dependency is verified here).
- Document the deploy workflow (`sam build` → `sam deploy --guided` → `sam deploy`) in `CLAUDE.md` if needed.

## Capabilities

### New Capabilities

- `sam-infrastructure`: AWS SAM template and config that provisions the full deployment stack (S3, Athena, Glue, IAM, Lambda, API Gateway) and enables one-command deploys via `sam deploy`.

### Modified Capabilities

_(none — this is purely additive.)_

## Impact

- **New files**: `template.yaml`, `samconfig.toml` (project root).
- **Existing files touched**: `requirements.txt` (verify `mangum` present); no app code changes.
- **AWS resources created on first deploy**: S3 bucket, Athena workgroup, Glue database, IAM role, Lambda function, HTTP API Gateway, CloudWatch log group.
- **Cost surface**: minimal at idle (S3 + Glue catalog metadata); Athena scans + Lambda invocations are pay-per-use.
- **Prerequisites**: AWS CLI configured with credentials that can create the resources above; SAM CLI installed locally.
- **No breaking changes**: local `uvicorn app.main:app --reload` workflow is unchanged.
