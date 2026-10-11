"""WhatsApp alerts (End User Messaging Social) and phone calls (Amazon Connect)."""

import json
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from api import phones, voice_calls, whatsapp
from api.main import app
from api.routers import alerts as alerts_router

client = TestClient(app)


class FakeAws:
    def __init__(self, connect_error_after=None):
        self.wa, self.calls, self.connect_error_after = [], [], connect_error_after

    def client(self, service):
        outer = self

        class Social:
            def send_whatsapp_message(self, originationPhoneNumberId, message, metaApiVersion):
                outer.wa.append({"from": originationPhoneNumberId, "msg": json.loads(message), "v": metaApiVersion})
                return {"messageId": f"m{len(outer.wa)}"}

        class Connect:
            def start_outbound_voice_contact(self, **kw):
                if outer.connect_error_after is not None and len(outer.calls) >= outer.connect_error_after:
                    err = Exception("throttled")
                    err.response = {"Error": {"Code": "LimitExceededException"}}
                    raise err
                outer.calls.append(kw)
                return {"ContactId": f"c{len(outer.calls)}"}
        return {"socialmessaging": Social(), "connect": Connect()}[service]


@pytest.fixture()
def env(fake_city, monkeypatch):
    fake = FakeAws()
    monkeypatch.setattr("api.aws.client", fake.client)
    monkeypatch.setenv("WHATSAPP_PHONE_NUMBER_ID", "phone-number-id-0123456789abcdef0123456789abcdef")
    monkeypatch.setenv("CONNECT_INSTANCE_ID", "inst-1")
    monkeypatch.setenv("CONNECT_CONTACT_FLOW_ID", "flow-1")
    for v in ("OFFICER_TOKEN", "OFFICER_TOKEN_SECRET_ARN", "COGNITO_USER_POOL_ID", "PHONE_ALERTS_TABLE",
              "PHONE_KEY_SECRET_ARN"):
        monkeypatch.delenv(v, raising=False)
    alerts_router._ip_signups.clear()
    yield fake
    alerts_router._ip_signups.clear()


def _link_params(url):
    q = parse_qs(urlparse(url).query)
    return q["id"][0], q["sig"][0]


def test_numbers_are_normalised_masked_and_hashed():
    assert phones.normalize("98765 43210") == "+919876543210"
    assert phones.normalize("+91-98765-43210") == phones.normalize("09876543210") == "+919876543210"
    assert phones.normalize("12345") is None and phones.normalize("+15551234567") is None
    assert phones.mask("+919876543210") == "+91 98•••••210"
    pid = phones.phone_id("whatsapp", "+919876543210")
    assert pid.startswith("whatsapp#") and "9876543210" not in pid


def test_whatsapp_double_opt_in_alert_and_unsubscribe(env):
    r = client.post("/api/v1/phone-alerts/whatsapp/subscribe",
                    json={"phone": "98765 43210", "city": "new_delhi", "min_level": "orange", "consent": True})
    assert r.status_code == 202
    optin = env.wa[0]["msg"]
    assert optin["messaging_product"] == "whatsapp" and optin["to"] == "+919876543210" and optin["type"] == "template"
    assert optin["template"]["name"] == "heatrelief_optin" and env.wa[0]["v"] == "v20.0"
    city_param, confirm_url = [p["text"] for p in optin["template"]["components"][0]["parameters"]]
    cid, sig = _link_params(confirm_url)

    # no alerts before confirming
    assert whatsapp.send_city_alert("new_delhi", "New Delhi", "red", 45, ["Zone 1"], "Stay in", "https://s")["sent"] == 0
    assert client.get("/api/v1/phone-alerts/confirm", params={"id": cid, "sig": "0" * 32}).status_code == 400  # forged
    assert client.get("/api/v1/phone-alerts/confirm", params={"id": cid, "sig": sig}).status_code == 200
    assert client.get("/api/v1/phone-alerts/confirm", params={"id": cid, "sig": sig}).status_code == 400  # one use

    assert whatsapp.send_city_alert("new_delhi", "New Delhi", "yellow", 41, [], "x", "https://s")["sent"] == 0  # below level
    out = whatsapp.send_city_alert("new_delhi", "New Delhi", "red", 45.2, ["Zone 1", "Zone 2"], "Stay in", "https://s")
    assert out["sent"] == 1
    params = [p["text"] for p in env.wa[-1]["msg"]["template"]["components"][0]["parameters"]]
    assert params[:4] == ["New Delhi", "RED", "45.2", "Zone 1, Zone 2"] and params[5].endswith("/citizen?city=new_delhi")
    uid, usig = _link_params(params[6])
    assert client.get("/api/v1/phone-alerts/unsubscribe", params={"id": uid, "sig": usig}).status_code == 200
    assert phones.get(uid) is None
    assert whatsapp.send_city_alert("new_delhi", "New Delhi", "red", 45, [], "x", "https://s")["sent"] == 0


def test_whatsapp_signup_rules(env, monkeypatch):
    url = "/api/v1/phone-alerts/whatsapp/subscribe"
    body = {"phone": "98765 43210", "city": "new_delhi", "min_level": "red", "consent": True}
    assert client.post(url, json={**body, "consent": False}).status_code == 400
    assert client.post(url, json={**body, "phone": "12345"}).status_code == 400
    assert client.post(url, json={**body, "website": "bot"}).status_code == 202 and env.wa == []   # honeypot
    assert client.post(url, json={**body, "city": "kochi"}).status_code == 422                     # real cities only
    monkeypatch.delenv("WHATSAPP_PHONE_NUMBER_ID")
    assert client.post(url, json=body).status_code == 501


def test_voice_contacts_are_officer_managed_and_masked(env, monkeypatch):
    from models.risk import ward_table
    ward = ward_table("new_delhi")["ward_id"].iloc[0]
    url = "/api/v1/phone-alerts/voice/contacts?city=new_delhi"
    body = {"phone": "9876543210", "ward_id": ward, "language": "hi", "consent_note": "resident agreed in person"}
    r = client.post(url, json=body)
    assert r.status_code == 201 and r.json()["phone"] == "+91 98•••••210" and r.json()["consent_by"] == "local officer"
    listed = client.get(url).json()["contacts"]
    assert len(listed) == 1 and "9876543210" not in json.dumps(listed)
    assert client.post(url, json={**body, "ward_id": "nope"}).status_code == 404
    monkeypatch.setenv("OFFICER_TOKEN", "s3cret")
    assert client.get(url).status_code == 401                                   # officers only
    cid = listed[0]["id"].replace("#", "%23")
    assert client.delete(f"/api/v1/phone-alerts/voice/contacts/{cid}", headers={"X-Officer-Token": "s3cret"}).status_code == 204
    assert phones.list_contacts("voice", "new_delhi") == []


def test_calls_only_at_the_level_capped_and_stop_when_throttled(env, monkeypatch):
    for i in range(5):
        voice_calls.register(f"98765432{i}{i}", "new_delhi", "Z0000", "hi" if i % 2 else "en", "officer", "agreed")
    texts = {"en": "Extreme heat today.", "hi": "आज भीषण गर्मी है।"}
    assert voice_calls.call_city("new_delhi", "orange", texts, "2026-10-11")["called"] == 0          # below red
    monkeypatch.setenv("MAX_CALLS_PER_RUN", "3")
    out = voice_calls.call_city("new_delhi", "red", texts, "2026-10-11")
    assert out == {"called": 3, "failed": 0, "not_called_limit": 2}
    call = env.calls[0]
    assert call["InstanceId"] == "inst-1" and call["ContactFlowId"] == "flow-1"
    assert call["ClientToken"].startswith("2026-10-11-voice#")
    assert call["Attributes"]["message"] in texts.values() and call["Attributes"]["voice"] == "Kajal"
    env.calls.clear()
    env.connect_error_after = 1
    monkeypatch.setenv("MAX_CALLS_PER_RUN", "10")
    out = voice_calls.call_city("new_delhi", "red", texts, "2026-10-12")
    assert out["called"] == 1 and out["not_called_limit"] == 4


def test_simulated_alert_never_messages_or_calls(env, monkeypatch):
    from lambdas.refresh_forecast import app as refresh
    voice_calls.register("9876543210", "new_delhi", "Z0000", "hi", "officer", "agreed")
    monkeypatch.setattr(refresh, "get_forecast", lambda c, n: {"today": {"date": "2026-10-11", "tmax_c": 46.0,
                                                                         "heat_index_c": 50.0, "humidity_pct": 20},
                                                               "days": []})
    out = refresh.process_city("new_delhi", simulate="red")
    assert out["whatsapp"] == out["voice"] == "skipped (simulation)" and env.calls == [] and env.wa == []
