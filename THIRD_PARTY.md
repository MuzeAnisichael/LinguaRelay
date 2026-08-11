# Third-party components

LinguaRelay source code is MIT licensed. Dependencies and downloaded model
weights retain their own licenses. Model weights are distributed as a separate
GitHub Release asset and retain their upstream licenses.

Implemented M1/M2/M3 dependencies (M4's OpenAI-compatible transport uses only
the Python standard library):

| Component | Purpose | Declared license | Project |
|---|---|---|---|
| PyAudioWPatch | PortAudio bindings with WASAPI loopback | Apache-2.0 | https://github.com/s0d3s/PyAudioWPatch |
| python-soxr / libsoxr | Streaming sample-rate conversion | LGPL-2.1-or-later | https://github.com/dofuuz/python-soxr |
| NumPy | PCM arrays and signal calculations | BSD-3-Clause | https://numpy.org |
| psutil | Stress-test process memory metrics | BSD-3-Clause | https://github.com/giampaolo/psutil |
| PySide6 / Qt | Desktop overlay | LGPL-3.0 / GPL/commercial options | https://www.qt.io/qt-for-python |
| faster-whisper | Multilingual Whisper inference integration | MIT | https://github.com/SYSTRAN/faster-whisper |
| CTranslate2 | CPU/CUDA Transformer inference runtime | MIT | https://github.com/OpenNMT/CTranslate2 |
| Silero VAD | Speech filtering used through faster-whisper | MIT | https://github.com/snakers4/silero-vad |
| OpenCC Python reimplementation | Traditional-to-Simplified Chinese normalization | Apache-2.0 | https://github.com/yichen0831/opencc-python |
| NVIDIA cuBLAS/cuDNN Python wheels | Optional Windows CUDA runtime libraries | NVIDIA SDK/component licenses | https://pypi.org/project/nvidia-cublas-cu12/ |
| M2M100 418M | Direct four-language machine translation weights | MIT | https://huggingface.co/facebook/m2m100_418M |
| SentencePiece | M2M100 runtime tokenization | Apache-2.0 | https://github.com/google/sentencepiece |
| PyInstaller | Windows application bundling | GPL-2.0-or-later with bootloader exception | https://pyinstaller.org/ |
| Inno Setup | Optional Windows installer compiler | Custom permissive license | https://jrsoftware.org/isinfo.php |

M2 evaluation data uses Google FLEURS under CC-BY-4.0. Audio is downloaded on
demand from `google/fleurs` at revision
`70bb2e84b976b7e960aa89f1c648e09c59f894dd`; it is ignored by Git and is not
redistributed in this repository. Benchmark reports may contain the public
reference and ASR hypothesis text needed to audit WER/CER.

Each release includes an SPDX software bill of materials. The trusted model
manifest pins every redistributed model file by path, size, and SHA-256.
