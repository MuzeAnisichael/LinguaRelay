from dataclasses import replace

from lingua_relay.config import Settings
from lingua_relay.ui.advanced_models import missing_model_downloads


def test_reports_only_missing_selected_advanced_models(tmp_path, monkeypatch) -> None:
    settings = Settings()
    settings = replace(
        settings,
        asr=replace(settings.asr, model="medium"),
        translation=replace(
            settings.translation,
            model="facebook/m2m100_1.2B",
            model_path=tmp_path / "m2m100_1.2b_ct2",
        ),
    )
    monkeypatch.setattr(
        "lingua_relay.ui.advanced_models._asr_installed",
        lambda *_args: False,
    )

    downloads = missing_model_downloads(settings, tmp_path)

    assert [item.kind for item in downloads] == ["asr", "translation"]
    assert [item.label for item in downloads] == ["Whisper medium", "M2M100 1.2B"]


def test_does_not_request_download_for_installed_base_profile(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        "lingua_relay.ui.advanced_models._asr_installed",
        lambda *_args: True,
    )
    assert missing_model_downloads(Settings(), tmp_path) == ()
