"""Watch filesystem and trigger incremental graph updates."""
import time
import threading
from pathlib import Path
from typing import Dict, Callable, Optional
from queue import Queue

try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler, FileModifiedEvent, FileCreatedEvent, FileDeletedEvent
    HAS_WATCHDOG = True
except ImportError:
    HAS_WATCHDOG = False

from .db import GraphDB
from .scanner import incremental_scan
from .languages import detect_language


class _ChangeHandler(FileSystemEventHandler):
    def __init__(self, root: Path, queue: "Queue[Path]", config: Dict):
        self.root = root
        self.queue = queue
        self.config = config
        self.ignore_patterns = config.get("ignore_patterns", [])

    def _should_ignore(self, p: Path) -> bool:
        rel = str(p.relative_to(self.root))
        for pat in self.ignore_patterns:
            if pat.startswith("*"):
                if p.name.endswith(pat[1:]):
                    return True
            elif pat in rel or p.match(pat):
                return True
        return False

    def on_modified(self, event):
        if isinstance(event, FileModifiedEvent) and not event.is_directory:
            p = Path(event.src_path)
            if not self._should_ignore(p) and detect_language(p):
                self.queue.put(p)

    def on_created(self, event):
        if isinstance(event, FileCreatedEvent) and not event.is_directory:
            p = Path(event.src_path)
            if not self._should_ignore(p) and detect_language(p):
                self.queue.put(p)

    def on_deleted(self, event):
        if isinstance(event, FileDeletedEvent) and not event.is_directory:
            p = Path(event.src_path)
            if not self._should_ignore(p) and detect_language(p):
                self.queue.put(p)


class GraphWatcher:
    def __init__(self, root: Path, db: GraphDB, config: Dict):
        self.root = root
        self.db = db
        self.config = config
        self.queue: Queue[Path] = Queue()
        self.observer: Optional[Observer] = None
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self):
        if not HAS_WATCHDOG:
            raise RuntimeError("watchdog not installed. Run: pip install watchdog")

        handler = _ChangeHandler(self.root, self.queue, self.config)
        self.observer = Observer()
        self.observer.schedule(handler, str(self.root), recursive=True)
        self.observer.start()

        self._thread = threading.Thread(target=self._process_loop, daemon=True)
        self._thread.start()

    def _process_loop(self):
        while not self._stop_event.is_set():
            changed: set = set()
            # Collect all pending changes
            while not self.queue.empty():
                changed.add(self.queue.get())

            if changed:
                try:
                    incremental_scan(self.root, self.db, self.config, list(changed))
                except Exception as e:
                    print(f"[ai-memory] Update error: {e}")

            self._stop_event.wait(1.0)

    def stop(self):
        self._stop_event.set()
        if self.observer:
            self.observer.stop()
            self.observer.join()
        if self._thread:
            self._thread.join(timeout=2)


def watch_project(root: Path, db: GraphDB, config: Dict):
    watcher = GraphWatcher(root, db, config)
    watcher.start()
    print(f"[ai-memory] Watching {root} for changes...")
    print("[ai-memory] Press Ctrl+C to stop.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        watcher.stop()
        print("[ai-memory] Stopped.")
