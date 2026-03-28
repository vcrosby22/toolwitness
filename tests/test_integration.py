"""End-to-end integration tests.

Exercises the full flow: register → execute → verify → persist → query.
Uses a temp SQLite database, no real API keys.
"""

import pytest

from toolwitness import Classification, ToolWitnessDetector
from toolwitness.adapters.anthropic import wrap as wrap_anthropic
from toolwitness.adapters.langchain import ToolWitnessMiddleware
from toolwitness.adapters.openai import wrap as wrap_openai
from toolwitness.storage.sqlite import SQLiteStorage


@pytest.fixture()
def storage(tmp_path):
    db = SQLiteStorage(tmp_path / "integration.db")
    yield db
    db.close()


class TestDetectorToStorage:
    """ToolWitnessDetector with SQLite persistence."""

    def test_full_flow_verified(self, storage):
        detector = ToolWitnessDetector(storage=storage)

        @detector.tool()
        def get_weather(city: str) -> dict:
            return {"city": city, "temp_f": 72, "condition": "sunny"}

        detector.execute_sync("get_weather", {"city": "Miami"})
        results = detector.verify_sync("The weather in Miami is 72°F and sunny.")

        assert len(results) == 1
        assert results[0].classification == Classification.VERIFIED

        # Verify data landed in SQLite
        verifications = storage.query_verifications()
        assert len(verifications) == 1
        assert verifications[0]["classification"] == "verified"
        assert verifications[0]["tool_name"] == "get_weather"
        assert verifications[0]["session_id"] == detector.session_id

    def test_full_flow_fabricated(self, storage):
        detector = ToolWitnessDetector(storage=storage)

        @detector.tool()
        def get_weather(city: str) -> dict:
            return {"city": city, "temp_f": 72, "condition": "sunny"}

        detector.execute_sync("get_weather", {"city": "Miami"})
        results = detector.verify_sync("The weather in Miami is 95°F and rainy.")

        assert results[0].classification == Classification.FABRICATED

        verifications = storage.query_verifications()
        assert verifications[0]["classification"] == "fabricated"

    def test_session_recorded(self, storage):
        detector = ToolWitnessDetector(storage=storage)
        sessions = storage.query_sessions()
        assert len(sessions) == 1
        assert sessions[0]["session_id"] == detector.session_id

    def test_execution_recorded(self, storage):
        detector = ToolWitnessDetector(storage=storage)

        @detector.tool()
        def add(a: int, b: int) -> int:
            return a + b

        detector.execute_sync("add", {"a": 2, "b": 3})

        # Query the executions table directly
        cursor = storage._conn.execute(
            "SELECT * FROM executions WHERE tool_name = ?", ("add",)
        )
        rows = cursor.fetchall()
        assert len(rows) == 1

    def test_tool_stats_populated(self, storage):
        detector = ToolWitnessDetector(storage=storage)

        @detector.tool()
        def get_weather(city: str) -> dict:
            return {"city": city, "temp_f": 72}

        detector.execute_sync("get_weather", {"city": "Miami"})
        detector.verify_sync("Miami is 72°F.")

        detector.execute_sync("get_weather", {"city": "NYC"})
        detector.verify_sync("NYC is 95°F.")

        stats = storage.get_tool_stats()
        assert "get_weather" in stats
        assert stats["get_weather"]["total"] == 2

    def test_no_storage_still_works(self):
        detector = ToolWitnessDetector()

        @detector.tool()
        def echo(msg: str) -> str:
            return msg

        detector.execute_sync("echo", {"msg": "hello"})
        results = detector.verify_sync("hello")
        assert len(results) == 1


class TestOpenAIAdapterToStorage:
    """OpenAI adapter with SQLite persistence."""

    def test_full_flow(self, storage):
        class FakeClient:
            pass

        client = wrap_openai(FakeClient(), storage=storage)
        client.toolwitness.register_tool(
            "get_weather",
            lambda city: {"city": city, "temp_f": 72, "condition": "sunny"},
        )

        response = {
            "choices": [{
                "message": {
                    "tool_calls": [{
                        "id": "call_1",
                        "function": {
                            "name": "get_weather",
                            "arguments": '{"city": "Miami"}',
                        },
                    }],
                },
            }],
        }

        client.toolwitness.extract_tool_calls(response)
        client.toolwitness.execute_tool_calls()
        results = client.toolwitness.verify("Miami is 72°F and sunny.")

        assert results[0].classification == Classification.VERIFIED

        verifications = storage.query_verifications()
        assert len(verifications) == 1
        assert verifications[0]["classification"] == "verified"


class TestAnthropicAdapterToStorage:
    """Anthropic adapter with SQLite persistence."""

    def test_full_flow(self, storage):
        class FakeClient:
            pass

        client = wrap_anthropic(FakeClient(), storage=storage)
        client.toolwitness.register_tool(
            "get_weather",
            lambda city: {"city": city, "temp_f": 72, "condition": "sunny"},
        )

        response = {
            "content": [{
                "type": "tool_use",
                "id": "toolu_1",
                "name": "get_weather",
                "input": {"city": "Miami"},
            }],
        }

        client.toolwitness.extract_tool_uses(response)
        client.toolwitness.execute_tool_uses()
        results = client.toolwitness.verify("Miami is 72°F and sunny.")

        assert results[0].classification == Classification.VERIFIED

        verifications = storage.query_verifications()
        assert len(verifications) == 1


class TestLangChainMiddlewareToStorage:
    """LangChain middleware with SQLite persistence."""

    def test_full_flow(self, storage):
        mw = ToolWitnessMiddleware(storage=storage)
        mw.on_tool_start(
            {"name": "get_weather"},
            '{"city": "Miami"}',
        )
        mw.on_tool_end(
            '{"city": "Miami", "temp_f": 72, "condition": "sunny"}'
        )

        results = mw.verify("The weather in Miami is 72°F and sunny.")
        assert results[0].classification == Classification.VERIFIED

        verifications = storage.query_verifications()
        assert len(verifications) == 1
        assert verifications[0]["classification"] == "verified"


class TestCrossSessionIsolation:
    """Verify sessions don't bleed into each other."""

    def test_separate_sessions(self, storage):
        d1 = ToolWitnessDetector(storage=storage, session_id="session-A")
        d2 = ToolWitnessDetector(storage=storage, session_id="session-B")

        @d1.tool()
        def tool_a(x: int) -> int:
            return x * 2

        @d2.tool()
        def tool_b(x: int) -> int:
            return x * 3

        d1.execute_sync("tool_a", {"x": 5})
        d1.verify_sync("The result is 10.")

        d2.execute_sync("tool_b", {"x": 5})
        d2.verify_sync("The result is 15.")

        v_a = storage.query_verifications(session_id="session-A")
        v_b = storage.query_verifications(session_id="session-B")

        assert len(v_a) == 1
        assert len(v_b) == 1
        assert v_a[0]["session_id"] == "session-A"
        assert v_b[0]["session_id"] == "session-B"


class TestMultiAgentSessionHierarchy:
    """Phase 1: agent_name and parent_session_id on sessions."""

    def test_agent_name_stored(self, storage):
        d = ToolWitnessDetector(
            storage=storage, agent_name="researcher",
        )
        sessions = storage.query_sessions()
        assert len(sessions) == 1
        assert sessions[0]["agent_name"] == "researcher"

    def test_parent_child_link(self, storage):
        parent = ToolWitnessDetector(
            storage=storage, agent_name="orchestrator",
        )
        child = ToolWitnessDetector(
            storage=storage,
            agent_name="researcher",
            parent_session_id=parent.session_id,
        )
        sessions = storage.query_sessions()
        child_row = [
            s for s in sessions if s["session_id"] == child.session_id
        ][0]
        assert child_row["parent_session_id"] == parent.session_id
        assert child_row["agent_name"] == "researcher"

    def test_session_tree(self, storage):
        root = ToolWitnessDetector(
            storage=storage, agent_name="orchestrator",
        )
        child_a = ToolWitnessDetector(
            storage=storage,
            agent_name="researcher",
            parent_session_id=root.session_id,
        )
        child_b = ToolWitnessDetector(
            storage=storage,
            agent_name="writer",
            parent_session_id=root.session_id,
        )
        tree = storage.query_session_tree(root.session_id)
        ids = {s["session_id"] for s in tree}
        assert root.session_id in ids
        assert child_a.session_id in ids
        assert child_b.session_id in ids
        assert len(tree) == 3

    def test_detector_properties(self, storage):
        d = ToolWitnessDetector(
            storage=storage,
            agent_name="writer",
            parent_session_id="parent-123",
        )
        assert d.agent_name == "writer"
        assert d.parent_session_id == "parent-123"


class TestHandoffTracking:
    """Phase 2: handoff registration and persistence."""

    def test_register_handoff(self, storage):
        src = ToolWitnessDetector(
            storage=storage, agent_name="orchestrator",
        )
        tgt = ToolWitnessDetector(
            storage=storage,
            agent_name="researcher",
            parent_session_id=src.session_id,
        )

        @src.tool()
        def get_customer(name: str) -> dict:
            return {"name": name, "id": 42}

        src.execute_sync("get_customer", {"name": "Jane Doe"})
        handoff = src.register_handoff(tgt, data="customer record")

        assert handoff is not None
        assert handoff.source_session_id == src.session_id
        assert handoff.target_session_id == tgt.session_id
        assert len(handoff.source_receipt_ids) == 1

        stored = storage.query_handoffs(session_id=src.session_id)
        assert len(stored) == 1
        assert stored[0]["data_summary"] == "customer record"

    def test_handoff_without_storage(self):
        src = ToolWitnessDetector(agent_name="a")
        tgt = ToolWitnessDetector(agent_name="b")
        handoff = src.register_handoff(tgt, data="test")
        assert handoff is not None
        assert handoff.source_session_id == src.session_id


class TestCrossAgentVerification:
    """Phase 3: verify_with_handoffs detects corruption across agents."""

    def test_faithful_handoff(self, storage):
        """No corruption — receiving agent reports data accurately."""
        src = ToolWitnessDetector(
            storage=storage, agent_name="orchestrator",
        )
        tgt = ToolWitnessDetector(
            storage=storage,
            agent_name="writer",
            parent_session_id=src.session_id,
        )

        @src.tool()
        def get_customer(name: str) -> dict:
            return {"name": name, "email": "jane@example.com"}

        src.execute_sync("get_customer", {"name": "Jane Doe"})
        src.register_handoff(tgt, data="customer record")

        local, handoff_results = tgt.verify_with_handoffs(
            "The customer is Jane Doe, email jane@example.com.",
        )
        assert len(handoff_results) == 0

    def test_corrupted_handoff(self, storage):
        """Receiving agent misrepresents source tool data."""
        src = ToolWitnessDetector(
            storage=storage, agent_name="orchestrator",
        )
        tgt = ToolWitnessDetector(
            storage=storage,
            agent_name="writer",
            parent_session_id=src.session_id,
        )

        @src.tool()
        def get_customer(name: str) -> dict:
            return {"name": name, "email": "jane@example.com", "id": 42}

        src.execute_sync("get_customer", {"name": "Jane Doe"})
        src.register_handoff(tgt, data="customer record")

        local, handoff_results = tgt.verify_with_handoffs(
            "The customer is John Smith with email john@other.com and id 99.",
        )
        assert len(handoff_results) >= 1
        hr = handoff_results[0]
        assert hr.source_session_id == src.session_id
        assert hr.tool_name == "get_customer"
        assert len(hr.corruption_chain) == 3
        assert hr.corruption_chain[0]["step"] == "original_tool_output"
        assert hr.corruption_chain[1]["step"] == "handoff"
        assert hr.corruption_chain[2]["step"] == "receiving_agent_response"

    def test_summary_includes_agent_info(self, storage):
        d = ToolWitnessDetector(
            storage=storage,
            agent_name="researcher",
            parent_session_id="parent-1",
        )
        s = d.summary()
        assert s["agent_name"] == "researcher"
        assert s["parent_session_id"] == "parent-1"
