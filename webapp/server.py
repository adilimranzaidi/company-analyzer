"""The web dashboard's server: serves the page and the data each panel asks for.

Run:  python -m webapp.server        then open http://127.0.0.1:8600
Only this computer can open it (it listens on 127.0.0.1).
"""

import json
import queue
import threading
from datetime import date

from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.middleware import Middleware
from starlette.middleware.gzip import GZipMiddleware
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response, StreamingResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from analyzer.edgar_client import EdgarError
from webapp import ai, payloads, service

STATIC = service.ROOT / "webapp" / "static"


class PageFiles(StaticFiles):
    """The page's own files. "no-cache" makes the browser check for a newer copy each time
    (a tiny "not modified" reply when nothing changed), so an update always shows."""

    def file_response(self, *args, **kwargs):
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "no-cache"
        return response
HOST, PORT = "127.0.0.1", 8600


def _ticker(request: Request) -> str:
    return request.path_params["ticker"].strip().upper()


async def _json(fn, *args, max_age: int = 0) -> Response:
    """Run slow work off the main thread, and turn known problems into a clear message."""
    try:
        data = await run_in_threadpool(fn, *args)
    except EdgarError as err:
        return JSONResponse({"error": str(err)}, status_code=404)
    headers = {"Cache-Control": f"private, max-age={max_age}"} if max_age else {}
    return JSONResponse(data, headers=headers)


# --- Page ----------------------------------------------------------------------

async def index(request: Request) -> Response:
    return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-cache"})


# --- Data ----------------------------------------------------------------------

async def search(request: Request) -> Response:
    return await _json(service.search_index, max_age=3600)


async def company(request: Request) -> Response:
    t = _ticker(request)
    # Start the slower lookups now, so they're ready when the page asks for them.
    # (Reading filings for the chat is heavier, so it waits until Ask is opened: see warm.)
    for fn in (service.profile, service.logo, service.filed_events, service.peers):
        service.POOL.submit(_quietly, fn, t)
    return await _json(payloads.company_payload, t, max_age=300)


def _quietly(fn, *args):
    try:
        fn(*args)
    except Exception:          # a background warm-up; the real request reports any problem
        pass


async def warm(request: Request) -> Response:
    """Start reading the filings a first question usually needs. The page calls this when
    Ask is opened, or once it has been quiet for a while."""
    service.POOL.submit(_quietly, ai.prefetch_for_chat, _ticker(request))
    return Response(status_code=204)


async def price(request: Request) -> Response:
    return await _json(payloads.price_payload, _ticker(request), max_age=300)


async def events(request: Request) -> Response:
    return await _json(payloads.events_payload, _ticker(request), max_age=300)


async def around(request: Request) -> Response:
    day = date.fromisoformat(request.query_params["day"])
    return await _json(payloads.headlines_around_payload, _ticker(request), day, max_age=600)


async def peers(request: Request) -> Response:
    chosen = [t.strip().upper() for t in request.query_params.get("tickers", "").split(",")
              if t.strip()]
    return await _json(payloads.peers_payload, _ticker(request), tuple(chosen) or None,
                       max_age=300)


async def industry(request: Request) -> Response:
    return await _json(payloads.industry_payload, _ticker(request), max_age=600)


async def drivers_get(request: Request) -> Response:
    return await _json(ai.drivers_status, _ticker(request))


async def drivers_post(request: Request) -> Response:
    return _stream(ai.write_drivers, _ticker(request))


async def update_get(request: Request) -> Response:
    return await _json(ai.update_status, _ticker(request))


async def update_post(request: Request) -> Response:
    return _stream(ai.write_update, _ticker(request))


async def filings(request: Request) -> Response:
    return await _json(payloads.filings_payload, _ticker(request), max_age=300)


async def glossary(request: Request) -> Response:
    return await _json(payloads.glossary_payload, max_age=86400)


async def logo(request: Request) -> Response:
    data = await run_in_threadpool(service.logo, _ticker(request))
    if not data:
        return Response(status_code=404)
    return Response(data, media_type="image/png",
                    headers={"Cache-Control": "private, max-age=604800"})


# --- The assistant -------------------------------------------------------------

async def briefing_get(request: Request) -> Response:
    return await _json(ai.briefing_status, _ticker(request))


async def briefing_post(request: Request) -> Response:
    return _stream(ai.write_briefing, _ticker(request))


async def explain_get(request: Request) -> Response:
    q = request.query_params
    return await _json(ai.explain_status, _ticker(request), q["kind"], q["id"])


async def explain_post(request: Request) -> Response:
    body = await request.json()
    return _stream(ai.explain, _ticker(request), body["kind"], body["id"])


async def ask(request: Request) -> Response:
    body = await request.json()
    history = [(h[0], h[1]) for h in body.get("history", [])][-6:]
    return _stream(ai.ask_question, _ticker(request), body["question"], history)


def _stream(fn, *args) -> StreamingResponse:
    """Run an assistant task in a background thread and send its progress to the page as it
    happens: one JSON message per line (status updates, the answer's words, the final
    answer with its sources)."""
    messages: queue.Queue = queue.Queue()

    def send(kind: str, **data):
        messages.put(json.dumps({"type": kind, **data}) + "\n")

    def work():
        try:
            fn(*args, send=send)
        except Exception as err:            # reported to the page, never a crash
            send("error", message=ai.friendly(err))
        finally:
            messages.put(None)

    threading.Thread(target=work, daemon=True).start()

    async def lines():
        while True:
            item = await run_in_threadpool(messages.get)
            if item is None:
                break
            yield item

    return StreamingResponse(lines(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


routes = [
    Route("/", index),
    Route("/api/search", search),
    Route("/api/company/{ticker}", company),
    Route("/api/price/{ticker}", price),
    Route("/api/events/{ticker}", events),
    Route("/api/around/{ticker}", around),
    Route("/api/peers/{ticker}", peers),
    Route("/api/filings/{ticker}", filings),
    Route("/api/industry/{ticker}", industry),
    Route("/api/drivers/{ticker}", drivers_get, methods=["GET"]),
    Route("/api/drivers/{ticker}", drivers_post, methods=["POST"]),
    Route("/api/update/{ticker}", update_get, methods=["GET"]),
    Route("/api/update/{ticker}", update_post, methods=["POST"]),
    Route("/api/logo/{ticker}", logo),
    Route("/api/glossary", glossary),
    Route("/api/warm/{ticker}", warm, methods=["POST"]),
    Route("/api/briefing/{ticker}", briefing_get, methods=["GET"]),
    Route("/api/briefing/{ticker}", briefing_post, methods=["POST"]),
    Route("/api/explain/{ticker}", explain_get, methods=["GET"]),
    Route("/api/explain/{ticker}", explain_post, methods=["POST"]),
    Route("/api/ask/{ticker}", ask, methods=["POST"]),
    Mount("/static", PageFiles(directory=STATIC), name="static"),
]

# GZip shrinks the data sent to the page (the company payload by about 85%). It leaves
# "text/event-stream" alone, which is why the assistant's live stream uses that type: its
# words then arrive as they're written instead of being held back for compression.
app = Starlette(routes=routes, middleware=[Middleware(GZipMiddleware, minimum_size=1024)])


def main() -> None:
    import uvicorn

    from analyzer.assistant import warm_up
    warm_up()                                   # load the AI library in the background
    uvicorn.run(app, host=HOST, port=PORT, log_level="warning")


if __name__ == "__main__":
    main()
