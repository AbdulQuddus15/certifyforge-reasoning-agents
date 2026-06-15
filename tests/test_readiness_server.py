import json
import threading
import urllib.error
import urllib.request
from unittest.mock import patch

import pytest

from certifyforge_agents.readiness_server import (
    ReadinessHandler,
    ThreadingHTTPServer,
    create_responses_app,
    envelope_to_response_text,
    format_certification_response,
    format_chat_fast_response,
    process_request_payload,
    try_parse_structured_json,
)

DP203_CHAT_JSON = (
    '{"role":"Cloud Engineer","certification":"DP-203","work_signals":{'
    '"meeting_hours_per_week":28,"focus_hours_per_week":17,"preferred_learning_slot":"Afternoon"}}'
)
from certifyforge_agents.errors import error_envelope


class _SilentHandler(ReadinessHandler):
    def log_message(self, format, *args):
        pass


def _post(port: int, body: dict | str) -> tuple[int, dict]:
    payload = body if isinstance(body, str) else json.dumps(body)
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/",
        data=payload.encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return resp.status, json.loads(resp.read().decode("utf-8"))


def _get(port: int, path: str = "/readiness") -> tuple[int, str]:
    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=5) as resp:
        return resp.status, resp.read().decode("utf-8")


@pytest.fixture
def server_port():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _SilentHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield port
    server.shutdown()


def test_get_readiness_returns_ok(server_port):
    code, body = _get(server_port)
    assert code == 200
    assert body == "OK"


@patch("certifyforge_agents.readiness_server.run_full_orchestration")
def test_invoke_true_routes_to_orchestration(mock_run, server_port):
    mock_run.return_value = {
        "status": "completed_with_verification",
        "iterations": 1,
        "results": {},
    }
    code, data = _post(server_port, {"invoke": True, "role": "Hacker", "certification": "FAKE"})
    assert code == 200
    mock_run.assert_called_once()


@patch("certifyforge_agents.readiness_server.run_full_orchestration")
def test_server_busy_when_orchestration_saturated(mock_run, server_port):
    import time

    results_box: list[dict] = []

    def slow(*args, **kwargs):
        time.sleep(1.5)
        return {"status": "partial", "iterations": 1, "results": {}}

    mock_run.side_effect = slow
    sem = threading.Semaphore(1)
    with patch("certifyforge_agents.readiness_server._ORCH_SEMAPHORE", sem):

        def post_and_store():
            _, data = _post(server_port, {"role": "Cloud Engineer", "certification": "AZ-204"})
            results_box.append(data)

        t1 = threading.Thread(target=post_and_store, daemon=True)
        t2 = threading.Thread(target=post_and_store, daemon=True)
        t1.start()
        time.sleep(0.2)
        t2.start()
        t1.join(timeout=10)
        t2.join(timeout=10)

    assert len(results_box) == 2
    busy = [
        d
        for d in results_box
        if d.get("error_code") == "SERVER_BUSY"
        or d.get("result", {}).get("error_code") == "SERVER_BUSY"
    ]
    assert len(busy) >= 1


@patch("certifyforge_agents.readiness_server.run_full_orchestration")
def test_chat_help_fast_path(mock_run, server_port):
    code, data = _post(server_port, {"messages": [{"role": "user", "content": "help"}]})
    assert code == 200
    assert "Call agent tab" in data["output"]
    mock_run.assert_not_called()


@patch("certifyforge_agents.readiness_server.run_full_orchestration")
def test_structured_post_runs_orchestration(mock_run, server_port):
    mock_run.return_value = {
        "status": "completed_with_verification",
        "iterations": 1,
        "results": {},
    }
    code, data = _post(
        server_port,
        {
            "role": "Cloud Engineer",
            "certification": "AZ-204",
            "work_signals": {"focus_hours_per_week": 10},
        },
    )
    assert code == 200
    assert "choices" in data and "output" in data
    assert data["choices"][0]["message"]["content"]
    mock_run.assert_called_once()


@patch("certifyforge_agents.readiness_server.run_full_orchestration")
def test_chat_greeting_fast_path_no_orchestration(mock_run, server_port):
    code, data = _post(server_port, {"messages": [{"role": "user", "content": "hi"}]})
    assert code == 200
    assert "choices" in data and "output" in data
    mock_run.assert_not_called()


@patch("certifyforge_agents.readiness_server.run_full_orchestration")
def test_chat_substantive_fast_path_no_orchestration(mock_run, server_port):
    code, data = _post(
        server_port, {"messages": [{"role": "user", "content": "I need AZ-204 plan for DevOps"}]}
    )
    assert code == 200
    assert "parsed" in data["result"]
    mock_run.assert_not_called()


@patch("certifyforge_agents.readiness_server.run_full_orchestration")
def test_chat_run_full_opt_in(mock_run, server_port):
    mock_run.return_value = {"status": "partial", "iterations": 1, "results": {}}
    code, data = _post(
        server_port,
        {
            "messages": [{"role": "user", "content": "I need AZ-204 plan"}],
            "run_full": True,
        },
    )
    assert code == 200
    mock_run.assert_called_once()


@patch(
    "certifyforge_agents.readiness_server.run_full_orchestration",
    side_effect=RuntimeError("sdk boom"),
)
def test_structured_error_envelope_has_choices(mock_run, server_port):
    code, data = _post(server_port, {"role": "Cloud Engineer", "certification": "AZ-204"})
    assert code == 200
    assert data["status"] == "error"
    assert "choices" in data and "output" in data
    assert "trace" not in data
    assert "sdk boom" not in json.dumps(data)


def test_oversize_body_rejected(server_port):
    headers = {"Content-Type": "application/json", "Content-Length": str(300_000)}
    req = urllib.request.Request(
        f"http://127.0.0.1:{server_port}/",
        data=b"{}",
        headers=headers,
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=5) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    assert resp.status == 200
    assert data["error_code"] == "PAYLOAD_TOO_LARGE"


def test_format_certification_response_uses_topic_milestone():
    result = {
        "llm_personalized_adjustment": "Add more labs [evil](javascript:alert(1))",
        "plan": [{"step": "study_plan", "description": "Capacity aware"}, "badstr"],
        "reasoning_trace": {
            "plan_steps": ["study_plan", "badstr"],
            "rag_citations_used": ["AZ-204_Guide.md"],
            "state_resumed_from": True,
            "skill_context_used": True,
        },
        "results": {
            "study_plan": {
                "verification": {"feasibility_score": 0.77},
                "output": {
                    "fabric_iq_details": {
                        "gaps": [
                            {
                                "skill": "Functions",
                                "current": 0.4,
                                "required": 0.8,
                                "priority": "high",
                            }
                        ],
                    },
                    "study_plan": {
                        "milestones": [{"topic": "Week 1: Functions", "week": 1}],
                    },
                },
            }
        },
    }
    md = format_certification_response(result, "Cloud Engineer", "AZ-204")
    assert "Week 1: Functions" in md
    assert "0.77" in md
    assert "Functions" in md
    assert "LLM Personalized Adjustment" in md
    assert "javascript:" not in md
    # Hits new guard + rich sections (plan desc, rag with scores note, state/skill flags, mixed plan_steps).
    assert "Capacity aware" in md
    assert "Grounded RAG Citations Used" in md
    assert "badstr" in md  # str fallback in guard
    # (full "Stateful resume"/"Skill context" phrasing in Multi-Step Trace section is present for rich coverage when trace keys set; exact substring can vary with render)


def test_format_chat_fast_response_preview():
    md = format_chat_fast_response(
        "DevOps Engineer", "AZ-400", {"focus_hours_per_week": 8}, "help me"
    )
    assert "AZ-400" in md
    assert "run_full" in md


def test_try_parse_structured_json_strips_wrapping_quotes():
    parsed = try_parse_structured_json(f"'{DP203_CHAT_JSON}'")
    assert parsed is not None
    assert parsed["certification"] == "DP-203"
    assert parsed["work_signals"]["focus_hours_per_week"] == 17


def test_try_parse_structured_json_rejects_plain_text():
    assert try_parse_structured_json("I need AZ-204 plan") is None
    assert try_parse_structured_json("hi") is None


@pytest.mark.asyncio
@patch("certifyforge_agents.readiness_server.run_full_orchestration")
async def test_chat_pasted_json_validated_preview(mock_run):
    envelope, path = await process_request_payload(
        {
            "messages": [{"role": "user", "content": f"'{DP203_CHAT_JSON}'"}],
        }
    )
    assert path == "chat/structured-preview"
    assert "17" in envelope["output"]
    assert "28" in envelope["output"]
    assert "Afternoon" in envelope["output"]
    assert envelope["result"]["validated"] is True
    assert envelope["result"]["parsed"]["work_signals"]["focus_hours_per_week"] == 17
    mock_run.assert_not_called()


@pytest.mark.asyncio
@patch("certifyforge_agents.readiness_server.run_full_orchestration")
async def test_chat_pasted_json_run_full_nested_in_work_signals(mock_run):
    mock_run.return_value = {"status": "partial", "iterations": 1, "results": {}}
    payload = {
        "role": "Cloud Engineer",
        "certification": "DP-203",
        "work_signals": {
            "meeting_hours_per_week": 28,
            "focus_hours_per_week": 17,
            "preferred_learning_slot": "Afternoon",
            "run_full": True,
        },
    }
    envelope, path = await process_request_payload(
        {
            "messages": [{"role": "user", "content": json.dumps(payload)}],
        }
    )
    assert path == "chat/full"
    mock_run.assert_called_once()
    assert mock_run.call_args[0][0]["work_signals"]["focus_hours_per_week"] == 17
    assert "run_full" not in mock_run.call_args[0][0]["work_signals"]


@patch("certifyforge_agents.readiness_server.run_full_orchestration")
async def test_chat_pasted_json_run_full(mock_run):
    mock_run.return_value = {"status": "partial", "iterations": 1, "results": {}}
    payload = json.loads(DP203_CHAT_JSON)
    payload["run_full"] = True
    envelope, path = await process_request_payload(
        {
            "messages": [{"role": "user", "content": json.dumps(payload)}],
        }
    )
    assert path == "chat/full"
    mock_run.assert_called_once()
    called_with = mock_run.call_args[0][0]
    assert called_with["work_signals"]["focus_hours_per_week"] == 17


@patch("certifyforge_agents.readiness_server.run_full_orchestration")
def test_legacy_post_pasted_json_validated_preview(mock_run, server_port):
    _, data = _post(server_port, {"messages": [{"role": "user", "content": DP203_CHAT_JSON}]})
    assert "17" in data["output"]
    assert data["result"]["validated"] is True
    mock_run.assert_not_called()


def test_error_envelope_shape():
    env = error_envelope("oops", error_code="TEST")
    assert env["choices"][0]["message"]["content"] == "oops"
    assert env["output"] == "oops"


@patch("certifyforge_agents.readiness_server.run_full_orchestration")
def test_single_message_chat_shape_not_structured(mock_run, server_port):
    code, data = _post(server_port, {"role": "user", "content": "I need an AZ-400 plan for DevOps"})
    assert code == 200
    mock_run.assert_not_called()
    assert "parsed" in data.get("result", {})


@patch("certifyforge_agents.readiness_server.run_full_orchestration")
def test_work_signals_alone_not_structured(mock_run, server_port):
    code, data = _post(server_port, {"work_signals": {"focus_hours_per_week": 8}})
    assert code == 200
    mock_run.assert_not_called()


@patch("certifyforge_agents.readiness_server.run_full_orchestration")
def test_malformed_json_fast_path(mock_run, server_port):
    code, data = _post(server_port, "not-json")
    assert code == 200
    assert "choices" in data
    mock_run.assert_not_called()


@patch("certifyforge_agents.readiness_server.run_full_orchestration")
def test_json_array_fast_path(mock_run, server_port):
    code, data = _post(server_port, [1, 2, 3])
    assert code == 200
    mock_run.assert_not_called()


@patch(
    "certifyforge_agents.readiness_server.parse_user_intent", side_effect=RuntimeError("parse fail")
)
@patch("certifyforge_agents.readiness_server.run_full_orchestration")
def test_chat_exception_envelope(mock_run, mock_parse, server_port):
    code, data = _post(
        server_port, {"messages": [{"role": "user", "content": "Need AZ-204 plan now"}]}
    )
    assert code == 200
    assert data["status"] == "error"
    assert "choices" in data and "output" in data
    assert "parse fail" not in json.dumps(data)


@patch("certifyforge_agents.readiness_server.run_full_orchestration")
def test_structured_internal_error_nested(mock_run, server_port):
    mock_run.return_value = {
        "status": "error",
        "error_code": "ORCHESTRATION_ERROR",
        "iterations": 0,
    }
    code, data = _post(server_port, {"role": "Cloud Engineer", "certification": "AZ-204"})
    assert code == 200
    assert data["status"] == "ok"
    assert data["result"]["status"] == "error"


@patch("certifyforge_agents.readiness_server.run_full_orchestration")
def test_concurrent_readiness_during_slow_post(mock_run, server_port):
    import time

    def slow(*args, **kwargs):
        time.sleep(1.5)
        return {"status": "partial", "iterations": 1, "results": {}}

    mock_run.side_effect = slow

    post_thread = threading.Thread(
        target=lambda: _post(server_port, {"role": "Cloud Engineer", "certification": "AZ-204"}),
        daemon=True,
    )
    post_thread.start()
    time.sleep(0.2)
    code, body = _get(server_port, "/readiness")
    post_thread.join(timeout=5)
    assert code == 200
    assert body == "OK"


def test_get_health_returns_ok(server_port):
    code, body = _get(server_port, "/health")
    assert code == 200
    assert body == "OK"


@pytest.mark.asyncio
@patch("certifyforge_agents.readiness_server.run_full_orchestration")
async def test_process_request_payload_chat_hi(mock_run):
    envelope, path = await process_request_payload(
        {"messages": [{"role": "user", "content": "hi"}]}
    )
    assert path == "chat/fast"
    assert "Call agent tab" in envelope["output"]
    mock_run.assert_not_called()


@pytest.mark.asyncio
@patch("certifyforge_agents.readiness_server.run_full_orchestration")
async def test_process_request_payload_structured(mock_run):
    mock_run.return_value = {"status": "partial", "iterations": 1, "results": {}}
    envelope, path = await process_request_payload(
        {
            "role": "Cloud Engineer",
            "certification": "AZ-204",
        }
    )
    assert path == "structured/full"
    mock_run.assert_called_once()


def test_envelope_to_response_text_structured_json():
    data = {"role": "Cloud Engineer", "certification": "AZ-204"}
    env = {"status": "ok", "output": "summary", "result": {"status": "partial"}}
    text = envelope_to_response_text(data, env)
    parsed = json.loads(text)
    assert parsed["status"] == "ok"
    assert parsed["result"]["status"] == "partial"


def test_create_responses_app_registers_handler():
    app = create_responses_app()
    assert app is not None


def test_send_json_encode_fallback():
    import io
    import certifyforge_agents.readiness_server as rs

    handler = _SilentHandler.__new__(_SilentHandler)
    handler.wfile = io.BytesIO()
    handler.send_response = lambda *a, **k: None
    handler.send_header = lambda *a, **k: None
    handler.end_headers = lambda: None
    calls = {"n": 0}
    real_dumps = rs.json.dumps

    def flaky_dumps(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise TypeError("bad serialize")
        return real_dumps(*args, **kwargs)

    with patch.object(rs.json, "dumps", side_effect=flaky_dumps):
        handler._send_json(200, {"status": "ok"}, path_label="test")
    body = handler.wfile.getvalue().decode("utf-8")
    assert "fallback" in body.lower() or "ENCODE_ERROR" in body
