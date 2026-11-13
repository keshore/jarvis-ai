"""Voice activity detection and utterance segmentation.

Silero VAD (a small neural model, ONNX, via `pysilero-vad`) tells speech from everything else: keyboard clicks, fans, music,
a loud room. If it cannot load, a plain volume gate is used instead. The Segmenter turns a stream of (audio block, speech
probability) into whole utterances; it has no audio dependencies, so it is unit-tested on its own."""
import collections

import numpy as np

SR = 16000
BLOCK = 512                       # Silero needs exactly 512 samples (32 ms) at 16 kHz


class VolumeVad:
    """Fallback: 1.0 when the block is louder than the threshold, else 0.0."""
    name = "volume"

    def __init__(self, threshold):
        self.threshold = threshold

    def prob(self, block):
        return 1.0 if float(np.sqrt(np.mean(block ** 2))) > self.threshold else 0.0

    def reset(self):
        pass


class SileroVad:
    name = "silero"

    def __init__(self):
        from pysilero_vad import SileroVoiceActivityDetector
        self._cls = SileroVoiceActivityDetector
        self._v = self._cls()

    def prob(self, block):
        pcm = (np.clip(block, -1.0, 1.0) * 32767).astype(np.int16).tobytes()
        return float(self._v(pcm))

    def reset(self):
        self._v = self._cls()                 # fresh LSTM state


def make(cfg, volume_threshold):
    """The configured detector, falling back to the volume gate when Silero is unavailable."""
    if cfg.get("vad", "silero") == "silero":
        try:
            return SileroVad()
        except Exception as e:                # missing package, broken onnxruntime, ...
            print(f"  (Silero VAD unavailable, using a volume gate: {e})", flush=True)
    return VolumeVad(volume_threshold)


class Segmenter:
    """Speech starts after `start_blocks` blocks above `start`; it ends after `end_silence` seconds below `end`
    (probabilities in between keep it going, so a short dip inside a word does not cut the sentence)."""

    def __init__(self, start=0.6, end=0.35, end_silence=0.65, min_speech=0.4, pre_roll=0.3, max_utt=30.0,
                 start_blocks=3, block=BLOCK, sr=SR, end_silence_short=None, short=1.2):
        self.start, self.end, self.start_blocks = start, end, start_blocks
        self.bs = block / sr
        self.end_silence, self.min_speech, self.max_utt = end_silence, min_speech, max_utt
        # a short command ("stop") ends quickly; once you are into a sentence, pauses to think are allowed to be longer
        self.end_silence_short, self.short = (end_silence if end_silence_short is None else min(end_silence_short, end_silence)), short
        self._pre = collections.deque(maxlen=int(pre_roll / self.bs) + start_blocks)
        self.reset()

    def reset(self):
        self.active, self._buf, self._hot, self._quiet = False, [], 0, 0
        self._pre.clear()

    def start_from(self, blocks):
        """Begin an utterance right now (used when you talk over the voice)."""
        self.active, self._buf, self._hot, self._quiet = True, list(blocks), 0, 0
        self._pre.clear()

    def push(self, block, p):
        """Feed one block and its speech probability. Returns the finished utterance (float32 audio) or None."""
        if not self.active:
            self._pre.append(block)
            self._hot = self._hot + 1 if p >= self.start else 0
            if self._hot >= self.start_blocks:
                self.start_from(self._pre)
            return None
        self._buf.append(block)
        self._quiet = self._quiet + 1 if p < self.end else 0
        dur = len(self._buf) * self.bs
        speech = dur - self._quiet * self.bs
        wait = self.end_silence_short if speech < self.short else self.end_silence
        if self._quiet * self.bs < wait and dur < self.max_utt:
            return None
        audio = np.concatenate(self._buf)
        self.reset()
        return audio if speech >= self.min_speech else None
