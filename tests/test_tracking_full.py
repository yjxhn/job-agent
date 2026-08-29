"""Exhaustive tests for the application tracking state machine (T5-5).

Covers every status x target combination: all legal transitions succeed and
record a timeline entry, every illegal transition raises ValueError and
leaves the status unchanged.
"""

import pytest

from agent_core.storage.db import get_db, migrate
from agent_core.storage.models import VALID_STATUSES
from agent_core.tracking.tracker import STATUS_FLOW, add_application, get_timeline, update_status

# Linear career chain (待投递/已终止 are handled separately).
CHAIN = ["已投递", "HR已读", "约面", "一面", "二面", "Offer", "入职"]


@pytest.fixture
def db(tmp_path):
    conn = get_db(str(tmp_path / "track.db"))
    migrate(conn)
    yield conn
    conn.close()


def _advance_to(db, app_id, start):
    """Fast-forward a fresh application (starts at 已投递) to `start`."""
    if start == "已投递":
        return
    if start == "待投递":  # dashboard-only initial state (materials confirm)
        db.execute("UPDATE applications SET status='待投递' WHERE id=?", (app_id,))
        db.commit()
        return
    if start == "已终止":
        update_status(db, app_id, "已终止")
        return
    for st in CHAIN[1 : CHAIN.index(start) + 1]:
        update_status(db, app_id, st)


def test_status_flow_covers_all_valid_statuses():
    """STATUS_FLOW must define exactly the valid statuses (no drift)."""
    assert set(STATUS_FLOW.keys()) == set(VALID_STATUSES)


def test_add_application_starts_at_submitted(db):
    app_id = add_application(db, "job_start")
    row = db.execute("SELECT status FROM applications WHERE id=?", (app_id,)).fetchone()
    assert row["status"] == "已投递"


@pytest.mark.parametrize("start", sorted(STATUS_FLOW.keys()))
def test_terminal_states_have_no_outgoing_edges(db, start):
    if start in ("入职", "已终止"):
        assert STATUS_FLOW[start] == []


def test_invalid_app_id_raises(db):
    with pytest.raises(ValueError):
        update_status(db, 99999, "已投递")


@pytest.mark.parametrize(
    "start,target",
    [(s, t) for s, allowed in STATUS_FLOW.items() for t in allowed],
)
def test_legal_transition_succeeds_and_records_timeline(db, start, target):
    app_id = add_application(db, f"job_{start}_to_{target}")
    _advance_to(db, app_id, start)
    app = update_status(db, app_id, target)
    assert app["status"] == target
    tl = get_timeline(db, app_id)
    assert tl[-1]["from_status"] == start
    assert tl[-1]["to_status"] == target


@pytest.mark.parametrize(
    "start,target",
    [(s, t) for s in STATUS_FLOW for t in VALID_STATUSES if t not in STATUS_FLOW[s]],
)
def test_illegal_transition_raises_and_keeps_status(db, start, target):
    app_id = add_application(db, f"job_{start}_to_{target}")
    _advance_to(db, app_id, start)
    with pytest.raises(ValueError):
        update_status(db, app_id, target)
    row = db.execute("SELECT status FROM applications WHERE id=?", (app_id,)).fetchone()
    assert row["status"] == start


def test_status_update_also_from_self_is_rejected(db):
    """A status transition to the current status is illegal for every state."""
    for start in STATUS_FLOW:
        app_id = add_application(db, f"self_{start}")
        _advance_to(db, app_id, start)
        with pytest.raises(ValueError):
            update_status(db, app_id, start)
