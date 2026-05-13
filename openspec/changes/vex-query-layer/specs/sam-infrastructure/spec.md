## ADDED Requirements

### Requirement: SAM template provisions all required AWS resources
`template.yaml` SHALL define an AWS SAM template that provisions the S3 bucket, Athena workgroup, Glue database, IAM role, Lambda function, and HTTP API Gateway required by the application.

#### Scenario: sam build succeeds
- **WHEN** `sam build` is run from the project root
- **THEN** the build SHALL complete without errors and produce a `.aws-sam/build/` directory

#### Scenario: sam deploy creates all resources
- **WHEN** `sam deploy --guided` is run against a target AWS account
- **THEN** CloudFormation SHALL create: S3 bucket `vex-data`, Athena workgroup `vex-data-wg`, Glue database `vex_data`, IAM execution role, Lambda function `VexDataFunction`, HTTP API Gateway
- **AND** the stack Outputs SHALL include the API URL

### Requirement: Lambda function wraps FastAPI via Mangum
`app/main.py` SHALL export a `handler = Mangum(app)` symbol that serves as the AWS Lambda entry point. The same `app` object SHALL be usable with `uvicorn app.main:app` for local development.

#### Scenario: Local uvicorn startup
- **WHEN** `uvicorn app.main:app --reload` is run locally
- **THEN** the server SHALL start and `POST /query/execute` SHALL be reachable at `http://localhost:8000`

#### Scenario: Lambda invocation via API Gateway
- **WHEN** the deployed Lambda receives an API Gateway HTTP event
- **THEN** Mangum SHALL translate it to an ASGI request and the FastAPI app SHALL handle it identically to the local case

### Requirement: Environment variables are injected from SAM template
All runtime configuration SHALL be sourced from environment variables injected by the SAM `Globals.Function.Environment` block. The Lambda function SHALL NOT require a `.env` file.

#### Scenario: Required env vars are present at runtime
- **WHEN** the Lambda function is invoked
- **THEN** `S3_BUCKET`, `ATHENA_DATABASE`, `ATHENA_OUTPUT_LOCATION`, and `ROBOTEVENTS_API_KEY` SHALL be available as environment variables with values derived from SAM template parameters or resource references (`!Ref`, `!Sub`)

### Requirement: IAM role grants least-privilege access
The Lambda execution role SHALL grant only the permissions required: S3 read/write on the `vex-data` bucket, Athena query execution on the `vex-data-wg` workgroup, and Glue read/write for table DDL.

#### Scenario: Role allows S3 operations on vex-data bucket only
- **WHEN** the IAM policy is evaluated
- **THEN** `s3:GetObject`, `s3:PutObject`, `s3:ListBucket` SHALL be scoped to the `vex-data` bucket ARN and its objects — NOT `Resource: "*"`

#### Scenario: Role allows Athena and Glue
- **WHEN** the Lambda function calls `athena:StartQueryExecution` or `glue:GetTable`
- **THEN** the IAM policy SHALL permit those actions

### Requirement: samconfig.toml persists deployment parameters
`samconfig.toml` SHALL store the default stack name, region, S3 deployment bucket, and parameter overrides so that subsequent `sam deploy` calls require no interactive prompts.

#### Scenario: Subsequent deploy is non-interactive
- **WHEN** `sam deploy` (without `--guided`) is run after the first deployment
- **THEN** it SHALL read all parameters from `samconfig.toml` and proceed without prompting
