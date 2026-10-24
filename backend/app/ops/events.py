"""Live change notifications for every connected device / branch.

Every audited change runs `pg_notify('mytech_events', ...)` inside its own
transaction, so the event is delivered only if the change is committed, and
it reaches every API worker. A listener thread fans events out to the
WebSocket clients of the same company. Payloads carry no personal data:
only entity, id and action; clients re-fetch through the normal API, which
applies permissions.
"""
from __future__ import annotations

import asyncio
import json
import logging
import threading
import uuid
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.engine import make_url

from app.core.config import get_settings

CHANNEL = "mytech_events"
log = logging.getLogger("mytech.events")


def notify(db, company_id, entity: str, entity_id, action: str) -> None:
    payload = json.dumps({"cid": str(company_id), "entity": entity, "id": str(entity_id), "action": action,
                          "at": datetime.now(timezone.utc).isoformat()})
    db.execute(text("SELECT pg_notify(:ch, :p)"), {"ch": CHANNEL, "p": payload})


class EventHub:
    def __init__(self) -> None:
        self._subs: dict[str, set[tuple[asyncio.Queue, asyncio.AbstractEventLoop]]] = {}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def subscribe(self, company_id: uuid.UUID) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=1000)
        with self._lock:
            self._subs.setdefault(str(company_id), set()).add((q, asyncio.get_running_loop()))
        return q

    def unsubscribe(self, company_id: uuid.UUID, q: asyncio.Queue) -> None:
        with self._lock:
            subs = self._subs.get(str(company_id), set())
            for item in list(subs):
                if item[0] is q:
                    subs.discard(item)

    def dispatch(self, payload: str) -> None:
        try:
            event = json.loads(payload)
        except ValueError:
            return
        with self._lock:
            targets = list(self._subs.get(event.get("cid", ""), set()))
        for q, loop in targets:
            loop.call_soon_threadsafe(_put, q, event)

    def start(self) -> None:
        if self._thread is None:
            self._stop.clear()
            self._thread = threading.Thread(target=self._run, name="event-listener", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
        self._thread = None

    def _run(self) -> None:
        import psycopg

        dsn = make_url(get_settings().database_system_url).set(drivername="postgresql").render_as_string(
            hide_password=False)
        while not self._stop.is_set():
            try:
                with psycopg.connect(dsn, autocommit=True) as conn:
                    conn.execute(f"LISTEN {CHANNEL}")
                    while not self._stop.is_set():
                        for n in conn.notifies(timeout=1.0):
                            self.dispatch(n.payload)
            except Exception as exc:  # reconnect after database restarts
                log.warning("event listener reconnecting: %s", type(exc).__name__)
                self._stop.wait(3)


def _put(q: asyncio.Queue, event: dict) -> None:
    if not q.full():
        q.put_nowait(event)


hub = EventHub()
