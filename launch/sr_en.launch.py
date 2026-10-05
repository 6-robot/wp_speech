from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue
from launch_ros.substitutions import FindPackageShare

from wp_speech.download_model import DEFAULT_MODELS


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument('model_path', default_value=DEFAULT_MODELS['en'],
                              description='Local unpacked English Vosk model'),
        DeclareLaunchArgument('device', default_value='default',
                              description='ALSA input; default follows the system input selection'),
        DeclareLaunchArgument('channel', default_value='0',
                              description='Microphone index 0..3; -1 averages channels'),
        DeclareLaunchArgument('gain', default_value='1.0',
                              description='Positive audio gain before conversion to 16-bit PCM'),
        DeclareLaunchArgument('wav_path', default_value='',
                              description='Optional local 16 kHz PCM WAV, replacing live capture'),
        DeclareLaunchArgument('text_topic', default_value='/speech/text',
                              description='Topic for final recognized text (std_msgs/String)'),
        Node(
            package='wp_speech', executable='recognizer', name='vosk_recognizer',
            output='screen', emulate_tty=True,
            parameters=[
                PathJoinSubstitution([FindPackageShare('wp_speech'), 'config', 'kinect2.yaml']),
                {
                    'model_path': ParameterValue(LaunchConfiguration('model_path'), value_type=str),
                    'device': ParameterValue(LaunchConfiguration('device'), value_type=str),
                    'channel': ParameterValue(LaunchConfiguration('channel'), value_type=int),
                    'gain': ParameterValue(LaunchConfiguration('gain'), value_type=float),
                    'wav_path': ParameterValue(LaunchConfiguration('wav_path'), value_type=str),
                },
            ],
            remappings=[('speech/text', LaunchConfiguration('text_topic'))],
        ),
    ])
