"""ALSA capture and PCM conversion for system or multichannel microphones."""

import os
import selectors
import subprocess
import time

import numpy as np


class AudioError(RuntimeError):
    """Audio capture stopped or lost data."""


def to_mono_s16(data, channels, sample_width, channel=0, gain=1.0):
    """Convert interleaved little-endian signed PCM; channel -1 averages channels."""
    if channels < 1 or sample_width not in (2, 4):
        raise ValueError('Only signed 16/32-bit PCM with at least one channel is supported')
    if not -1 <= channel < channels:
        raise ValueError('channel must be -1 or a valid zero-based channel index')
    if not np.isfinite(gain) or gain <= 0:
        raise ValueError('gain must be finite and positive')
    if len(data) % (channels * sample_width):
        raise ValueError('Audio chunk contains an incomplete PCM frame')
    samples = np.frombuffer(data, dtype='<i2' if sample_width == 2 else '<i4')
    samples = samples.reshape(-1, channels).astype(np.float64)
    mono = samples.mean(axis=1) if channel == -1 else samples[:, channel]
    if sample_width == 4:
        mono /= 65536.0
    return np.clip(np.rint(mono * gain), -32768, 32767).astype('<i2').tobytes()


class ArecordSource:
    """Read arecord without shell expansion; drain stderr and bound stall/shutdown time."""

    def __init__(self, device, channels=1, sample_format='S16_LE', block_frames=1600):
        if sample_format not in ('S16_LE', 'S32_LE') or channels < 1:
            raise ValueError('Invalid capture format or channel count')
        self.sample_width = 2 if sample_format == 'S16_LE' else 4
        self.block_bytes = block_frames * channels * self.sample_width
        self.command = [
            'arecord', '-q', '-D', device, '-t', 'raw', '-f', sample_format,
            '-r', '16000', '-c', str(channels), '--buffer-time=500000',
        ]
        self.process = None

    def chunks(self, stop_event):
        pending = bytearray()
        errors = bytearray()
        last_audio = time.monotonic()
        self.process = subprocess.Popen(
            self.command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL, bufsize=0, env=dict(os.environ, LC_ALL='C'),
        )
        try:
            with selectors.DefaultSelector() as selector:
                selector.register(self.process.stdout, selectors.EVENT_READ, 'audio')
                selector.register(self.process.stderr, selectors.EVENT_READ, 'error')
                while not stop_event.is_set():
                    ended = False
                    for key, _ in selector.select(timeout=0.2):
                        block = os.read(key.fd, self.block_bytes)
                        if not block:
                            selector.unregister(key.fileobj)
                            if key.data == 'audio':
                                ended = True
                            continue
                        if key.data == 'error':
                            errors.extend(block)
                            errors = errors[-4096:]
                            if b'overrun' in errors.lower():
                                raise AudioError('ALSA overrun; resetting recognition to discard broken audio')
                        else:
                            last_audio = time.monotonic()
                            pending.extend(block)
                            while len(pending) >= self.block_bytes:
                                yield bytes(pending[:self.block_bytes])
                                del pending[:self.block_bytes]
                    if ended or self.process.poll() is not None:
                        detail = errors.decode('utf-8', errors='replace').strip()
                        raise AudioError(detail or 'arecord exited; check the microphone connection')
                    if time.monotonic() - last_audio > 3.0:
                        raise AudioError('No microphone data for 3 seconds')
        finally:
            self.close()

    def close(self):
        if self.process is None:
            return
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
        self.process.stdout.close()
        self.process.stderr.close()
        self.process = None
