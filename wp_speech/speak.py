"""Send one text message to the speech synthesis node."""

import argparse
import math
import sys
import time

import rclpy
from rclpy.duration import Duration
from rclpy.utilities import remove_ros_args
from std_msgs.msg import String


def main(args=None):
    argv = sys.argv if args is None else ['speak', *args]
    parser = argparse.ArgumentParser(description='发送文字给 TTS 节点朗读')
    parser.add_argument('text', help='要朗读的文字，包含空格时请使用引号')
    parser.add_argument('--topic', default='/tts/text', help='文字话题（默认 /tts/text）')
    parser.add_argument('--timeout', type=float, default=5.0,
                        help='等待订阅者及发送确认的超时秒数（默认 5）')
    options = parser.parse_args(remove_ros_args(args=argv)[1:])
    if not options.text.strip() or '\x00' in options.text:
        parser.error('文字不能为空或包含 NUL 字符')
    if not math.isfinite(options.timeout) or options.timeout <= 0:
        parser.error('--timeout 必须是有限的正数')

    node = None
    try:
        rclpy.init(args=argv)
        node = rclpy.create_node('speech_speak')
        publisher = node.create_publisher(String, options.topic, 10)
        deadline = time.monotonic() + options.timeout
        while publisher.get_subscription_count() == 0:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                node.get_logger().error(
                    f'话题 {publisher.topic_name} 没有订阅者，请先启动 TTS 节点。')
                return 1
            rclpy.spin_once(node, timeout_sec=min(0.05, remaining))

        publisher.publish(String(data=options.text))
        if not publisher.wait_for_all_acked(Duration(seconds=options.timeout)):
            node.get_logger().error('发送确认超时，消息可能已送达。')
            return 1
        node.get_logger().info(f'已发送到 {publisher.topic_name}: {options.text}')
        return 0
    except KeyboardInterrupt:
        return 130
    finally:
        if node is not None:
            node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    sys.exit(main())
