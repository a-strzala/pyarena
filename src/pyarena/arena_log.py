import os
import platform
from pathlib import Path

from watchdog.events import PatternMatchingEventHandler
from watchdog.observers import Observer
from watchdog.observers.api import BaseObserver
from watchdog.observers.polling import PollingObserver

WINDOWS_PLATFORM_IDENTIFIER = "Windows"
# MACOS_PLATFORM_IDENTIFIER = "Darwin"

COMPANY_SUBFOLDER_NAME = "Wizards Of The Coast"
APPLICATION_SUBFOLDER_NAME = "MTGA"
CURRENT_LOGFILE_NAME = "Player.log"
PREVIOUS_LOGFILE_NAME = "Player-prev.log"

DEFAULT_POLLING_OBSERVER_INTERVAL = 1
UNABLE_TO_STOP_OBSERVER_EXCEPTION = RuntimeError("Unable to stop watchdog observer")


class ArenaLog:
    """This class provides a main interface for handling Arena logfiles. It allows you
    to specify the path to the logfile to analyze, or it will automatically attempt to
    locate the logfile based on typical locations for the detected platform. You can
    also provide a custom Watchdog observer if desired, although the class will
    automatically create one if not provided. Please note that on Windows, the default
    observer uses polling due to how the Win API interacts with Arena's log rotation.

    Args:
        path: Path to the logfile to watch. If not provided, will attempt to
            automatically locate the logfile.
        observer: Watchdog observer to use. If not provided, will automatically
            create an observer.
        follow_current: If true, will follow the logfile if Arena rotates the
            logfile. If false, will stop watching if the logfile is moved or renamed.

    Raises:
        TypeError: If the provided path is neither a pathlib path nor path string.
        ValueError: If the provided path does not exist.
        RuntimeError: If the logfile cannot be found automatically.
        NotImplementedError: If the current platform is not supported.
        RuntimeError: If the watchdog observer cannot be stopped.
    """

    def __init__(
        self,
        path: Path | None = None,
        observer: BaseObserver | None = None,
        follow_current: bool = True,
    ) -> None:
        if not path:
            self.path = self.find_logfile()
        else:
            self.path = path
        if isinstance(self.path, str):
            self.path = Path(self.path)
        if isinstance(self.path, Path):
            self.path = self.path.resolve()
        else:
            raise TypeError(f"Unsupported path type: {type(path)}")
        if not self.path.exists():
            raise ValueError(f"Provided file does not exist at {self.path}")

        if not observer:
            self.observer = self.get_watchdog_observer()
        else:
            self.observer = observer

        self.event_handler = FileEventHandler(self)
        self.follow_current = follow_current

        self.observer.schedule(self.event_handler, self.path.parent, recursive=False)
        self.observer.start()

    def find_logfile(self) -> Path:
        """Attempts to automatically locate the Arena logfile based on typical
        locations for the current platform.

        Returns:
            Path: Path to the Arena logfile.

        Raises:
            RuntimeError: If the logfile cannot be found.
            NotImplementedError: If the current platform is not supported.
        """
        NO_LOGFILE_FOUND_EXCEPTION = RuntimeError(
            "Unable to automatically locate logfile location"
        )
        if platform.system() == WINDOWS_PLATFORM_IDENTIFIER:
            try:
                appdata_roaming = Path(os.environ["appdata"])
                appdata_locallow = appdata_roaming.parent / "LocalLow"
            except KeyError:
                appdata_locallow = Path.home() / "AppData" / "LocalLow"
            if not appdata_locallow.exists():
                raise NO_LOGFILE_FOUND_EXCEPTION
            logfile_path = (
                appdata_locallow
                / COMPANY_SUBFOLDER_NAME
                / APPLICATION_SUBFOLDER_NAME
                / CURRENT_LOGFILE_NAME
            )
            if not logfile_path.exists():
                raise NO_LOGFILE_FOUND_EXCEPTION
            return logfile_path.resolve()
        else:
            raise NotImplementedError(f"Unsupported platform: {platform.system()}")

    def get_watchdog_observer(self) -> BaseObserver:
        """Creates a watchdog observer based on the current platform.

        Returns:
            BaseObserver: Watchdog observer for the current platform.
        """
        if platform.system() == WINDOWS_PLATFORM_IDENTIFIER:
            observer = PollingObserver(timeout=DEFAULT_POLLING_OBSERVER_INTERVAL)
        else:
            observer = Observer()
        return observer

    def handle_log_moved(self) -> None:
        """Handles the event where the logfile is moved or renamed, usually due to
        Arena's log rotation. If follow_current is true, will attempt to follow
        the logfile. If false, will stop watching the logfile gracefully.

        Raises:
            RuntimeError: If the watchdog observer cannot be stopped.
        """
        if self.follow_current:
            self.path = self.find_logfile()
            print("New path:", self.path)
            self.observer.stop()
            self.observer.join()
            if self.observer.is_alive():
                raise UNABLE_TO_STOP_OBSERVER_EXCEPTION
            self.observer = self.get_watchdog_observer()
            self.observer.schedule(
                self.event_handler, self.path.parent, recursive=False
            )
            self.observer.start()
        else:
            self.handle_log_deleted()

    def handle_log_deleted(self) -> None:
        """Handles the event where the logfile is deleted. Will stop watching the
        logfile gracefully.

        Raises:
            RuntimeError: If the watchdog observer cannot be stopped.
        """
        self.observer.stop()
        self.observer.join()
        if self.observer.is_alive():
            raise UNABLE_TO_STOP_OBSERVER_EXCEPTION
        self.event_handler = None

    def __del__(self) -> None:
        self.observer.stop()
        self.observer.join()
        if self.observer.is_alive():
            raise UNABLE_TO_STOP_OBSERVER_EXCEPTION


class FileEventHandler(PatternMatchingEventHandler):
    """Event handler for the Arena logfile. Only dispatches events for the
    parent ArenaLog's logfile.

    Args:
        parent_log: ArenaLog instance that this event handler is associated with.
    """

    def __init__(self, parent_log: ArenaLog) -> None:
        super().__init__(
            patterns=[
                CURRENT_LOGFILE_NAME,
                PREVIOUS_LOGFILE_NAME,
                parent_log.path.name,
            ],
            ignore_directories=True,
        )
        self.parent_log = parent_log

    def dispatch(self, event) -> None:
        """Dispatches the event if it is for the parent ArenaLog's logfile.

        Args:
            event: Watchdog event to dispatch.
        """
        if event.is_directory:
            return
        if src_path := getattr(event, "src_path", None):
            if src_path != str(self.parent_log.path):
                return
        return super().dispatch(event)

    def on_any_event(self, event):
        """Prints the event for debugging purposes."""
        print(event)

    def on_moved(self, event):
        """Signals the parent ArenaLog that the logfile has been moved or renamed."""
        self.parent_log.handle_log_moved()

    def on_deleted(self, event):
        """Signals the parent ArenaLog that the logfile has been deleted."""
        self.parent_log.handle_log_deleted()


if __name__ == "__main__":
    # TODO: Move this to a proper debug script
    al = ArenaLog()
    while al.observer.is_alive():
        al.observer.join(1)
