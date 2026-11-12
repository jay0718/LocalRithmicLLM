from lrl_common import service_name


def test_service_name_has_project_prefix() -> None:
    assert service_name("gex") == "lrl-gex"
