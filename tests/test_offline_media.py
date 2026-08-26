from __future__ import annotations

import wave

from lingua_relay.offline.media import decode_media_to_wav, export_audio, probe_media


def _wave(path, *, frames: int = 8000) -> None:
    with wave.open(str(path), "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(8000)
        stream.writeframes(b"\0\0" * frames)


def test_probe_decode_and_mp3_export(tmp_path) -> None:
    source = tmp_path / "source.wav"
    _wave(source)
    info = probe_media(source)
    assert info.audio_streams == 1
    assert 990 <= info.duration_ms <= 1010

    normalized = decode_media_to_wav(source, tmp_path / "normalized.wav")
    with wave.open(str(normalized), "rb") as stream:
        assert stream.getframerate() == 16_000
        assert stream.getnchannels() == 1

    mp3 = export_audio(normalized, tmp_path / "speech.mp3")
    assert mp3.stat().st_size > 0
    assert probe_media(mp3).audio_streams == 1
