# Proposal — Gateway, Slave and Device Identity

- **Status:** proposal only. No code or contract change is implied.
- **Date:** 18 October 2026
- **Scope:** the logical hierarchy used by the point map and the Modbus source.
- **Non-goal:** changing the frozen `Sample` / `Batch` contract.

## Why this needs a decision

The collector currently has one `gateway_id` and samples carry one `device_id`.
That is enough for the synthetic source. It is not enough for a real solar site,
where:

- one gateway may poll several Modbus connections;
- one Modbus TCP connection may address several unit IDs;
- one RS-485 bus may contain many slaves;
- a physical asset may expose more than one slave or connection;
- a slave may expose data for more than one logical asset.

Without a hierarchy, `device_id` becomes a mixture of asset, wiring and protocol
identity. That would leak into topics and dashboards and be difficult to correct.

## Proposed hierarchy

```text
Gateway  (collector instance / Greengrass core)
  └── Source  (one connection: Modbus TCP host:port or RTU serial port)
        └── Slave  (Modbus unit/slave id on that connection)
              └── Device  (logical asset: inverter, meter, weather station)
                    └── Point  (metric + address + type + scale + unit)
```

The first three levels describe **how to reach the data**. The last two describe
**what the data means**.

## Recommended point-map shape

A source owns a list of slaves. Each slave has a unit id, an optional stable
source name, a device id, and points.

```yaml
version: 1
source:
  id: inv-yard-1
  type: modbus_tcp
  host: 192.0.2.10
  port: 502
  timeout_s: 2.0
  slaves:
    - unit_id: 1
      device_id: inv-01
      points:
        - metric: ac_power_kw
          function: holding_register
          address: 100
          type: float32
          word_order: big
          scale: 1.0
          unit: kW
    - unit_id: 2
      device_id: meter-01
      points:
        - metric: export_power_kw
          function: input_register
          address: 10
          type: int32
          scale: 0.1
          unit: kW
```

For RTU, the same shape works with `type: modbus_rtu` and serial settings.

## Identity rules

| Field | Scope | Rule |
|---|---|---|
| `gateway_id` | One collector | Existing pattern; used in the topic and status |
| `source.id` | Unique per gateway | Stable, human-readable connection name |
| `source.unit_id` / slave `unit_id` | Unique per source | RTU: 1–247; TCP: 0–255; explicit unless a one-slave profile is declared |
| `device_id` | Unique per gateway | Stable logical asset, existing device-id pattern |
| `device_id` + `metric` | Unique | Duplicate metric on one device is rejected |
| `slave_id` | Per source | Not used as the topic identity |

`device_id` must not be derived from the slave number. A meter may be replaced
or re-addressed without changing the asset identity.

## Topic mapping

The existing rule stays:

```text
edge/<gateway_id>/<device_id>/telemetry
```

No slave or source name appears in the topic. Consumers care about the asset, not
the wiring. `origin` may carry the protocol-level address for diagnostics, for
example `modbus://192.0.2.10:502/unit-1/holding-100`.

## One device, several slaves

Some assets expose multiple endpoints: an inverter plus a separate meter, or a
skid with two controllers. They can use the same `device_id` under different
slaves:

```yaml
- unit_id: 1
  device_id: inv-01
  points: [...]
- unit_id: 7
  device_id: inv-01
  points: [...]
```

The collector merges samples by `device_id` into one batch. Per-slave failures
must not mark the whole device bad if another endpoint is still healthy. Quality
is attached to the sample that actually failed.

## One slave, several devices

This is less common but possible for a gateway or data concentrator. Support it
by allowing multiple device groups under one slave:

```yaml
- unit_id: 4
  devices:
    - device_id: inv-01
      points: [...]
    - device_id: inv-02
      points: [...]
```

The simpler `device_id` + `points` form can be sugar for a one-device group.

## Failure behaviour

- A timeout or Modbus exception affects **only the points read from that slave**.
- Other slaves on the same source continue.
- A slave failure increments `parse_errors`/timeouts and emits `quality: bad` for
  its points; it does not stop the source.
- A source-level connection failure affects all slaves on that source and is
  retried with backoff.
- No stale value is emitted as `good`.

## Validation

The point-map validator should reject:

- duplicate `source.id` within a gateway;
- duplicate `(device_id, metric)` within a gateway;
- an RTU unit id outside 1–247 or a TCP unit id outside 0–255;
- a missing `device_id`;
- an empty slave/point list;
- an address block that overlaps another point with a conflicting type, unless
  explicitly allowed;
- a metric name that does not match the contract.

## Compatibility

- `Sample` and `Batch` do not change.
- `Sample.device_id` remains the logical asset.
- Existing synthetic source is unaffected.
- A single-slave source can use a shorthand profile, but the normalized model is
  always gateway → source → slave → device → point.
- The point-map schema is versioned; adding `slaves` is a schema-version decision,
  not a silent change.

## Open questions

1. Is a **device** always a physical asset, or can it be a logical grouping?
2. Should one point map cover one source or several sources per gateway?
3. Should `origin` include the slave/unit id, or only the register address?
4. Do we need a stable `source_id` in `Sample.tags`, or is it diagnostic-only?
5. How should a device that spans two protocols (for example Modbus meter plus
   OPC UA inverter) be represented without duplicating `device_id`?

## Recommendation

Adopt the hierarchy **gateway → source → slave → device → point**, with
`slaves` grouped under a source and `device_id` at the group or point level.
Keep the topic and `Sample` contract asset-centric. Implement this in the point-map
schema and Modbus source, not in the frozen data contract.
