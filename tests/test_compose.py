"""Static checks on compose.yaml. The running stack is checked by scripts/smoke_compose.sh."""

import re
from pathlib import Path

import pytest
import yaml
from lrl_common.topics import ALL_TOPICS

ROOT = Path(__file__).resolve().parent.parent
COMPOSE = yaml.safe_load((ROOT / "compose.yaml").read_text())
SERVICES = COMPOSE["services"]
LONG_RUNNING = [name for name, service in SERVICES.items() if service.get("restart") != "no"]
# Memory available for this project on the Pi, after the other apps. See docs/resource-budget.md.
PI_BUDGET_MIB = 2560


def memory_mib(service: dict) -> int:
    value = service["deploy"]["resources"]["limits"]["memory"]
    number, unit = re.fullmatch(r"(\d+)([MG])", value).groups()
    return int(number) * (1024 if unit == "G" else 1)


@pytest.mark.parametrize("name", list(SERVICES))
def test_every_service_has_limits_and_bounded_logs(name: str) -> None:
    limits = SERVICES[name]["deploy"]["resources"]["limits"]
    assert limits["memory"] and limits["cpus"]
    assert SERVICES[name]["logging"]["options"]["max-size"]


@pytest.mark.parametrize("name", LONG_RUNNING)
def test_long_running_services_have_healthchecks(name: str) -> None:
    assert SERVICES[name]["healthcheck"]["test"]


def test_total_memory_fits_the_pi_budget() -> None:
    assert sum(memory_mib(service) for service in SERVICES.values()) <= PI_BUDGET_MIB


@pytest.mark.parametrize("name", list(SERVICES))
def test_host_ports_bind_to_localhost(name: str) -> None:
    for port in SERVICES[name].get("ports", []):
        assert port.startswith("127.0.0.1:")


def test_no_default_passwords() -> None:
    assert ":?" in SERVICES["postgres"]["environment"]["POSTGRES_PASSWORD"]
    assert ":?" in SERVICES["grafana"]["environment"]["GF_SECURITY_ADMIN_PASSWORD"]


def test_images_are_pinned() -> None:
    for service in SERVICES.values():
        assert not service["image"].endswith(":latest") and ":" in service["image"]


@pytest.mark.parametrize("topic", ALL_TOPICS, ids=lambda t: t.name)
def test_topic_setup_matches_code(topic) -> None:
    script = " ".join(SERVICES["redpanda-init"]["command"])
    create = re.search(rf"rpk topic create {re.escape(topic.name)} (.*?);", script).group(1)
    assert f"-p {topic.partitions} " in create
    assert f"retention.ms={topic.retention_ms}" in create
    assert f"retention.bytes={topic.retention_bytes_per_partition}" in create
    alter = re.search(rf"alter-config {re.escape(topic.name)} (.*?)(;|$)", script).group(1)
    assert f"retention.ms={topic.retention_ms}" in alter
    assert f"retention.bytes={topic.retention_bytes_per_partition}" in alter
