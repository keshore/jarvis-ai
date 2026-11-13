import numpy as np
import pytest

from jarvis_ai import vad

B = vad.BLOCK


def blk(v=0.1):
    return np.full(B, v, np.float32)


def run(seg, probs):
    """Feed probabilities; return the list of finished utterances."""
    out = []
    for p in probs:
        a = seg.push(blk(), p)
        if a is not None:
            out.append(a)
    return out


def seg(**kw):
    return vad.Segmenter(**kw)


def test_one_clean_utterance():
    out = run(seg(), [0.0] * 10 + [0.9] * 30 + [0.0] * 30)
    assert len(out) == 1
    assert 30 * B <= len(out[0]) <= 65 * B                 # 30 speech + pre-roll + 0.65 s of trailing silence


def test_short_blip_is_ignored():
    assert run(seg(), [0.0] * 5 + [0.9] * 2 + [0.0] * 40) == []        # two blocks < start_blocks


def test_a_dip_inside_a_sentence_does_not_cut_it():
    probs = [0.9] * 15 + [0.5] * 6 + [0.9] * 15 + [0.0] * 30          # 0.5 is between end (0.35) and start (0.6)
    assert len(run(seg(), probs)) == 1


def test_pause_longer_than_end_silence_splits_in_two():
    probs = [0.9] * 20 + [0.0] * 30 + [0.9] * 20 + [0.0] * 30          # 30 blocks = 0.96 s > 0.65 s
    assert len(run(seg(), probs)) == 2


def test_utterance_shorter_than_min_speech_is_dropped():
    assert run(seg(min_speech=0.4), [0.9] * 3 + [0.0] * 40) == []      # 3 blocks = 96 ms


def test_max_length_cuts_a_never_ending_utterance():
    out = run(seg(max_utt=2.0), [0.9] * 200)
    assert len(out) >= 2 and all(len(a) <= (2.0 / (B / 16000) + 2) * B for a in out)


def test_pre_roll_keeps_the_start_of_the_word():
    s = seg(pre_roll=0.3)
    marks = [np.full(B, i / 100, np.float32) for i in range(10)]       # distinguishable blocks
    for m in marks[:5]:
        assert s.push(m, 0.0) is None
    for m in marks[5:8]:
        s.push(m, 0.9)                                                  # speech detected on the 3rd one
    for _ in range(15):
        s.push(blk(), 0.9)                                              # enough speech to be kept
    audio = None
    for _ in range(40):
        got = s.push(blk(), 0.0)
        if got is not None:
            audio = got
    assert audio is not None and audio[0] == pytest.approx(0.0, abs=1e-6)    # started from the early blocks


def test_start_from_begins_immediately_for_barge_in():
    s = seg()
    s.start_from([blk(), blk()])
    assert s.active
    out = run(s, [0.9] * 20 + [0.0] * 30)
    assert len(out) == 1 and not s.active


def test_volume_fallback():
    v = vad.VolumeVad(0.02)
    assert v.prob(np.zeros(B, np.float32)) == 0.0
    assert v.prob(np.full(B, 0.1, np.float32)) == 1.0


def test_make_falls_back_when_silero_is_missing(monkeypatch):
    monkeypatch.setattr(vad.SileroVad, "__init__", lambda self: (_ for _ in ()).throw(ImportError("missing")))
    d = vad.make({"vad": "silero"}, 0.03)
    assert d.name == "volume" and d.threshold == 0.03
    assert vad.make({"vad": "volume"}, 0.05).name == "volume"


def test_silero_ignores_noise():
    pytest.importorskip("pysilero_vad")
    d = vad.SileroVad()
    rng = np.random.default_rng(1)
    p = [d.prob((rng.standard_normal(B) * 0.08).astype(np.float32)) for _ in range(60)]
    assert max(p) < 0.5                                                  # loud white noise is not speech


def test_a_pause_inside_a_sentence_is_allowed_but_a_short_command_ends_quickly():
    import numpy as np
    from jarvis_ai import vad
    bs = vad.BLOCK / vad.SR
    blk = np.zeros(vad.BLOCK, np.float32)

    def run(pattern):                                   # pattern: list of (seconds, speech?)  -> number of utterances
        seg = vad.Segmenter(end_silence=1.1, end_silence_short=0.6, min_speech=0.2)
        n = 0
        for secs, speech in pattern:
            for _ in range(int(secs / bs)):
                n += seg.push(blk, 0.9 if speech else 0.0) is not None
        return n
    assert run([(2.5, True), (0.9, False), (2.0, True), (1.3, False)]) == 1      # 0.9 s thinking pause mid-sentence: one sentence
    assert run([(2.5, True), (1.3, False), (2.0, True), (1.3, False)]) == 2      # a real stop
    assert run([(0.6, True), (0.7, False)]) == 1                                 # "stop": done after 0.6 s, no long wait
