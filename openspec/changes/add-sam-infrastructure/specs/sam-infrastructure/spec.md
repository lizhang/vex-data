## ADDED Requirements

### Requirement: SAM template provisions all required AWS resources
`template.yaml` SHALL define an AWS SAM template (`Transform: AWS::Serverless-2016-10-31`) that provisions an S3 bucket, Athena workgroup, Glue database, IAM execution role, Lambda function, and HTTP API Gateway in a single stack.

#### Scenario: sam build succeeds
- **WHEN** `sam build` is run from the project root
- **THEN** the build SHALL complete without errors and produce a `.aws-sam/build/` directory containing the packaged Lambda artifact

#### Scenario: sam deploy creates all resources
- **WHEN** `sam deploy --guided` is run against a target AWS account
- **THEN** CloudFormation SHALL create the following resources in one stack: `AWS::S3::Bucket` named `vex-data`, `AWS::Athena::WorkGroup` named `vex-data-wg`, `AWS::Glue::Database` named `vex_data`, `AWS::IAM::Role` for Lambda execution, `AWS::Serverless::Function` (Python 3.12) named `VexDataFunction`, and `AWS::Serverless::HttpApi` named `VexDataApi`
- **AND** the stack `Outputs` SHALL include an `ApiUrl` value pointing to the HTTP API base URL

#### Scenario: Stack idempotency on re-deploy
- **WHEN** `sam deploy` is run a second time with no template changes
- **THEN** CloudFormation SHALL report "No changes to deploy" and SHALL NOT recreate or modify any resource

### Requirement: Lambda function wraps FastAPI via Mangum
The `VexDataFunction` resource SHALL use `Handler: app.main.handler` and `Runtime: python3.12`. `app/main.py` exports `handler = Mangum(app)` so the Lambda entry point translates API Gateway HTTP events to ASGI requests for the FastAPI app.

#### Scenario: Local uvicorn startup is unaffected
- **WHEN** `uvicorn app.main:app --reload` is run locally
- **THEN** the server SHALL start and `POST /query/execute` SHALL be reachable at `http://localhost:8000`

#### Scenario: Lambda invocation via API Gateway
- **WHEN** the deployed Lambda receives an API Gateway HTTP event for `POST /query/execute`
- **THEN** Mangum SHALL translate it to an ASGI request and the FastAPI app SHALL handle it identically to the local case

### Requirement: Lambda timeout exceeds Athena polling cap
The Lambda function SHALL be configured with `Timeout: 90` (seconds) and `MemorySize: 512` (MB), giving 30 seconds of headroom above the 60-second Athena polling cap implemented in `athena.execute_query`.

#### Scenario: Long Athena query does not exceed Lambda timeout
- **WHEN** an Athena query runs for 55 seconds and returns SUCCEEDED
- **THEN** the Lambda SHALL complete and return the result rows without hitting its own 90s timeout

### Requirement: Environment variables are injected from SAM template
All runtime configuration SHALL be sourced from environment variables injected by `Globals.Function.Environment.Variables` so the Lambda function does NOT require a `.env` file at runtime.

#### Scenario: Required env vars are present at runtime
- **WHEN** the Lambda function is invoked
- **THEN** `S3_BUCKET`, `ATHENA_DATABASE`, `ATHENA_OUTPUT_LOCATION`, `AWS_REGION`, and `ROBOTEVENTS_API_KEY` SHALL be available as environment variables
- **AND** their values SHALL be derived from SAM template parameters or resource references (`!Ref`, `!Sub`, `!GetAtt`), not hardcoded duplications

### Requirement: IAM role grants least-privilege access
The Lambda execution role SHALL attach the managed `AWSLambdaBasicExecutionRole` policy for CloudWatch Logs AND an inline policy that grants ONLY the specific actions and resources the application needs.

#### Scenario: S3 access is scoped to vex-data bucket only
- **WHEN** the inline policy is evaluated
- **THEN** `s3:GetObject`, `s3:PutObject`, and `s3:ListBucket` SHALL be granted on `arn:aws:s3:::vex-data` and `arn:aws:s3:::vex-data/*` only — not `Resource: "*"`

#### Scenario: Athena access is scoped to workgroup
- **WHEN** the inline policy is evaluated
- **THEN** `athena:StartQueryExecution`, `athena:GetQueryExecution`, `athena:GetQueryResults`, and `athena:StopQueryExecution` SHALL be granted on the `vex-data-wg` workgroup ARN

#### Scenario: Glue access is scoped to vex_data database
- **WHEN** the inline policy is evaluated
- **THEN** `glue:GetTable`, `glue:GetTables`, `glue:GetDatabase`, `glue:CreateTable`, and `glue:UpdateTable` SHALL be granted on the `vex_data` Glue database and its tables — not on all Glue resources

### Requirement: Athena workgroup writes results to vex-data bucket
The `AthenaWorkgroup` SHALL be configured with `WorkGroupConfiguration.ResultConfiguration.OutputLocation = s3://vex-data/athena-results/` and `EnforceWorkGroupConfiguration = true`, so client-side overrides cannot redirect query results elsewhere.

#### Scenario: Query results land in vex-data bucket
- **WHEN** any query is submitted to the `vex-data-wg` workgroup
- **THEN** the result files SHALL be written under `s3://vex-data/athena-results/` regardless of the client's `ResultConfiguration` argument

### Requirement: HTTP API Gateway routes all paths to the Lambda
The `VexDataApi` SHALL define a single catch-all event mapping (`Path: /{proxy+}`, `Method: ANY`) on the Lambda function, so every route handled by the FastAPI app is reachable via the API Gateway URL.

#### Scenario: API Gateway forwards POST /query/execute
- **WHEN** a client sends `POST https://<api-id>.execute-api.<region>.amazonaws.com/query/execute` with a valid `SearchQuery` body
- **THEN** the request SHALL reach the FastAPI app's `/query/execute` handler and return the same response as a local `POST` to `http://localhost:8000/query/execute`

### Requirement: samconfig.toml persists deployment parameters
`samconfig.toml` SHALL store the default `stack_name`, `region`, capability flags, and parameter overrides so subsequent `sam deploy` calls run without prompts.

#### Scenario: Subsequent deploy is non-interactive
- **WHEN** `sam deploy` (without `--guided`) is run after the first deployment
- **THEN** it SHALL read all parameters from `samconfig.toml`, proceed without prompting, and update the stack in place

#### Scenario: CAPABILITY_IAM is persisted
- **WHEN** `samconfig.toml` is read
- **THEN** the `[default.deploy.parameters]` section SHALL contain `capabilities = "CAPABILITY_IAM"`

### Requirement: SAM template parameter for RobotEventsApiKey
`template.yaml` SHALL declare a `RobotEventsApiKey` parameter with `Type: String` and `NoEcho: true`, and inject its value into the Lambda environment as `ROBOTEVENTS_API_KEY`.

#### Scenario: API key is not echoed in CloudFormation events
- **WHEN** `sam deploy` is run and a value is provided for `RobotEventsApiKey`
- **THEN** CloudFormation events and outputs SHALL NOT display the raw key value (NoEcho behavior)
