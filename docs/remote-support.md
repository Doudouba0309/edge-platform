# Remote support

The default support path is **evidence first**, not a remote shell.

## Live pieces

- Collector JSON logs are shipped by `aws.greengrass.LogManager` 2.3.14.
- Log group: `/aws/greengrass/UserComponent/ap-southeast-1/io.github.doudouba0309.EdgePlatform.Collector`
- System log group: `/aws/greengrass/GreengrassSystemComponent/ap-southeast-1/System`
- Heartbeat log event: `status published: heartbeat`
- CloudWatch alarm: `edge-platform-sandbox-heartbeat-missing` (5 minutes, missing = breaching)
- SNS topic: `edge-platform-sandbox-alerts` (subscribe the support address)
- Log retention: 30 days (CloudWatch) and 30 days for `support/` objects.
- No inbound SSH; no shell is exposed by default.

## Support bundle upload

```bash
# On the gateway or a support machine with the bundle:
scripts/upload-support-bundle.sh --bundle support-bundle-*.zip
```

The script uploads to `s3://$S3_BUCKET/support/` and prints a 7-day presigned
URL. Use `--dry-run` to inspect the key first.

## Remote tunnel

Only after a site approves interactive access:

```bash
scripts/open-support-tunnel.sh --thing edge-platform-sandbox-core --dry-run
```

The core must run `aws.greengrass.SecureTunneling` and an approved destination
service. The collector image does not install an SSH server, so a tunnel cannot
be used to obtain a shell by default. This is deliberate.

## Role policy

The live TES role must grant `logs:DescribeLogStreams` in addition to create/put.
The canonical template is `deploy/aws/tes-role-policy.json.tmpl`; render
`__REGION__`, `__ACCOUNT_ID__` and `__BUCKET__` before applying it.

## Alarm

The heartbeat alarm is only useful when the SNS topic has a subscriber. Add one:

```bash
aws sns subscribe --topic-arn "$(aws sns list-topics --query "Topics[?contains(TopicArn,'edge-platform-sandbox-alerts')].TopicArn" --output text)" \
  --protocol email --notification-endpoint support@example.com
```

Replace the endpoint with the client-approved support address. The helper
`scripts/subscribe-alerts.sh --email ...` does the same and prints the pending
subscription notice.
