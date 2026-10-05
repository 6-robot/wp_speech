# WP Speech · ROS2 离线语音

**中文 / 英文识别 · 中英文语音合成 · Kinect2 麦克风**

`wp_speech` 为 ROS2 机器人提供语音识别与文字朗读功能。识别使用 **Vosk**，合成使用 **sherpa-onnx + vits-melo-tts-zh_en**，通过 ROS2 字符串话题与其他节点对接。

适用环境：**Ubuntu 22.04 · ROS2 Humble · Python 3.10**。依赖和模型部署完成后，识别与合成可离线运行。

## 功能

| 功能 | 内容 |
| --- | --- |
| 语音识别 | 连续中文或英文识别，发布最终文字、中间文字及 JSON 结果 |
| Kinect2 麦克风 | ALSA 四通道采集，选择单个通道或取通道平均，支持软件增益 |
| 输入恢复 | 麦克风连接失败、断流或采集溢出后自动重试 |
| 文件识别 | 读取本地 16 kHz PCM WAV，便于离线验证 |
| 语音合成 | 订阅文字，按接收顺序合成中文、英文或中英文混读并播放 |
| 文字发送 | `speak` 程序接收命令行字符串，发送成功后退出 |
| 状态显示 | 发布识别与合成状态，终端以黄色文字显示最终识别结果及待朗读内容 |

## 安装部署

### 1. 放置源码

先安装 ROS2 Humble，将本软件包放到工作空间的 `src` 中。下面以 `~/ros2_ws` 为例；工作空间名称不同时，替换为实际路径。

```text
ros2_ws/
└── src/
    ├── wp_speech/
    └── wpb_home_ros2/   # 使用启智机器人时放在同一层
```

### 2. 安装依赖、下载模型并编译

以普通用户执行独立安装脚本；系统依赖安装时会请求 sudo 密码：

```bash
source /opt/ros/humble/setup.bash
cd ~/ros2_ws/src/wp_speech
bash scripts/install_for_humble.sh
```

脚本安装 ALSA、PulseAudio 播放工具、ROS2 与 Python 依赖，安装 `vosk==0.3.45`、`sherpa-onnx==1.13.8`，下载中英文识别模型及 TTS 模型。放在上述目录结构时，脚本会自动找到工作空间并编译 `wp_speech`。

使用机器人完整工程时，也可执行 `wpb_home_ros2/wpb_home_bringup/scripts/install_for_humble.sh`；其中已包含语音依赖与模型准备步骤。

修改软件包后，在工作空间根目录重新编译：

```bash
source /opt/ros/humble/setup.bash
cd ~/ros2_ws
colcon build --packages-select wp_speech
```

### 3. 加载环境

每个新终端使用节点前，先加载环境：

```bash
source /opt/ros/humble/setup.bash
source ~/ros2_ws/install/setup.bash
```

## 中英文语音识别

### 检查麦克风

在 Ubuntu“设置 → 声音 → 输入”中选择电脑麦克风或 Kinect2；使用 Kinect2 时接好电源与 USB 连接。检查系统录音设备：

```bash
arecord -l
```

默认设备为 `default`，通过系统音频服务读取 Ubuntu 中选择的输入设备。Kinect2 通常显示为 `Xbox NUI Sensor`；仅使用其麦克风时无需启动 `kinect2_bridge`，也无需安装 libfreenect2。切换系统输入后，重启识别节点以使用新设备。

### 启动识别

中文识别：

```bash
source ~/ros2_ws/install/setup.bash
ros2 launch wp_speech sr_cn.launch.py
```

英文识别：

```bash
source ~/ros2_ws/install/setup.bash
ros2 launch wp_speech sr_en.launch.py
```

按所需语言选择一个入口。出现 `Listening` 后开始说话，一句话结束后稍作停顿。默认采集 16 kHz、单通道、S16_LE 音频，最终文字在终端以黄色显示。

保持识别终端运行，新开终端查看结果：

```bash
source ~/ros2_ws/install/setup.bash
ros2 topic echo /speech/text std_msgs/msg/String
```

### 调整输入

启动文件支持以下参数；参数在启动时读取，修改后需重启节点。

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `device` | `default` | 系统默认录音设备，可在 Ubuntu 声音设置中选择输入 |
| `channel` | `0` | 默认单通道时使用 0；多通道输入可指定通道，-1 为通道平均 |
| `gain` | `1.0` | 正数的软件增益 |
| `model_path` | 所选语言的缓存目录 | 解压后的本地 Vosk 模型 |
| `wav_path` | 空 | 非空时读取 WAV，替代实时录音 |
| `text_topic` | `/speech/text` | 最终识别文字话题 |

例如提高输入增益：

```bash
source ~/ros2_ws/install/setup.bash
ros2 launch wp_speech sr_cn.launch.py gain:=2.0
```

录音通道数与位宽在 [config/kinect2.yaml](config/kinect2.yaml) 中设置，默认为单通道、`S16_LE`、16 kHz；系统音频服务完成通道与格式转换。直接使用 Kinect2 原始 ALSA 设备时，需改为 `channels: 4`、`sample_format: S32_LE`，重新编译，并在 launch 中指定 `device:=hw:CARD=Sensor,DEV=0`。16 kHz 采样率固定；支持 `S16_LE` 和 `S32_LE` 输入。

### 使用 WAV 验证

先停止占用同一麦克风的识别程序，再录制 10 秒音频：

```bash
arecord -D default -f S16_LE -r 16000 -c 1 -d 10 ~/speech_cn.wav
```

使用录音进行识别：

```bash
source ~/ros2_ws/install/setup.bash
ros2 launch wp_speech sr_cn.launch.py wav_path:=~/speech_cn.wav
```

输入为未压缩的 16 kHz、有符号 16 位或 32 位 PCM WAV。文件读完后发布最后的识别结果与 `finished` 状态，然后退出。

## 中英文语音合成

### 启动与朗读

先确认电脑扬声器及系统输出设备正常，启动 TTS：

```bash
source ~/ros2_ws/install/setup.bash
ros2 launch wp_speech tts.launch.py
```

出现 `TTS ready` 后，保持此终端运行，新开终端发送文字：

```bash
source ~/ros2_ws/install/setup.bash
ros2 run wp_speech speak '你好，我是六部工坊启智机器人。Hello, welcome.'
```

`speak` 默认等待订阅者最多 5 秒，发送成功后退出；可用 `--timeout 10` 延长等待。发送成功表示消息已送达，朗读完成由 `/tts/done` 通知。

其他 ROS2 程序可直接向 `/tts/text` 发布 `std_msgs/msg/String`。也可使用通用命令：

```bash
ros2 topic pub --once /tts/text std_msgs/msg/String "{data: '你好，欢迎使用启智机器人。'}"
```

保持 TTS 终端运行，新开已加载环境的终端查看完成通知：

```bash
ros2 topic echo /tts/done std_msgs/msg/String
```

### 调整输出

| 启动参数 | 默认值 | 说明 |
| --- | --- | --- |
| `text_topic` | `/tts/text` | 待朗读文字话题 |
| `model_path` | TTS 模型缓存目录 | 解压后的本地模型 |
| `speed` | `1.0` | 语速，正数，越大越快 |
| `volume` | `1.0` | 软件音量，范围 0～2 |
| `audio_backend` | `auto` | `auto`、`pulse` 或 `alsa` |
| `audio_device` | 空 | 输出设备名；空表示系统默认设备 |
| `playback` | `true` | 是否播放合成音频 |
| `output_dir` | 空 | 非空时保存生成的 WAV |

例如降低音量、加快语速：

```bash
source ~/ros2_ws/install/setup.bash
ros2 launch wp_speech tts.launch.py volume:=0.5 speed:=1.2
```

只合成并保存 WAV：

```bash
source ~/ros2_ws/install/setup.bash
ros2 launch wp_speech tts.launch.py playback:=false output_dir:=~/tts_audio
```

关闭播放时，`/tts/done` 表示合成和 WAV 保存成功。默认不保留音频文件，临时文件在任务完成后删除。生成的 WAV 为 44.1 kHz、16 位、单声道。

修改文字话题时，发送端使用相同名称：

```bash
# TTS 终端
source ~/ros2_ws/install/setup.bash
ros2 launch wp_speech tts.launch.py text_topic:=/txt
```

保持该终端运行，在新终端执行：

```bash
source ~/ros2_ws/install/setup.bash
ros2 run wp_speech speak '你好，欢迎使用六部工坊启智机器人。' --topic /txt
```

线程数、队列容量和文字长度上限在 [config/tts.yaml](config/tts.yaml) 中设置，默认为 2 个 CPU 线程、10 条等待任务、每条最多 500 个字符。修改后重新编译并重启。空白文字忽略；超长文字、含 NUL 的文字或队列满时的新任务会被拒绝。

## ROS2 话题接口

默认话题均为 `std_msgs/msg/String`。

| 话题 | 方向 | 内容 |
| --- | --- | --- |
| `/speech/text` | 发布 | 一句话的最终识别文字 |
| `/speech/partial` | 发布 | 中间识别文字，可能被后续结果修正 |
| `/speech/result` | 发布 | Vosk 结果 JSON，包含文字及词级信息 |
| `/speech/status` | 发布 | `loading`、`opening`、`listening`、`reconnecting`、`finished`、`error` |
| `/tts/text` | 订阅 | 待朗读文字 |
| `/tts/status` | 发布 | `loading`、`idle`、`synthesizing`、`playing`、`error` |
| `/tts/done` | 发布 | 本次成功完成的原始文字，去除首尾空白 |

状态话题使用 reliable、transient local、深度 1；其他话题使用 reliable、深度 10。查看最近状态：

```bash
ros2 topic echo /speech/status std_msgs/msg/String --qos-durability transient_local
```

语音识别和合成独立运行。需要将识别结果用于对话或机器人控制时，由应用节点订阅 `/speech/text`，处理后向 `/tts/text` 或相应控制接口发布消息。

## 模型与离线使用

| 用途 | 默认模型目录 |
| --- | --- |
| 中文识别 | `~/.cache/vosk/vosk-model-small-cn-0.22` |
| 英文识别 | `~/.cache/vosk/vosk-model-small-en-us-0.15` |
| 中英文合成 | `~/.cache/sherpa-onnx/vits-melo-tts-zh_en` |

**启动 launch 只读取本地模型，不会自动下载。** 首次安装需要网络；已有完整模型会直接复用。模型存放在执行安装脚本的用户缓存中，部署与运行应使用同一用户，或通过 `model_path` 指定实际目录。

下载失败时，安装依赖并编译软件包后可单独重试：

```bash
source ~/ros2_ws/install/setup.bash
ros2 run wp_speech download_model --language all
ros2 run wp_speech download_tts_model
```

`download_model` 还支持 `--language cn` 或 `--language en`。下载工具支持 `--model-dir /绝对路径` 指定单个模型的目标目录。模型和测试录音无需放入源码仓库。

## 常见问题

| 现象 | 检查方法 |
| --- | --- |
| 找不到 Kinect2 麦克风 | 用 `arecord -l` 检查设备，确认 Kinect2 电源、USB 连接及 ALSA 设备名称 |
| `Device or resource busy` | 结束占用该录音设备的程序；中文和英文入口选一个运行 |
| 正在监听，但识别不准确 | 检查录音音量与噪声，确认系统输入选择正确并适当提高 gain；多通道输入可尝试其他通道，增益过高会削波 |
| 模型缺失或不完整 | 确认 model_path 指向解压后的模型目录，并检查下载日志 |
| 发送文字提示没有订阅者 | 先启动 TTS，等待 `TTS ready`，确认发送与订阅话题相同 |
| 合成正常，但扬声器没有声音 | 检查电源、系统音量、输出设备及 playback；用 `pactl list short sinks` 或 `aplay -l` 查看输出设备 |

按 Ctrl+C 停止节点：识别节点回收录音子进程；TTS 停止播放并丢弃等待任务，正在执行的推理在计算完成后响应退出。

Kinect2 用于录音，朗读声音从电脑音频输出设备播放。本包采用通道选择或算术平均，不提供波束成形、回声消除、唤醒词或声源定位。

## 软件包结构

```text
wp_speech/
├── launch/                 # 中文、英文识别和 TTS 启动入口
├── config/                 # 麦克风与 TTS 默认配置
├── scripts/                # Humble 依赖安装、模型下载与构建
├── wp_speech/
│   ├── node.py             # Vosk 识别节点
│   ├── audio.py            # ALSA 采集与 PCM 转换
│   ├── tts.py              # 合成队列与音频播放
│   ├── speak.py            # 命令行文字发送节点
│   ├── download_model.py   # Vosk 模型下载
│   └── download_tts_model.py
└── test/                   # 音频、识别接口和 TTS 测试
```
