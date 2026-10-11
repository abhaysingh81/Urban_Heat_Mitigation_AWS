"""
Branded HTML heat alerts (Feature I: Amazon SES).

When SES_FROM_EMAIL and SES_CONTACT_LIST are set, citizen signups and the daily alert go through
Amazon SES instead of plain-text SNS email:

  signup  -> contact created in the SES contact list, opted OUT, with a hashed one-time token
          -> confirmation email with a link (double opt-in; the link is valid for 48 hours)
  confirm -> the contact is opted IN to one topic: "<city>-<minimum level>"
  alert   -> an HTML card to every opted-in contact of the topics at or below today's level;
             SES adds the unsubscribe link and honours it on the next send

Addresses live only inside the SES contact list. Nothing here stores or logs one; logs carry a
short hash. Without the two variables every function reports "not enabled" and the callers use SNS.
"""

from __future__ import annotations

import hashlib
import html
import json
import os
import secrets
import time
from urllib.parse import quote

from api import aws

LEVELS = ["green", "yellow", "orange", "red"]
SIGNUP_LEVELS = LEVELS[1:]                 # nobody is alerted for a normal (green) day
CONFIRM_TTL_S = 48 * 3600
MAX_SENDS_PER_RUN = 500                    # one daily run stays inside the Lambda timeout and SES limits
LEVEL_COLOUR = {"green": "#1b8a4b", "yellow": "#b98900", "orange": "#d9620b", "red": "#c81e3a"}
LEVEL_HI = {"green": "सामान्य", "yellow": "पीला", "orange": "नारंगी", "red": "लाल"}


def sender() -> str:
    return os.environ.get("SES_FROM_EMAIL", "")


def contact_list() -> str:
    return os.environ.get("SES_CONTACT_LIST", "")


def enabled() -> bool:
    return bool(sender() and contact_list())


def topic(city: str, level: str) -> str:
    return f"{city}-{level}"


def site_url() -> str:
    """Public address of the web app (the CloudFront URL the deploy script adds to CORS_ORIGINS)."""
    for origin in os.environ.get("CORS_ORIGINS", "").split(","):
        if origin.strip().startswith("https://"):
            return origin.strip().rstrip("/")
    return ""


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _ses():
    return aws.client("sesv2")


def _error_code(e: Exception) -> str:
    return getattr(e, "response", {}).get("Error", {}).get("Code", type(e).__name__)


def _attrs(contact: dict) -> dict:
    try:
        return json.loads(contact.get("AttributesData") or "{}")
    except ValueError:
        return {}


# ── signup (double opt-in) ───────────────────────────────────
def start_signup(email: str, city: str, level: str, confirm_base_url: str) -> None:
    """Record a pending signup and email the confirmation link. Raises on SES errors."""
    token = secrets.token_urlsafe(24)
    pending = {"pending": {"topic": topic(city, level), "hash": _hash(token),
                           "exp": int(time.time()) + CONFIRM_TTL_S}}
    try:
        _ses().create_contact(
            ContactListName=contact_list(), EmailAddress=email, UnsubscribeAll=False,
            TopicPreferences=[{"TopicName": topic(city, level), "SubscriptionStatus": "OPT_OUT"}],
            AttributesData=json.dumps(pending))
    except Exception as e:
        if _error_code(e) != "AlreadyExistsException":
            raise
        # known address: keep what it is already subscribed to, replace only the pending request
        current = _ses().get_contact(ContactListName=contact_list(), EmailAddress=email)
        _ses().update_contact(
            ContactListName=contact_list(), EmailAddress=email,
            UnsubscribeAll=current.get("UnsubscribeAll", False),
            TopicPreferences=current.get("TopicPreferences", []),
            AttributesData=json.dumps({**_attrs(current), **pending}))

    link = f"{confirm_base_url.rstrip('/')}/api/v1/alerts/confirm?email={quote(email)}&token={token}"
    city_name = city.replace("_", " ").title()
    text = (f"Confirm heat alerts for {city_name} ({level} and above).\n\n"
            f"Open this link to confirm:\n{link}\n\n"
            "The link works for 48 hours. If you did not ask for this, ignore this email and "
            "nothing more will be sent.\n\n"
            f"{city_name} के लिए गर्मी की चेतावनी की पुष्टि करने के लिए ऊपर दिया गया लिंक खोलें। "
            "लिंक 48 घंटे तक काम करेगा।")
    body = (f'<div style="font-family:Arial,Helvetica,sans-serif;max-width:520px;margin:auto;color:#1d2230">'
            f'<h2 style="margin:0 0 12px">HeatRelief</h2>'
            f'<p>Confirm heat alerts for <b>{html.escape(city_name)}</b> ({html.escape(level)} and above).</p>'
            f'<p><a href="{html.escape(link)}" style="display:inline-block;background:#1f6feb;color:#ffffff;'
            f'padding:12px 20px;border-radius:6px;text-decoration:none;font-weight:bold">Confirm alerts</a></p>'
            f'<p style="font-size:13px;color:#555">The link works for 48 hours. If you did not ask for this, '
            f'ignore this email and nothing more will be sent.</p>'
            f'<p lang="hi" style="font-size:14px">{html.escape(city_name)} के लिए गर्मी की चेतावनी की पुष्टि करने के लिए '
            f'ऊपर का बटन दबाएँ। लिंक 48 घंटे तक काम करेगा।</p></div>')
    _ses().send_email(
        FromEmailAddress=sender(), Destination={"ToAddresses": [email]},
        Content={"Simple": {"Subject": {"Data": f"Confirm heat alerts for {city_name}", "Charset": "UTF-8"},
                            "Body": {"Text": {"Data": text, "Charset": "UTF-8"},
                                     "Html": {"Data": body, "Charset": "UTF-8"}}}})


def confirm(email: str, token: str) -> str | None:
    """Opt the address in if the token matches. Returns the topic, or None (wrong/expired/unknown)."""
    try:
        current = _ses().get_contact(ContactListName=contact_list(), EmailAddress=email)
    except Exception:
        return None
    attrs = _attrs(current)
    pending = attrs.get("pending") or {}
    if not pending or pending.get("exp", 0) < time.time() \
            or not secrets.compare_digest(pending.get("hash", ""), _hash(token)):
        return None
    wanted = pending["topic"]
    city = wanted.rsplit("-", 1)[0]
    # one level per city: a second level for the same city would mean duplicate emails
    prefs = {p["TopicName"]: p["SubscriptionStatus"] for p in current.get("TopicPreferences", [])}
    for lvl in SIGNUP_LEVELS:
        prefs[topic(city, lvl)] = "OPT_OUT"
    prefs[wanted] = "OPT_IN"
    attrs.pop("pending")
    attrs["confirmed_at"] = int(time.time())
    _ses().update_contact(
        ContactListName=contact_list(), EmailAddress=email, UnsubscribeAll=False,
        TopicPreferences=[{"TopicName": k, "SubscriptionStatus": v} for k, v in sorted(prefs.items())],
        AttributesData=json.dumps(attrs))
    return wanted


# ── daily alert ──────────────────────────────────────────────
def build_card(city_name: str, res: dict, texts: tuple[str, str], *, audio_url: str | None = None,
               citizen_url: str | None = None, regional: tuple[str, str] | None = None,
               simulated: bool = False) -> tuple[str, str, str]:
    """(subject, html, plain text) for one city's alert. `regional` is (language name, translated advice)."""
    level = res["alert_level"]
    colour = LEVEL_COLOUR[level]
    e = html.escape
    zones = res.get("top_wards", [])[:5]
    subject = f"{'[SIMULATION] ' if simulated else ''}Heat alert: {city_name} — {level.upper()}"

    lines = []
    if simulated:
        lines.append("*** SIMULATION — this is a test, not a real alert ***\n")
    lines += [f"HEAT ALERT — {city_name}: {level.upper()}",
              f"Forecast high {res.get('forecast_tmax_c')} °C, heat index {res.get('forecast_heat_index_c')} °C.",
              "", texts[0], texts[1]]
    if regional:
        lines.append(f"{regional[1]} ({regional[0]}, machine translated)")
    if zones:
        lines += ["", "Highest-risk zones today:"] + [f"  {z['rank']}. {z['ward_name']}" for z in zones]
    lines += ["", "Drink water often. Avoid the sun from 12 to 4 pm. Check on older people and children.",
              "Emergency: 112 · Ambulance: 108"]
    if citizen_url:
        lines.append(f"Nearest cooling places: {citizen_url}")
    if audio_url:
        lines.append(f"Hindi audio advisory: {audio_url}")
    text = "\n".join(lines)

    def row(inner: str, pad: str = "14px 20px") -> str:
        return f'<tr><td style="padding:{pad}">{inner}</td></tr>'

    zone_rows = "".join(
        f'<tr><td style="padding:4px 0;font-size:14px">{z["rank"]}. {e(str(z["ward_name"]))}</td></tr>' for z in zones)
    parts = []
    if simulated:
        parts.append(row('<div style="background:#fff3cd;border:1px solid #e0b100;padding:10px;font-weight:bold;'
                         'text-align:center">SIMULATION — this is a test, not a real alert</div>'))
    parts.append(
        f'<tr><td style="background:{colour};color:#ffffff;padding:20px;text-align:center">'
        f'<div style="font-size:13px;letter-spacing:1px">HEAT ALERT · {e(city_name)}</div>'
        f'<div style="font-size:30px;font-weight:bold;margin:6px 0">{e(level.upper())} · '
        f'<span lang="hi">{LEVEL_HI[level]}</span></div>'
        f'<div style="font-size:15px">Forecast high {e(str(res.get("forecast_tmax_c")))} °C · '
        f'heat index {e(str(res.get("forecast_heat_index_c")))} °C</div></td></tr>')
    advice = f'<p style="margin:0 0 8px;font-size:16px">{e(texts[0])}</p>' \
             f'<p lang="hi" style="margin:0;font-size:16px">{e(texts[1])}</p>'
    if regional:
        advice += (f'<p style="margin:8px 0 0;font-size:16px">{e(regional[1])}</p>'
                   f'<p style="margin:2px 0 0;font-size:12px;color:#666">{e(regional[0])} — machine translated</p>')
    parts.append(row(advice))
    parts.append(row(
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#eef6ff;'
        'border-radius:6px"><tr><td style="padding:12px 14px;font-size:14px">'
        '<b>Stay safe</b><br>Drink water often, even if you are not thirsty.<br>'
        'Avoid the sun from 12 to 4 pm.<br>Check on older people, children and outdoor workers.'
        '</td></tr></table>', "0 20px 14px"))
    if zones:
        parts.append(row('<div style="font-weight:bold;font-size:14px;margin-bottom:4px">Highest-risk zones today</div>'
                         f'<table role="presentation" cellpadding="0" cellspacing="0">{zone_rows}</table>', "0 20px 14px"))
    buttons = ""
    if citizen_url:
        buttons += (f'<a href="{e(citizen_url)}" style="display:inline-block;background:#1f6feb;color:#ffffff;'
                    'padding:12px 18px;border-radius:6px;text-decoration:none;font-weight:bold;margin:0 8px 8px 0">'
                    'Find a place to cool down</a>')
    if audio_url:
        buttons += (f'<a href="{e(audio_url)}" style="display:inline-block;border:1px solid #1f6feb;color:#1f6feb;'
                    'padding:11px 18px;border-radius:6px;text-decoration:none;font-weight:bold;margin:0 0 8px 0">'
                    '<span lang="hi">हिंदी में सुनें</span></a>')
    if buttons:
        parts.append(row(buttons, "0 20px 8px"))
    parts.append(row('<div style="background:#fdecef;border-radius:6px;padding:12px 14px;font-size:15px">'
                     '<b>Emergency: 112</b> &nbsp;·&nbsp; <b>Ambulance: 108</b></div>', "0 20px 14px"))
    parts.append(row('<div style="font-size:12px;color:#666">Sent automatically by HeatRelief from the daily forecast. '
                     'Risk is a relative ranking of areas, not a medical assessment.<br>'
                     '<a href="{{amazonSESUnsubscribeUrl}}" style="color:#666">Unsubscribe</a></div>', "0 20px 18px"))
    body = ('<!doctype html><html lang="en"><body style="margin:0;background:#f2f4f7">'
            '<table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr><td align="center" '
            'style="padding:16px 8px"><table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
            'style="max-width:560px;background:#ffffff;border-radius:10px;overflow:hidden;'
            'font-family:Arial,Helvetica,sans-serif;color:#1d2230">'
            + "".join(parts) + '</table></td></tr></table></body></html>')
    return subject, body, text + "\n\nUnsubscribe: {{amazonSESUnsubscribeUrl}}"


def _opted_in(topic_name: str):
    token = None
    while True:
        kwargs = {"ContactListName": contact_list(), "PageSize": 100,
                  "Filter": {"FilteredStatus": "OPT_IN",
                             "TopicFilter": {"TopicName": topic_name, "UseDefaultIfPreferenceUnavailable": False}}}
        if token:
            kwargs["NextToken"] = token
        page = _ses().list_contacts(**kwargs)
        for c in page.get("Contacts", []):
            if not c.get("UnsubscribeAll"):
                yield c["EmailAddress"]
        token = page.get("NextToken")
        if not token:
            return


def send_city_alert(city: str, level: str, subject: str, html_body: str, text_body: str) -> dict:
    """Send the card to everyone subscribed to this city at `level` or lower. Never raises."""
    out = {"sent": 0, "failed": 0, "skipped_over_limit": 0}
    if not enabled() or level not in SIGNUP_LEVELS:
        return out
    seen: set[str] = set()
    for lvl in SIGNUP_LEVELS[: SIGNUP_LEVELS.index(level) + 1]:
        try:
            for email in _opted_in(topic(city, lvl)):
                key = _hash(email.lower())
                if key in seen:
                    continue
                seen.add(key)
                if out["sent"] + out["failed"] >= MAX_SENDS_PER_RUN:
                    out["skipped_over_limit"] += 1
                    continue
                try:
                    _ses().send_email(
                        FromEmailAddress=sender(), Destination={"ToAddresses": [email]},
                        ListManagementOptions={"ContactListName": contact_list(), "TopicName": topic(city, lvl)},
                        Content={"Simple": {"Subject": {"Data": subject, "Charset": "UTF-8"},
                                            "Body": {"Text": {"Data": text_body, "Charset": "UTF-8"},
                                                     "Html": {"Data": html_body, "Charset": "UTF-8"}}}})
                    out["sent"] += 1
                    time.sleep(0.08)  # stay under the default 14 emails/second
                except Exception as e:
                    out["failed"] += 1
                    print(f"ses send failed for {key[:12]}: {_error_code(e)}")
        except Exception as e:
            print(f"ses list failed for {topic(city, lvl)}: {_error_code(e)}")
    return out


def purge_expired_signups(limit: int = 100) -> int:
    """Delete contacts that never confirmed within 48 hours (SNS did this by itself; SES does not)."""
    if not enabled():
        return 0
    removed = 0
    try:
        page = _ses().list_contacts(ContactListName=contact_list(), PageSize=limit)
        for c in page.get("Contacts", []):
            if any(p.get("SubscriptionStatus") == "OPT_IN" for p in c.get("TopicPreferences", [])):
                continue
            full = _ses().get_contact(ContactListName=contact_list(), EmailAddress=c["EmailAddress"])
            attrs = _attrs(full)
            pending = attrs.get("pending")
            if pending and pending.get("exp", 0) < time.time() and "confirmed_at" not in attrs:
                _ses().delete_contact(ContactListName=contact_list(), EmailAddress=c["EmailAddress"])
                removed += 1
    except Exception as e:
        print(f"ses purge failed: {_error_code(e)}")
    return removed
