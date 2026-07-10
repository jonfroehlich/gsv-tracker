"""
Boundary-decision applier (scripts/apply_decisions.py, issue #91 part 3).

Pure, network-/DB-free tests of plan_row: it maps one exported decision-CSV row
plus the city's live catalog geometry to an APPLY / NOCHANGE / SKIP action.
"""

import importlib.util
import os

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_spec = importlib.util.spec_from_file_location(
    "apply_decisions", os.path.join(PROJECT_ROOT, "scripts", "apply_decisions.py")
)
ad = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ad)

CURRENT = ad.Current(center_lat=42.35, center_lon=-71.06, width_m=20000, height_m=20000)


def row(**kw):
    base = {
        "city_id": "boston",
        "display_name": "Boston",
        "decision": "accept",
        "chosen_center_lat": "42.31",
        "chosen_center_lon": "-71.00",
        "chosen_width_m": "31885",
        "chosen_height_m": "18779",
    }
    base.update(kw)
    return base


def test_apply_when_chosen_differs():
    p = ad.plan_row(row(), CURRENT)
    assert p.action == "APPLY"
    assert (p.new_center_lat, p.new_width_m) == (42.31, 31885)
    assert (p.old_center_lat, p.old_width_m) == (42.35, 20000)


def test_nochange_when_chosen_equals_current():
    same = row(
        chosen_center_lat="42.35",
        chosen_center_lon="-71.06",
        chosen_width_m="20000",
        chosen_height_m="20000",
        decision="keep_current",
    )
    p = ad.plan_row(same, CURRENT)
    assert p.action == "NOCHANGE"


def test_skip_when_no_decision():
    p = ad.plan_row(row(decision=""), CURRENT)
    assert p.action == "SKIP"
    assert "no decision" in p.reason


def test_skip_when_decision_but_blank_geometry():
    # skip/defer/rework export a decision but no chosen_* geometry.
    p = ad.plan_row(
        row(
            decision="skip",
            chosen_center_lat="",
            chosen_center_lon="",
            chosen_width_m="",
            chosen_height_m="",
        ),
        CURRENT,
    )
    assert p.action == "SKIP"
    assert "no geometry" in p.reason


def test_skip_when_not_in_catalog():
    p = ad.plan_row(row(city_id="ghost"), None)
    assert p.action == "SKIP"
    assert "not found" in p.reason


def test_chosen_none_on_partial_geometry():
    assert ad._chosen(row(chosen_width_m="")) is None
    assert ad._chosen(row()) == (42.31, -71.00, 31885, 18779)
