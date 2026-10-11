"""Phase 2 features (G-M): sign-in roles, SES, Translate, sensors, live updates, edge check.
Every AWS call is stubbed; nothing here needs an account or the network."""

import json
import time

import pytest
from fastapi.testclient import TestClient

from api import auth, email_alerts, live, net, store, translate
from api.main import app
from tests.test_aws_features import Recorder, SIGNUP

client = TestClient(app)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for var in ("COGNITO_USER_POOL_ID", "COGNITO_CLIENT_ID", "OFFICER_TOKEN", "EDGE_SECRET", "TRANSLATE_ENABLED",
                "SES_FROM_EMAIL", "SES_CONTACT_LIST", "WS_CONNECTIONS_TABLE", "WS_API_ENDPOINT",
                "SENSOR_LATEST_TABLE", "ALERT_TOPIC_ARN", "RATE_LIMIT_TABLE"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr("models.forecast.get_forecast", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("offline")))
    translate._cache.clear()


# ── Feature K: Cognito roles ─────────────────────────────────
@pytest.fixture
def cognito(monkeypatch):
    """A user pool whose signing key we hold, so real RS256 tokens can be minted."""
    import jwt
    from cryptography.hazmat.primitives.asymmetric import rsa
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    monkeypatch.setenv("COGNITO_USER_POOL_ID", "us-east-1_TestPool1")
    monkeypatch.setenv("COGNITO_CLIENT_ID", "client123")
    monkeypatch.setattr(auth, "_signing_key", lambda token: key.public_key())

    def token(groups, *, use="access", client_id="client123", exp=3600, signer=key, issuer=None):
        return jwt.encode({"sub": "u-1", "username": "officer1", "token_use": use, "client_id": client_id,
                           "cognito:groups": groups, "iss": issuer or auth.issuer(),
                           "exp": int(time.time()) + exp}, signer, algorithm="RS256")
    token.other_key = other
    return token


def _bearer(t):
    return {"Authorization": f"Bearer {t}"}


def test_plan_approval_needs_the_planner_role(fake_city, cognito):
    plan = store.save_plan(fake_city, {"items": []})
    url, body = f"/api/v1/plans/{plan['id']}/status", {"status": "approved"}
    assert client.put(url, json=body).status_code == 401                                   # not signed in
    assert client.put(url, json=body, headers=_bearer(cognito(["ward_officer"]))).status_code == 403
    assert client.put(url, json=body, headers=_bearer(cognito([]))).status_code == 403
    r = client.put(url, json=body, headers=_bearer(cognito(["city_planner"])))
    assert r.status_code == 200 and r.json()["status"] == "approved"
    assert r.json()["audit"][-1]["actor"] == "officer1"                                    # who approved is recorded


def test_forged_or_wrong_tokens_are_refused(fake_city, cognito):
    plan = store.save_plan(fake_city, {"items": []})
    url, body = f"/api/v1/plans/{plan['id']}/status", {"status": "approved"}
    bad = [cognito(["city_planner"], use="id"),                        # an ID token is not an access token
           cognito(["city_planner"], client_id="another-app"),
           cognito(["city_planner"], exp=-60),                         # expired
           cognito(["city_planner"], issuer="https://evil.example/pool"),
           cognito(["city_planner"], signer=cognito.other_key),        # signed by someone else
           "not-a-token"]
    for t in bad:
        assert client.put(url, json=body, headers=_bearer(t)).status_code == 401
    assert store.get_plan(plan["id"])["status"] == "draft"


def test_shared_token_and_open_modes_still_work(fake_city, monkeypatch):
    plan = store.save_plan(fake_city, {"items": []})
    url = f"/api/v1/plans/{plan['id']}/status"
    assert auth.mode() == "open" and client.put(url, json={"status": "approved"}).status_code == 200
    monkeypatch.setenv("OFFICER_TOKEN", "s3cret")
    assert auth.mode() == "token"
    assert client.put(url, json={"status": "implemented"}).status_code == 401
    assert client.put(url, json={"status": "implemented"}, headers={"X-Officer-Token": "s3cret"}).status_code == 200


# ── officer report verification + Feature L live updates ─────
def test_report_verification_flow_and_live_events(fake_city, cognito, monkeypatch):
    events = []
    monkeypatch.setattr(live, "broadcast", lambda e: events.append(e) or 1)
    made = client.post(f"/api/v1/reports?city={fake_city}", json={"lat": 28.55, "lon": 77.06, "kind": "no_water"})
    rid = made.json()["id"]                                            # citizens report without signing in
    assert events[0]["type"] == "report.created" and "lat" not in json.dumps(events[0])

    assert client.get(f"/api/v1/reports?city={fake_city}").status_code == 401
    officer = _bearer(cognito(["ward_officer"]))
    listed = client.get(f"/api/v1/reports?city={fake_city}", headers=officer).json()["reports"]
    assert listed[0]["id"] == rid and listed[0]["status"] == "new"
    r = client.put(f"/api/v1/reports/{rid}/status", json={"status": "dispatched", "note": "tanker sent"}, headers=officer)
    assert r.status_code == 200 and r.json()["status"] == "dispatched" and r.json()["audit"][-1]["note"] == "tanker sent"
    assert events[-1]["type"] == "report.updated" and events[-1]["report"]["status"] == "dispatched"
    assert client.put(f"/api/v1/reports/{rid}/status", json={"status": "bogus"}, headers=officer).status_code == 400
    assert client.put("/api/v1/reports/nope/status", json={"status": "verified"}, headers=officer).status_code == 404


def test_live_broadcast_sends_to_connections_and_drops_dead_ones(monkeypatch):
    from botocore.exceptions import ClientError
    assert live.broadcast({"type": "x"}) == 0                          # not configured: silent no-op
    monkeypatch.setenv("WS_CONNECTIONS_TABLE", "conns")
    monkeypatch.setenv("WS_API_ENDPOINT", "https://abc.execute-api.us-east-1.amazonaws.com/live")
    table = Recorder(scan={"Items": [{"id": "alive"}, {"id": "gone"}]})
    posted = []

    class Api:
        def post_to_connection(self, ConnectionId, Data):
            if ConnectionId == "gone":
                raise ClientError({"Error": {"Code": "GoneException"}}, "PostToConnection")
            posted.append((ConnectionId, json.loads(Data)))
    from api import aws
    monkeypatch.setattr(aws, "table", lambda name: table)
    monkeypatch.setattr("boto3.client", lambda *a, **k: Api())
    assert live.broadcast({"type": "report.created"}) == 1 and posted[0][0] == "alive"
    assert ("delete_item", {"Key": {"id": "gone"}}) in table.calls


def test_websocket_connect_registers_and_checks_role(cognito, monkeypatch):
    from lambdas.ws_connections import app as ws
    table = Recorder()
    monkeypatch.setattr(ws, "table", lambda: table)
    ev = lambda route, token=None: {"requestContext": {"routeKey": route, "connectionId": "c1"},  # noqa: E731
                                    "queryStringParameters": {"token": token} if token else None}
    assert ws.handler(ev("$connect"), None)["statusCode"] == 401
    assert ws.handler(ev("$connect", cognito([])), None)["statusCode"] == 403
    assert ws.handler(ev("$connect", cognito(["ward_officer"])), None)["statusCode"] == 200
    assert table.calls[0][0] == "put_item" and table.calls[0][1]["Item"]["id"] == "c1"
    assert ws.handler(ev("$disconnect"), None)["statusCode"] == 200 and table.calls[-1][0] == "delete_item"
    assert ws.handler(ev("$default"), None)["statusCode"] == 200


# ── Feature M: edge check and caller address ─────────────────
def test_api_refuses_direct_calls_when_waf_mode_is_on(monkeypatch):
    assert client.get("/health").status_code == 200
    monkeypatch.setenv("EDGE_SECRET", "edge-123")
    assert client.get("/health").status_code == 403
    assert client.get("/health", headers={"X-Origin-Verify": "wrong"}).status_code == 403
    assert client.get("/health", headers={"X-Origin-Verify": "edge-123"}).status_code == 200


def test_client_ip_trusts_only_what_aws_appended(monkeypatch):
    class Req:
        def __init__(self, xff, edge=None):
            self.client = type("C", (), {"host": "130.176.0.9"})()
            self.headers = {"x-forwarded-for": xff, **({"x-origin-verify": edge} if edge else {})}
    assert net.client_ip(Req("6.6.6.6, 130.176.0.9")) == "130.176.0.9"            # direct: XFF is not trusted
    monkeypatch.setenv("EDGE_SECRET", "edge-123")
    assert net.client_ip(Req("6.6.6.6, 203.0.113.7, 130.176.0.9", "edge-123")) == "203.0.113.7"   # viewer IP
    assert net.client_ip(Req("203.0.113.7, 130.176.0.9", "bad")) == "130.176.0.9"


# ── Feature H: Amazon Translate ──────────────────────────────
def test_translation_is_off_by_default_and_cached_when_on(monkeypatch):
    assert translate.translate("Stay hydrated.", "mr") is None and translate.languages() == []
    rec = Recorder(translate_text={"TranslatedText": "पाणी पीत रहा."})
    monkeypatch.setenv("TRANSLATE_ENABLED", "true")
    monkeypatch.setattr(translate.aws, "client", lambda service: rec)
    assert translate.translate("Stay hydrated.", "mr") == "पाणी पीत रहा."
    assert translate.translate("Stay hydrated.", "mr") == "पाणी पीत रहा." and len(rec.calls) == 1   # cached
    assert rec.calls[0][1] == {"Text": "Stay hydrated.", "SourceLanguageCode": "en", "TargetLanguageCode": "mr"}
    assert translate.translate("Stay hydrated.", "fr") is None                     # not an offered language
    assert [l["code"] for l in translate.languages()] == ["mr", "bn", "ta", "te", "gu", "kn"]
    rec.responses["translate_text"] = RuntimeError("throttled")
    assert translate.translate("Another sentence.", "ta") is None                  # failure -> caller shows the original


def test_citizen_page_gets_a_regional_message(fake_city, monkeypatch):
    base = f"/api/v1/citizen?city={fake_city}&lat=28.55&lon=77.06"
    plain = client.get(base + "&lang=mr").json()
    assert plain["message_local"] is None and plain["machine_translated"] is False
    monkeypatch.setenv("TRANSLATE_ENABLED", "true")
    monkeypatch.setattr(translate.aws, "client", lambda service: Recorder(translate_text={"TranslatedText": "मराठी सल्ला"}))
    local = client.get(base + "&lang=mr").json()
    assert local["message_local"] == "मराठी सल्ला" and local["message_local_lang"] == "mr" and local["machine_translated"]
    assert local["message_en"] and local["message_hi"]                             # originals always present
    assert client.get(base + "&lang=english").status_code == 422


def test_brief_translation_flags_changed_numbers(fake_city, monkeypatch):
    from models.risk import ward_table
    ward = ward_table(fake_city).iloc[0]["ward_id"]
    monkeypatch.setenv("TRANSLATE_ENABLED", "true")
    made = {}

    def fake_translate(**kw):
        made["text"] = kw["Text"]
        return {"TranslatedText": kw["Text"] if kw["TargetLanguageCode"] == "kn" else kw["Text"] + " 999999"}
    rec = Recorder()
    rec.translate_text = fake_translate
    monkeypatch.setattr(translate.aws, "client", lambda service: rec)
    out = client.post(f"/api/v1/brief?city={fake_city}",
                      json={"ward_id": ward, "use_llm": False, "make_pdf": False, "languages": ["kn", "ta", "xx"]}).json()
    assert set(out["translations"]) == {"kn", "ta"} and made["text"] == out["brief_en"]
    assert out["translations"]["kn"]["numbers_match"] is True and out["translations"]["kn"]["machine_translated"]
    assert out["translations"]["ta"]["numbers_match"] is False                     # a number the English brief lacks


# ── Feature I: Amazon SES ────────────────────────────────────
class FakeSes:
    """Enough of the SESv2 contact-list API to exercise the double opt-in."""

    def __init__(self):
        self.contacts, self.sent = {}, []

    def create_contact(self, ContactListName, EmailAddress, TopicPreferences, UnsubscribeAll, AttributesData):
        from botocore.exceptions import ClientError
        if EmailAddress in self.contacts:
            raise ClientError({"Error": {"Code": "AlreadyExistsException"}}, "CreateContact")
        self.contacts[EmailAddress] = {"EmailAddress": EmailAddress, "TopicPreferences": TopicPreferences,
                                       "UnsubscribeAll": UnsubscribeAll, "AttributesData": AttributesData}

    def get_contact(self, ContactListName, EmailAddress):
        return dict(self.contacts[EmailAddress])

    def update_contact(self, ContactListName, EmailAddress, TopicPreferences, UnsubscribeAll, AttributesData):
        self.contacts[EmailAddress].update(TopicPreferences=TopicPreferences, UnsubscribeAll=UnsubscribeAll,
                                           AttributesData=AttributesData)

    def delete_contact(self, ContactListName, EmailAddress):
        del self.contacts[EmailAddress]

    def list_contacts(self, ContactListName, PageSize, Filter=None, NextToken=None):
        out = []
        for c in self.contacts.values():
            if Filter:
                want = Filter["TopicFilter"]["TopicName"]
                if not any(p["TopicName"] == want and p["SubscriptionStatus"] == Filter["FilteredStatus"]
                           for p in c["TopicPreferences"]):
                    continue
            out.append(c)
        return {"Contacts": out}

    def send_email(self, **kw):
        self.sent.append(kw)


@pytest.fixture
def ses(monkeypatch):
    fake = FakeSes()
    monkeypatch.setenv("SES_FROM_EMAIL", "alerts@example.org")
    monkeypatch.setenv("SES_CONTACT_LIST", "heatrelief-alerts")
    monkeypatch.setattr(email_alerts.aws, "client", lambda service: fake)
    monkeypatch.setattr(email_alerts.time, "sleep", lambda s: None)
    from api.routers import alerts
    alerts._ip_signups.clear()
    return fake


def _token_from(ses):
    link = ses.sent[-1]["Content"]["Simple"]["Body"]["Text"]["Data"].split("Open this link to confirm:\n")[1].split("\n")[0]
    return link, link.split("token=")[1]


def test_ses_signup_is_double_opt_in(ses):
    assert client.post("/api/v1/alerts/subscribe", json=SIGNUP).status_code == 202
    contact = ses.contacts[SIGNUP["email"]]
    assert contact["TopicPreferences"] == [{"TopicName": "new_delhi-orange", "SubscriptionStatus": "OPT_OUT"}]
    link, token = _token_from(ses)
    assert token not in contact["AttributesData"]                                  # only a hash is stored
    assert "ListManagementOptions" not in ses.sent[-1] and "/api/v1/alerts/confirm?email=" in link

    assert client.get("/api/v1/alerts/confirm", params={"email": SIGNUP["email"], "token": "wrong-token-000"}).status_code == 400
    ok = client.get("/api/v1/alerts/confirm", params={"email": SIGNUP["email"], "token": token})
    assert ok.status_code == 200 and "Confirmed" in ok.text
    prefs = {p["TopicName"]: p["SubscriptionStatus"] for p in ses.contacts[SIGNUP["email"]]["TopicPreferences"]}
    assert prefs["new_delhi-orange"] == "OPT_IN" and prefs["new_delhi-yellow"] == "OPT_OUT"
    assert client.get("/api/v1/alerts/confirm", params={"email": SIGNUP["email"], "token": token}).status_code == 400  # one use


def test_ses_confirmation_expires_and_unknown_address_looks_the_same(ses, monkeypatch):
    client.post("/api/v1/alerts/subscribe", json=SIGNUP)
    _, token = _token_from(ses)
    later = time.time() + 49 * 3600
    monkeypatch.setattr(email_alerts.time, "time", lambda: later)
    assert client.get("/api/v1/alerts/confirm", params={"email": SIGNUP["email"], "token": token}).status_code == 400
    assert email_alerts.purge_expired_signups() == 1 and SIGNUP["email"] not in ses.contacts
    assert client.get("/api/v1/alerts/confirm", params={"email": "nobody@example.org", "token": token}).status_code == 400


def test_ses_alert_reaches_the_right_levels_once_with_unsubscribe(ses):
    def member(email, topic):
        ses.contacts[email] = {"EmailAddress": email, "UnsubscribeAll": False, "AttributesData": "{}",
                               "TopicPreferences": [{"TopicName": topic, "SubscriptionStatus": "OPT_IN"}]}
    member("y@example.org", "new_delhi-yellow"); member("o@example.org", "new_delhi-orange")
    member("r@example.org", "new_delhi-red"); member("m@example.org", "mumbai-orange")
    res = {"alert_level": "orange", "forecast_tmax_c": 44.1, "forecast_heat_index_c": 46.0,
           "top_wards": [{"rank": 1, "ward_name": "Zone <1>", "risk_score": 80}]}
    subject, html_body, text = email_alerts.build_card("New Delhi", res, ("Very hot.", "बहुत गर्मी।"),
                                                       citizen_url="https://site.example/citizen?city=new_delhi",
                                                       regional=("Marathi", "खूप उष्णता"))
    assert "{{amazonSESUnsubscribeUrl}}" in html_body and "{{amazonSESUnsubscribeUrl}}" in text
    assert "Zone &lt;1&gt;" in html_body and "112" in html_body and "ORANGE" in subject and "machine translated" in html_body
    out = email_alerts.send_city_alert("new_delhi", "orange", subject, html_body, text)
    to = sorted(m["Destination"]["ToAddresses"][0] for m in ses.sent)
    assert out["sent"] == 2 and to == ["o@example.org", "y@example.org"]           # not red-only, not Mumbai
    assert all(m["ListManagementOptions"]["ContactListName"] == "heatrelief-alerts" for m in ses.sent)
    assert email_alerts.send_city_alert("new_delhi", "green", subject, html_body, text)["sent"] == 0


# ── Feature G: street sensors ────────────────────────────────
def test_sensor_readings_are_cleaned_for_the_map(fake_city):
    from api.routers.sensors import clean
    now = time.time()
    good = clean({"sensor_id": "nd-01", "temp_c": "44.5", "humidity": 30, "lat": 28.6, "lon": 77.2,
                  "received_at": (now - 30) * 1000}, now)
    assert good["temp_c"] == 44.5 and good["heat_index_c"] is not None and good["stale"] is False
    assert good["alert_level"] in ("orange", "red")
    assert clean({"sensor_id": "x", "temp_c": 41, "lat": 28.6, "lon": 77.2, "received_at": (now - 3600) * 1000}, now)["stale"]
    assert clean({"sensor_id": "x", "temp_c": 999, "lat": 28.6, "lon": 77.2}) is None       # broken sensor
    assert clean({"sensor_id": "x", "temp_c": 40}) is None                                   # no position
    store.put_sensor_reading({"city": fake_city, "sensor_id": "nd-01", "temp_c": 41.0, "humidity": 35,
                              "lat": 28.55, "lon": 77.06, "received_at": int(now * 1000)})
    out = client.get(f"/api/v1/sensors?city={fake_city}").json()
    assert out["count"] == 1 and out["live"] == 1 and out["max_temp_c"] == 41.0
    assert client.get("/api/v1/sensors?city=kochi").status_code == 404


def test_hot_sensor_notifies_operators_once_an_hour(monkeypatch):
    from botocore.exceptions import ClientError
    from lambdas.sensor_alert import app as alarm
    sns = Recorder()
    monkeypatch.setattr(alarm, "sns", sns)
    monkeypatch.setenv("OPS_TOPIC_ARN", "arn:aws:sns:us-east-1:000000000000:ops")
    hot = {"temp_c": 47.2, "humidity": 30, "sensor_id": "nd-01", "city": "new_delhi"}
    assert alarm.handler(hot, None)["notified"] is True
    assert "operators only" in sns.calls[0][1]["Message"] and "47.2" in sns.calls[0][1]["Message"]
    assert alarm.handler({**hot, "temp_c": 36.0}, None)["notified"] is False          # below orange
    assert alarm.handler({"sensor_id": "nd-01"}, None)["notified"] is False
    monkeypatch.setenv("RATE_LIMIT_TABLE", "rate")
    monkeypatch.setattr(alarm, "dynamodb", Recorder(put_item=ClientError(
        {"Error": {"Code": "ConditionalCheckFailedException"}}, "PutItem")))
    assert alarm.handler(hot, None)["notified"] is False and len(sns.calls) == 1     # already told this hour


# ── daily job: SES card + Athena history ─────────────────────
def test_daily_job_sends_ses_cards_and_writes_risk_history(fake_city, ses, monkeypatch):
    from lambdas.refresh_forecast import app as refresh
    rec = Recorder(synthesize_speech={"AudioStream": type("S", (), {"read": lambda self: b"mp3"})()},
                   generate_presigned_url="https://example.invalid/audio")
    day = {"date": "2026-10-11", "tmax_c": 46.0, "heat_index_c": 47.0, "alert_level": "red"}
    monkeypatch.setattr(refresh, "get_forecast", lambda city, days: {"today": day, "days": [day]})
    monkeypatch.setattr(refresh.aws, "client", lambda service: ses if service == "sesv2" else rec)
    monkeypatch.setattr(refresh.aws, "DATA_BUCKET", "data")
    monkeypatch.setattr(refresh, "TOPIC_ARN", None)
    monkeypatch.setenv("ANALYTICS_ENABLED", "true")
    monkeypatch.setenv("CORS_ORIGINS", "https://d111.cloudfront.net")
    ses.contacts["c@example.org"] = {"EmailAddress": "c@example.org", "UnsubscribeAll": False, "AttributesData": "{}",
                                     "TopicPreferences": [{"TopicName": f"{fake_city}-orange", "SubscriptionStatus": "OPT_IN"}]}
    out = refresh.handler({"cities": [fake_city]})["results"][0]
    assert out["ses"]["sent"] == 1 and out["alert_sent"] is True
    card = ses.sent[-1]["Content"]["Simple"]["Body"]["Html"]["Data"]
    assert f"https://d111.cloudfront.net/citizen?city={fake_city}" in card and "RED" in card
    puts = {kw["Key"]: kw for name, kw in rec.calls if name == "put_object"}
    assert f"advisories/{fake_city}/2026-10-11-en.mp3" in puts and f"advisories/{fake_city}/2026-10-11.mp3" in puts
    rows = [json.loads(l) for l in puts[f"analytics/risk_daily/city={fake_city}/dt=2026-10-11/risk.json"]["Body"].decode().split("\n")]
    assert len(rows) > 10 and rows[0]["rank"] == 1 and rows[0]["alert_level"] == "red"
    assert set(rows[0]) == {"ward_id", "ward_name", "rank", "risk_score", "risk_today", "population", "lst_mean",
                            "alert_level", "forecast_tmax_c", "forecast_heat_index_c"}


# ── what the browser is told ─────────────────────────────────
def test_client_config_and_status_expose_no_secrets(cognito, monkeypatch):
    monkeypatch.setenv("EDGE_SECRET", "edge-123")
    monkeypatch.setenv("OFFICER_TOKEN", "s3cret")
    edge = {"X-Origin-Verify": "edge-123"}
    cfg = client.get("/api/v1/system/config", headers=edge).json()
    assert cfg["auth"] == {"mode": "cognito", "region": "us-east-1", "client_id": "client123",
                           "roles": ["ward_officer", "city_planner"]}
    status = client.get("/api/v1/system/status", headers=edge).json()
    assert status["features"]["waf"] is True and status["features"]["sign_in"] == "Amazon Cognito roles"
    blob = json.dumps(cfg) + json.dumps(status)
    assert "edge-123" not in blob and "s3cret" not in blob and "arn:" not in blob and "us-east-1_TestPool1" not in blob
