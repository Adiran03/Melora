"""Windows desktop entry point used by Melora.exe."""

import ctypes
import json
import logging
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path


HOST = "127.0.0.1"
PORTS = range(8765, 8775)
logger = logging.getLogger(__name__)
local_http = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def melora_is_ready(port, revision=None):
    try:
        with local_http.open(f"http://{HOST}:{port}/api/health", timeout=0.25) as response:
            data = json.load(response)
            return (isinstance(data, dict) and data.get("app") == "Melora"
                    and data.get("ready") is True
                    and (revision is None or data.get("revision") == revision))
    except (OSError, ValueError):
        return False


def open_window(port):
    url = f"http://{HOST}:{port}/"
    browsers = []
    for env in ("ProgramFiles(x86)", "ProgramFiles", "LOCALAPPDATA"):
        if base := os.getenv(env):
            browsers.extend((Path(base) / "Microsoft/Edge/Application/msedge.exe",
                             Path(base) / "Google/Chrome/Application/chrome.exe"))
    for browser in dict.fromkeys(browsers):
        if browser.is_file():
            try:
                subprocess.Popen([str(browser), f"--app={url}", "--window-size=1160,740"])
                return
            except OSError:
                logger.warning("Could not open %s", browser, exc_info=True)
    if not webbrowser.open(url):
        raise RuntimeError("Не удалось открыть браузер для Melora.")


def reserve_server_socket():
    busy = []
    for port in PORTS:
        listener = socket.socket()
        try:
            if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            listener.bind((HOST, port))
            return port, listener, busy
        except OSError:
            listener.close()
            busy.append(port)
    return None, None, busy


def run(app=None, ready_file=None):
    import uvicorn
    if app is None:
        from main import app

    def signal_ready(port):
        if ready_file is None:
            open_window(port)
        else:
            ready_file.write_text(f"http://{HOST}:{port}/", encoding="ascii")

    port, listener, busy = reserve_server_socket()
    try:
        for attempt in range(5 if busy else 0):
            for existing in busy:
                if melora_is_ready(existing, app.state.revision):
                    signal_ready(existing)
                    return
            if attempt < 4:
                time.sleep(0.15)
        if listener is None:
            raise RuntimeError("Локальные порты Melora заняты.")

        config = uvicorn.Config(app, host=HOST, port=port, log_level="warning", log_config=None)
        server = uvicorn.Server(config)

        def open_when_ready():
            while not server.started:
                time.sleep(0.05)
            try:
                signal_ready(port)
                if ready_file is not None:
                    stop_file = ready_file.with_suffix(".stop")
                    while not server.should_exit and not stop_file.exists():
                        time.sleep(0.2)
                    server.should_exit = True
            except (OSError, RuntimeError) as error:
                report_error(str(error), ready_file)
                server.should_exit = True

        threading.Thread(target=open_when_ready, daemon=True).start()
        server.run(sockets=[listener])
        if not server.started:
            raise RuntimeError("Сервер Melora не запустился.")
    finally:
        if listener is not None:
            listener.close()


def report_error(message, ready_file=None):
    if ready_file is not None:
        try:
            ready_file.with_suffix(".error").write_text(message, encoding="utf-8")
        except OSError:
            logger.error("Could not report launcher error: %s", message)
    elif sys.stderr is not None:
        print(message, file=sys.stderr)
    elif os.name == "nt":
        ctypes.windll.user32.MessageBoxW(None, message, "Melora", 0x10)


def main(app=None, ready_file=None):
    try:
        if sys.stderr is None:
            from database import user_data_directory

            log_dir = user_data_directory()
            log_dir.mkdir(parents=True, exist_ok=True)
            logging.basicConfig(filename=log_dir / "melora.log", encoding="utf-8", level=logging.WARNING)
        run(app, ready_file)
    except ModuleNotFoundError as error:
        report_error(f"Отсутствует модуль {error.name}. Установи зависимости Melora из requirements.txt.", ready_file)
    except Exception as error:
        logger.exception("Melora startup failed")
        report_error(f"Не удалось запустить Melora.\n\n{error}", ready_file)


if __name__ == "__main__":
    marker = Path(sys.argv[2]) if len(sys.argv) == 3 and sys.argv[1] == "--native" else None
    main(ready_file=marker)
