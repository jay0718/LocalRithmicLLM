"""Code shared by LocalRithmicLLM services."""


def service_name(short_name: str) -> str:
    """Return the name a service reports in logs and metrics."""
    return f"lrl-{short_name}"
