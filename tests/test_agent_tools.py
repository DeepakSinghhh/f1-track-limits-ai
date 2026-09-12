from src.agent.precedent import PrecedentStore
from src.agent.tools import AgentContext, build_tools
from src.config import load_event_config
from src.schemas import CarState, EventType, Verdict
from tests.factories import make_event

CONFIG_PATH = "config/events/red_bull_ring_2023.yaml"


def make_state(car_number, t, s, d=0.0):
    return CarState(
        car_number=car_number,
        session_time=t,
        s=s,
        d=d,
        heading=0.0,
        speed=60.0,
        yaw_rate=0.0,
        wheel_d=None,
        wheel_sigma=None,
        source="telemetry",
        reproj_error_px=None,
        occlusion_frac=0.0,
        n_sensors=1,
    )


def make_context(telemetry=None, precedents=None):
    return AgentContext(config=load_event_config(CONFIG_PATH), telemetry=telemetry or {}, precedents=precedents)


def test_schema_names_match_dispatch_keys():
    schemas, dispatch = build_tools(make_context())
    schema_names = {s["name"] for s in schemas}
    assert schema_names == set(dispatch.keys())
    for schema in schemas:
        assert "description" in schema
        assert "input_schema" in schema


def test_get_telemetry_filters_by_time_window():
    telemetry = {44: [make_state(44, t, s=t * 10) for t in [0.0, 0.5, 1.0, 1.5, 2.0]]}
    _, dispatch = build_tools(make_context(telemetry=telemetry))
    result = dispatch["get_telemetry"](car=44, t0=0.5, t1=1.5)
    assert "t=0.50s" in result
    assert "t=1.00s" in result
    assert "t=1.50s" in result
    assert "t=0.00s" not in result
    assert "t=2.00s" not in result


def test_get_telemetry_no_data_message():
    _, dispatch = build_tools(make_context())
    result = dispatch["get_telemetry"](car=99, t0=0.0, t1=1.0)
    assert "No telemetry" in result


def test_get_neighbouring_cars_finds_nearby_car():
    telemetry = {
        44: [make_state(44, t=0.5, s=100.0)],
        7: [make_state(7, t=0.5, s=105.0)],   # within 20m
        33: [make_state(33, t=0.5, s=500.0)],  # far away
    }
    _, dispatch = build_tools(make_context(telemetry=telemetry))
    result = dispatch["get_neighbouring_cars"](car=44, t0=0.0, t1=1.0)
    assert "7" in result
    assert "33" not in result


def test_get_neighbouring_cars_none_nearby():
    telemetry = {44: [make_state(44, t=0.5, s=100.0)]}
    _, dispatch = build_tools(make_context(telemetry=telemetry))
    result = dispatch["get_neighbouring_cars"](car=44, t0=0.0, t1=1.0)
    assert "No other cars" in result


def test_get_session_precedents_no_store():
    _, dispatch = build_tools(make_context(precedents=None))
    result = dispatch["get_session_precedents"](corner=1, event_type="excursion_no_advantage")
    assert "No precedent store" in result


def test_get_session_precedents_with_matches():
    store = PrecedentStore()
    store.record(make_event(event_id="a", corner=1, proposed_type=EventType.EXCURSION_NO_ADVANTAGE), Verdict.VIOLATION)
    _, dispatch = build_tools(make_context(precedents=store))
    result = dispatch["get_session_precedents"](corner=1, event_type="excursion_no_advantage")
    assert "a:" in result
    assert "violation" in result


def test_get_event_notes_reports_config():
    _, dispatch = build_tools(make_context())
    result = dispatch["get_event_notes"](circuit="red_bull_ring")
    assert "red_bull_ring" in result
    assert "2023" in result
    assert "F1SR Art. 33.3" in result


def test_get_driving_standards_guideline_known_topic():
    _, dispatch = build_tools(make_context())
    result = dispatch["get_driving_standards_guideline"](topic="forced_off")
    assert "not verbatim" in result
    assert "forced off" in result.lower()


def test_get_driving_standards_guideline_unknown_topic():
    _, dispatch = build_tools(make_context())
    result = dispatch["get_driving_standards_guideline"](topic="something_else")
    assert "No local summary" in result
