import importlib, json
import numpy as np
import pytest


@pytest.fixture
def lv(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_AI_HOME", str(tmp_path))
    from jarvis_ai import config, aec
    importlib.reload(config); importlib.reload(aec)
    return aec


def test_publish_then_timeline_returns_the_reference_at_the_right_time(lv):
    aec = lv
    samples = np.sin(np.linspace(0, 400, 24000)).astype(np.float32) * 0.5        # 1 s at 24 kHz
    aec.publish(samples, 24000, t0=1000.0, seq=1)
    tl = aec.RefTimeline(); tl.poll()
    assert tl.seq == 1 and len(tl.chunks[0][1]) == 16000                        # resampled to 16 kHz
    assert not tl.block(999.9).any()                                           # before playback: silence
    mid = tl.block(1000.5 + 512 / 16000)                                       # a block starting 0.5 s in
    assert np.abs(mid).max() > 0.3
    assert not tl.block(1002.0).any()                                          # after playback: silence


def test_timeline_ignores_a_half_written_update(lv):
    aec = lv
    aec.publish(np.ones(2400, np.float32) * 0.1, 24000, 5.0, 1)
    tl = aec.RefTimeline(); tl.poll()
    # a new meta announces more samples than ref.bin contains: must be ignored, not crash
    from jarvis_ai import config
    with open(config.path("ref.json"), "w") as fh:
        json.dump({"seq": 2, "t0": 6.0, "n": 99999}, fh)
    tl.poll()
    assert tl.seq == 1 and len(tl.chunks) == 1


class Identity:
    """Stand-in for the WebRTC processor: returns the near-end frame unchanged."""
    def process_reverse_stream(self, b): pass
    def process_stream(self, b): return b


def test_canceller_keeps_block_size_and_signal(lv):
    aec = lv
    ec = aec.EchoCanceller(processor=Identity())
    rng = np.random.default_rng(0)
    sig = (rng.standard_normal(512 * 6) * 0.1).astype(np.float32)
    outs = [ec.process(sig[i:i + 512], np.zeros(512, np.float32)) for i in range(0, len(sig), 512)]
    assert all(len(o) == 512 for o in outs)
    got = np.concatenate(outs)
    # one block of start-up latency, then the same signal (to int16 rounding)
    assert not got[:512].any()
    assert np.allclose(got[512:], sig[:-512], atol=2e-4)


def test_make_respects_off_and_missing_package(lv, monkeypatch):
    aec = lv
    assert aec.make({"echo_cancel": "off"}) is None
    monkeypatch.setattr(aec.EchoCanceller, "__init__", lambda self, *a, **k: (_ for _ in ()).throw(ImportError("nope")))
    assert aec.make({"echo_cancel": "auto"}) is None                      # falls back quietly
