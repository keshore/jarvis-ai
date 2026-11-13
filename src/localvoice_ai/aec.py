"""Acoustic echo cancellation (optional): subtract what the voice is playing from what the microphone hears.

The voice daemon publishes every chunk it plays (`ref.bin` + `ref.json`, 16 kHz int16, with the wall-clock time playback
started). The listener lines that reference up with each microphone block and runs WebRTC's echo canceller
(`aec-audio-processing`) on the pair. What is left is you, so voice detection on it can tell "you are talking over me" from
"that is just my own voice coming back". Without the package the listener falls back to a loudness heuristic."""
import json
import os

import numpy as np

from . import config

SR = 16000


def make(cfg):
    if cfg.get("echo_cancel", "auto") == "off":
        return None
    try:
        return EchoCanceller(int(cfg.get("aec_delay_ms", 150)))
    except Exception as e:                    # package not installed, or it failed to initialise
        print(f"  (echo cancellation unavailable, using the loudness heuristic: {e})", flush=True)
        return None


class EchoCanceller:
    FRAME = 160                               # WebRTC works on 10 ms frames; our blocks are 512 samples

    def __init__(self, delay_ms=150, processor=None):
        if processor is None:
            from aec_audio_processing import AudioProcessor
            processor = AudioProcessor(enable_aec=True, enable_ns=False, enable_agc=False, enable_vad=False)
            processor.set_stream_format(SR, 1)
            processor.set_reverse_stream_format(SR, 1)
            processor.set_stream_delay(delay_ms)         # speaker -> room -> microphone round trip
        self.ap = processor
        self._m = np.zeros(0, np.int16)
        self._r = np.zeros(0, np.int16)
        self._out = np.zeros(512, np.float32)            # one block of start-up latency keeps the output steady

    @staticmethod
    def _pcm(x):
        return (np.clip(x, -1.0, 1.0) * 32767).astype(np.int16)

    def process(self, mic, ref):
        """mic, ref: float32 blocks of equal length -> cleaned float32 block of the same length."""
        self._m = np.concatenate([self._m, self._pcm(mic)])
        self._r = np.concatenate([self._r, self._pcm(ref)])
        f = self.FRAME
        outs = []
        while len(self._m) >= f and len(self._r) >= f:
            fm, fr, self._m, self._r = self._m[:f], self._r[:f], self._m[f:], self._r[f:]
            self.ap.process_reverse_stream(fr.tobytes())                       # far end first, then near end
            outs.append(np.frombuffer(self.ap.process_stream(fm.tobytes()), np.int16).astype(np.float32) / 32767)
        if outs:
            self._out = np.concatenate([self._out] + outs)
        n = len(mic)
        blk, self._out = self._out[:n], self._out[n:]
        return blk if len(blk) == n else np.pad(blk, (0, n - len(blk)))


class RefTimeline:
    """Reads what the voice daemon has played and returns the reference for any time window."""

    def __init__(self):
        self.seq = -1
        self.chunks = []                      # (start wall-clock time, int16 samples)

    @staticmethod
    def _meta():
        try:
            with open(config.path("ref.json")) as fh:
                return json.load(fh)
        except (OSError, ValueError):
            return None

    def poll(self):
        m = self._meta()
        if not m or m.get("seq") == self.seq:
            return
        try:
            arr = np.fromfile(config.path("ref.bin"), dtype=np.int16)
        except OSError:
            return
        m2 = self._meta()
        if not m2 or m2.get("seq") != m["seq"] or len(arr) != m["n"]:
            return                            # the daemon replaced the file while we read it: try again next time
        self.seq = m["seq"]
        self.chunks.append((float(m["t0"]), arr))
        self.chunks = self.chunks[-12:]

    def block(self, t_end, n=512, sr=SR):
        """Reference samples for the n samples that ended at wall-clock time t_end (zeros when nothing was playing)."""
        out = np.zeros(n, np.float32)
        t_start = t_end - n / sr
        for t0, arr in self.chunks:
            a = int(round((t_start - t0) * sr))
            lo, hi = max(a, 0), min(a + n, len(arr))
            if hi > lo:
                out[lo - a:hi - a] += arr[lo:hi].astype(np.float32) / 32768
        return out


def publish(samples, sr, t0, seq):
    """Called by the voice daemon right before it plays `samples` (float32 at `sr`)."""
    n = int(len(samples) * SR / sr)
    x = np.interp(np.linspace(0, len(samples) - 1, n), np.arange(len(samples)), samples)
    pcm = (np.clip(x, -1.0, 1.0) * 32767).astype(np.int16)
    bin_p, json_p = config.path("ref.bin"), config.path("ref.json")
    with open(bin_p + ".tmp", "wb") as fh:
        fh.write(pcm.tobytes())
    os.replace(bin_p + ".tmp", bin_p)
    with open(json_p + ".tmp", "w") as fh:
        json.dump({"seq": seq, "t0": t0, "n": int(len(pcm))}, fh)
    os.replace(json_p + ".tmp", json_p)
