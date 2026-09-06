"""Small, testable helpers used only while building the frozen application."""

from __future__ import annotations

import importlib.metadata
from pathlib import Path

# The Widgets workbench plays audio, not PDF images or a QML virtual keyboard.
# Qt's default plugin discovery pulls these optional plugin dependencies in.
# Keep Qt Multimedia's FFmpeg ABI and PyAV's separate FFmpeg ABI intact.
OPTIONAL_QT_NAMES = frozenset(
    {
        "qpdf.dll",
        "qtvirtualkeyboardplugin.dll",
        "qt6pdf.dll",
        "qt6virtualkeyboard.dll",
        "qt6quick.dll",
        "qt6qml.dll",
        "qt6qmlmeta.dll",
        "qt6qmlmodels.dll",
        "qt6qmlworkerscript.dll",
    }
)


def trim_optional_qt(binaries: list[tuple[str, str, str]]) -> list[tuple[str, str, str]]:
    import pefile

    removed = {
        Path(name).name.lower()
        for name, _source, _kind in binaries
        if name.replace("\\", "/").lower().startswith("pyside6/")
        and Path(name).name.lower() in OPTIONAL_QT_NAMES
    }
    kept = [entry for entry in binaries if Path(entry[0]).name.lower() not in removed]
    # Refuse to prune if a changed Qt wheel adds a static or delayed dependency
    # from retained code. Dynamic use is covered by the final EXE media self-test.
    for name, source, _kind in kept:
        if Path(source).suffix.lower() not in {".dll", ".pyd", ".exe"}:
            continue
        with pefile.PE(source, fast_load=True) as executable:
            executable.parse_data_directories(
                directories=[
                    pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_IMPORT"],
                    pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_DELAY_IMPORT"],
                ]
            )
            imported = {
                item.dll.decode("ascii").lower()
                for group in ("DIRECTORY_ENTRY_IMPORT", "DIRECTORY_ENTRY_DELAY_IMPORT")
                for item in getattr(executable, group, [])
            }
        missing = imported & removed
        if missing:
            raise ValueError(f"cannot trim Qt dependencies required by {name}: {sorted(missing)}")
    print(f"Excluded {len(removed)} optional Qt PDF/virtual-keyboard/QML files")
    return kept


def collected_distribution_names(
    entries: list[tuple[str, str, str]],
) -> list[str]:
    """Identify wheels that own at least one collected Python module or binary."""
    sources = {Path(source).resolve() for _name, source, _kind in entries if source}
    names = set()
    for distribution in importlib.metadata.distributions():
        name = distribution.metadata.get("Name", "")
        if name.lower().replace("-", "").replace("_", "") == "linguarelay":
            continue
        if any(
            Path(distribution.locate_file(item)).resolve() in sources
            for item in distribution.files or ()
        ):
            names.add(name)
    return sorted(names, key=str.casefold)
