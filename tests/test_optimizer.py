import pytest

from models.optimizer import PlanRequest, compare_equity, optimize
from pipeline.config import REAL_INTERVENTIONS


@pytest.mark.parametrize("budget", [50, 500, 5000, 50000])
def test_never_exceeds_budget(fake_city, budget):
    plan = optimize(PlanRequest(city_id=fake_city, budget_lakh=budget))
    assert plan["impact_card"]["spent_lakh"] <= budget + 1e-6
    assert sum(i["cost_lakh"] for i in plan["items"]) <= budget + 1e-6


def test_deterministic(fake_city):
    a = optimize(PlanRequest(city_id=fake_city, budget_lakh=2000, equity_weight=0.5))
    b = optimize(PlanRequest(city_id=fake_city, budget_lakh=2000, equity_weight=0.5))
    assert [i["grid_id"] for i in a["items"]] == [i["grid_id"] for i in b["items"]]


def test_one_cooling_action_per_cell(fake_city):
    plan = optimize(PlanRequest(city_id=fake_city, budget_lakh=5000))
    cool = [i["grid_id"] for i in plan["items"] if i["intervention"] != "cooling_centre"]
    assert len(cool) == len(set(cool))


def test_cooling_ranges_ordered_and_within_published_band(fake_city):
    plan = optimize(PlanRequest(city_id=fake_city, budget_lakh=3000))
    for i in plan["items"]:
        c = i["cooling_c"]
        assert c["high"] <= c["mid"] <= c["low"] <= 0
        strongest = REAL_INTERVENTIONS[i["intervention"]]["cooling_range_c"][0]
        assert c["high"] >= strongest - 1e-9


def test_equity_weight_shifts_spend_to_vulnerable_cells(fake_city):
    cmp = compare_equity(PlanRequest(city_id=fake_city, budget_lakh=1500, include_centres=False))
    assert cmp["equity"]["high_vulnerability_spend_share"] >= cmp["efficiency"]["high_vulnerability_spend_share"]


def test_tree_survival_reduces_tree_cooling(fake_city):
    kw = dict(city_id=fake_city, budget_lakh=2000, interventions=["tree_cover"], include_centres=False)
    hi = optimize(PlanRequest(tree_survival=1.0, **kw))["impact_card"]["cooling_c"]["mid"]
    lo = optimize(PlanRequest(tree_survival=0.3, **kw))["impact_card"]["cooling_c"]["mid"]
    assert hi < lo <= 0  # more survival -> more negative (cooler)


def test_timeline_ramps_up(fake_city):
    plan = optimize(PlanRequest(city_id=fake_city, budget_lakh=3000, interventions=["tree_cover"],
                                include_centres=False))
    t = [p["pop_weighted_cooling_mid_c"] for p in plan["timeline"]]
    assert t[0] == 0.0 and t[-1] <= t[0] and t == sorted(t, reverse=True)


def test_invalid_inputs_rejected(fake_city):
    with pytest.raises(ValueError):
        optimize(PlanRequest(city_id=fake_city, budget_lakh=0))
    with pytest.raises(ValueError):
        optimize(PlanRequest(city_id=fake_city, budget_lakh=100, equity_weight=2))


def test_tiny_budget_returns_empty_plan_not_error(fake_city):
    plan = optimize(PlanRequest(city_id=fake_city, budget_lakh=1))
    assert plan["items"] == [] and plan["impact_card"]["spent_lakh"] == 0


def test_equity_weight_changes_the_plan(fake_city):
    kw = dict(city_id=fake_city, budget_lakh=1500, include_centres=False)
    a = {i["grid_id"] for i in optimize(PlanRequest(equity_weight=0.0, **kw))["items"]}
    b = {i["grid_id"] for i in optimize(PlanRequest(equity_weight=1.0, **kw))["items"]}
    assert a != b


def test_equity_plan_reaches_more_vulnerable_people_efficiency_plan_cools_more(fake_city):
    kw = dict(city_id=fake_city, budget_lakh=1500, include_centres=False)
    eff = optimize(PlanRequest(equity_weight=0.0, **kw))
    eq = optimize(PlanRequest(equity_weight=1.0, **kw))
    def vuln_people(p):
        return sum(i["people"] * i["vulnerability"] for i in p["items"])
    assert vuln_people(eq) >= vuln_people(eff)
    assert eff["impact_card"]["cooling_c"]["mid"] <= eq["impact_card"]["cooling_c"]["mid"] + 1e-9
