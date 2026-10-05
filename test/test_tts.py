import io
from pathlib import Path
import queue
import sys
import tarfile
import threading
import time
from types import SimpleNamespace
import wave

import numpy as np
import pytest
import rclpy
from std_msgs.msg import String

from wp_speech.download_tts_model import extract_model
from wp_speech.tts import TtsNode, WavPlayer, write_wav


def test_wav_volume_clips_and_preserves_format(tmp_path):
    file = tmp_path / 'audio.wav'
    assert write_wav(file, [-2, -1, 0, 0.5, 2], 16000) == 5 / 16000
    with wave.open(str(file), 'rb') as audio:
        assert (audio.getnchannels(), audio.getsampwidth(), audio.getframerate()) == (1, 2, 16000)
        assert np.frombuffer(audio.readframes(5), '<i2').tolist() == [-32768, -32768, 0, 16384, 32767]


@pytest.mark.parametrize('samples', [[], [float('nan')], [[1, 2]]])
def test_invalid_synthesis_audio_rejected(tmp_path, samples):
    with pytest.raises(ValueError):
        write_wav(tmp_path / 'bad.wav', samples, 44100)


@pytest.mark.parametrize('name,kind', [('../escape', tarfile.REGTYPE), ('link', tarfile.SYMTYPE)])
def test_model_archive_rejects_unsafe_entries(tmp_path, name, kind):
    archive = tmp_path / 'model.tar.bz2'
    with tarfile.open(archive, 'w:bz2') as bundle:
        info = tarfile.TarInfo(name)
        info.type = kind
        info.linkname = '/tmp'
        bundle.addfile(info, io.BytesIO())
    with pytest.raises(ValueError):
        extract_model(archive, tmp_path / 'model')


class Recorder:
    def __init__(self):
        self.messages = []

    def publish(self, message):
        self.messages.append(message.data)


@pytest.fixture
def node():
    rclpy.init()
    instance = TtsNode()
    instance.tasks = queue.Queue(maxsize=2)
    instance.max_chars = 20
    instance.volume = 1.0
    instance.speed = 1.0
    instance.output_dir = None
    instance.done_pub = Recorder()
    instance.status_pub = Recorder()
    try:
        yield instance
    finally:
        instance.stop()
        instance.destroy_node()
        rclpy.shutdown()


def test_queue_rejects_empty_oversized_and_newest_overflow(node):
    for text in (' ', 'a' * 21, '\x00bad', '第一句', 'second sentence', '第三句'):
        node.receive_text(String(data=text))
    assert node.tasks.qsize() == 2
    assert node.tasks.get_nowait() == '第一句'
    assert node.tasks.get_nowait() == 'second sentence'


def test_worker_preserves_order_and_recovers_after_playback_error(node):
    seen = []

    class Engine:
        def generate(self, text, **kwargs):
            seen.append(text)
            return SimpleNamespace(samples=np.ones(16) * 0.1, sample_rate=16000)

    class Player:
        def play(self, path, stop_event, duration):
            with wave.open(str(path), 'rb') as audio:
                assert audio.getnframes() == 16
            if len(seen) == 1:
                raise RuntimeError('test speaker failure')
            return True

    node.engine = Engine()
    node.player = Player()
    node.receive_text(String(data='第一句'))
    node.receive_text(String(data='second sentence'))
    node.worker = threading.Thread(target=node.run)
    node.worker.start()
    deadline = time.monotonic() + 3
    while not node.done_pub.messages:
        assert time.monotonic() < deadline
        time.sleep(0.01)
    assert seen == ['第一句', 'second sentence']
    assert node.done_pub.messages == ['second sentence']
    assert 'error' in node.status_pub.messages


def test_playback_cancellation_reaps_process(tmp_path):
    pid_file = tmp_path / 'player.pid'
    player = WavPlayer.__new__(WavPlayer)
    player.command = [sys.executable, '-c',
                      'import os,sys,time; open(sys.argv[1],"w").write(str(os.getpid())); time.sleep(30)',
                      str(pid_file)]
    stop = threading.Event()
    timer = threading.Timer(0.3, stop.set)
    timer.start()
    try:
        assert player.play(tmp_path / 'ignored.wav', stop, 30) is False
        assert not Path('/proc', pid_file.read_text()).exists()
    finally:
        timer.cancel()
