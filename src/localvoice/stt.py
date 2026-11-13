"""Speech to text with interchangeable local backends. Nothing leaves the machine.

  mlx     mlx-whisper: fastest on Apple Silicon
  faster  faster-whisper (CTranslate2): any CPU, or an NVIDIA GPU if present; Linux, Windows, Intel Macs
"""
import numpy as np

from . import platform_

ALIASES = {
    "mlx": {"small": "mlx-community/whisper-small.en-mlx", "big": "mlx-community/whisper-large-v3-turbo"},
    "faster": {"small": "small.en", "big": "large-v3-turbo"},
}


def backend_name(cfg):
    b = cfg.get("stt_backend", "auto")
    if b != "auto":
        return b
    if platform_.APPLE_SILICON:
        try:
            import mlx_whisper  # noqa: F401
            return "mlx"
        except Exception:
            pass
    return "faster"


def model_name(cfg, backend=None):
    backend = backend or backend_name(cfg)
    m = cfg.get("stt_model", "small")
    name = ALIASES[backend].get(m, m)
    if backend == "faster" and cfg.get("language", "en") != "en" and name.endswith(".en"):
        name = name[:-3]                      # English-only models cannot do other languages
    return name


def prefetch(cfg, which=None):
    """Download the model so the first start is instant."""
    backend = backend_name(cfg)
    c = dict(cfg)
    if which:
        c["stt_model"] = which
    name = model_name(c, backend)
    if backend == "mlx":
        from huggingface_hub import snapshot_download
        snapshot_download(name)
    else:
        from faster_whisper.utils import download_model
        download_model(name)
    return backend, name


class Transcriber:
    def __init__(self, cfg):
        self.cfg = cfg
        self.backend = backend_name(cfg)
        self.name = model_name(cfg, self.backend)
        self.lang = cfg.get("language", "en")
        if self.backend == "mlx":
            import mlx_whisper
            self._mlx = mlx_whisper
        else:
            from faster_whisper import WhisperModel
            self._fw = WhisperModel(self.name, device="auto", compute_type="auto")
        self.transcribe(np.zeros(16000, dtype=np.float32))          # warm up

    def transcribe(self, audio, prompt=None):
        """-> (text, confident). `confident` is False when the result is probably a hallucination on noise."""
        if self.backend == "mlx":
            res = self._mlx.transcribe(audio, path_or_hf_repo=self.name, language=self.lang,
                                       condition_on_previous_text=False, initial_prompt=prompt)
            text = res["text"].strip()
            segs = res.get("segments") or []
            nsp = [s.get("no_speech_prob", 0) for s in segs]
            lp = [s.get("avg_logprob", 0) for s in segs]
        else:
            segs_it, _ = self._fw.transcribe(audio, language=self.lang, initial_prompt=prompt,
                                             condition_on_previous_text=False, beam_size=1)
            segs = list(segs_it)
            text = " ".join(s.text.strip() for s in segs).strip()
            nsp = [s.no_speech_prob for s in segs]
            lp = [s.avg_logprob for s in segs]
        ok = not (nsp and (max(nsp) > 0.5 or min(lp) < -1.0))
        return text, ok
