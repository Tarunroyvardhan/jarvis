import sys
import types
from unittest.mock import MagicMock

from app.voice.wake_word import WakeWordDetector, WakeWordError


def _install_fake_openwakeword(monkeypatch, model_constructor=None, download_models=None):
    """Build and register a fully mocked `openwakeword` package (both the
    `.utils` and `.model` submodules) so success-path tests never touch
    real network/model-download/inference code, regardless of what's
    actually installed in the environment running the tests."""
    fake_model_module = types.ModuleType("openwakeword.model")
    fake_model_module.Model = model_constructor or MagicMock()

    fake_utils_module = types.ModuleType("openwakeword.utils")
    fake_utils_module.download_models = download_models or MagicMock()

    fake_package = types.ModuleType("openwakeword")
    fake_package.model = fake_model_module
    fake_package.utils = fake_utils_module

    monkeypatch.setitem(sys.modules, "openwakeword", fake_package)
    monkeypatch.setitem(sys.modules, "openwakeword.model", fake_model_module)
    monkeypatch.setitem(sys.modules, "openwakeword.utils", fake_utils_module)

    return fake_model_module, fake_utils_module


def test_get_model_reports_missing_dependency_honestly(monkeypatch):
    """Force the import to fail regardless of whether openwakeword is
    actually installed in the environment running this test — this must
    stay deterministic whether or not `pip install -e ".[voice]"` has
    been run."""
    monkeypatch.setitem(sys.modules, "openwakeword", None)
    monkeypatch.setitem(sys.modules, "openwakeword.utils", None)
    monkeypatch.setitem(sys.modules, "openwakeword.model", None)

    detector = WakeWordDetector()
    try:
        detector._get_model()
        assert False, "expected WakeWordError"
    except WakeWordError as exc:
        assert "Voice dependencies aren't installed" in str(exc)


def test_get_model_reports_download_failure_honestly(monkeypatch):
    failing_download = MagicMock(side_effect=RuntimeError("network unreachable"))
    _install_fake_openwakeword(monkeypatch, download_models=failing_download)

    detector = WakeWordDetector()
    try:
        detector._get_model()
        assert False, "expected WakeWordError"
    except WakeWordError as exc:
        assert "Failed to download wake word model files" in str(exc)


def test_get_model_reports_load_failure_honestly(monkeypatch):
    failing_constructor = MagicMock(side_effect=RuntimeError("could not load onnx model"))
    _install_fake_openwakeword(monkeypatch, model_constructor=failing_constructor)

    detector = WakeWordDetector()
    try:
        detector._get_model()
        assert False, "expected WakeWordError"
    except WakeWordError as exc:
        assert "Failed to load wake word model" in str(exc)


def test_get_model_downloads_before_loading(monkeypatch):
    """Regression test: the pip package doesn't ship every pretrained
    model's onnx file by default, so download_models() must run before
    Model() is constructed."""
    call_order = []

    def tracking_download(*args, **kwargs):
        call_order.append("download")

    def tracking_constructor(*args, **kwargs):
        call_order.append("load")
        instance = MagicMock()
        instance.predict.return_value = {"hey_jarvis": 0.1}
        return instance

    _install_fake_openwakeword(
        monkeypatch,
        model_constructor=tracking_constructor,
        download_models=MagicMock(side_effect=tracking_download),
    )

    detector = WakeWordDetector()
    detector._get_model()

    assert call_order == ["download", "load"]


def test_model_is_loaded_with_onnx_backend_explicitly(monkeypatch):
    """Regression test: openWakeWord defaults to tflite, which has no
    Windows wheel at all, so we must force onnx explicitly."""
    model_constructor = MagicMock()
    model_constructor.return_value.predict.return_value = {"hey_jarvis": 0.1}
    _install_fake_openwakeword(monkeypatch, model_constructor=model_constructor)

    detector = WakeWordDetector()
    detector.score_frame([0] * 1280)

    _, kwargs = model_constructor.call_args
    assert kwargs.get("inference_framework") == "onnx"


def test_score_frame_returns_confidence_from_mocked_model(monkeypatch):
    model_constructor = MagicMock()
    model_constructor.return_value.predict.return_value = {"hey_jarvis": 0.87}
    _install_fake_openwakeword(monkeypatch, model_constructor=model_constructor)

    detector = WakeWordDetector()
    score = detector.score_frame([0] * 1280)

    assert score == 0.87


def test_model_is_loaded_lazily_and_cached(monkeypatch):
    model_constructor = MagicMock()
    model_constructor.return_value.predict.return_value = {"hey_jarvis": 0.1}
    _install_fake_openwakeword(monkeypatch, model_constructor=model_constructor)

    detector = WakeWordDetector()
    assert model_constructor.call_count == 0

    detector.score_frame([0] * 1280)
    detector.score_frame([0] * 1280)

    assert model_constructor.call_count == 1


def test_score_frame_defaults_to_zero_for_missing_key(monkeypatch):
    model_constructor = MagicMock()
    model_constructor.return_value.predict.return_value = {}  # model name absent from output
    _install_fake_openwakeword(monkeypatch, model_constructor=model_constructor)

    detector = WakeWordDetector()
    score = detector.score_frame([0] * 1280)

    assert score == 0.0


def test_should_trigger_on_a_single_clear_detection():
    from app.voice.wake_word import should_trigger

    assert should_trigger([0.0, 0.05, 0.31], threshold=0.3)


def test_should_trigger_on_repeated_near_misses():
    """A real but quiet/fast "hey jarvis" often hovers just under the
    threshold for a few frames; that should still count."""
    from app.voice.wake_word import should_trigger

    assert should_trigger([0.2, 0.22, 0.05], threshold=0.3)
    assert should_trigger([0.0, 0.19, 0.25], threshold=0.3)


def test_should_not_trigger_on_noise_or_a_single_blip():
    from app.voice.wake_word import should_trigger

    assert not should_trigger([], threshold=0.3)
    assert not should_trigger([0.01, 0.02, 0.03], threshold=0.3)
    assert not should_trigger([0.0, 0.25, 0.0], threshold=0.3)
