# Phase 1 Scope — Solar + Modbus TCP

**Status:** agreed starting slice
**Source:** Aboitiz SOW, data-collection sections only. The SOW’s architecture,
IoT-platform, lakehouse and enterprise-platform requirements are explicitly out
of scope.

## Why this slice

The northbound path is already proven: the collector can normalize, batch,
buffer and publish `Sample` records. The missing piece is a real southbound
source.

Solar is the first asset class because:

- generation, inverter and weather data are well understood;
- Modbus TCP is common and easy to simulate;
- the data fits the existing scalar `Sample` contract without changes;
- a local surrogate can test the full path before a site is involved.

## What the SOW tells us

The SOW names:

- solar plants among the four asset classes;
- Huawei as an OEM example;
- SCADA, historians, PLCs and IoT sensors as source systems;
- OPC UA/DA, Modbus TCP/RTU, MQTT, IEC 60870-5-104, DNP3 and REST APIs as
  protocols;
- inverter performance, generation, plant availability and capacity factor as
  solar use cases;
- actual generation versus weather forecast as a cross-site use case;
- full-resolution operational telemetry.

It does **not** provide a register map, tag list, sampling rate or Huawei model.
Those must come from a vendor document, a site export, or a human. We will not
invent them.

## In scope for Phase 1

### Source

- One solar plant.
- One Modbus TCP connection.
- One inverter and, where available, a weather station or revenue meter.
- Read-only polling.
- Local surrogate first; real hardware later.

### Data categories

| Category | Representative points | Purpose |
|---|---|---|
| Inverter AC | AC power, voltage, current, frequency, power factor | Performance and availability |
| Inverter DC | DC power, DC voltage, DC current | String/array health |
| Energy | Daily and lifetime energy | Generation and capacity factor |
| Temperature | Inverter temperature, module temperature | Derating and diagnostics |
| Status | Operating state, fault code, alarm bits | Availability and fault detection |
| Weather | Irradiance, ambient temperature, wind speed | Actual vs forecast comparison |
| Meter | Export/import power and energy | Revenue-grade generation context |

Availability, capacity factor, revenue and forecast variance are **derived**
downstream. The edge collector publishes measurements; it does not calculate
business KPIs.

### Protocol

Modbus TCP:

- function codes 1–4;
- block reads;
- signed/unsigned 16-bit and 32-bit values;
- float32/float64 where the device exposes them;
- configurable byte and word order;
- configurable scale and offset;
- per-point deadband;
- timeouts and exceptions mapped to `quality: bad`, counted, and retried with
  backoff.

No writes in v1.

### Cadence

Initial defaults, to be confirmed against the vendor and site:

| Data | Cadence |
|---|---|
| Inverter power/status | 10 seconds |
| Energy counters | 60 seconds |
| Weather/meter | 60 seconds |

The point map can override cadence per source. The collector’s batching remains
unchanged.

## Out of scope

- Wind, hydro and geothermal adapters.
- Modbus RTU and OPC UA in this slice.
- Huawei-specific register maps invented without vendor documentation.
- Inverter control, setpoints or write commands.
- Financial spot price, ERP and revenue calculations at the edge.
- Lakehouse, Kafka, Kubernetes, Terraform, BI and data-science platforms.
- 40-site rollout architecture and central-platform SLAs.
- Availability/capacity-factor computation in the collector.

## Point-map shape

The exact schema is Phase 1A. The intended shape is:

```yaml
version: 1
source:
  type: modbus_tcp
  host: 127.0.0.1
  port: 5020
  unit_id: 1
points:
  - metric: ac_power_kw
    function: holding_register
    address: 100
    type: float32
    word_order: big
    scale: 1.0
    unit: kW
    deadband: 0.1
  - metric: fault_code
    function: holding_register
    address: 120
    type: uint16
    unit: code
```

Addresses above are **illustrative only**. The surrogate will use its own
documented map; a real site map must come from the vendor or a captured trace.

## Acceptance criteria

1. An invalid point map fails validation before deployment.
2. A valid map drives the Modbus TCP source.
3. A local surrogate produces the expected `Sample` values, units and quality.
4. A timeout or Modbus exception produces `quality: bad` and increments an
   error counter.
5. A batch produced from surrogate data passes the frozen schema and reaches
   AWS IoT Core.
6. No collector image change is required; this is configuration plus the
   source component.

## Inputs needed from the client

- Which solar site is first.
- Huawei inverter model and firmware.
- A Modbus register map or captured trace.
- Whether the weather station and revenue meter are on Modbus TCP, another
  protocol, or a separate gateway.
- Required sampling interval and deadbands.
- Which points are mandatory for the first pilot.

Until those arrive, Phase 1 uses a **local Modbus TCP surrogate** with
representative points and no claim about real Huawei addresses.
