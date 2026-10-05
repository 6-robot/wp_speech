from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue
from launch_ros.substitutions import FindPackageShare

from wp_speech.download_tts_model import DEFAULT_TTS_MODEL


def generate_launch_description():
    defaults = {
        'model_path': (DEFAULT_TTS_MODEL, str),
        'speed': ('1.0', float),
        'volume': ('1.0', float),
        'audio_backend': ('auto', str),
        'audio_device': ('', str),
        'playback': ('true', bool),
        'output_dir': ('', str),
    }
    return LaunchDescription([
        DeclareLaunchArgument('text_topic', default_value='/tts/text',
                              description='Text to speak (std_msgs/String)'),
        *[DeclareLaunchArgument(name, default_value=default) for name, (default, _) in defaults.items()],
        Node(
            package='wp_speech', executable='tts', name='speech_tts',
            output='screen', emulate_tty=True,
            parameters=[
                PathJoinSubstitution([FindPackageShare('wp_speech'), 'config', 'tts.yaml']),
                {name: ParameterValue(LaunchConfiguration(name), value_type=kind)
                 for name, (_, kind) in defaults.items()},
            ],
            remappings=[('tts/text', LaunchConfiguration('text_topic'))],
        ),
    ])
