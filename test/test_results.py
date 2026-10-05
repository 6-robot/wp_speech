import json
import time

import rclpy
from rclpy.executors import SingleThreadedExecutor
from rclpy.qos import DurabilityPolicy, QoSProfile
from std_msgs.msg import String

from wp_speech.node import SpeechRecognizer, chinese_text


def test_chinese_spacing_preserves_english_words():
    assert chinese_text(' 请 前进 到 厨房 ') == '请前进到厨房'
    assert chinese_text('hello world') == 'hello world'


def test_ros_text_json_and_repeated_utterances():
    rclpy.init()
    node = SpeechRecognizer()
    listener = rclpy.create_node('vosk_result_test')
    executor = SingleThreadedExecutor()
    executor.add_node(node)
    executor.add_node(listener)
    text, result, status = [], [], []
    subscriptions = [
        listener.create_subscription(String, 'speech/text', lambda msg: text.append(msg.data), 10),
        listener.create_subscription(String, 'speech/result', lambda msg: result.append(json.loads(msg.data)), 10),
    ]
    node.publish_partial = True
    try:
        deadline = time.monotonic() + 5
        while node.text_pub.get_subscription_count() == 0 or node.result_pub.get_subscription_count() == 0:
            assert time.monotonic() < deadline, 'DDS discovery timed out'
            executor.spin_once(timeout_sec=0.05)
        # Last status must reach subscribers that attach after it was published.
        node.status('listening')
        subscriptions.append(listener.create_subscription(
            String, 'speech/status', lambda msg: status.append(msg.data),
            QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL)))
        raw = json.dumps({'text': '你好 机器人', 'result': [{'word': '你好', 'conf': 0.9}]})
        node.final_result(raw)
        node.final_result('{"text": ""}')
        node.final_result(raw)
        deadline = time.monotonic() + 5
        while len(text) < 2 or len(result) < 2 or not status:
            assert time.monotonic() < deadline, 'ROS results were not delivered'
            executor.spin_once(timeout_sec=0.05)
        assert text == ['你好机器人', '你好机器人']
        assert result[0]['text'] == '你好 机器人'
        assert result[0]['result'][0]['conf'] == 0.9
        assert status[-1] == 'listening'
    finally:
        executor.shutdown()
        listener.destroy_node()
        node.destroy_node()
        rclpy.shutdown()
