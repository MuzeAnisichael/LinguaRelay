"""Remove converter-only imports from the frozen CTranslate2 runtime."""

from __future__ import annotations

import sys
from types import ModuleType

sys.modules.setdefault("ctranslate2.converters", ModuleType("ctranslate2.converters"))
