import pytest

from api import store


def test_plan_lifecycle_and_audit(fake_city):
    doc = store.save_plan(fake_city, {"x": 1})
    assert doc["status"] == "draft" and len(doc["audit"]) == 1
    store.set_plan_status(doc["id"], "approved", actor="ward officer")
    done = store.set_plan_status(doc["id"], "implemented")
    assert done["status"] == "implemented"
    assert [a["status"] for a in done["audit"]] == ["draft", "approved", "implemented"]
    assert store.get_plan(doc["id"])["status"] == "implemented"


def test_invalid_transitions_rejected(fake_city):
    doc = store.save_plan(fake_city, {})
    with pytest.raises(ValueError):
        store.set_plan_status(doc["id"], "implemented")      # skipping approval
    with pytest.raises(ValueError):
        store.set_plan_status(doc["id"], "bogus")
    with pytest.raises(KeyError):
        store.set_plan_status("nope", "approved")
