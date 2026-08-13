from __future__ import annotations

import os

from lingua_relay.audio.types import AudioProcess


class AudioProcessNotFoundError(RuntimeError):
    pass


class AudioProcessManager:
    """Enumerate safe user-facing process identities without exposing command lines."""

    def list_processes(self) -> tuple[AudioProcess, ...]:
        try:
            import psutil
        except ImportError as error:
            raise RuntimeError("psutil is required for process audio capture") from error

        processes: list[AudioProcess] = []
        own_pid = os.getpid()
        for process in psutil.process_iter(("pid", "name")):
            try:
                process_id = int(process.info["pid"])
                name = str(process.info.get("name") or "").strip()
            except (psutil.AccessDenied, psutil.NoSuchProcess, TypeError, ValueError):
                continue
            if process_id in {0, 4, own_pid} or not name:
                continue
            processes.append(AudioProcess(process_id, name))
        return tuple(sorted(processes, key=lambda item: (item.name.casefold(), item.process_id)))

    def resolve(self, process_id: int, process_name: str = "") -> AudioProcess:
        processes = self.list_processes()
        exact = next((item for item in processes if item.process_id == process_id), None)
        if exact is not None and (
            not process_name or exact.name.casefold() == process_name.strip().casefold()
        ):
            return exact
        wanted = process_name.strip().casefold()
        if wanted:
            matches = [item for item in processes if item.name.casefold() == wanted]
            if matches:
                return max(matches, key=lambda item: item.process_id)
        label = process_name.strip() or str(process_id)
        raise AudioProcessNotFoundError(f"audio target process is not running: {label}")
