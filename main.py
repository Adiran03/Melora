import ctypes
from hashlib import sha256
from typing import Literal
from ctypes import wintypes
import os
import logging
import re
import sqlite3
import sys
from urllib.error import HTTPError
from urllib.parse import urlsplit
import threading
import time
from pathlib import Path

import anyio
from starlette.background import BackgroundTask
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import database as db
import music_engine as engine

app = FastAPI(title="Melora")
logger = logging.getLogger(__name__)
STATIC_DIR = Path(__file__).parent / "static"
if getattr(sys, "frozen", False):
    app.state.revision = "installed-" + (STATIC_DIR.parent / "app_revision.txt").read_text(encoding="ascii").strip()
else:
    app.state.revision = sha256(b"".join(
        Path(module_file).read_bytes() for module_file in (__file__, db.__file__, engine.__file__)
    )).hexdigest()[:12]

_media_seq = 0
_media_action = ""
_media_lock = threading.Lock()
_last_hook_time = 0.0

def _push_media_command(action: str):
    global _media_seq, _media_action, _last_hook_time
    now = time.time()
    if now - _last_hook_time < 0.7:
        return
    _last_hook_time = now
    with _media_lock:
        _media_seq += 1
        _media_action = action

def _start_windows_media_hook():
    if os.name != "nt":
        return

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    WH_KEYBOARD_LL = 13
    WM_KEYDOWN = 0x0100
    WM_SYSKEYDOWN = 0x0104

    VK_MAP = {
        0xB0: "next",
        0xB1: "prev",
        0xB2: "stop",
        0xB3: "toggle",
    }

    class KBDLLHOOKSTRUCT(ctypes.Structure):
        _fields_ = [
            ("vkCode", wintypes.DWORD),
            ("scanCode", wintypes.DWORD),
            ("flags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
        ]

    HOOKPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)

    user32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC, wintypes.HINSTANCE, wintypes.DWORD]
    user32.SetWindowsHookExW.restype = wintypes.HHOOK
    user32.CallNextHookEx.argtypes = [wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
    user32.CallNextHookEx.restype = ctypes.c_ssize_t
    user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
    user32.GetMessageW.restype = wintypes.BOOL

    def low_level_handler(nCode, wParam, lParam):
        if nCode >= 0 and wParam in (WM_KEYDOWN, WM_SYSKEYDOWN):
            kb = ctypes.cast(lParam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
            cmd = VK_MAP.get(kb.vkCode)
            if cmd:
                _push_media_command(cmd)
        return user32.CallNextHookEx(None, nCode, wParam, lParam)

    hook_cb = HOOKPROC(low_level_handler)
    hook_id = user32.SetWindowsHookExW(WH_KEYBOARD_LL, hook_cb, None, 0)
    if not hook_id:
        return

    msg = wintypes.MSG()
    while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
        user32.TranslateMessage(ctypes.byref(msg))
        user32.DispatchMessageW(ctypes.byref(msg))

@app.middleware("http")
async def no_cache_middleware(request: Request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/static") or request.url.path == "/":
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response

class TrackModel(BaseModel):
    video_id: str
    title: str
    artist: str
    thumbnail: str = ""
    duration: str = ""

class PlaylistCreateModel(BaseModel):
    name: str

class WaveRequest(BaseModel):
    page: int = Field(default=0, ge=0)
    exclude: list[str] = Field(default_factory=list, max_length=20000)


class PrefetchModel(BaseModel):
    video_ids: list[str]

@app.on_event("startup")
def on_startup():
    db.init_db()
    threading.Thread(target=_start_windows_media_hook, daemon=True).start()

@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")

@app.get("/api/media-poll")
def api_media_poll():
    with _media_lock:
        return {"seq": _media_seq, "action": _media_action}

@app.get("/api/health")
def api_health():
    return {"app": "Melora", "ready": True, "revision": app.state.revision}


@app.get("/api/recommendations")
def api_recommendations():
    return engine.get_personalized_recommendations(db.get_taste_seeds(), db.get_liked_ids())


@app.post("/api/recommendations")
def api_wave_page(data: WaveRequest):
    return engine.get_personalized_recommendations(
        db.get_taste_seeds(), db.get_liked_ids(), page=data.page, exclude=set(data.exclude)
    )


@app.post("/api/history")
def api_record_history(track: TrackModel):
    db.record_play(track.model_dump())
    return {"ok": True}

@app.post("/api/dislikes")
def api_add_dislike(track: TrackModel):
    db.add_dislike(track.model_dump())
    return {"ok": True}

@app.post("/api/prefetch")
def api_prefetch(data: PrefetchModel):
    engine.prefetch_streams(data.video_ids)
    return {"ok": True}

@app.get("/api/search")
def api_search(q: str = "", kind: Literal["all", "tracks", "artists"] = "all"):
    if not q.strip():
        return {"tracks": [], "artists": []}
    try:
        liked_ids = db.get_liked_ids()
        res = engine.search_catalog(q.strip(), liked_ids, kind)
        tracks = res.get("tracks") or []
        return {"tracks": tracks, "artists": res.get("artists") or []}
    except Exception:
        logger.exception("Catalog search failed")
        raise HTTPException(status_code=502, detail="Поиск временно недоступен")

@app.get("/api/artist")
def api_artist_profile(browse_id: str = "", name: str = ""):
    liked_ids = db.get_liked_ids()
    prof = engine.get_artist_profile(browse_id.strip(), name.strip(), liked_ids)
    return prof

@app.get("/api/album/{browse_id:path}")
def api_album_tracks(browse_id: str, title: str = "", artist: str = ""):
    liked_ids = db.get_liked_ids()
    alb = engine.get_album_tracks(browse_id.strip(), liked_ids, title.strip(), artist.strip())
    return alb

@app.get("/api/likes")
def api_likes():
    tracks = db.get_likes()
    return {"tracks": tracks}

@app.post("/api/likes/toggle")
def api_toggle_like(track: TrackModel):
    is_liked = db.toggle_like(track.model_dump())
    return {"liked": is_liked}

@app.get("/api/playlists")
def api_get_playlists():
    return {"playlists": db.get_playlists()}

@app.post("/api/playlists")
def api_create_playlist(data: PlaylistCreateModel):
    if not data.name.strip():
        raise HTTPException(status_code=400, detail="Название не может быть пустым")
    return db.create_playlist(data.name)

@app.delete("/api/playlists/{playlist_id}")
def api_delete_playlist(playlist_id: int):
    db.delete_playlist(playlist_id)
    return {"ok": True}

@app.get("/api/playlists/{playlist_id}/tracks")
def api_playlist_tracks(playlist_id: int):
    liked_sigs = db.get_liked_sigs()
    tracks = db.get_playlist_tracks(playlist_id)
    for t in tracks:
        t["liked"] = db.normalize_sig(t["artist"], t["title"]) in liked_sigs
    return {"tracks": tracks}

@app.post("/api/playlists/{playlist_id}/tracks")
def api_add_playlist_track(playlist_id: int, track: TrackModel):
    if not db.add_track_to_playlist(playlist_id, track.model_dump()):
        raise HTTPException(status_code=404, detail="Плейлист не найден")
    return {"ok": True}

@app.delete("/api/playlists/{playlist_id}/tracks/{video_id:path}")
def api_remove_playlist_track(playlist_id: int, video_id: str):
    db.remove_track_from_playlist(playlist_id, video_id)
    return {"ok": True}

def _audio_content_type(response, url: str) -> str:
    content_type = (response.headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()
    if content_type.startswith("audio/") or content_type in {"video/mp4", "video/webm", "application/ogg"}:
        return content_type
    if content_type and content_type != "application/octet-stream":
        return ""
    suffix = Path(urlsplit(url).path).suffix.lower()
    return {
        ".m4a": "audio/mp4",
        ".mp4": "audio/mp4",
        ".aac": "audio/aac",
        ".webm": "audio/webm",
        ".ogg": "audio/ogg",
        ".opus": "audio/ogg",
        ".wav": "audio/wav",
        ".flac": "audio/flac",
    }.get(suffix, "audio/mpeg")


def _proxy_audio_stream(video_id: str, artist: str, title: str, request: Request):
    if not video_id or len(video_id) > 500:
        raise HTTPException(status_code=400, detail="Некорректный идентификатор трека")
    rng = request.headers.get("range")
    requested = re.fullmatch(r"bytes=(\d{0,18})-(\d{0,18})", rng or "", re.ASCII)
    if rng and (not requested or not any(requested.groups())):
        raise HTTPException(status_code=416, detail="Неподдерживаемый диапазон")
    extra = {"Range": rng} if rng else {}
    candidates = engine.get_candidate_stream_urls(video_id, artist, title)
    deadline = time.monotonic() + 5
    range_error = None

    # Если сохранённый адрес устарел, ищем новый даже при наличии записи в кеше.
    for refresh in (False, True):
        for cand_url in candidates:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            response = None
            try:
                response = engine.open_url_stream(cand_url, extra_headers=extra, timeout=min(2.5, remaining))
                status = response.status
                content_type = _audio_content_type(response, response.geturl())
                content_range = response.headers.get("Content-Range")
                if status == 206:
                    actual = re.fullmatch(r"bytes (\d+)-(\d+)/(?:\d+|\*)", content_range or "", re.ASCII)
                    if not actual or (requested and requested[1] and int(actual[1]) != int(requested[1])):
                        continue
                elif status != 200 or (rng and rng != "bytes=0-"):
                    continue
                if not content_type:
                    continue
                headers = {"Cache-Control": "no-store", "Content-Type": content_type}
                if status == 206 or response.headers.get("Accept-Ranges", "").lower() == "bytes":
                    headers["Accept-Ranges"] = "bytes"
                for name in ("Content-Length", "Content-Range"):
                    if value := response.headers.get(name):
                        headers[name] = value
                try:
                    engine.remember_stream(video_id, cand_url)
                except sqlite3.Error:
                    logger.warning("Could not cache audio source", exc_info=True)
                upstream, response = response, None

                async def stream_chunks():
                    try:
                        while chunk := await anyio.to_thread.run_sync(upstream.read1, 65536):
                            yield chunk
                    finally:
                        upstream.close()

                return StreamingResponse(
                    stream_chunks(), status_code=status, headers=headers,
                    background=BackgroundTask(upstream.close),
                )
            except HTTPError as error:
                if error.code == 416:
                    range_error = error.headers.get("Content-Range")
                error.close()
            except (OSError, ValueError):
                logger.debug("Audio source unavailable", exc_info=True)
            finally:
                if response is not None:
                    response.close()
        if refresh or not candidates or range_error or time.monotonic() >= deadline:
            break
        candidates = engine.get_candidate_stream_urls(video_id, artist, title, exclude=candidates)
        deadline = time.monotonic() + 3

    if range_error:
        raise HTTPException(status_code=416, detail="Диапазон вышел за пределы трека",
                            headers={"Content-Range": range_error})
    raise HTTPException(status_code=502, detail="Аудиоисточник недоступен")


@app.get("/api/stream")
def api_stream_query(request: Request, id: str = "", artist: str = "", title: str = ""):
    return _proxy_audio_stream(id, artist, title, request)

@app.get("/api/stream/{video_id:path}")
def api_stream_path(video_id: str, request: Request):
    return _proxy_audio_stream(video_id, "", "", request)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

if __name__ == "__main__":
    from desktop import main

    main(app)
