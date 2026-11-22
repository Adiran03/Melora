const SVG = {
    play: '<svg class="ico ico-fill" viewBox="0 0 24 24"><path d="M8 5v14l11-7z"/></svg>',
    pause: '<svg class="ico ico-fill" viewBox="0 0 24 24"><rect x="6" y="5" width="4" height="14" rx="1"/><rect x="14" y="5" width="4" height="14" rx="1"/></svg>',
    loader: '<svg class="ico" viewBox="0 0 24 24"><path d="M12 3v3M12 18v3M4.9 4.9l2.1 2.1M17 17l2.1 2.1M3 12h3M18 12h3M4.9 19.1 7 17M17 7l2.1-2.1"/></svg>',
    heart: '<svg class="ico" viewBox="0 0 24 24"><path d="M12 20.5s-7-4.4-9-8.8C1.4 8.2 3.8 4.5 7.5 4.5c2 0 3.6 1 4.5 2.4.9-1.4 2.5-2.4 4.5-2.4 3.7 0 6.1 3.7 4.5 7.2-2 4.4-9 8.8-9 8.8Z"/></svg>',
    heartFill: '<svg class="ico ico-fill" viewBox="0 0 24 24"><path d="M12 20.5s-7-4.4-9-8.8C1.4 8.2 3.8 4.5 7.5 4.5c2 0 3.6 1 4.5 2.4.9-1.4 2.5-2.4 4.5-2.4 3.7 0 6.1 3.7 4.5 7.2-2 4.4-9 8.8-9 8.8Z"/></svg>',
    dislike: '<svg class="ico" viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="m5.7 5.7 12.6 12.6"/></svg>',
    plus: '<svg class="ico" viewBox="0 0 24 24"><path d="M12 5v14M5 12h14"/></svg>',
    volOn: '<svg class="ico" viewBox="0 0 24 24"><path d="M11 5 6 9H3v6h3l5 4V5ZM15.5 8.5a5 5 0 0 1 0 7M18.5 6a8.5 8.5 0 0 1 0 12"/></svg>',
    volOff: '<svg class="ico" viewBox="0 0 24 24"><path d="M11 5 6 9H3v6h3l5 4V5ZM22 9l-6 6M16 9l6 6"/></svg>'
};

const audio = document.getElementById("audio-player");
const placeholderCover = "/static/cover-placeholder.svg";
const MAX_RECOVERY_ATTEMPTS = 2;

let queue = [];
let currentIndex = -1;
let currentTrack = null;
let queueOrigin = "wave";
let currentMode = "wave";
let activePlaylistId = null;
let trackForPlaylist = null;
let volumeLevel = 0.8;
let unmutedVolume = volumeLevel;
let isDraggingSeek = false;
let playRequestId = 0;
let recoveryAttempts = 0;
let playbackTimer;
let playbackWanted = false;
let buffering = false;
let resumePosition = 0;
let playbackRecorded = false;
let mediaArtwork;
let waveRequestId = 0;
let waveRequest;
let wavePage = 0;
let waveExhausted = false;
let waveAdvance;
let waveBasis = "";
let queueVisible = false;
const heardInWave = new Set();
let searchKind = "tracks";
let viewRequestId = 0;

let hudTimeout = null;
let searchTimer = null;
let searchAbortController = null;
let lastMediaHotkeyAt = 0;
let lastMediaAction = null;
let lastPolledSeq = -1;
let lastSearchQuery = "";
let viewHistory = [];

function on(id, event, handler) {
    const el = document.getElementById(id);
    if (el) el.addEventListener(event, handler);
}

const themeButton = document.getElementById("theme-btn");

function setTheme(theme) {
    document.documentElement.dataset.theme = theme;
    const label = theme === "dark" ? "Включить светлую тему" : "Включить тёмную тему";
    themeButton.setAttribute("aria-label", label);
    themeButton.title = label;
}

setTheme(document.documentElement.dataset.theme);
themeButton.addEventListener("click", () => {
    const theme = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
    setTheme(theme);
    try { localStorage.setItem("muzon-theme", theme); } catch {}
});

const playerCovers = ["cover-img", "hero-cover-img"].map(id => document.getElementById(id));
for (const cover of playerCovers) {
    cover.addEventListener("error", () => {
        if (cover.getAttribute("src") !== placeholderCover) cover.src = placeholderCover;
    });
}

function setPlayerCover(artwork) {
    for (const cover of playerCovers) {
        if (cover.dataset.artwork === artwork) continue;
        cover.dataset.artwork = artwork;
        cover.src = artwork;
    }
}

function esc(str) {
    return String(str || "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

function fmtTime(sec) {
    if (!Number.isFinite(sec) || sec <= 0) return "0:00";
    const m = Math.floor(sec / 60);
    const s = Math.floor(sec % 60).toString().padStart(2, "0");
    return `${m}:${s}`;
}

function showHud(text) {
    const hud = document.getElementById("hud-toast");
    if (!hud) return;
    hud.textContent = text;
    hud.classList.remove("hidden");
    clearTimeout(hudTimeout);
    hudTimeout = setTimeout(() => hud.classList.add("hidden"), 1500);
}

function syncSearchExitButtons() {
    const inp = document.getElementById("search-input");
    const q = inp ? inp.value.trim() : "";
    const isSearching = currentMode === "search" || q.length > 0;
    const exitBtn = document.getElementById("exit-search-btn");
    const drawerExitBtn = document.getElementById("drawer-exit-search-btn");
    if (exitBtn) exitBtn.classList.toggle("hidden", !isSearching);
    if (drawerExitBtn) drawerExitBtn.classList.toggle("hidden", !isSearching);
}

function buildStreamUrl(track) {
    if (!track) return "";
    return `/api/stream?id=${encodeURIComponent(track.video_id || "")}&artist=${encodeURIComponent(track.artist || "")}&title=${encodeURIComponent(track.title || "")}`;
}

function showCustomDialog({ title, placeholder = "", text = "", isPrompt = false }) {
    return new Promise((resolve) => {
        const modal = document.getElementById("custom-dialog");
        const titleEl = document.getElementById("dialog-title");
        const inputEl = document.getElementById("dialog-input");
        const textEl = document.getElementById("dialog-text");
        const okBtn = document.getElementById("dialog-ok-btn");
        const cancelBtn = document.getElementById("dialog-cancel-btn");

        titleEl.textContent = title;
        if (isPrompt) {
            inputEl.value = "";
            inputEl.placeholder = placeholder;
            inputEl.classList.remove("hidden");
            textEl.classList.add("hidden");
        } else {
            textEl.textContent = text;
            textEl.classList.remove("hidden");
            inputEl.classList.add("hidden");
        }

        modal.classList.remove("hidden");
        const previousFocus = document.activeElement;
        (isPrompt ? inputEl : cancelBtn).focus();
        const onEscape = event => {
            if (event.key !== "Escape") return;
            event.stopPropagation();
            cleanup(null);
        };
        modal.addEventListener("keydown", onEscape);

        const cleanup = (val) => {
            modal.classList.add("hidden");
            okBtn.onclick = null;
            cancelBtn.onclick = null;
            inputEl.onkeydown = null;
            modal.removeEventListener("keydown", onEscape);
            previousFocus?.focus();
            resolve(val);
        };

        okBtn.onclick = () => cleanup(isPrompt ? inputEl.value.trim() : true);
        cancelBtn.onclick = () => cleanup(null);
        inputEl.onkeydown = (e) => {
            if (e.key === "Enter") cleanup(inputEl.value.trim());
        };
    });
}

function prefetchQueueWindow(idx) {
    if (queue.length < 2) return;
    const ids = [];
    for (let offset = 1; offset <= Math.min(2, queue.length - 1); offset++) {
        const next = idx + offset;
        const t = queue[queueOrigin === "wave" ? next : next % queue.length];
        if (t && t.video_id) ids.push(t.video_id);
    }
    if (ids.length) {
        fetch("/api/prefetch", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ video_ids: ids })
        }).catch(() => {});
    }
}

const seekBar = document.getElementById("seek-bar");

if (seekBar) {
    seekBar.disabled = true;
    seekBar.addEventListener("input", () => {
        if (!Number.isFinite(audio.duration)) return;
        isDraggingSeek = true;
        const preview = Number(seekBar.value) * audio.duration / 100;
        document.getElementById("cur-time").textContent = fmtTime(preview);
    });
    seekBar.addEventListener("change", () => {
        isDraggingSeek = false;
        if (Number.isFinite(audio.duration)) {
            audio.currentTime = Number(seekBar.value) * audio.duration / 100;
        }
    });
    seekBar.addEventListener("pointercancel", () => {
        isDraggingSeek = false;
        updateProgress();
    });
}

function updateProgress() {
    if (isDraggingSeek || !Number.isFinite(audio.duration) || audio.duration <= 0) return;
    const canSeek = audio.seekable.length > 0;
    if (seekBar) {
        seekBar.disabled = !canSeek;
        seekBar.value = audio.currentTime * 100 / audio.duration;
    }
    document.getElementById("cur-time").textContent = fmtTime(audio.currentTime);
    document.getElementById("tot-time").textContent = fmtTime(audio.duration);
}

function cancelPlaybackTimer() {
    clearTimeout(playbackTimer);
    playbackTimer = undefined;
}

function setBuffering(value) {
    if (buffering === value) return;
    buffering = value;
    updateAllPlayerUI();
}

function recoverPlayback() {
    cancelPlaybackTimer();
    if (!playbackWanted || !currentTrack) return;
    if (recoveryAttempts >= MAX_RECOVERY_ATTEMPTS) {
        playbackWanted = false;
        setBuffering(false);
        audio.pause();
        updateAllPlayerUI();
        showHud("Не удалось продолжить. Нажми «Воспроизвести» или выбери другой трек");
        return;
    }
    recoveryAttempts++;
    const position = audio.currentTime || resumePosition;
    const request = playRequestId;
    setBuffering(true);
    playbackTimer = setTimeout(() => {
        if (request === playRequestId && playbackWanted) startAudio(position);
    }, 300);
}

function watchBuffering() {
    if (!playbackWanted) return;
    setBuffering(true);
    if (playbackTimer !== undefined) return;
    const request = playRequestId;
    playbackTimer = setTimeout(() => {
        if (request === playRequestId) recoverPlayback();
    }, 12000);
}

function playAudio() {
    const request = playRequestId;
    playbackWanted = true;
    watchBuffering();
    audio.play().catch(error => {
        if (request !== playRequestId || !playbackWanted || error.name === "AbortError") return;
        if (error.name === "NotAllowedError") {
            pauseAudio();
            showHud("Нажми «Воспроизвести», чтобы запустить трек");
        } else if (!audio.error) {
            recoverPlayback();
        }
    });
}

function startAudio(position = 0) {
    cancelPlaybackTimer();
    resumePosition = position;
    const url = buildStreamUrl(currentTrack);
    audio.src = recoveryAttempts ? `${url}&retry=${recoveryAttempts}` : url;
    playAudio();
}

function pauseAudio() {
    playbackWanted = false;
    cancelPlaybackTimer();
    audio.pause();
    setBuffering(false);
    updateAllPlayerUI();
}

audio.addEventListener("timeupdate", updateProgress);
audio.addEventListener("durationchange", updateProgress);
audio.addEventListener("progress", updateProgress);
audio.addEventListener("loadedmetadata", () => {
    if (resumePosition && Number.isFinite(audio.duration) && resumePosition < audio.duration) {
        audio.currentTime = resumePosition;
    }
    resumePosition = 0;
    updateProgress();
});
audio.addEventListener("waiting", watchBuffering);
audio.addEventListener("seeking", watchBuffering);
audio.addEventListener("ended", () => {
    cancelPlaybackTimer();
    if (playbackWanted) nextTrack();
});
audio.addEventListener("pause", updateAllPlayerUI);
audio.addEventListener("error", () => {
    if (audio.error?.code !== 1) recoverPlayback();
});
audio.addEventListener("playing", () => {
    if (!playbackWanted) {
        audio.pause();
        return;
    }
    cancelPlaybackTimer();
    setBuffering(false);
    updateAllPlayerUI();
    if (!playbackRecorded && queueOrigin !== "wave" && currentTrack) {
        playbackRecorded = true;
        fetch("/api/history", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(currentTrack)
        }).catch(() => {});
    }
});

function updateAllPlayerUI() {
    const centerPlayBtn = document.getElementById("play-pause-btn");
    const dockPlayBtn = document.getElementById("dock-play-btn");
    const likeBtn = document.getElementById("like-btn");

    if (!currentTrack) {
        for (const button of [centerPlayBtn, dockPlayBtn]) {
            button.innerHTML = SVG.play;
            button.classList.remove("buffering");
            button.setAttribute("aria-busy", "false");
            button.setAttribute("aria-label", "Воспроизвести");
        }
        setPlayerCover(placeholderCover);
        likeBtn.classList.remove("liked");
        likeBtn.innerHTML = `${SVG.heart}<span>Нравится</span>`;
        document.getElementById("center-title").textContent = "Выбери трек";
        document.getElementById("center-artist").textContent = "Melora";
        document.getElementById("dock-title").textContent = "Melora";
        document.getElementById("dock-artist").textContent = "Выбери трек";
        document.getElementById("cur-time").textContent = "0:00";
        document.getElementById("tot-time").textContent = "0:00";
        seekBar.disabled = true;
        seekBar.value = 0;
        if ("mediaSession" in navigator) {
            navigator.mediaSession.metadata = null;
            navigator.mediaSession.playbackState = "none";
        }
        return;
    }

    const isPlaying = !audio.paused && !!audio.src;
    const iconHtml = buffering ? SVG.loader : isPlaying ? SVG.pause : SVG.play;
    for (const button of [centerPlayBtn, dockPlayBtn]) {
        button.classList.toggle("buffering", buffering);
        button.setAttribute("aria-label", playbackWanted ? "Пауза" : "Воспроизвести");
        button.setAttribute("aria-busy", String(buffering));
    }
    if (centerPlayBtn) centerPlayBtn.innerHTML = iconHtml;
    if (dockPlayBtn) dockPlayBtn.innerHTML = iconHtml;

    document.getElementById("center-title").textContent = currentTrack.title;
    document.getElementById("center-artist").textContent = currentTrack.artist;

    document.getElementById("dock-title").textContent = currentTrack.title;
    document.getElementById("dock-artist").textContent = currentTrack.artist;
    const artwork = currentTrack.thumbnail || placeholderCover;
    setPlayerCover(artwork);

    if (likeBtn) {
        likeBtn.classList.toggle("liked", !!currentTrack.liked);
        likeBtn.innerHTML = `${currentTrack.liked ? SVG.heartFill : SVG.heart}<span>${currentTrack.liked ? "В любимом" : "Нравится"}</span>`;
    }

    if ("mediaSession" in navigator) {
        const session = navigator.mediaSession;
        if (session.metadata?.title !== currentTrack.title ||
            session.metadata?.artist !== currentTrack.artist ||
            mediaArtwork !== artwork) {
            mediaArtwork = artwork;
            try {
                session.metadata = new MediaMetadata({
                    title: currentTrack.title,
                    artist: currentTrack.artist,
                    artwork: [{ src: artwork }]
                });
            } catch {
                session.metadata = null;
            }
        }
        session.playbackState = isPlaying ? "playing" : "paused";
    }
}

function playAt(idx) {
    if (idx < 0 || idx >= queue.length) return;
    playRequestId++;
    recoveryAttempts = 0;
    playbackRecorded = false;
    isDraggingSeek = false;
    currentIndex = idx;
    currentTrack = queue[idx];
    if (queueOrigin === "wave") {
        heardInWave.add(waveKey(currentTrack));
        if (queue.length - idx <= 5) extendWave().catch(() => {});
    }
    updateWaveBasis();
    if (seekBar) {
        seekBar.value = 0;
        seekBar.disabled = true;
    }
    document.getElementById("cur-time").textContent = "0:00";
    document.getElementById("tot-time").textContent = currentTrack.duration || "0:00";
    audio.volume = volumeLevel;
    startAudio();
    updateAllPlayerUI();
    prefetchQueueWindow(idx);
    highlightActiveRow();
    syncSearchExitButtons();
}

async function togglePlay() {
    if (playbackWanted) {
        pauseAudio();
    } else if (!queue.length) {
        await loadWave(true);
    } else if (queueOrigin === "wave" && (audio.ended || !currentTrack)) {
        await nextTrack();
    } else if (!audio.getAttribute("src") || audio.error || audio.ended || recoveryAttempts >= MAX_RECOVERY_ATTEMPTS) {
        playAt(Math.max(currentIndex, 0));
    } else {
        recoveryAttempts = 0;
        playAudio();
    }
}

async function nextTrack() {
    if (!queue.length) {
        await loadWave(true);
        return;
    }
    if (queueOrigin !== "wave") {
        playAt((currentIndex + 1) % queue.length);
        return;
    }
    const next = currentIndex + 1;
    if (next < queue.length) {
        playAt(next);
        return;
    }
    if (waveAdvance) return;
    const playbackId = playRequestId;
    const waveId = waveRequestId;
    const advance = extendWave();
    waveAdvance = advance;
    if (!waveExhausted) showHud("Загружаем новые треки…");
    try {
        await advance;
        if (queueOrigin !== "wave" || playbackId !== playRequestId || waveId !== waveRequestId) return;
        if (next < queue.length) {
            playAt(next);
        } else {
            if (audio.ended) pauseAudio();
            showHud("Новых треков пока нет. Обнови волну позже");
        }
    } catch {
        if (waveId === waveRequestId && playbackId === playRequestId) showHud("Не удалось продолжить волну");
    } finally {
        if (waveAdvance === advance) waveAdvance = null;
    }
}

async function prevTrack() {
    if (!queue.length) {
        await loadWave(true);
        return;
    }
    if (audio.currentTime > 4) {
        audio.currentTime = 0;
        return;
    }
    if (queueOrigin === "wave") {
        if (currentIndex > 0) playAt(currentIndex - 1);
        return;
    }
    playAt(currentIndex < 0 ? 0 : (currentIndex - 1 + queue.length) % queue.length);
}

on("play-pause-btn", "click", togglePlay);
on("next-btn", "click", nextTrack);
on("prev-btn", "click", prevTrack);

on("dock-play-btn", "click", togglePlay);
on("dock-next-btn", "click", nextTrack);
on("dock-prev-btn", "click", prevTrack);

function applyVolume(val) {
    volumeLevel = Math.max(0, Math.min(1, val));
    if (volumeLevel > 0) unmutedVolume = volumeLevel;
    audio.volume = volumeLevel;
    const vb = document.getElementById("volume-bar");
    if (vb) vb.value = Math.round(volumeLevel * 100);
    const mb = document.getElementById("mute-btn");
    if (mb) mb.innerHTML = volumeLevel === 0 ? SVG.volOff : SVG.volOn;
}

on("volume-bar", "input", (e) => applyVolume(e.target.value / 100));
on("mute-btn", "click", () => {
    applyVolume(volumeLevel > 0 ? 0 : unmutedVolume);
    showHud(volumeLevel === 0 ? "Звук выключен" : `Громкость ${Math.round(volumeLevel * 100)}%`);
});

function waveKey(track) {
    return track.wave_key || track.video_id;
}

function updateWaveBasis() {
    const basis = document.getElementById("wave-basis");
    basis.textContent = waveBasis && queueOrigin === "wave" ? `В основе волны · ${waveBasis}` : "";
    basis.classList.toggle("hidden", !basis.textContent);
}

function invalidateWave() {
    waveRequestId++;
    waveRequest = null;
    waveAdvance = null;
    wavePage = 0;
    waveExhausted = false;
}

async function fetchWaveTracks(existing, stillCurrent) {
    const excluded = new Set([...heardInWave, ...existing.map(waveKey)]);
    for (let attempt = 0; attempt < 3; attempt++) {
        const data = await requestJson("/api/recommendations", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ page: wavePage++, exclude: [...excluded] })
        });
        if (!stillCurrent()) return null;
        const tracks = [];
        for (const track of data.tracks || []) {
            const key = waveKey(track);
            if (excluded.has(key)) continue;
            excluded.add(key);
            tracks.push(track);
        }
        if (tracks.length) return { tracks, basis: data.basis };
    }
    return { tracks: [], basis: "" };
}

function refreshQueueView() {
    if (queueVisible) {
        renderTrackRowsInto(document.getElementById("tracks-container"), queue, false, queueOrigin);
    }
}

function extendWave() {
    if (queueOrigin !== "wave" || waveExhausted) return Promise.resolve();
    if (waveRequest) return waveRequest;
    const waveId = waveRequestId;
    const stillCurrent = () => waveId === waveRequestId && queueOrigin === "wave";
    const request = fetchWaveTracks(queue, stillCurrent).then(data => {
        if (!data || !stillCurrent()) return;
        if (!data.tracks.length) {
            waveExhausted = true;
            return;
        }
        queue = [...queue, ...data.tracks];
        waveBasis = data.basis;
        updateWaveBasis();
        refreshQueueView();
    }).finally(() => {
        if (waveRequest === request) waveRequest = null;
    });
    waveRequest = request;
    return request;
}

async function loadWave(autoPlay = false, refresh = false) {
    cancelSearch();
    currentMode = "wave";
    activePlaylistId = null;
    setActiveNav("nav-wave");
    syncSearchExitButtons();

    if (!refresh && queueOrigin === "wave" && queue.length) return;
    if (!refresh && waveRequest) {
        try { await waveRequest; } catch { return; }
        if (autoPlay && currentMode === "wave" && queueOrigin === "wave" && queue.length && !playbackWanted) {
            playAt(Math.max(currentIndex, 0));
        }
        return;
    }
    invalidateWave();
    const waveId = waveRequestId;
    const playbackId = playRequestId;
    const stillCurrent = () => waveId === waveRequestId && playbackId === playRequestId && currentMode === "wave";
    if (autoPlay) showHud("Загружаем волну…");

    const request = fetchWaveTracks([], stillCurrent).then(data => {
        if (!data || !stillCurrent()) return;
        const newTracks = data.tracks.filter(track => track.video_id !== currentTrack?.video_id);
        if (!newTracks.length) {
            if (!currentTrack) document.getElementById("center-title").textContent = "Найди трек в поиске";
            if (autoPlay) showHud("Новых рекомендаций пока нет");
            return;
        }
        waveBasis = data.basis;
        queueOrigin = "wave";
        queue = newTracks;
        if (autoPlay) {
            playAt(0);
        } else if (currentTrack) {
            queue = [currentTrack, ...newTracks];
            currentIndex = 0;
        } else {
            currentIndex = 0;
            currentTrack = queue[0];
            updateAllPlayerUI();
        }
        updateWaveBasis();
        prefetchQueueWindow(currentIndex);
        refreshQueueView();
    }).catch(() => {
        if (!stillCurrent()) return;
        if (!currentTrack) document.getElementById("center-title").textContent = "Не удалось загрузить волну";
        if (autoPlay) showHud("Не удалось загрузить волну");
    }).finally(() => {
        if (waveRequest === request) waveRequest = null;
    });
    waveRequest = request;
    await request;
}

function refreshWaveAfterLike() {
    if (queueOrigin !== "wave") {
        invalidateWave();
        return;
    }
    const kept = queue.slice(0, currentIndex + 1);
    queue = kept;
    invalidateWave();
    refreshQueueView();
    extendWave().catch(() => {});
}

async function dislikeTrack(track) {
    if (!track) return false;
    try {
        await requestJson("/api/dislikes", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(track)
        });
    } catch {
        showHud("Не удалось сохранить дизлайк");
        return false;
    }

    const bannedArtist = (track.artist || "").split(",")[0].trim().toLowerCase();
    const keep = item => item.video_id !== track.video_id &&
        (queueOrigin !== "wave" || !bannedArtist || item.artist.split(",")[0].trim().toLowerCase() !== bannedArtist);
    const nextIndex = queue.slice(0, Math.max(0, currentIndex)).filter(keep).length;
    queue = queue.filter(keep);
    if (queueOrigin === "wave") invalidateWave();
    if (currentTrack && !keep(currentTrack)) {
        if (queue.length && (queueOrigin !== "wave" || nextIndex < queue.length)) {
            playAt(nextIndex % queue.length);
        } else {
            pauseAudio();
            audio.removeAttribute("src");
            audio.load();
            currentIndex = -1;
            currentTrack = null;
            updateAllPlayerUI();
            if (queueOrigin === "wave" && queue.length) {
                currentIndex = queue.length - 1;
                await nextTrack();
            } else {
                await loadWave(true);
            }
        }
    } else {
        currentIndex = queue.findIndex(item => item.video_id === currentTrack?.video_id);
    }
    refreshQueueView();
    showHud("Дизлайк сохранён");
    return true;
}

on("dislike-btn", "click", () => {
    if (currentTrack) dislikeTrack(currentTrack);
});

function openDrawer(title, { showPlChips = false, isArtistProfile = false } = {}) {
    document.getElementById("drawer-title").textContent = title;
    const request = ++viewRequestId;
    queueVisible = false;
    document.getElementById("search-modes").classList.add("hidden");
    const panel = document.getElementById("drawer-panel");
    panel.classList.remove("hidden");
    document.querySelector(".center-stage").inert = true;
    panel.scrollTop = 0;

    document.getElementById("standard-view").classList.toggle("hidden", isArtistProfile);
    document.getElementById("artist-profile-view").classList.toggle("hidden", !isArtistProfile);

    document.getElementById("playlists-chips").classList.toggle("hidden", !showPlChips);
    document.getElementById("drawer-create-pl-btn").classList.toggle("hidden", !showPlChips);
    document.getElementById("drawer-delete-pl-btn").classList.add("hidden");
    document.getElementById("artists-block").classList.add("hidden");
    document.getElementById("drawer-back-btn").classList.toggle("hidden", viewHistory.length === 0);
    document.getElementById("top-back-player-btn").classList.remove("hidden");
    syncSearchExitButtons();
    return request;
}

function minimizeDrawerToPlayer() {
    queueVisible = false;
    cancelSearch();
    viewRequestId++;
    document.getElementById("drawer-panel").classList.add("hidden");
    document.querySelector(".center-stage").inert = false;
    document.getElementById("top-back-player-btn").classList.add("hidden");
    syncSearchExitButtons();
}

function exitSearchAndReturnToWave() {
    clearTimeout(searchTimer);
    cancelSearch();
    if (searchInput) searchInput.value = "";
    lastSearchQuery = "";
    viewHistory = [];
    if (clearSearchBtn) clearSearchBtn.classList.add("hidden");
    currentMode = "wave";
    syncSearchExitButtons();
    minimizeDrawerToPlayer();

    loadWave();
}

on("close-drawer-btn", "click", minimizeDrawerToPlayer);
on("top-back-player-btn", "click", minimizeDrawerToPlayer);
on("exit-search-btn", "click", exitSearchAndReturnToWave);
on("drawer-exit-search-btn", "click", exitSearchAndReturnToWave);

on("drawer-back-btn", "click", () => {
    const prev = viewHistory.pop();
    if (!prev) {
        minimizeDrawerToPlayer();
        return;
    }
    if (prev.type === "search") {
        searchKind = prev.kind;
        executeSearch(prev.query, false);
    } else if (prev.type === "artist") {
        openArtistCard(prev.browseId, prev.name, false);
    }
});

function renderTrackRowsInto(container, tracks, isPlaylist = false, originTag = "search") {
    if (!tracks.length) {
        container.innerHTML = "<p class='panel-message'>Ничего не найдено...</p>";
        return;
    }

    container.innerHTML = tracks.map((t, idx) => `
        <div class="track-item ${currentTrack?.video_id === t.video_id ? 'playing' : ''}" data-idx="${idx}" data-vid="${esc(t.video_id)}">
            <div class="track-item-left">
                <img loading="lazy" decoding="async" src="${esc(t.thumbnail || placeholderCover)}" alt="">
                <div class="track-item-meta">
                    <div class="track-item-title">${esc(t.title)}</div>
                    <div class="track-item-artist" data-artist="${esc(t.artist)}" data-aid="${esc(t.artist_id || '')}">${esc(t.artist)}</div>
                </div>
            </div>
            <div class="track-item-right" onclick="event.stopPropagation()">
                <span class="track-dur">${esc(t.duration || '')}</span>
                <button class="row-btn ${t.liked ? 'liked' : ''}" data-like-idx="${idx}" title="Нравится">
                    ${t.liked ? SVG.heartFill : SVG.heart}
                </button>
                <button class="row-btn dislike-row-btn" data-dislike-idx="${idx}" title="Дизлайк — скрыть трек">
                    ${SVG.dislike}
                </button>
                <button class="row-btn" data-add-idx="${idx}" title="В плейлист">
                    ${SVG.plus}
                </button>
                ${isPlaylist ? `<button class="row-btn" data-del-vid="${esc(t.video_id)}" title="Удалить">✕</button>` : ''}
            </div>
        </div>
    `).join("");

    container.querySelectorAll(".track-item").forEach(row => {
        row.onclick = () => {
            if (queueVisible) {
                const index = queue.findIndex(track => track === tracks[Number(row.dataset.idx)]);
                if (index >= 0) playAt(index);
                return;
            }
            invalidateWave();
            queue = tracks.slice();
            queueOrigin = originTag;
            playAt(Number(row.dataset.idx));
        };
    });

    container.querySelectorAll(".track-item-artist").forEach(el => {
        el.onclick = (e) => {
            e.stopPropagation();
            const aName = el.dataset.aid ? el.dataset.artist : el.dataset.artist.split(",")[0].trim();
            openArtistCard(el.dataset.aid, aName, true);
        };
    });

    container.querySelectorAll("[data-like-idx]").forEach(btn => {
        btn.onclick = async () => {
            const track = tracks[Number(btn.dataset.likeIdx)];
            if (!track) return;
            const view = viewRequestId;
            btn.disabled = true;
            if (await toggleLikeTrack(track) && view === viewRequestId) {
                if (originTag === "likes" && !track.liked) {
                    renderTrackRowsInto(container, tracks.filter(item => item !== track), isPlaylist, originTag);
                } else {
                    btn.classList.toggle("liked", track.liked);
                    btn.innerHTML = track.liked ? SVG.heartFill : SVG.heart;
                }
            }
            btn.disabled = false;
        };
    });

    container.querySelectorAll("[data-dislike-idx]").forEach(btn => {
        btn.onclick = async () => {
            const idx = Number(btn.dataset.dislikeIdx);
            const track = tracks[idx];
            if (!track) return;
            const view = viewRequestId;
            if (await dislikeTrack(track) && view === viewRequestId) {
                const remaining = tracks.filter(item => item.video_id !== track.video_id);
                renderTrackRowsInto(container, remaining, isPlaylist, originTag);
            }
        };
    });

    container.querySelectorAll("[data-add-idx]").forEach(btn => {
        btn.onclick = () => {
            openAddModalWithTrack(tracks[Number(btn.dataset.addIdx)]);
        };
    });

    container.querySelectorAll("[data-del-vid]").forEach(btn => {
        btn.onclick = () => removeTrackFromPl(btn.dataset.delVid);
    });
}

function highlightActiveRow() {
    const activeVid = currentTrack?.video_id;
    document.querySelectorAll(".track-item").forEach(el => {
        el.classList.toggle("playing", el.dataset.vid === activeVid);
    });
}

async function openArtistCard(browseId, name, pushHistory = true) {
    if (!name && !browseId) return;

    if (pushHistory && !document.getElementById("drawer-panel").classList.contains("hidden")) {
        if (currentMode === "search" && lastSearchQuery) {
            viewHistory.push({ type: "search", query: lastSearchQuery, kind: searchKind });
        } else if (currentMode === "artist" && window._currentArtistMeta) {
            viewHistory.push({ type: "artist", browseId: window._currentArtistMeta.browseId, name: window._currentArtistMeta.name });
        }
    }

    currentMode = "artist";
    window._currentArtistMeta = { browseId, name };
    setActiveNav(null);
    cancelSearch();
    const view = openDrawer(name || "Исполнитель", { isArtistProfile: true });
    document.getElementById("ap-play-all-btn").disabled = true;

    document.getElementById("ap-name").textContent = name || "Загрузка...";
    document.getElementById("ap-subs").textContent = "";
    document.getElementById("ap-photo").src = placeholderCover;
    document.getElementById("ap-songs-list").innerHTML = "<p class='panel-message'>Загружаем популярные песни, альбомы и похожих артистов...</p>";
    document.getElementById("ap-albums-grid").innerHTML = "";
    document.getElementById("ap-similar-row").innerHTML = "";

    try {
        const res = await fetch(`/api/artist?browse_id=${encodeURIComponent(browseId || "")}&name=${encodeURIComponent(name || "")}`);
        if (!res.ok) throw new Error("Artist load failed");
        const prof = await res.json();
        if (view !== viewRequestId) return;

        window._currentArtistMeta = { browseId: prof.browse_id || browseId, name: prof.name || name };
        document.getElementById("drawer-title").textContent = prof.name || name;
        document.getElementById("ap-name").textContent = prof.name || name;
        document.getElementById("ap-subs").textContent = prof.subscribers || "";
        if (prof.photo) {
            document.getElementById("ap-photo").src = prof.photo;
        }

        const songs = prof.top_songs || [];
        renderTrackRowsInto(document.getElementById("ap-songs-list"), songs, false, "artist");

        document.getElementById("ap-play-all-btn").disabled = !songs.length;
        document.getElementById("ap-play-all-btn").onclick = () => {
            if (songs.length > 0) {
                invalidateWave();
                queue = songs.slice();
                queueOrigin = "artist";
                playAt(0);
            }
        };

        const albums = prof.albums || [];
        const albumsSec = document.getElementById("ap-albums-section");
        const albumsGrid = document.getElementById("ap-albums-grid");
        if (albums.length > 0) {
            albumsSec.classList.remove("hidden");
            albumsGrid.innerHTML = albums.map(alb => `
                <div class="album-card" data-aid="${esc(alb.browse_id)}" data-title="${esc(alb.title)}" data-artist="${esc(alb.artist || prof.name || name)}">
                    <img loading="lazy" decoding="async" src="${esc(alb.thumbnail || placeholderCover)}" alt="">
                    <div class="album-card-title" title="${esc(alb.title)}">${esc(alb.title)}</div>
                    <div class="album-card-sub">${esc([alb.year, alb.type].filter(Boolean).join(" • "))}</div>
                </div>
            `).join("");
            albumsGrid.querySelectorAll(".album-card").forEach(card => {
                card.onclick = () => openAlbumView(card.dataset.aid, card.dataset.title, card.dataset.artist);
            });
        } else {
            albumsSec.classList.add("hidden");
        }

        const similar = prof.similar_artists || [];
        const simSec = document.getElementById("ap-similar-section");
        const simRow = document.getElementById("ap-similar-row");
        if (similar.length > 0) {
            simSec.classList.remove("hidden");
            simRow.innerHTML = similar.map(sa => `
                <div class="artist-pill-card" data-bid="${esc(sa.browse_id || '')}" data-name="${esc(sa.name)}">
                    <img loading="lazy" decoding="async" src="${esc(sa.thumbnail || placeholderCover)}" alt="">
                    <span>${esc(sa.name)}</span>
                </div>
            `).join("");
            simRow.querySelectorAll(".artist-pill-card").forEach(card => {
                card.onclick = () => openArtistCard(card.dataset.bid, card.dataset.name, true);
            });
        } else {
            simSec.classList.add("hidden");
        }
    } catch {
        if (view !== viewRequestId) return;
        document.getElementById("ap-songs-list").innerHTML = "<p class='panel-message error'>Не удалось загрузить профиль артиста</p>";
    }
}

async function openAlbumView(browseId, title, artist = "") {
    if (!browseId) return;
    if (currentMode === "artist" && window._currentArtistMeta) {
        viewHistory.push({ type: "artist", browseId: window._currentArtistMeta.browseId, name: window._currentArtistMeta.name });
    }
    currentMode = "album";
    const view = openDrawer(`Альбом: ${title}`, { isArtistProfile: false });
    const container = document.getElementById("tracks-container");
    container.innerHTML = "<p class='panel-message'>Загружаем треки альбома...</p>";

    try {
        const res = await fetch(`/api/album/${encodeURIComponent(browseId)}?title=${encodeURIComponent(title || "")}&artist=${encodeURIComponent(artist || "")}`);
        if (!res.ok) throw new Error("Album load failed");
        const alb = await res.json();
        if (view !== viewRequestId) return;
        document.getElementById("drawer-title").textContent = `${alb.title} — ${alb.artist}${alb.year ? ` (${alb.year})` : ""}`;
        renderTrackRowsInto(container, alb.tracks || [], false, "album");
    } catch {
        if (view !== viewRequestId) return;
        container.innerHTML = "<p class='panel-message error'>Ошибка загрузки альбома</p>";
    }
}

const searchInput = document.getElementById("search-input");
const clearSearchBtn = document.getElementById("clear-search-btn");

function cancelSearch() {
    clearTimeout(searchTimer);
    searchAbortController?.abort();
}

async function requestJson(url, options) {
    const response = await fetch(url, options);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return response.json();
}

async function executeSearch(q, resetHistory = true) {
    cancelSearch();
    searchAbortController = new AbortController();

    if (resetHistory) viewHistory = [];
    currentMode = "search";
    lastSearchQuery = q;
    setActiveNav(null);
    const kind = searchKind;
    const view = openDrawer(`Поиск: «${q}»`, { isArtistProfile: false });
    document.getElementById("search-modes").classList.remove("hidden");
    for (const button of document.querySelectorAll("[data-search-kind]")) {
        button.setAttribute("aria-pressed", String(button.dataset.searchKind === kind));
    }
    syncSearchExitButtons();

    const container = document.getElementById("tracks-container");
    container.innerHTML = "<p class='panel-message'>Ищем...</p>";

    try {
        const params = new URLSearchParams({ q, kind });
        const data = await requestJson(`/api/search?${params}`, {
            signal: searchAbortController.signal
        });
        if (view !== viewRequestId) return;

        const artistsBlock = document.getElementById("artists-block");
        const artistsRow = document.getElementById("artists-row");
        if (data.artists && data.artists.length > 0) {
            artistsBlock.classList.remove("hidden");
            artistsRow.innerHTML = data.artists.map(a => `
                <div class="artist-pill-card" data-bid="${esc(a.browse_id || '')}" data-name="${esc(a.name)}">
                    <img loading="lazy" decoding="async" src="${esc(a.thumbnail || placeholderCover)}" alt="">
                    <span>${esc(a.name)}</span>
                </div>
            `).join("");
            artistsRow.querySelectorAll(".artist-pill-card").forEach(card => {
                card.onclick = () => openArtistCard(card.dataset.bid, card.dataset.name, true);
            });
        } else {
            artistsBlock.classList.add("hidden");
        }

        if (kind === "artists") {
            container.textContent = data.artists?.length ? "" : "Артисты не найдены";
        } else if (data.tracks?.length) {
            renderTrackRowsInto(container, data.tracks, false, "search");
        } else {
            container.textContent = "Песни не найдены";
        }
    } catch (e) {
        if (e.name !== "AbortError" && view === viewRequestId) {
            container.innerHTML = "<p class='panel-message error'>Ошибка сети при поиске</p>";
        }
    }
}

if (searchInput) {
    searchInput.addEventListener("input", (e) => {
        const q = e.target.value.trim();
        if (clearSearchBtn) clearSearchBtn.classList.toggle("hidden", !q);
        cancelSearch();

        if (!q) {
            exitSearchAndReturnToWave();
            return;
        }
        currentMode = "search";
        syncSearchExitButtons();
        searchTimer = setTimeout(() => executeSearch(q, true), 350);
    });

    searchInput.addEventListener("keydown", (e) => {
        if (e.key === "Enter") {
            e.preventDefault();
            clearTimeout(searchTimer);
            const q = searchInput.value.trim();
            if (q) executeSearch(q, true);
        }
    });
}

on("search-btn-ico", "click", () => {
    const q = searchInput.value.trim();
    if (q) executeSearch(q, true);
    else searchInput.focus();
});

on("search-modes", "click", event => {
    const kind = event.target.closest("[data-search-kind]")?.dataset.searchKind;
    const query = searchInput.value.trim() || lastSearchQuery;
    if (kind && kind !== searchKind && query) {
        searchKind = kind;
        executeSearch(query, false);
    }
});

on("clear-search-btn", "click", exitSearchAndReturnToWave);

function openCurrentTrackArtist() {
    if (!currentTrack || !currentTrack.artist || currentTrack.artist === "Melora") return;
    const name = currentTrack.artist_id ? currentTrack.artist : currentTrack.artist.split(",")[0].trim();
    openArtistCard(currentTrack.artist_id || "", name, false);
}
on("center-artist", "click", openCurrentTrackArtist);
on("dock-artist", "click", openCurrentTrackArtist);

const pendingLikes = new Set();

async function toggleLikeTrack(track) {
    if (!track || pendingLikes.has(track.video_id)) return false;
    pendingLikes.add(track.video_id);
    try {
        const data = await requestJson("/api/likes/toggle", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(track)
        });
        track.liked = data.liked;
        for (const item of queue) {
            if (item.video_id === track.video_id) item.liked = data.liked;
        }
        if (currentTrack?.video_id === track.video_id) currentTrack.liked = data.liked;
        updateAllPlayerUI();
        for (const row of document.querySelectorAll(".track-item")) {
            if (row.dataset.vid !== track.video_id) continue;
            const button = row.querySelector("[data-like-idx]");
            button.classList.toggle("liked", data.liked);
            button.innerHTML = data.liked ? SVG.heartFill : SVG.heart;
        }
        refreshWaveAfterLike();
        showHud(data.liked ? "Добавлено в Любимое" : "Убрано из Любимого");
        return true;
    } catch {
        showHud("Не удалось изменить Любимое");
        return false;
    } finally {
        pendingLikes.delete(track.video_id);
    }
}

on("like-btn", "click", () => toggleLikeTrack(currentTrack));

function openLibrary(mode, title, options) {
    cancelSearch();
    searchInput.value = "";
    clearSearchBtn.classList.add("hidden");
    lastSearchQuery = "";
    viewHistory = [];
    currentMode = mode;
    setActiveNav(`nav-${mode}`);
    const view = openDrawer(title, options);
    document.getElementById("tracks-container").textContent = "Загрузка…";
    return view;
}

async function openLikesDrawer() {
    const view = openLibrary("likes", "Любимое");
    try {
        const data = await requestJson("/api/likes");
        if (view !== viewRequestId) return;
        renderTrackRowsInto(document.getElementById("tracks-container"), data.tracks, false, "likes");
    } catch {
        if (view === viewRequestId) document.getElementById("tracks-container").textContent = "Не удалось загрузить Любимое";
    }
}

async function openPlaylistsDrawer() {
    const view = openLibrary("playlists", "Плейлисты", { showPlChips: true });
    const chips = document.getElementById("playlists-chips");
    const container = document.getElementById("tracks-container");
    chips.replaceChildren();
    try {
        const data = await requestJson("/api/playlists");
        if (view !== viewRequestId) return;
        if (!data.playlists.length) {
            activePlaylistId = null;
            container.textContent = "Плейлистов пока нет";
            return;
        }
        chips.innerHTML = data.playlists.map(p => `
            <button class="pl-chip" data-id="${p.id}" data-name="${esc(p.name)}">
                ${esc(p.name)} (${p.track_count})
            </button>
        `).join("");
        chips.querySelectorAll(".pl-chip").forEach(btn => {
            btn.onclick = () => loadPlaylistTracks(Number(btn.dataset.id), btn.dataset.name);
        });
        const target = data.playlists.find(p => p.id === activePlaylistId) || data.playlists[0];
        await loadPlaylistTracks(target.id, target.name);
    } catch {
        if (view === viewRequestId) container.textContent = "Не удалось загрузить плейлисты";
    }
}

async function loadPlaylistTracks(plId, plName) {
    const view = ++viewRequestId;
    const container = document.getElementById("tracks-container");
    activePlaylistId = plId;
    document.getElementById("drawer-title").textContent = `Плейлист: ${plName}`;
    document.getElementById("drawer-delete-pl-btn").classList.remove("hidden");
    document.querySelectorAll(".pl-chip").forEach(c => c.classList.toggle("active", Number(c.dataset.id) === plId));
    container.textContent = "Загрузка…";
    try {
        const data = await requestJson(`/api/playlists/${plId}/tracks`);
        if (view === viewRequestId) renderTrackRowsInto(container, data.tracks, true, "playlist");
    } catch {
        if (view === viewRequestId) container.textContent = "Не удалось загрузить треки плейлиста";
    }
}

async function createPlaylist(placeholder) {
    const name = await showCustomDialog({ title: "Новый плейлист", placeholder, isPrompt: true });
    if (!name) return null;
    try {
        return await requestJson("/api/playlists", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ name })
        });
    } catch {
        showHud("Не удалось создать плейлист");
        return null;
    }
}

on("drawer-create-pl-btn", "click", async () => {
    const view = viewRequestId;
    const created = await createPlaylist("Например: Ночной вайб");
    if (created && view === viewRequestId) {
        activePlaylistId = created.id;
        openPlaylistsDrawer();
    }
});

on("drawer-delete-pl-btn", "click", async () => {
    const id = activePlaylistId;
    const view = viewRequestId;
    if (!id) return;
    const ok = await showCustomDialog({ title: "Удалить плейлист?", text: "Все треки из этого плейлиста будут убраны." });
    if (!ok) return;
    try {
        await requestJson(`/api/playlists/${id}`, { method: "DELETE" });
        if (view === viewRequestId) {
            activePlaylistId = null;
            openPlaylistsDrawer();
        }
    } catch {
        showHud("Не удалось удалить плейлист");
    }
});

async function removeTrackFromPl(videoId) {
    if (!activePlaylistId) return;
    const view = viewRequestId;
    try {
        await requestJson(`/api/playlists/${activePlaylistId}/tracks/${encodeURIComponent(videoId)}`, { method: "DELETE" });
        if (view === viewRequestId) openPlaylistsDrawer();
    } catch {
        showHud("Не удалось убрать трек");
    }
}

async function openAddModalWithTrack(track) {
    if (!track) return;
    trackForPlaylist = track;
    try {
        const data = await requestJson("/api/playlists");
        if (trackForPlaylist !== track) return;
        const list = document.getElementById("modal-pl-list");
        list.innerHTML = data.playlists.map(p =>
            `<button class="modal-pl-item" data-id="${p.id}">${esc(p.name)}</button>`
        ).join("");
        if (!data.playlists.length) list.textContent = "Плейлистов пока нет";
        list.querySelectorAll("button").forEach(button => {
            button.onclick = () => confirmAddPl(Number(button.dataset.id), track);
        });
        document.getElementById("playlist-modal").classList.remove("hidden");
    } catch {
        showHud("Не удалось загрузить плейлисты");
    }
}

on("add-pl-btn", "click", () => openAddModalWithTrack(currentTrack));

async function confirmAddPl(plId, track) {
    try {
        await requestJson(`/api/playlists/${plId}/tracks`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(track)
        });
        if (trackForPlaylist === track) closeAddModal();
        showHud("Трек в плейлисте");
    } catch {
        showHud("Не удалось добавить трек");
    }
}

on("modal-new-pl-btn", "click", async () => {
    const track = trackForPlaylist;
    closeAddModal();
    const created = await createPlaylist("Введите название");
    if (created && track) await confirmAddPl(created.id, track);
});

function closeAddModal() {
    trackForPlaylist = null;
    document.getElementById("playlist-modal").classList.add("hidden");
}

on("modal-close-btn", "click", closeAddModal);

function setActiveNav(id) {
    document.querySelectorAll(".pill-btn").forEach(b => b.classList.toggle("active", b.id === id));
}

on("nav-wave", "click", () => exitSearchAndReturnToWave());
on("brand-wave-btn", "click", () => minimizeDrawerToPlayer());

on("refresh-wave-btn", "click", () => {
    if (searchInput) searchInput.value = "";
    lastSearchQuery = "";
    if (clearSearchBtn) clearSearchBtn.classList.add("hidden");
    syncSearchExitButtons();
    minimizeDrawerToPlayer();
    loadWave(true, true);
});
on("nav-likes", "click", openLikesDrawer);
on("nav-playlists", "click", openPlaylistsDrawer);

function toggleQueue() {
    if (!document.getElementById("drawer-panel").classList.contains("hidden")) {
        minimizeDrawerToPlayer();
    } else {
        cancelSearch();
        setActiveNav(null);
        currentMode = "queue";
        viewHistory = [];
        openDrawer("Текущая очередь", { isArtistProfile: false });
        queueVisible = true;
        renderTrackRowsInto(document.getElementById("tracks-container"), queue, false, queueOrigin);
    }
}

on("dock-cover-btn", "click", toggleQueue);
on("hero-cover-btn", "click", toggleQueue);

function handleGlobalMediaCommand(cmd) {
    const now = Date.now();
    const action = ["toggle", "play", "pause"].includes(cmd) ? "playback" : cmd;
    if (action === lastMediaAction && now - lastMediaHotkeyAt < 500) return;
    lastMediaHotkeyAt = now;
    lastMediaAction = action;

    if (cmd === "toggle" || (cmd === "play" && !playbackWanted)) togglePlay();
    else if (cmd === "pause") pauseAudio();
    else if (cmd === "next") nextTrack();
    else if (cmd === "prev") prevTrack();
    else if (cmd === "stop") {
        pauseAudio();
        if (Number.isFinite(audio.duration)) audio.currentTime = 0;
    }
}

async function pollMediaCommands() {
    try {
        const res = await fetch("/api/media-poll");
        const data = await res.json();
        if (lastPolledSeq === -1) {
            lastPolledSeq = data.seq;
        } else if (data.seq !== lastPolledSeq) {
            lastPolledSeq = data.seq;
            if (data.action) handleGlobalMediaCommand(data.action);
        }
    } catch {}
    finally { setTimeout(pollMediaCommands, 300); }
}
pollMediaCommands();

document.addEventListener("keydown", (e) => {
    if (e.repeat && !(e.code === "ArrowUp" || e.code === "ArrowDown")) return;
    if (e.code === "MediaPlayPause") { e.preventDefault(); return handleGlobalMediaCommand("toggle"); }
    if (e.code === "MediaTrackNext") { e.preventDefault(); return handleGlobalMediaCommand("next"); }
    if (e.code === "MediaTrackPrevious") { e.preventDefault(); return handleGlobalMediaCommand("prev"); }

    const isTyping = document.activeElement === searchInput || document.activeElement === document.getElementById("dialog-input");

    if (e.key === "Escape") {
        if (document.activeElement === searchInput) searchInput.blur();
        minimizeDrawerToPlayer();
        closeAddModal();
        return;
    }

    if ((e.ctrlKey && e.code === "KeyK") || (!isTyping && e.key === "/")) {
        e.preventDefault();
        searchInput.focus();
        return;
    }

    if (isTyping || e.ctrlKey || e.altKey || e.metaKey ||
        !document.getElementById("playlist-modal").classList.contains("hidden") ||
        !document.getElementById("custom-dialog").classList.contains("hidden") ||
        e.target.matches("input, textarea, [contenteditable]") ||
        (e.code === "Space" && e.target.matches("button"))) return;

    if (e.code === "Space") {
        e.preventDefault();
        togglePlay();
    } else if (e.code === "ArrowRight") {
        e.preventDefault();
        nextTrack();
    } else if (e.code === "ArrowLeft") {
        e.preventDefault();
        prevTrack();
    } else if (e.code === "ArrowUp") {
        e.preventDefault();
        applyVolume(volumeLevel + 0.05);
        showHud(`Громкость: ${Math.round(volumeLevel * 100)}%`);
    } else if (e.code === "ArrowDown") {
        e.preventDefault();
        applyVolume(volumeLevel - 0.05);
        showHud(`Громкость: ${Math.round(volumeLevel * 100)}%`);
    } else if (e.code === "KeyL") {
        toggleLikeTrack(currentTrack);
    } else if (e.code === "KeyD") {
        if (currentTrack) dislikeTrack(currentTrack);
    } else if (e.code === "KeyM") {
        applyVolume(volumeLevel > 0 ? 0 : unmutedVolume);
        showHud(volumeLevel === 0 ? "Звук выключен" : `Громкость: ${Math.round(volumeLevel * 100)}%`);
    }
});

if ("mediaSession" in navigator) {
    navigator.mediaSession.setActionHandler("play", () => handleGlobalMediaCommand("play"));
    navigator.mediaSession.setActionHandler("pause", () => handleGlobalMediaCommand("pause"));
    navigator.mediaSession.setActionHandler("previoustrack", () => handleGlobalMediaCommand("prev"));
    navigator.mediaSession.setActionHandler("nexttrack", () => handleGlobalMediaCommand("next"));
    navigator.mediaSession.setActionHandler("stop", () => handleGlobalMediaCommand("stop"));
}

loadWave(false);