import sys
import threading
import time

import numpy as np
import pytest

from wp_speech.audio import ArecordSource, AudioError, to_mono_s16


def test_kinect_channel_and_signed_range():
    pcm = np.array([
        [0, 65536, -65536, 2147483647],
        [-2147483648, 131072, -131072, 0],
    ], dtype='<i4').tobytes()
    assert np.frombuffer(to_mono_s16(pcm, 4, 4, 0), '<i2').tolist() == [0, -32768]
    assert np.frombuffer(to_mono_s16(pcm, 4, 4, 2), '<i2').tolist() == [-1, -2]
    assert np.frombuffer(to_mono_s16(pcm, 4, 4, 3), '<i2').tolist() == [32767, 0]


def test_average_and_gain_clip_without_integer_overflow():
    pcm = np.array([[32767, 32767], [-32768, -32768], [2000, -1000]], dtype='<i2').tobytes()
    assert np.frombuffer(to_mono_s16(pcm, 2, 2, -1, 2.0), '<i2').tolist() == [32767, -32768, 1000]


@pytest.mark.parametrize('args', [
    (b'\x00', 4, 4, 0, 1.0),
    (b'', 4, 4, 4, 1.0),
    (b'', 4, 4, -2, 1.0),
    (b'', 0, 4, 0, 1.0),
    (b'', 4, 3, 0, 1.0),
    (b'', 4, 4, 0, float('nan')),
    (b'', 4, 4, 0, 0.0),
])
def test_invalid_pcm_rejected(args):
    with pytest.raises(ValueError):
        to_mono_s16(*args)


def fake_source(code):
    source = ArecordSource('unused', channels=1, sample_format='S16_LE', block_frames=4)
    source.command = [sys.executable, '-c', code]
    return source


def test_fragmented_pipe_preserves_pcm_frames_and_stops_child():
    source = fake_source(
        "import os,time; os.write(1,b'abc'); time.sleep(.1); "
        "os.write(1,b'defghijklmnop'); time.sleep(10)")
    stop = threading.Event()
    stream = source.chunks(stop)
    try:
        assert next(stream) == b'abcdefgh'
        child = source.process
        assert next(stream) == b'ijklmnop'
        stop.set()
        with pytest.raises(StopIteration):
            next(stream)
        assert child.poll() is not None
    finally:
        stream.close()


def test_capture_failure_reports_stderr():
    source = fake_source("import sys; sys.stderr.write('audio open error: No such device\\n'); sys.exit(1)")
    with pytest.raises(AudioError, match='No such device'):
        list(source.chunks(threading.Event()))
    assert source.process is None


def test_stalled_capture_times_out_and_cleans_up():
    source = fake_source('import time; time.sleep(30)')
    start = time.monotonic()
    with pytest.raises(AudioError, match='No microphone data'):
        list(source.chunks(threading.Event()))
    assert time.monotonic() - start < 6
    assert source.process is None


def test_overrun_is_not_silently_fed_to_recognizer():
    source = fake_source("import os,time; os.write(2,b'overrun!!!\\n'); time.sleep(30)")
    with pytest.raises(AudioError, match='overrun'):
        list(source.chunks(threading.Event()))
    assert source.process is None
