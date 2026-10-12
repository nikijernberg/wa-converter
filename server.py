"""Web API for decoding WeakAuras exports and adapting them for WoW: Forever."""

import json
import logging
import os
import re
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from forever_translate import format_report, load_aura_document, translate_document
from wa_tool import aura_label, extract_wa_string, run_lua

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
INLINE_LIMIT = 750_000
MAX_JSON = 40_000_000
MAX_DOCS = 8
TTL_SECONDS = 30 * 60
TOKEN_RE = re.compile(r"^[0-9a-f]{32}$")
INVALID_FILENAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("wa-converter")


class UTF8JSONResponse(JSONResponse):
    def render(self, content) -> bytes:
        return json.dumps(content, ensure_ascii=False).encode("utf-8")


class Job(BaseModel):
    text: str | None = None
    token: str | None = None


@dataclass
class Stored:
    text: str
    label: str
    created: float


store: dict[str, Stored] = {}
store_lock = threading.Lock()

app = FastAPI(title="WeakAuras Converter", default_response_class=UTF8JSONResponse)


def safe_filename(name: str) -> str:
    cleaned = INVALID_FILENAME.sub("_", name).strip(" .")
    return cleaned[:80] or "aura"


def friendly_error(error: BaseException) -> str:
    if isinstance(error, json.JSONDecodeError):
        return f"JSON is invalid on line {error.lineno}. {error.msg}."
    text = str(error)
    if "no !WA:" in text:
        return "No WeakAuras string found. Copy the whole export. It should start with !WA:2!"
    if "unsupported wa version" in text:
        return "This string is an older WeakAuras version. The tool reads !WA:2! and newer."
    if "failed to decode JSON to lua table" in text:
        return "JSON is missing the aura. Decode an export first, or open a JSON file from a decode."
    if "decode failed" in text or "failed to decode" in text or "failed to decompress" in text:
        return "The string could not be decoded. Check that the whole export was included."
    if "encode failed" in text or "failed to serialize" in text or "failed to compress" in text:
        return "JSON could not be turned into an import string."
    if "does not contain an aura" in text:
        return str(error)
    return text


def _reject_size(text: str) -> None:
    if len(text) > MAX_JSON:
        raise ValueError("That file is larger than 40 MB.")


def remember(text: str, label: str) -> str:
    _reject_size(text)
    now = time.monotonic()
    token = uuid.uuid4().hex
    with store_lock:
        expired = [key for key, item in store.items() if now - item.created > TTL_SECONDS]
        for key in expired:
            del store[key]
        while len(store) >= MAX_DOCS:
            oldest = min(store, key=lambda key: store[key].created)
            del store[oldest]
        store[token] = Stored(text, label, now)
    return token


def lookup(token: str) -> Stored:
    if not TOKEN_RE.fullmatch(token or ""):
        raise HTTPException(status_code=404, detail="That converted aura is no longer available.")
    with store_lock:
        item = store.get(token)
    if item is None or time.monotonic() - item.created > TTL_SECONDS:
        with store_lock:
            store.pop(token, None)
        raise HTTPException(
            status_code=404,
            detail="That converted aura expired. Decode or open the file again.",
        )
    return item


def resolve_text(job: Job) -> str:
    if isinstance(job.text, str) and job.text.strip():
        _reject_size(job.text)
        return job.text
    if isinstance(job.token, str) and job.token.strip():
        return lookup(job.token.strip()).text
    raise ValueError("Paste a WeakAuras string or open a JSON file.")


def payload(text: str, label: str, download_name: str, **extra) -> dict:
    token = remember(text, label)
    body = {
        "label": label,
        "size": len(text),
        "token": token,
        "download_name": download_name,
        "json_text": text if len(text) <= INLINE_LIMIT else None,
    }
    body.update(extra)
    return body


def is_import_string(text: str) -> bool:
    compact = "".join(text.split())
    return "!WA:" in compact and not text.lstrip().startswith(("{", "["))


def decode_text(text: str) -> tuple[str, str]:
    data = json.loads(run_lua("decode", extract_wa_string(text)))
    pretty = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    return pretty, aura_label(data)


def as_http(error: Exception) -> HTTPException:
    return HTTPException(status_code=400, detail=friendly_error(error))


@app.get("/api/health")
def health() -> dict:
    return {"ok": True}


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.post("/api/open")
def open_json(job: Job) -> dict:
    try:
        text = resolve_text(job)
        document, source = load_aura_document(text)
        name = aura_label(document)
        return payload(source, name, f"{safe_filename(name)}.json")
    except HTTPException:
        raise
    except (OSError, ValueError, json.JSONDecodeError, RuntimeError) as error:
        raise as_http(error) from error


@app.post("/api/decode")
def decode(job: Job) -> dict:
    try:
        text = resolve_text(job)
        pretty, name = decode_text(text)
        return payload(pretty, name, f"{safe_filename(name)}.json")
    except HTTPException:
        raise
    except (OSError, ValueError, json.JSONDecodeError, RuntimeError) as error:
        raise as_http(error) from error


@app.post("/api/forever")
def forever(job: Job) -> dict:
    try:
        text = resolve_text(job)
        if is_import_string(text):
            text, _name = decode_text(text)
        document, _source = load_aura_document(text)
        translated, report = translate_document(document)
        pretty = json.dumps(translated, indent=2, ensure_ascii=False) + "\n"
        imported = run_lua("encode", pretty)
        name = aura_label(translated)
        return payload(
            pretty,
            name,
            f"{safe_filename(name)}-forever.json",
            import_string=imported,
            report=format_report(name, report),
        )
    except HTTPException:
        raise
    except (OSError, ValueError, json.JSONDecodeError, RuntimeError) as error:
        raise as_http(error) from error
    except Exception as error:
        log.exception("forever conversion failed")
        raise HTTPException(status_code=500, detail="Something went wrong while converting that aura.") from error


@app.post("/api/encode")
def encode(job: Job) -> dict:
    try:
        text = resolve_text(job)
        document, source = load_aura_document(text)
        imported = run_lua("encode", source)
        name = aura_label(document)
        stored = source if source.strip() else text
        return payload(stored, name, f"{safe_filename(name)}.json", import_string=imported)
    except HTTPException:
        raise
    except (OSError, ValueError, json.JSONDecodeError, RuntimeError) as error:
        raise as_http(error) from error


@app.get("/api/files/{token}")
def download(token: str) -> Response:
    item = lookup(token)
    filename = f"{safe_filename(item.label)}.json"
    disposition = f"attachment; filename=\"{filename}\"; filename*=UTF-8''{quote(filename)}"
    return Response(
        content=item.text.encode("utf-8"),
        media_type="application/json; charset=utf-8",
        headers={"Content-Disposition": disposition, "Cache-Control": "no-store"},
    )


app.mount("/static", StaticFiles(directory=STATIC), name="static")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("server:app", host="127.0.0.1", port=int(os.environ.get("PORT", "8000")))
