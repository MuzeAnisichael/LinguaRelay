"""Remove converter-only imports from the frozen CTranslate2 runtime."""

from __future__ import annotations

import os
import sys
from types import ModuleType

# Prefer the Windows system directory for OS-owned DLLs such as ICU. This also
# protects frozen builds from unrelated copies injected through the user's PATH.
if sys.platform == "win32":
    system_root = os.environ.get("SYSTEMROOT")
    if system_root:
        _system_dll_handle = os.add_dll_directory(os.path.join(system_root, "System32"))

sys.modules.setdefault("ctranslate2.converters", ModuleType("ctranslate2.converters"))
