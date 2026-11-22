import re
import sqlite3
from pathlib import Path
from contextlib import contextmanager

DB_PATH = Path(__file__).parent / "music_data.db"

@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        with conn:
            yield conn
    finally:
        conn.close()

def normalize_sig(artist: str, title: str) -> str:
    a = re.sub(r"[^a-zа-яё0-9]+", "", (artist or "").split(",")[0].split("feat")[0].split("ft.")[0].lower())
    t = re.sub(r"[\(\[].*?[\)\]]", "", (title or "").lower())
    t = re.sub(r"[^a-zа-яё0-9]+", "", t)
    return f"{a}::{t}"

def normalize_artist(artist: str) -> str:
    return re.sub(r"[^a-zа-яё0-9]+", "", (artist or "").split(",")[0].split("&")[0].lower())

def init_db():
    with get_conn() as conn:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS likes (
                video_id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                artist TEXT NOT NULL,
                thumbnail TEXT,
                duration TEXT,
                liked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS dislikes (
                video_id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                artist TEXT NOT NULL,
                sig TEXT NOT NULL,
                artist_norm TEXT NOT NULL,
                disliked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS taste_history (
                video_id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                artist TEXT NOT NULL,
                thumbnail TEXT,
                duration TEXT,
                play_count INTEGER DEFAULT 1,
                last_played TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS stream_map (
                track_key TEXT PRIMARY KEY,
                stream_url TEXT NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS playlists (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS playlist_tracks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                playlist_id INTEGER NOT NULL,
                video_id TEXT NOT NULL,
                title TEXT NOT NULL,
                artist TEXT NOT NULL,
                thumbnail TEXT,
                duration TEXT,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(playlist_id, video_id),
                FOREIGN KEY (playlist_id) REFERENCES playlists(id) ON DELETE CASCADE
            );
        """)
        conn.execute("DELETE FROM stream_map WHERE updated_at < datetime('now', '-2 hours')")

def get_liked_ids() -> set:
    with get_conn() as conn:
        rows = conn.execute("SELECT video_id FROM likes").fetchall()
        return {row["video_id"] for row in rows}

def get_liked_sigs() -> set:
    with get_conn() as conn:
        rows = conn.execute("SELECT artist, title FROM likes").fetchall()
        return {normalize_sig(r["artist"], r["title"]) for r in rows}

def get_likes() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM likes ORDER BY liked_at DESC").fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["liked"] = True
            out.append(d)
        return out

def lookup_track_query_by_id(vid: str) -> str:
    if vid.startswith("q:"):
        return vid[2:].strip()
    with get_conn() as conn:
        for table in ("likes", "playlist_tracks", "taste_history"):
            row = conn.execute(f"SELECT artist, title FROM {table} WHERE video_id = ? LIMIT 1", (vid,)).fetchone()
            if row and row["artist"] and row["title"]:
                return f"{row['artist']} - {row['title']}"
    return vid

def get_dislike_filters() -> dict:
    with get_conn() as conn:
        rows = conn.execute("SELECT video_id, sig, artist_norm FROM dislikes").fetchall()
        return {
            "ids": {r["video_id"] for r in rows},
            "sigs": {r["sig"] for r in rows if r["sig"]},
            "artists": {r["artist_norm"] for r in rows if r["artist_norm"]}
        }

def add_dislike(track: dict):
    vid = track.get("video_id", "")
    title = track.get("title", "")
    artist = track.get("artist", "")
    if not vid:
        return
    sig = normalize_sig(artist, title)
    art_norm = normalize_artist(artist)
    with get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO dislikes (video_id, title, artist, sig, artist_norm) VALUES (?, ?, ?, ?, ?)",
            (vid, title, artist, sig, art_norm)
        )
        liking_rows = conn.execute("SELECT video_id, artist, title FROM likes").fetchall()
        conn.executemany(
            "DELETE FROM likes WHERE video_id = ?",
            [(r["video_id"],) for r in liking_rows
             if r["video_id"] == vid or normalize_sig(r["artist"], r["title"]) == sig],
        )
        conn.execute("DELETE FROM taste_history WHERE video_id = ? OR artist = ?", (vid, artist))

def get_cached_stream_url(track_key: str) -> str:
    with get_conn() as conn:
        row = conn.execute("SELECT stream_url FROM stream_map WHERE track_key = ? AND updated_at >= datetime('now', '-2 hours')", (track_key,)).fetchone()
        if not row:
            return ""
        url = row["stream_url"]
        if "apple.com" in url or "mzstatic.com" in url:
            return ""
        return url

def save_cached_stream_url(track_key: str, stream_url: str):
    if not track_key or not stream_url:
        return
    if "apple.com" in stream_url or "mzstatic.com" in stream_url:
        return
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO stream_map (track_key, stream_url) VALUES (?, ?)
               ON CONFLICT(track_key) DO UPDATE SET stream_url = excluded.stream_url, updated_at = CURRENT_TIMESTAMP
               WHERE stream_map.stream_url != excluded.stream_url OR stream_map.updated_at < datetime('now', '-1 hour')""",
            (track_key, stream_url)
        )

def record_play(track: dict):
    vid = track.get("video_id")
    if not vid:
        return
    with get_conn() as conn:
        is_disliked = conn.execute("SELECT 1 FROM dislikes WHERE video_id = ?", (vid,)).fetchone()
        if is_disliked:
            return
        conn.execute(
            """INSERT INTO taste_history (video_id, title, artist, thumbnail, duration, play_count, last_played)
               VALUES (?, ?, ?, ?, ?, 1, CURRENT_TIMESTAMP)
               ON CONFLICT(video_id) DO UPDATE SET
                   play_count = play_count + 1,
                   last_played = CURRENT_TIMESTAMP""",
            (vid, track.get("title", ""), track.get("artist", ""), track.get("thumbnail", ""), track.get("duration", ""))
        )

def get_taste_seeds(limit: int = 120) -> list[dict]:
    dis = get_dislike_filters()
    likes = get_likes()[:limit]
    with get_conn() as conn:
        history = [dict(row) for row in conn.execute(
            """SELECT video_id, title, artist, play_count FROM taste_history
               ORDER BY last_played DESC LIMIT 24"""
        )]
    seeds = []
    seen = set()
    for track in (*likes, *history):
        signature = normalize_sig(track["artist"], track["title"])
        if track["video_id"] in dis["ids"] or signature in dis["sigs"] or signature in seen:
            continue
        seen.add(signature)
        seeds.append(track)
    return seeds


def toggle_like(track: dict) -> bool:
    vid = track["video_id"]
    sig = normalize_sig(track.get("artist", ""), track.get("title", ""))
    with get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        rows = conn.execute("SELECT video_id, artist, title FROM likes").fetchall()
        matched_vid = None
        for r in rows:
            if r["video_id"] == vid or normalize_sig(r["artist"], r["title"]) == sig:
                matched_vid = r["video_id"]
                break
        if matched_vid:
            conn.execute("DELETE FROM likes WHERE video_id = ?", (matched_vid,))
            return False
        else:
            conn.execute("DELETE FROM dislikes WHERE video_id = ? OR sig = ?", (vid, sig))
            conn.execute(
                "INSERT OR REPLACE INTO likes (video_id, title, artist, thumbnail, duration) VALUES (?, ?, ?, ?, ?)",
                (vid, track["title"], track["artist"], track.get("thumbnail", ""), track.get("duration", ""))
            )
            return True

def get_playlists() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT p.id, p.name, COUNT(pt.id) as track_count
            FROM playlists p
            LEFT JOIN playlist_tracks pt ON p.id = pt.playlist_id
            GROUP BY p.id
            ORDER BY p.created_at DESC
        """).fetchall()
        return [dict(r) for r in rows]

def create_playlist(name: str) -> dict:
    with get_conn() as conn:
        cur = conn.execute("INSERT INTO playlists (name) VALUES (?)", (name.strip(),))
        return {"id": cur.lastrowid, "name": name.strip(), "track_count": 0}

def delete_playlist(playlist_id: int):
    with get_conn() as conn:
        conn.execute("DELETE FROM playlist_tracks WHERE playlist_id = ?", (playlist_id,))
        conn.execute("DELETE FROM playlists WHERE id = ?", (playlist_id,))

def get_playlist_tracks(playlist_id: int) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM playlist_tracks WHERE playlist_id = ? ORDER BY added_at DESC",
            (playlist_id,)
        ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            out.append(d)
        return out

def add_track_to_playlist(playlist_id: int, track: dict) -> bool:
    with get_conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        if not conn.execute("SELECT 1 FROM playlists WHERE id = ?", (playlist_id,)).fetchone():
            return False
        conn.execute(
            """INSERT OR IGNORE INTO playlist_tracks
               (playlist_id, video_id, title, artist, thumbnail, duration)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                playlist_id,
                track["video_id"],
                track["title"],
                track["artist"],
                track.get("thumbnail", ""),
                track.get("duration", "")
            )
        )
        return True

def remove_track_from_playlist(playlist_id: int, video_id: str):
    with get_conn() as conn:
        conn.execute(
            "DELETE FROM playlist_tracks WHERE playlist_id = ? AND video_id = ?",
            (playlist_id, video_id)
        )