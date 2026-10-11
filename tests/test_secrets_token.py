"""Officer token from AWS Secrets Manager (api/auth.py) — cached, and fail-closed."""

import pytest
from fastapi.testclient import TestClient

from api import auth
from api.main import app

client = TestClient(app)


class FakeSecrets:
    def __init__(self, value="s3cret-from-sm", fail=False):
        self.value, self.fail, self.calls = value, fail, 0

    def get_secret_value(self, SecretId):
        self.calls += 1
        if self.fail:
            raise RuntimeError("AccessDenied")
        return {"SecretString": self.value + "\n"}


@pytest.fixture()
def secret_mode(fake_city, monkeypatch):
    for v in ("OFFICER_TOKEN", "COGNITO_USER_POOL_ID", "COGNITO_CLIENT_ID"):
        monkeypatch.delenv(v, raising=False)
    monkeypatch.setenv("OFFICER_TOKEN_SECRET_ARN", "arn:aws:secretsmanager:us-east-1:1:secret:heatrelief/officer-token")
    auth._secret_cache.update(value=None, at=0.0)
    yield
    auth._secret_cache.update(value=None, at=0.0)


def _plan_id():
    r = client.post("/api/v1/plans/optimize?city=new_delhi", json={"budget_lakh": 500, "save": True})
    return r.json()["plan_id"]


def test_secret_arn_means_token_mode_and_value_is_cached(secret_mode, monkeypatch):
    fake = FakeSecrets()
    monkeypatch.setattr("api.aws.client", lambda svc: fake)
    assert auth.mode() == "token"
    assert auth.officer_token() == "s3cret-from-sm" and auth.officer_token() == "s3cret-from-sm"
    assert fake.calls == 1


def test_plan_approval_uses_the_secret(secret_mode, monkeypatch):
    monkeypatch.setattr("api.aws.client", lambda svc: FakeSecrets())
    url = f"/api/v1/plans/{_plan_id()}/status"
    assert client.put(url, json={"status": "approved"}).status_code == 401
    assert client.put(url, json={"status": "approved"}, headers={"X-Officer-Token": "s3cret-from-sm"}).status_code == 200


def test_unreadable_secret_fails_closed_never_open(secret_mode, monkeypatch):
    monkeypatch.setattr("api.aws.client", lambda svc: FakeSecrets(fail=True))
    url = f"/api/v1/plans/{_plan_id()}/status"
    r = client.put(url, json={"status": "approved"}, headers={"X-Officer-Token": "anything"})
    assert r.status_code == 503 and auth.mode() == "token"


def test_env_token_still_wins(secret_mode, monkeypatch):
    monkeypatch.setenv("OFFICER_TOKEN", "from-env")
    monkeypatch.setattr("api.aws.client", lambda svc: (_ for _ in ()).throw(AssertionError("no AWS call")))
    assert auth.officer_token() == "from-env"
