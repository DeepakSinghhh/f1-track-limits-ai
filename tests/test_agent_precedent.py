from src.agent.precedent import PrecedentStore
from src.schemas import EventType, Verdict
from tests.factories import make_event


def test_empty_store_returns_no_matches():
    store = PrecedentStore()
    assert store.find_similar(corner=1, event_type=EventType.EXCURSION_NO_ADVANTAGE) == []
    assert len(store) == 0


def test_exact_corner_and_type_match_is_preferred():
    store = PrecedentStore()
    e1 = make_event(event_id="a", corner=1, proposed_type=EventType.EXCURSION_NO_ADVANTAGE)
    e2 = make_event(event_id="b", corner=1, proposed_type=EventType.FORCED_OFF)
    store.record(e1, Verdict.NO_VIOLATION)
    store.record(e2, Verdict.NO_VIOLATION)

    matches = store.find_similar(corner=1, event_type=EventType.EXCURSION_NO_ADVANTAGE)
    assert len(matches) == 1
    assert matches[0].event_id == "a"


def test_falls_back_to_nearest_when_no_exact_match():
    store = PrecedentStore()
    e1 = make_event(event_id="a", corner=1, proposed_type=EventType.EXCURSION_NO_ADVANTAGE)
    store.record(e1, Verdict.VIOLATION)

    # no precedent at corner 5, but the store is not empty -- should fall back
    matches = store.find_similar(corner=5, event_type=EventType.EXCURSION_NO_ADVANTAGE)
    assert matches == [store._precedents[0]]


def test_k_limits_number_of_results():
    store = PrecedentStore()
    for i in range(10):
        e = make_event(event_id=f"e{i}", corner=1, proposed_type=EventType.EXCURSION_NO_ADVANTAGE)
        store.record(e, Verdict.NO_VIOLATION)

    matches = store.find_similar(corner=1, event_type=EventType.EXCURSION_NO_ADVANTAGE, k=3)
    assert len(matches) == 3


def test_len_reflects_recorded_count():
    store = PrecedentStore()
    assert len(store) == 0
    store.record(make_event(event_id="a"), Verdict.VIOLATION)
    store.record(make_event(event_id="b"), Verdict.NO_VIOLATION)
    assert len(store) == 2
