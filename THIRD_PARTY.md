# Third-party components

LinguaRelay source code is MIT licensed. Dependencies and downloaded model
weights retain their own licenses. The project does not currently redistribute
model weights.

M1 audio dependencies:

| Component | Purpose | Declared license | Project |
|---|---|---|---|
| PyAudioWPatch | PortAudio bindings with WASAPI loopback | Apache-2.0 | https://github.com/s0d3s/PyAudioWPatch |
| python-soxr / libsoxr | Streaming sample-rate conversion | LGPL-2.1-or-later | https://github.com/dofuuz/python-soxr |
| NumPy | PCM arrays and signal calculations | BSD-3-Clause | https://numpy.org |
| psutil | Stress-test process memory metrics | BSD-3-Clause | https://github.com/giampaolo/psutil |
| PySide6 / Qt | Desktop overlay | LGPL-3.0 / GPL/commercial options | https://www.qt.io/qt-for-python |

Before distributing a packaged executable, generate a complete software bill of
materials, ship all required notices and dynamic libraries, and re-check the
exact versions selected by the lock file.
