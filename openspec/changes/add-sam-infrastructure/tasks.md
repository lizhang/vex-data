## 1. SAM template skeleton

- [x] 1.1 Create `template.yaml` with `AWSTemplateFormatVersion: '2010-09-09'` and `Transform: AWS::Serverless-2016-10-31`
- [x] 1.2 Add `Parameters` block: `RobotEventsApiKey` (Type: String, NoEcho: true), `AthenaDatabase` (Type: String, Default: `vex_data`)
- [x] 1.3 Add `Globals.Function` block with `Runtime: python3.12`, `Timeout: 90`, `MemorySize: 512`, and `Environment.Variables` for `S3_BUCKET`, `ATHENA_DATABASE`, `ATHENA_OUTPUT_LOCATION`, `AWS_REGION`, `ROBOTEVENTS_API_KEY`

## 2. AWS resources

- [x] 2.1 Add `VexDataBucket` (`AWS::S3::Bucket`, BucketName `vex-data`, VersioningConfiguration enabled)
- [x] 2.2 Add `GlueDatabase` (`AWS::Glue::Database`, name `!Ref AthenaDatabase`, CatalogId `!Ref AWS::AccountId`)
- [x] 2.3 Add `AthenaWorkgroup` (`AWS::Athena::WorkGroup`, Name `vex-data-wg`, ResultConfiguration.OutputLocation `!Sub s3://${VexDataBucket}/athena-results/`, EnforceWorkGroupConfiguration true)
- [x] 2.4 Add `AppRole` (`AWS::IAM::Role`) with assume-role policy for `lambda.amazonaws.com` and managed `AWSLambdaBasicExecutionRole`
- [x] 2.5 Add inline policy on `AppRole`: S3 actions scoped to vex-data bucket + objects; Athena actions scoped to `vex-data-wg` workgroup ARN; Glue actions scoped to `vex_data` database and its tables
- [x] 2.6 Add `VexDataFunction` (`AWS::Serverless::Function`) with `Handler: app.main.handler`, `CodeUri: .`, `Role: !GetAtt AppRole.Arn`
- [x] 2.7 Add `VexDataApi` (`AWS::Serverless::HttpApi`)
- [x] 2.8 Wire `VexDataFunction.Events.Api` to `VexDataApi` with `Path: /{proxy+}`, `Method: ANY`

## 3. Outputs and packaging

- [x] 3.1 Add `Outputs.ApiUrl` exposing `!Sub https://${VexDataApi}.execute-api.${AWS::Region}.amazonaws.com`
- [x] 3.2 Verify `requirements.txt` includes `mangum` (add if missing)
- [x] 3.3 Add `.aws-sam/` to `.gitignore` if not already present

## 4. samconfig.toml

- [x] 4.1 Create `samconfig.toml` with `version = 0.1`
- [x] 4.2 Add `[default.global.parameters]` with `stack_name = "vex-data"`
- [x] 4.3 Add `[default.deploy.parameters]`: `region = "us-east-1"`, `resolve_s3 = true`, `capabilities = "CAPABILITY_IAM"`, `confirm_changeset = false`, `disable_rollback = false`
- [x] 4.4 Add `parameter_overrides` line as a placeholder for `RobotEventsApiKey` (filled on first `sam deploy --guided`)

## 5. Verification

- [x] 5.1 `sam validate` reports no errors
- [ ] 5.2 `sam build` completes and produces `.aws-sam/build/VexDataFunction/`
- [ ] 5.3 `sam deploy --guided` succeeds end-to-end and creates all 6 resources in CloudFormation
- [ ] 5.4 Stack `Outputs.ApiUrl` is reachable; `POST <api>/query/create-tables` returns 200 with all 8 table names
- [ ] 5.5 `POST <api>/query/execute` with a sample `SearchQuery` returns 200 with rows
- [ ] 5.6 IAM policy is verified in the AWS console: no `Resource: "*"` for S3, Athena, or Glue actions
- [ ] 5.7 Re-run `sam deploy` (no flags) confirms non-interactive update with "No changes to deploy"
- [ ] 5.8 `RobotEventsApiKey` value is NOT visible in CloudFormation stack events or template parameters listing
