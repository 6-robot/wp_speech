#!/usr/bin/env bash
set -euo pipefail

sudo apt-get update
sudo apt-get install -y alsa-utils pulseaudio-utils python3-numpy python3-pip python3-pytest
sudo apt-get install -y python3-colcon-common-extensions \
  ros-humble-rclpy ros-humble-std-msgs ros-humble-launch-ros \
  ros-humble-ament-index-python ros-humble-ros2run ros-humble-ros2launch
python3 -m pip install --user 'vosk==0.3.45' 'sherpa-onnx==1.13.8'

# Works both from the source tree and the installed package share directory.
script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if [[ -f "$script_dir/../wp_speech/download_model.py" ]]; then
  python3 "$script_dir/../wp_speech/download_model.py" --language all
  python3 "$script_dir/../wp_speech/download_tts_model.py"
else
  python3 -m wp_speech.download_model --language all
  python3 -m wp_speech.download_tts_model
fi

# Build the speech executables (recognizer, tts, speak and model downloaders).
workspace_dir="$script_dir"
while [[ "$workspace_dir" != / && ! -f "$workspace_dir/src/wp_speech/package.xml" ]]; do
  workspace_dir="$(dirname -- "$workspace_dir")"
done
if [[ "$workspace_dir" != / ]]; then
  # ROS environment scripts may reference unset variables.
  set +u
  source /opt/ros/humble/setup.bash
  set -u
  (cd -- "$workspace_dir" && colcon build --packages-select wp_speech)
  printf '部署完成。请在使用终端执行：\nsource "%s/install/setup.bash"\n' "$workspace_dir"
else
  printf '依赖和模型已安装；未找到源码工作空间，请在工作空间编译 wp_speech。\n'
fi
