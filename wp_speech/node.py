"""Publish offline speech recognition from an ALSA microphone or a local WAV file."""

import json
import math
from pathlib import Path
import re
import shutil
import threading
import wave

import rclpy
from rcl_interfaces.msg import ParameterDescriptor
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile
from std_msgs.msg import String

from .audio import ArecordSource, AudioError, to_mono_s16
from .download_model import DEFAULT_MODEL, check_model


def chinese_text(text):
    """Remove Chinese token separators while preserving spaces between English words."""
    return re.sub(r'(?<=[\u3400-\u9fff])\s+(?=[\u3400-\u9fff])', '', text.strip())


class SpeechRecognizer(Node):
    def __init__(self):
        super().__init__('vosk_recognizer')
        self.stop_event = threading.Event()
        self.done = threading.Event()
        self.exit_code = 0
        self.worker = None
        self.last_partial = ''
        self.text_pub = self.create_publisher(String, 'speech/text', 10)
        self.partial_pub = self.create_publisher(String, 'speech/partial', 10)
        self.result_pub = self.create_publisher(String, 'speech/result', 10)
        self.status_pub = self.create_publisher(
            String, 'speech/status', QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL))

    def parameter(self, name, default, description):
        return self.declare_parameter(
            name, default, ParameterDescriptor(description=description, read_only=True)).value

    def start(self):
        self.model_path = self.parameter('model_path', DEFAULT_MODEL, 'Local unpacked Vosk model directory')
        self.device = self.parameter('device', 'default', 'ALSA input; default follows the system input selection')
        self.channels = self.parameter('channels', 1, 'Number of interleaved capture channels')
        self.sample_format = self.parameter('sample_format', 'S16_LE', 'Signed PCM format: S16_LE or S32_LE')
        self.channel = self.parameter('channel', 0, 'Zero-based microphone index; -1 averages all channels')
        self.gain = self.parameter('gain', 1.0, 'Positive software gain applied before 16-bit clipping')
        self.retry_seconds = self.parameter('retry_seconds', 3.0, 'Delay before reopening a failed microphone')
        self.publish_partial = self.parameter('publish_partial', True, 'Publish changing partial hypotheses')
        self.wav_path = self.parameter('wav_path', '', 'Optional 16 kHz PCM WAV file for offline recognition')
        if self.sample_format not in ('S16_LE', 'S32_LE'):
            raise ValueError('sample_format must be S16_LE or S32_LE')
        if self.channels < 1 or not -1 <= self.channel < self.channels:
            raise ValueError('channels must be positive; channel must be -1 or less than channels')
        if not math.isfinite(self.gain) or self.gain <= 0:
            raise ValueError('gain must be finite and positive')
        if not math.isfinite(self.retry_seconds) or self.retry_seconds < 0.1:
            raise ValueError('retry_seconds must be finite and at least 0.1')
        try:
            path = check_model(self.model_path)
        except ValueError as error:
            raise ValueError(f'{error}. Download with: ros2 run wp_speech download_model --language all') from error
        if not self.wav_path and not shutil.which('arecord'):
            raise RuntimeError('arecord is missing; install alsa-utils')
        try:
            from vosk import KaldiRecognizer, Model, SetLogLevel
        except ImportError as error:
            raise RuntimeError('Install Vosk with: python3 -m pip install --user vosk==0.3.45') from error
        self.status('loading')
        self.get_logger().info(f'Loading Vosk model: {path}')
        SetLogLevel(-1)
        self.model = Model(str(path))  # Explicit path: no network/model download during recognition.
        self.recognizer_factory = KaldiRecognizer
        self.worker = threading.Thread(target=self.run, name='vosk_audio')
        self.worker.start()

    def status(self, state):
        if self.context.ok():
            self.status_pub.publish(String(data=state))

    def new_recognizer(self):
        recognizer = self.recognizer_factory(self.model, 16000)
        recognizer.SetWords(True)
        self.clear_partial()
        return recognizer

    def clear_partial(self):
        if self.publish_partial and self.last_partial and self.context.ok():
            self.partial_pub.publish(String(data=''))
        self.last_partial = ''

    def final_result(self, raw):
        result = json.loads(raw)
        text = chinese_text(result.get('text', ''))
        if text and self.context.ok():
            self.text_pub.publish(String(data=text))
            self.result_pub.publish(String(data=json.dumps(result, ensure_ascii=False)))
            self.get_logger().info(f'\033[33m{text}\033[0m')
        self.clear_partial()

    def accept(self, recognizer, pcm):
        if recognizer.AcceptWaveform(pcm):
            self.final_result(recognizer.Result())
        elif self.publish_partial:
            text = chinese_text(json.loads(recognizer.PartialResult()).get('partial', ''))
            if text != self.last_partial and self.context.ok():
                self.partial_pub.publish(String(data=text))
                self.last_partial = text

    def run(self):
        try:
            if self.wav_path:
                self.run_wav()
            else:
                self.run_microphone()
        except Exception as error:
            self.exit_code = 1
            if self.context.ok():
                self.get_logger().error(str(error))
                self.status('error')
        finally:
            self.done.set()

    def run_microphone(self):
        while not self.stop_event.is_set():
            recognizer = self.new_recognizer()
            source = ArecordSource(self.device, self.channels, self.sample_format)
            try:
                self.status('opening')
                first = True
                for block in source.chunks(self.stop_event):
                    if self.stop_event.is_set():
                        break
                    if first:
                        self.status('listening')
                        self.get_logger().info(f'Listening: {self.device}, channel={self.channel}, 16000 Hz')
                        first = False
                    self.accept(recognizer, to_mono_s16(
                        block, self.channels, source.sample_width, self.channel, self.gain))
            except (AudioError, OSError) as error:
                if not self.stop_event.is_set() and self.context.ok():
                    self.get_logger().warning(f'Microphone unavailable: {error}; retrying in {self.retry_seconds}s')
                    self.clear_partial()
                    self.status('reconnecting')
            finally:
                source.close()
            self.stop_event.wait(self.retry_seconds)

    def run_wav(self):
        with wave.open(str(Path(self.wav_path).expanduser()), 'rb') as wav:
            channels, width = wav.getnchannels(), wav.getsampwidth()
            if wav.getframerate() != 16000 or wav.getcomptype() != 'NONE' or width not in (2, 4):
                raise ValueError('wav_path requires uncompressed 16 kHz signed 16/32-bit PCM WAV')
            if self.channel >= channels:
                raise ValueError('channel exceeds the WAV channel count')
            recognizer = self.new_recognizer()
            self.status('listening')
            while not self.stop_event.is_set():
                block = wav.readframes(1600)
                if not block:
                    self.final_result(recognizer.FinalResult())
                    self.status('finished')
                    return
                self.accept(recognizer, to_mono_s16(block, channels, width, self.channel, self.gain))
                # Real-time playback allows subscribers to discover the node before EOF.
                self.stop_event.wait(len(block) / (16000 * channels * width))

    def stop(self):
        self.stop_event.set()
        if self.worker is not None:
            self.worker.join()


def main(args=None):
    rclpy.init(args=args)
    node = SpeechRecognizer()
    exit_code = 0
    try:
        node.start()
        while rclpy.ok() and not node.done.is_set():
            rclpy.spin_once(node, timeout_sec=0.1)
        exit_code = node.exit_code
        # Give DDS a brief opportunity to deliver the WAV EOF result before teardown.
        if rclpy.ok() and node.wav_path and exit_code == 0:
            rclpy.spin_once(node, timeout_sec=0.2)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    except Exception as error:
        node.get_logger().error(str(error))
        node.status('error')
        exit_code = 1
    finally:
        node.stop()
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
    return exit_code
