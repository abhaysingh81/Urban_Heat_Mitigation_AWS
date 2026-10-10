from agent.heat_officer import GUIDANCE, gather_facts, generate_brief, template_brief
from agent.numbers_check import collect_allowed, find_unsupported
from models.risk import ward_table


def _facts(city):
    ward = ward_table(city).iloc[0]["ward_id"]
    return ward, gather_facts(city, ward, 3000.0, 0.5, forecast={"today_max_temp_c": 44.0,
                              "today_heat_index_c": 46.0, "today_alert_level": "orange"})


def test_template_brief_numbers_all_come_from_facts(fake_city):
    _, facts = _facts(fake_city)
    b = template_brief(facts)
    allowed = collect_allowed(facts, GUIDANCE)
    assert find_unsupported(b["en"] + b["hi"], allowed) == []
    assert b["hi"].strip() and b["en"].strip()


def test_generate_brief_without_llm_is_verified_template(fake_city):
    ward, facts = _facts(fake_city)
    out = generate_brief(fake_city, ward, 3000.0, 0.5, use_llm=True, facts=facts)
    assert out["source"] == "template" and out["numbers_verified"] is True


def test_invented_number_in_llm_output_is_rejected(fake_city, monkeypatch):
    import agent.heat_officer as ho
    ward, facts = _facts(fake_city)
    monkeypatch.setenv("BEDROCK_MODEL_ID", "test-model")
    monkeypatch.setattr(ho, "_run_llm", lambda c, w, b, e, log, extra="": (log.append({"x": 1}) or {"en": "Spend Rs 987654 lakh.", "hi": "ठीक है"}))
    out = generate_brief(fake_city, ward, 3000.0, 0.5, use_llm=True, facts=facts)
    assert out["source"] == "template"          # fell back
    assert "987654" not in out["brief_en"]


def test_good_llm_output_is_accepted(fake_city, monkeypatch):
    import agent.heat_officer as ho
    ward, facts = _facts(fake_city)
    rank = facts["ward"]["rank"]
    monkeypatch.setenv("BEDROCK_MODEL_ID", "test-model")
    def fake(c, w, b, e, log, extra=""):
        log.append(facts["ward"])          # the agent "called" get_ward_risk
        return {"en": f"This ward ranks {rank}.", "hi": f"यह वार्ड {rank} नंबर पर है।"}
    monkeypatch.setattr(ho, "_run_llm", fake)
    out = generate_brief(fake_city, ward, 3000.0, 0.5, use_llm=True, facts=facts)
    assert out["source"] == "bedrock" and out["numbers_verified"]


def test_llm_answer_without_calling_tools_is_rejected(fake_city, monkeypatch):
    import agent.heat_officer as ho
    ward, facts = _facts(fake_city)
    rank = facts["ward"]["rank"]
    monkeypatch.setenv("BEDROCK_MODEL_ID", "test-model")
    monkeypatch.setattr(ho, "_run_llm", lambda c, w, b, e, log, extra="": {
        "en": f"This ward ranks {rank}.", "hi": "ठीक"})
    out = generate_brief(fake_city, ward, 3000.0, 0.5, use_llm=True, facts=facts)
    assert out["source"] == "template"
