from glob import glob

from setuptools import find_packages, setup

package_name = 'wp_speech'

setup(
    name=package_name,
    version='0.1.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml', 'requirements.txt', 'README.md']),
        ('share/' + package_name + '/launch', glob('launch/*.launch.py')),
        ('share/' + package_name + '/config', glob('config/*.yaml')),
        ('share/' + package_name + '/scripts', glob('scripts/*.sh')),
    ],
    install_requires=['setuptools', 'numpy', 'vosk==0.3.45', 'sherpa-onnx==1.13.8'],
    zip_safe=True,
    maintainer='robot',
    maintainer_email='zhangwanjie@126.com',
    description='Offline Chinese/English speech recognition and Melo text-to-speech',
    license='BSD-3-Clause',
    tests_require=['pytest'],
    entry_points={'console_scripts': [
        'recognizer = wp_speech.node:main',
        'download_model = wp_speech.download_model:main',
        'tts = wp_speech.tts:main',
        'speak = wp_speech.speak:main',
        'download_tts_model = wp_speech.download_tts_model:main',
    ]},
)
