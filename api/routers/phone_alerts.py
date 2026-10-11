"""WhatsApp alert signup (citizens) and voice-call contacts (registered by ward officers)."""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from api import auth, email_alerts, phones, voice_calls, whatsapp
from api.net import client_ip, edge_secret
from api.routers.alerts import _PAGE, _over_limit
from api.routers.risk import require_real
from pipeline.config import CITIES, REAL_CITIES

router = APIRouter(prefix="/api/v1/phone-alerts", tags=["phone alerts"])
ACCEPTED = {"detail": "If this number can receive WhatsApp messages, a confirmation message is on its way."}


class WhatsAppSignup(BaseModel):
    phone: str = Field(..., max_length=20)
    city: Literal[*REAL_CITIES]
    min_level: Literal["yellow", "orange", "red"]
    consent: bool
    website: str = Field("", max_length=100)    # honeypot


class VoiceContact(BaseModel):
    phone: str = Field(..., max_length=20)
    ward_id: str = Field(..., max_length=40)
    language: Literal["hi", "en"] = "hi"
    consent_note: str = Field(..., min_length=3, max_length=200,
                              description="who agreed and how, e.g. 'resident agreed in person, 11 Oct'")


@router.post("/whatsapp/subscribe", status_code=202)
def whatsapp_subscribe(req: WhatsAppSignup, request: Request):
    if not whatsapp.enabled():
        raise HTTPException(501, "WhatsApp alerts are not switched on for this deployment")
    if not req.consent:
        raise HTTPException(400, "Consent is required")
    if not phones.normalize(req.phone):
        raise HTTPException(400, "Please enter a 10-digit Indian mobile number")
    if req.website or _over_limit(client_ip(request)):
        return ACCEPTED                           # same answer for bots and throttled callers
    base = (email_alerts.site_url() if edge_secret() else "") or str(request.base_url)
    try:
        cid = whatsapp.start_signup(req.phone, req.city, req.min_level, CITIES[req.city]["name"], base)
        print(f"whatsapp signup started for {cid} ({req.city}, {req.min_level})")
    except Exception as e:
        print(f"whatsapp signup failed: {type(e).__name__}")
    return ACCEPTED


@router.get("/confirm", response_class=HTMLResponse)
def confirm(id: str = Query(..., max_length=80), sig: str = Query(..., max_length=80)):
    doc = whatsapp.confirm(id, sig)
    if not doc:
        return HTMLResponse(_PAGE.format(
            en="This link is not valid any more. Please sign up again from the HeatRelief page.",
            hi="यह लिंक अब मान्य नहीं है। कृपया HeatRelief पेज से दोबारा साइन अप करें।"), status_code=400)
    city = CITIES[doc["city_id"]]["name"]
    return HTMLResponse(_PAGE.format(
        en=f"Confirmed. You will get WhatsApp heat alerts for {city} at {doc['min_level']} level and above. "
           "Every alert has a link to stop them.",
        hi=f"पुष्टि हो गई। आपको {city} के लिए व्हाट्सऐप पर गर्मी की चेतावनी मिलेगी। हर संदेश में बंद करने का लिंक है।"))


@router.get("/unsubscribe", response_class=HTMLResponse)
def unsubscribe(id: str = Query(..., max_length=80), sig: str = Query(..., max_length=80)):
    ok = whatsapp.unsubscribe(id, sig)
    return HTMLResponse(_PAGE.format(
        en="You will not get WhatsApp heat alerts any more, and your number has been deleted." if ok
        else "This link is not valid, or the number was already removed.",
        hi="अब आपको व्हाट्सऐप पर चेतावनी नहीं मिलेगी और आपका नंबर हटा दिया गया है।" if ok
        else "यह लिंक मान्य नहीं है, या नंबर पहले ही हटाया जा चुका है।"), status_code=200 if ok else 400)


# ── voice-call contacts: ward officers only ──────────────────
officer = auth.require_role(auth.WARD_OFFICER, auth.CITY_PLANNER)


@router.get("/voice/contacts")
def list_voice_contacts(city_id: str = Depends(require_real), user: dict = Depends(officer)):
    return {"city_id": city_id, "enabled": voice_calls.enabled(),
            "contacts": [voice_calls.public_view(d) for d in phones.list_contacts(voice_calls.CHANNEL, city_id)]}


@router.post("/voice/contacts", status_code=201)
def add_voice_contact(body: VoiceContact, city_id: str = Depends(require_real), user: dict = Depends(officer)):
    from models.risk import ward_table
    if body.ward_id not in set(ward_table(city_id)["ward_id"]):
        raise HTTPException(404, "unknown ward")
    try:
        doc = voice_calls.register(body.phone, city_id, body.ward_id, body.language, user["name"], body.consent_note)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return voice_calls.public_view(doc)


@router.delete("/voice/contacts/{contact_id}", status_code=204)
def remove_voice_contact(contact_id: str, user: dict = Depends(officer)):
    if not contact_id.startswith(f"{voice_calls.CHANNEL}#") or not phones.get(contact_id):
        raise HTTPException(404, "contact not found")
    phones.delete(contact_id)
