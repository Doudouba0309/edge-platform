# Environment Portability — Sandbox to Client

**Status:** current state, migration runbook and coupling audit
**Scope:** Git ownership, component namespace, AWS account, and every place the
current sandbox identity leaks into the repository.

## Current vs client environment

| Item | Current sandbox | Client target |
|---|---|---|
| Git remote | Personal repository | Client-owned organization/repository |
| Component namespace | `io.github.doudouba0309.EdgePlatform` | Client-owned reverse-DNS, e.g. `com.client.EdgePlatform` |
| AWS account | `632839730725` | Client-owned account |
| AWS profile | `edge-platform-admin` | Client-approved role/profile, no personal root |
| Region | `ap-southeast-1` | Client-approved region |
| Bucket | `edge-platform-sandbox-632839730725-ap-southeast-1` | Client-owned, private bucket |
| Thing/group | `edge-platform-sandbox-core` / `edge-platform-sandbox` | Client naming convention |
| TES role/alias | `edge-platform-sandbox-TESRole` / `...Alias` | Client IAM roles |
| SNS/logs | `edge-platform-sandbox-*` | Client-owned monitoring |

## 1. Git ownership

The Git remote and the Greengrass component namespace are **independent
concepts**, but both are currently personal:

- The repository is the source of the build and tests.
- The component namespace is the identity consumers use when resolving a
  component.
- The current namespace is a **placeholder**, not a technical dependency.

For client delivery:

1. Transfer or fork the repository into the client’s Git organization.
2. Preserve history and tags; do not preserve the personal remote as the
   canonical remote.
3. Make the client own the branch protection, CI credentials and release tags.
4. Do not copy `.env`, `certs/`, `var/` or any credential into the client repo.
5. Confirm the license/IP terms separately; the SOW says client ownership.

## 2. Component namespace migration

Changing `io.github.doudouba0309.EdgePlatform` is a **breaking component identity
change**, not a rename of a Git repository.

### Rules

- Published component versions are immutable.
- The old and new component names can coexist during migration.
- The new namespace should be a stable client-owned reverse-DNS prefix.
- Client and site names still never appear in component names.
- Bump the component version for the first release under the new namespace.

### Files and values to change

| Location | Current value | Change |
|---|---|---|
| `scripts/build-component.sh` | `GG_COMPONENT_NAME` default | Set the client component name |
| `deploy/greengrass/recipe.yaml.tmpl` | `__COMPONENT_NAME__` | Rendered from the new name |
| `deploy/greengrass/logmanager-config.json` | component name and work path | New component name/path |
| `tests/test_aws_artifacts.py` | hard-coded component name | Parameterize or update fixture |
| `docs/` | examples/log paths | Update current runbooks |
| `AGENTS.md` | namespace rule | Keep the rule, change the example |

### Procedure

1. Agree the client namespace and component name.
2. Add a build-time `GG_COMPONENT_NAMESPACE` or `GG_COMPONENT_NAME` override if not
   already sufficient.
3. Build and test the artifact under the new name.
4. Publish the new component version to the client bucket.
5. Create a client deployment using the new component.
6. Verify telemetry, status and logs.
7. Remove the old components from the client deployment.
8. Keep the sandbox namespace for the sandbox only.

Do not edit the published sandbox component in place.

## 3. AWS account migration

The current account is for development only. Never use a personal account for the
client deployment.

### Non-negotiables

- Client owns the AWS account, root identity and customer-managed keys.
- The client creates or approves the deployment role/profile.
- No personal root user, personal access key or personal bucket in the client
  account.
- The client decides region, retention, logging and network boundaries.
- Use a dedicated client profile, not `edge-platform-admin`.

### Procedure

1. Confirm the client account ID, region, profile and naming convention.
2. Create a private artifact bucket and public-access block.
3. Create the IoT thing/group, certificate and IoT policy for the client core.
4. Create the TES role, role alias and least-privilege policy.
5. Configure SNS/log groups/alarm names under the client naming convention.
6. Build the component under the client namespace.
7. Publish, create the component version and deploy.
8. Validate telemetry, status, logs, support bundle and alarm.
9. Record the client resource inventory in their own document.
10. Remove the sandbox resources only after the client proof is accepted.

### Things that change automatically

- CloudWatch log group names include component and region; they change with the
  component.
- Log stream names include the thing name.
- S3 artifact keys include component and version.
- IoT topics include the gateway/device ids from config.

## 4. Coupling audit

These are all current environment-specific values found by a repository search.

| Coupling | Where | Class | Action at handover |
|---|---|---|---|
| Component namespace | recipe, build script, logmanager config, tests, docs | **Must change** | New client namespace |
| Account ID `632839730725` | tests, docs, sandbox env | **Must change** | Client account |
| Profile `edge-platform-admin` | scripts, docs, testing | **Must change** | Client profile/role |
| Region `ap-southeast-1` | scripts, docs, tests | **Confirm** | Client region |
| Bucket name | build script/docs | **Must change** | Client bucket |
| Thing/group names | tests, scripts, docs | **Must change** | Client convention |
| TES role/alias | tests, docs, scripts | **Must change** | Client IAM |
| SNS/alarm names | `heartbeat-alarm.json`, scripts/docs | **Must change** | Client monitoring |
| Log group name | `remote-support.md` | Derived | Recompute |
| Docker container name | local docs/scripts | Local only | Optional |
| `certs/sandbox/` | git-ignored | **Never commit** | New client certs |
| `config/collector-container.yaml` gateway id | local dev | Local only | Site config |
| `test_aws_artifacts` fixture values | tests | Test fixture | Update with client names |
| `deploy/aws/heartbeat-alarm.json` alarm name | AWS integration | **Must change** | Client name |

## 5. What a future agent should do

1. Read this document before changing namespace, account, region, bucket or thing
   names.
2. Never edit a published component version.
3. Prefer environment variables over new literals.
4. Update tests and docs in the same change as any identity rename.
5. Run `make check`, `make component`, `make smoke` and the relevant AWS validation.
6. Do not copy sandbox credentials into the client environment.
7. Record the client resource inventory separately; do not leave personal names in
   client runbooks.

## 6. What is intentionally not done yet

- The actual client namespace has not been chosen.
- The client account has not been created or accessed.
- No client credentials, certificates or account IDs exist in this repository.
- The sandbox remains live for Phase 1.
