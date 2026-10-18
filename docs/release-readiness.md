# Release Readiness Checklist — 18 October 2026

**Scope:** operational readiness of the sandbox and support path. This is not a
protocol review; the point map, Modbus and OPC UA are not implemented yet.

**Verdict:** **Sandbox supportability is ready. Client-pilot release is not.**
Two blockers and several actions remain.

## Pass

| Check | Evidence |
|---|---|
| Collector live | `1.0.10` RUNNING on `edge-platform-sandbox-core` |
| Log shipping | `aws.greengrass.LogManager` 2.3.14 RUNNING |
| Log retention | 30 days on both Greengrass log groups |
| Support bundle retention | `support/` objects expire after 30 days |
| Bucket privacy | All four public-access blocks enabled |
| Certificate | ACTIVE; sandbox certificate valid to 2050 |
| Heartbeat | `version: 1.0.10`, `ready: true`, `expires_at` present |
| Alarm state | `edge-platform-sandbox-heartbeat-missing` = OK |
| No inbound shell | No exposed Docker ports; no active tunnels; no SSH by default |
| Support upload | Dry-run resolves the S3 key correctly |
| Health | `/healthz` 200, `/readyz` 200 |
| Disk | 11% used on `/greengrass/v2` |
| Tests | 147 passing; CI and security green |
| Versioning | Component 1.0.10 immutable; hashed wheel lock |

## Blockers

| # | Blocker | Why it matters | Action |
|---|---|---|---|
| B1 | **SNS topic has no subscriber** | The heartbeat alarm fires into an empty topic; no human is paged. | Subscribe the client-approved address: `scripts/subscribe-alerts.sh --email ...`. |
| B2 | **No missing-heartbeat drill** | The alarm has not been proven to go from OK to ALARM when heartbeats stop. | Pause the collector in a controlled window; confirm SNS delivery and recovery. Do this before a pilot. |

## Actions before a client pilot

| # | Action | Owner |
|---|---|---|
| A1 | Verify restart policy. The sandbox container is `restart=no`; production must use systemd or a managed service with restart-on-failure. | Engineering |
| A2 | Prove rollback: deploy a bad component version, confirm `ROLLBACK`, then return to 1.0.10. | Engineering |
| A3 | Test support-bundle upload end to end with a real bundle and a presigned URL. | Support |
| A4 | Decide remote access explicitly: logs/bundle only, or an approved outbound tunnel. A tunnel is not usable until an approved destination service exists. | Client + engineering |
| A5 | Confirm data residency and retention with the client (CloudWatch 30 days, S3 support 30 days). | Client |
| A6 | Review IAM scope: the sandbox operator role is broad; production uses least privilege. | Security |
| A7 | Document credential rotation and sandbox teardown/rebuild. | Engineering |
| A8 | Add the real support contact and escalation path to the runbook. | Support |

## Not applicable yet

- Point-map validation.
- Modbus TCP/RTU surrogate and HIL.
- OPC UA.
- Production base image (601 MB test core accepted; target ~400 MB).
- Client security review.

## Release decision

Do **not** call this client-pilot ready yet. The supportability path is real and
observable, but the alert is not delivered and no protocol adapter exists.

Minimum gate to start a supervised pilot:

1. B1 and B2 closed.
2. A1, A2 and A4 closed.
3. One protocol with a passing surrogate and HIL.
4. Client approval of retention and remote access.
