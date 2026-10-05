"""Offline Melo TTS and sequential audio playback for ROS2 text messages."""

import math
from pathlib import Path
import queue
import shutil
import signal
import subprocess
import tempfile
import threading
import time
import uuid
import wave

import numpy as np
import rclpy
from rcl_interfaces.msg import ParameterDescriptor
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile
from std_msgs.msg import String

from .download_tts_model import DEFAULT_TTS_MODEL, check_tts_model


def write_wav(path, samples, sample_rate, volume=1.0):
    samples = np.asarray(samples, dtype=np.float64)
    if samples.ndim != 1 or samples.size == 0 or not np.all(np.isfinite(samples)):
        raise ValueError('TTS returned empty or invalid audio')
    if sample_rate <= 0 or not math.isfinite(volume) or volume < 0:
        raise ValueError('Invalid sample rate or volume')
    pcm = np.clip(np.rint(samples * volume * 32768), -32768, 32767).astype('<i2')
    with wave.open(str(path), 'wb') as output:
        output.setparams((1, 2, int(sample_rate), 0, 'NONE', 'not compressed'))
        output.writeframes(pcm.tobytes())
    return len(pcm) / sample_rate


class WavPlayer:
    def __init__(self, backend='auto', device=''):
        if backend == 'auto':
            backend = 'alsa'
            if shutil.which('paplay') and shutil.which('pactl'):
                try:
                    if subprocess.run(['pactl', 'info'], stdout=subprocess.DEVNULL,
                                      stderr=subprocess.DEVNULL, timeout=2).returncode == 0:
                        backend = 'pulse'
                except (OSError, subprocess.TimeoutExpired):
                    pass
        if backend not in ('pulse', 'alsa'):
            raise ValueError('audio_backend must be auto, pulse or alsa')
        program = 'paplay' if backend == 'pulse' else 'aplay'
        if not shutil.which(program):
            raise ValueError(f'{program} is missing; install pulseaudio-utils and alsa-utils')
        self.command = [program] if backend == 'pulse' else [program, '-q']
        if device:
            self.command += ['--device', device] if backend == 'pulse' else ['-D', device]
        self.backend = backend

    def play(self, path, stop_event, duration):
        if stop_event.is_set():
            return False
        with tempfile.TemporaryFile() as errors:
            process = subprocess.Popen(
                self.command + [str(path)], stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL, stderr=errors)
            try:
                deadline = time.monotonic() + duration + 10
                while process.poll() is None:
                    if stop_event.wait(0.1):
                        return False
                    if time.monotonic() > deadline:
                        raise RuntimeError('Audio playback timed out')
                if process.returncode:
                    errors.seek(0)
                    detail = errors.read(4096).decode('utf-8', errors='replace').strip()
                    raise RuntimeError(f'Audio playback failed: {detail or process.returncode}')
                return not stop_event.is_set()
            finally:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()


class TtsNode(Node):
    def __init__(self):
        super().__init__('speech_tts')
        self.stop_event = threading.Event()
        self.worker = None
        self.status_pub = self.create_publisher(
            String, 'tts/status', QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL))
        self.done_pub = self.create_publisher(String, 'tts/done', 10)

    def parameter(self, name, default, description):
        return self.declare_parameter(
            name, default, ParameterDescriptor(description=description, read_only=True)).value

    def start(self):
        model_dir = self.parameter('model_path', DEFAULT_TTS_MODEL, 'Local unpacked Melo TTS model')
        self.speed = self.parameter('speed', 1.0, 'Positive speech speed; larger is faster')
        self.volume = self.parameter('volume', 1.0, 'Software volume from 0 to 2')
        num_threads = self.parameter('num_threads', 2, 'CPU inference threads')
        self.max_chars = self.parameter('max_chars', 500, 'Maximum characters per text message')
        queue_size = self.parameter('queue_size', 10, 'Maximum number of waiting utterances')
        self.playback = self.parameter('playback', True, 'Play audio after synthesis')
        backend = self.parameter('audio_backend', 'auto', 'auto, pulse or alsa')
        device = self.parameter('audio_device', '', 'PulseAudio sink or ALSA device; empty uses default')
        output_dir = self.parameter('output_dir', '', 'Optional directory to retain generated WAV files')
        if not math.isfinite(self.speed) or self.speed <= 0:
            raise ValueError('speed must be finite and positive')
        if not math.isfinite(self.volume) or not 0 <= self.volume <= 2:
            raise ValueError('volume must be finite and between 0 and 2')
        if min(num_threads, self.max_chars, queue_size) < 1:
            raise ValueError('num_threads, max_chars and queue_size must be positive')
        self.tasks = queue.Queue(maxsize=queue_size)
        self.output_dir = Path(output_dir).expanduser() if output_dir else None
        if self.output_dir:
            self.output_dir.mkdir(parents=True, exist_ok=True)
        try:
            model = check_tts_model(model_dir)
        except ValueError as error:
            raise ValueError(f'{error}. Download with: ros2 run wp_speech download_tts_model') from error
        try:
            import sherpa_onnx
        except ImportError as error:
            raise RuntimeError('Install: python3 -m pip install --user sherpa-onnx==1.13.8') from error
        self.player = WavPlayer(backend, device) if self.playback else None
        self.status('loading')
        config = sherpa_onnx.OfflineTtsConfig(
            model=sherpa_onnx.OfflineTtsModelConfig(
                vits=sherpa_onnx.OfflineTtsVitsModelConfig(
                    model=str(model / 'model.onnx'), tokens=str(model / 'tokens.txt'),
                    lexicon=str(model / 'lexicon.txt')),
                num_threads=num_threads, provider='cpu', debug=False),
            rule_fsts=','.join(str(model / name) for name in ('phone.fst', 'date.fst', 'number.fst')),
            max_num_sentences=1)
        if not config.validate():
            raise ValueError('Invalid sherpa-onnx TTS configuration')
        self.get_logger().info(f'Loading TTS model: {model}')
        self.engine = sherpa_onnx.OfflineTts(config)
        self.subscription = self.create_subscription(String, 'tts/text', self.receive_text, 10)
        self.status('idle')
        self.worker = threading.Thread(target=self.run, name='tts_worker')
        self.worker.start()
        self.get_logger().info(f'TTS ready; topic={self.subscription.topic_name}')

    def status(self, state):
        if self.context.ok():
            self.status_pub.publish(String(data=state))

    def receive_text(self, message):
        text = message.data.strip()
        if not text or self.stop_event.is_set():
            return
        if len(text) > self.max_chars or '\x00' in text:
            self.get_logger().warning(f'Rejected text: maximum {self.max_chars} characters; NUL is unsupported')
            return
        try:
            self.tasks.put_nowait(text)
        except queue.Full:
            self.get_logger().warning('TTS queue is full; rejected newest text')

    def run(self):
        while not self.stop_event.is_set():
            try:
                text = self.tasks.get(timeout=0.1)
            except queue.Empty:
                continue
            if self.stop_event.is_set():
                self.tasks.task_done()
                break
            try:
                self.status('synthesizing')
                self.get_logger().info(f'\033[33m朗读: {text}\033[0m')
                # VITS 1.13.8 uses 1 to continue and 0 to stop between sentence batches.
                audio = self.engine.generate(
                    text, sid=0, speed=self.speed,
                    callback=lambda samples, progress: int(not self.stop_event.is_set()))
                if self.stop_event.is_set():
                    break
                with tempfile.TemporaryDirectory(prefix='wpb-tts-') as tmp:
                    directory = self.output_dir if self.output_dir else Path(tmp)
                    path = directory / (uuid.uuid4().hex + '.wav')
                    duration = write_wav(path, audio.samples, audio.sample_rate, self.volume)
                    if self.player:
                        self.status('playing')
                        if not self.player.play(path, self.stop_event, duration):
                            break
                if self.context.ok():
                    self.done_pub.publish(String(data=text))
                self.status('idle')
            except Exception as error:
                if self.context.ok() and not self.stop_event.is_set():
                    self.get_logger().error(f'TTS failed: {error}')
                    self.status('error')
            finally:
                self.tasks.task_done()

    def stop(self):
        self.stop_event.set()
        if self.worker is not None:
            self.worker.join()


def main(args=None):
    rclpy.init(args=args)
    node = TtsNode()
    exit_code = 0
    try:
        node.start()
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    except Exception as error:
        node.get_logger().error(str(error))
        node.status('error')
        exit_code = 1
    finally:
        # launch may forward another SIGINT after the terminal already signalled us.
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        node.stop()
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
    return exit_code
