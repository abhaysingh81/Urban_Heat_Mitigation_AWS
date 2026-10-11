"""Static checks of infra/template.yaml wiring that unit tests of the Python code cannot see."""

import importlib
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")
ROOT = Path(__file__).resolve().parents[1]


class _Loader(yaml.SafeLoader):
    pass


def _tag(loader, suffix, node):            # keep !Ref / !If / !Sub … as plain data
    if isinstance(node, yaml.ScalarNode):
        return {suffix: loader.construct_scalar(node)}
    if isinstance(node, yaml.SequenceNode):
        return {suffix: loader.construct_sequence(node, deep=True)}
    return {suffix: loader.construct_mapping(node, deep=True)}


_Loader.add_multi_constructor("!", _tag)
T = yaml.load((ROOT / "infra" / "template.yaml").read_text(), Loader=_Loader)
R = T["Resources"]


def env(fn):
    return R[fn]["Properties"].get("Environment", {}).get("Variables", {})


def test_api_has_its_new_settings():
    e = env("ApiFunction")
    for k in ("SHELTERS_TABLE", "OFFICER_TOKEN_SECRET_ARN", "BATCH_BRIEFS_ENABLED", "CANARY_ENABLED"):
        assert k in e, k


def test_daily_job_has_map_and_refuge_settings():
    e = env("RefreshFunction")
    for k in ("STATIC_MAP_ENABLED", "FRONTEND_BUCKET", "SHELTERS_TABLE"):
        assert k in e, k
    assert "OFFICER_TOKEN_SECRET_ARN" not in e


def test_phone_alert_settings_reach_every_function():
    g = T["Globals"]["Function"]["Environment"]["Variables"]
    for k in ("PHONE_ALERTS_TABLE", "PHONE_KEY_SECRET_ARN", "WHATSAPP_PHONE_NUMBER_ID", "CONNECT_INSTANCE_ID"):
        assert k in g, k


def test_every_image_command_is_an_importable_handler():
    for name, res in R.items():
        if res.get("Type") != "AWS::Serverless::Function" or res["Properties"].get("PackageType") != "Image":
            continue
        cmd = res["Properties"].get("ImageConfig", {}).get("Command", ["api.lambda_handler.handler"])[0]
        module, func = cmd.rsplit(".", 1)
        assert callable(getattr(importlib.import_module(module), func)), f"{name}: {cmd}"


def test_canary_handler_matches_the_packaged_script():
    code = R["UptimeCanary"]["Properties"]["Code"]
    file, func = code["Handler"].split(".")
    script = ROOT / "infra" / "canary" / "python" / f"{file}.py"
    assert script.exists() and f"def {func}(" in script.read_text()


def test_new_conditional_resources_have_conditions():
    for name in ("BriefBatchFunction", "BriefBatchRole", "UptimeCanary", "SensorHistoryStream",
                 "OfficerTokenSecret", "PhoneAlertsTable", "PhoneKeySecret"):
        assert R[name].get("Condition"), name
