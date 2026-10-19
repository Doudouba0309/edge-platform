"""Cross-artifact drift tests for the Greengrass recipe and IoT policy.

These read the real build inputs, not a hand-written copy. A change to a topic,
client id, component name or IPC resource that is not mirrored in the other
artifact fails here instead of failing as "not authorized" on a core device.
"""

from __future__ import annotations

import fnmatch
import json
import tomllib
from pathlib import Path
from typing import Any

import yaml

from edge_collector.topics import status_topic, telemetry_topic

ROOT = Path(__file__).resolve().parents[1]
RECIPE_TEMPLATE = ROOT / "deploy" / "greengrass" / "recipe.yaml.tmpl"
POLICY_TEMPLATE = ROOT / "deploy" / "aws" / "iot-policy.json.tmpl"

THING_NAME = "edge-platform-sandbox-core"
ROLE_ALIAS = "edge-platform-sandbox-TESRoleAlias"
GATEWAY_ID = THING_NAME
DEVICE_ID = "plc-line-1"
REGION = "ap-southeast-1"
ACCOUNT_ID = "123456789012"
BUCKET = f"edge-platform-sandbox-{ACCOUNT_ID}-{REGION}"
COMPONENT_NAME = "io.github.doudouba0309.EdgePlatform.Collector"
COMPONENT_VERSION = "1.0.12"
ARTIFACT_NAME = f"EdgeCollector-{COMPONENT_VERSION}.zip"
ARTIFACT_STEM = f"EdgeCollector-{COMPONENT_VERSION}"
DIST_VERSION = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"][
    "version"
]


def _values() -> dict[str, str]:
    return {
        "COMPONENT_NAME": COMPONENT_NAME,
        "COMPONENT_VERSION": COMPONENT_VERSION,
        "ARTIFACT_NAME": ARTIFACT_NAME,
        "ARTIFACT_STEM": ARTIFACT_STEM,
        "BUCKET": BUCKET,
        "GATEWAY_ID": GATEWAY_ID,
        "DEVICE_ID": DEVICE_ID,
        "DIST_VERSION": DIST_VERSION,
        "REGION": REGION,
        "ACCOUNT_ID": ACCOUNT_ID,
        "THING_NAME": THING_NAME,
        "ROLE_ALIAS": ROLE_ALIAS,
    }


def _render(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    for key, value in _values().items():
        text = text.replace(f"__{key}__", value)
    assert "__" not in text, f"unrendered placeholder in {path}"
    return text


def _recipe() -> dict[str, Any]:
    return yaml.safe_load(_render(RECIPE_TEMPLATE))


def _policy() -> dict[str, Any]:
    return json.loads(_render(POLICY_TEMPLATE))


def _topic_resources(statements: list[dict[str, Any]], action: str) -> list[str]:
    resources: list[str] = []
    for statement in statements:
        actions = statement.get("Action", [])
        if isinstance(actions, str):
            actions = [actions]
        if action in actions:
            values = statement.get("Resource", [])
            if isinstance(values, str):
                values = [values]
            resources.extend(values)
    return resources


def _mqtt_matches(topic: str, topic_filter: str) -> bool:
    """Match a concrete topic against an MQTT filter (+ one level, # rest)."""
    topic_parts = topic.split("/")
    filter_parts = topic_filter.split("/")
    for index, part in enumerate(filter_parts):
        if part == "#":
            return index == len(filter_parts) - 1
        if index >= len(topic_parts):
            return False
        if part == "+":
            continue
        if part != topic_parts[index]:
            return False
    return len(topic_parts) == len(filter_parts)


def _matches(topic: str, resource: str) -> bool:
    if resource.startswith("arn:") and ":topic/" in resource:
        resource = resource.split(":topic/", 1)[1]
    elif resource.startswith("arn:") and ":topicfilter/" in resource:
        resource = resource.split(":topicfilter/", 1)[1]
    # * and ? are IAM/Greengrass globs and span '/', unlike MQTT + and #.
    return fnmatch.fnmatchcase(topic, resource)


def test_recipe_and_policy_agree_on_identity_and_topics() -> None:
    recipe = _recipe()
    policy = _policy()

    assert recipe["ComponentName"] == COMPONENT_NAME
    assert recipe["ComponentVersion"] == COMPONENT_VERSION
    assert "Container" not in recipe

    manifests = recipe["Manifests"]
    assert len(manifests) == 2
    platforms = {
        (manifest["Platform"]["os"], manifest["Platform"]["architecture"]) for manifest in manifests
    }
    assert platforms == {("linux", "aarch64"), ("linux", "amd64")}
    assert manifests[0]["Artifacts"] == manifests[1]["Artifacts"]
    assert manifests[0]["Lifecycle"] == manifests[1]["Lifecycle"]

    artifact_uri = manifests[0]["Artifacts"][0]["URI"]
    assert artifact_uri == (f"s3://{BUCKET}/{COMPONENT_NAME}/{COMPONENT_VERSION}/{ARTIFACT_NAME}")

    config = recipe["ComponentConfiguration"]["DefaultConfiguration"]
    assert config["gatewayId"] == GATEWAY_ID
    assert config["deviceId"] == DEVICE_ID

    access = config["accessControl"]["aws.greengrass.ipc.mqttproxy"]
    operations: set[str] = set()
    resources: set[str] = set()
    for entry in access.values():
        operations.update(entry["operations"])
        resources.update(entry["resources"])
    assert "aws.greengrass#PublishToIoTCore" in operations
    assert "edge/+/+/telemetry" in resources
    assert "edge/+/status" in resources
    assert _mqtt_matches(telemetry_topic(GATEWAY_ID, DEVICE_ID), "edge/+/+/telemetry")

    statements = policy["Statement"]
    connect = _topic_resources(statements, "iot:Connect")
    assert connect == [f"arn:aws:iot:{REGION}:{ACCOUNT_ID}:client/{THING_NAME}"]

    publish = _topic_resources(statements, "iot:Publish")
    assert f"arn:aws:iot:{REGION}:{ACCOUNT_ID}:topic/edge/*" in publish
    assert any(_matches(telemetry_topic(GATEWAY_ID, DEVICE_ID), r) for r in publish)
    assert any(_matches(status_topic(GATEWAY_ID), r) for r in publish)

    subscribe = _topic_resources(statements, "iot:Subscribe")
    assert any(_matches("edge/any/telemetry", r) for r in subscribe)

    greengrass_actions: list[str] = []
    for statement in statements:
        actions = statement.get("Action", [])
        if isinstance(actions, str):
            actions = [actions]
        greengrass_actions.extend(action for action in actions if action.startswith("greengrass:"))
    assert "greengrass:ResolveComponentCandidates" in greengrass_actions
    assert "greengrass:GetDeploymentConfiguration" in greengrass_actions

    assume = _topic_resources(statements, "iot:AssumeRoleWithCertificate")
    assert assume == [f"arn:aws:iot:{REGION}:{ACCOUNT_ID}:rolealias/{ROLE_ALIAS}"]

    for resource in publish:
        assert "#" not in resource
        assert "+" not in resource


def test_recipe_install_uses_the_universal_wheelhouse() -> None:
    recipe = _recipe()
    script = recipe["Manifests"][0]["Lifecycle"]["Install"]["Script"]
    assert "python3 -m venv" in script
    assert "--force-reinstall" in script
    assert "--no-index --find-links" in script
    assert f"edge-collector[aws]=={_values()['DIST_VERSION']}" in script


def test_policy_has_no_mqtt_wildcards() -> None:
    policy = _policy()
    for statement in policy["Statement"]:
        resources = statement.get("Resource", [])
        if isinstance(resources, str):
            resources = [resources]
        for resource in resources:
            assert "+" not in resource
            assert "#" not in resource


def test_component_requirements_are_pinned() -> None:
    requirements = (ROOT / "deploy" / "greengrass" / "component-requirements.lock").read_text()
    lines = [
        line.strip()
        for line in requirements.splitlines()
        if line.strip() and not line.startswith("#")
    ]
    packages = [line for line in lines if not line.startswith("--hash")]
    assert packages
    for line in packages:
        assert "==" in line
        assert ">=" not in line and "<" not in line and "~=" not in line
    assert any("--hash=sha256:" in line for line in lines)


def test_tes_role_policy_grants_log_manager_permissions() -> None:
    policy = (ROOT / "deploy" / "aws" / "tes-role-policy.json.tmpl").read_text()
    assert "logs:DescribeLogStreams" in policy
    assert "logs:PutLogEvents" in policy
