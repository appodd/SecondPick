from __future__ import annotations

import asyncio
import json
import time

from shopping_agent.conversation_store import ConversationStore, TERMINAL_OPERATION_STATES


async def stream_operation_events(store: ConversationStore, operation_id: int, after_id: int = 0):
    heartbeat = time.monotonic()
    while True:
        # Read state first so a completion committed between reads is not missed.
        operation = await asyncio.to_thread(store.get_operation, operation_id)
        events = await asyncio.to_thread(store.list_events, operation_id, after_id)
        for event in events:
            payload = json.dumps(event.payload, ensure_ascii=False, separators=(",", ":"))
            yield f"id: {event.id}\nevent: {event.event_type}\ndata: {payload}\n\n"
            after_id = event.id
        if operation.state in TERMINAL_OPERATION_STATES or operation.state == "waiting_confirmation":
            return
        if time.monotonic() - heartbeat >= 15:
            yield ": heartbeat\n\n"
            heartbeat = time.monotonic()
        await asyncio.sleep(.2)
