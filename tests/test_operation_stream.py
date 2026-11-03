import asyncio

from shopping_agent.config import AppConfig
from shopping_agent.conversation_service import ConversationService
from shopping_agent.operation_stream import stream_operation_events


def test_replay_is_ordered_and_closes_after_completed_operation(tmp_path):
    service = ConversationService(AppConfig(database_path=tmp_path / "test.sqlite"))
    created = service.create_task("Find laptop")
    store = service.store
    queued = store.list_events(created.operation.id, 0)[0]
    store.transition_operation(created.operation.id, {"queued"}, "running")
    stage = store.append_event(created.operation.id, "stage", {"stage": "preparing_answer"})
    store.complete_with_answer(created.operation.id, "Done", [])

    async def collect():
        return [frame async for frame in stream_operation_events(store, created.operation.id, queued.id)]

    frames = asyncio.run(collect())
    assert len(frames) == 2
    assert frames[0].startswith(f"id: {stage.id}\nevent: stage\n")
    assert '"stage":"preparing_answer"' in frames[0]
    assert "event: completed" in frames[1]
