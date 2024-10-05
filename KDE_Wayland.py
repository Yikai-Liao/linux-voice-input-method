from PyQt6.QtWidgets import QApplication, QWidget, QPushButton, QTextEdit
from PyQt6.QtGui import QMouseEvent, QIcon
from PyQt6.QtCore import QProcess, Qt, QEvent, QTimer, pyqtSignal, QPointF
from funasr_onnx import Paraformer, CT_Transformer
import keyboard
import threading
from opencc import OpenCC
import sounddevice as sd
import numpy as np
import soundfile as sf
import subprocess
import time
import  pyperclip

def simulate_keyboard_input(text):
    for char in text:
        subprocess.run(['xdotool', 'type', char])

class MyButton(QPushButton):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.isPressed = False
        self.pressed.connect(self.change_color)
        self.released.connect(self.restore_color)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def change_color(self):
        self.setStyleSheet("background-color: rgba(90, 133, 15, 0.8);")  # Change to red when pressed

    def restore_color(self):
        if self.underMouse():
            self.setStyleSheet("background-color: rgba(100, 145, 40, 1);")  # Change to hover color if mouse is still over the button
        else:
            self.setStyleSheet("background-color: rgba(90, 133, 15, 1);")  # Restore to original color when released

    def enterEvent(self, event):
        self.setStyleSheet("background-color: rgba(100, 145, 40, 1);")  # Change to blue when mouse enters

    def leaveEvent(self, event):
        self.restore_color()  # Restore to original color when mouse leaves

    def simulatePress(self):
        if not self.isPressed:
            pressEvent = QMouseEvent(QEvent.Type.MouseButtonPress, QPointF(self.rect().center()), Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
            QApplication.postEvent(self, pressEvent)
            self.isPressed = True

    def simulateRelease(self):
        if self.isPressed:
            releaseEvent = QMouseEvent(QEvent.Type.MouseButtonRelease, QPointF(self.rect().center()), Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
            QApplication.postEvent(self, releaseEvent)
            self.isPressed = False

class MyWindow(QWidget):
    # Define a signal
    transcription_ready = pyqtSignal(str)
    text_ready = pyqtSignal(str)  # Define a new signal
    def __init__(self):
        super().__init__()

        # 设置窗口的透明度
        self.setWindowOpacity(0.8)

        # 设置全局热键
        # self.global_hotkey = keyboard.Key.scroll_lock

        # Connect the signal to a slot
        self.transcription_ready.connect(self.update_transcription)

        # Connect the signal to a slot
        self.text_ready.connect(self.update_text)

        # 窗口置顶
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)

        # 设置窗口图标
        self.setWindowIcon(QIcon('./icon.png'))

        # 设置窗口的标题
        self.setWindowTitle('RTX-IM')

        # 设置窗口的大小
        self.resize(200, 100)

        # 在窗口中间添加一个按钮，大小是窗口宽度的一半
        self.button = MyButton(self)
        self.button.setText("长按输入")
        self.button.resize(self.width() // 2, 32)

        # 添加一个新的按钮，位置在窗口宽度的一半，大小也是窗口宽度的一半
        self.convertButton = MyButton(self)
        self.convertButton.setText("繁简转换")
        self.convertButton.resize(self.width() // 2, 32)
        self.convertButton.move(self.width() // 2, int(self.height() - self.convertButton.height()))
        self.convertButton.released.connect(self.convertText)


        # 添加一个文本编辑框
        self.textEdit = QTextEdit(self)
        self.textEdit.move(0, 0)
        self.textEdit.resize(self.width(), self.height() - self.button.height())

        # # 设置文本编辑框的背景颜色为半透明的黑色，文本颜色为白色
        # self.textEdit.setStyleSheet("background-color: rgba(0, 0, 0, 128); color: white;")

        # 使按钮居中
        self.button.move(int((self.width() - self.button.width()) / 2), int(self.height() - self.button.height()))

        # 创建一个进程对象用于录音
        self.recorder = QProcess()

        # 初始化模型
        # model_dir = "./speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-pytorch"
        self.model = Paraformer('/home/lyk/.cache/modelscope/hub/iic/speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-pytorch', batch_size=1, quantize=True)
        self.ct_model = CT_Transformer('/home/lyk/.cache/modelscope/hub/iic/punc_ct-transformer_cn-en-common-vocab471067-large', batch_size=1, quantize=True)

        # 预热模型，避免第一次推理时的延迟
        self.model(['./warmup.wav'])
        self.ct_model("你好")

        # 当按钮被按下时开始录音
        self.button.pressed.connect(self.startRecording)
        self.button.released.connect(self.stopRecording)

        # Setup global hotkey
        self.setup_hotkey()

        self.timer = QTimer()
        self.timer.timeout.connect(self.simulatePress)

        # Initialize dragPosition attribute
        self.dragPosition = None

        # Initialize a lock for the convertTextThread
        self.convert_lock = threading.Lock()

        # 添加一个定时器
        self.timer = QTimer()
        self.timer.timeout.connect(self.simulatePress)

        # Initialize OpenCC
        self.cc_s2t = OpenCC('s2twp')
        self.cc_t2s = OpenCC('t2s')

        # 打开并读取文件
        with open('library.txt', 'r', encoding='utf-8') as f:
            library_text = f.read()

        # 将读取的内容转换为一个集合
        self.traditional_chars = set(library_text)

    def convertText(self):
        # 创建一个新的线程来处理转换操作
        thread = threading.Thread(target=self.convertTextThread)
        thread.start()

    def convertTextThread(self):
        # Acquire the lock before starting the conversion
        self.convert_lock.acquire()
        try:
            text = self.textEdit.toPlainText()
            if any(char in self.traditional_chars for char in text):
                converted = self.cc_t2s.convert(text)
            else:
                converted = self.cc_s2t.convert(text)
            self.text_ready.emit(converted)  # Emit the signal with the converted text

            # 将转换后的文本复制到剪贴板
            # clipboard = QApplication.clipboard()
            # clipboard.setText(converted)
            pyperclip.copy(converted)
            print("Text converted")
        finally:
            # Release the lock after the conversion is done
            self.convert_lock.release()

    def update_text(self, text):
        self.textEdit.setText(text)  # Update the textEdit in the main thread

    def setup_hotkey(self):
        def on_press(key):
            try:
                if not self.button.isPressed:  # Use the global_hotkey variable here
                    print('Key pressed: {0}'.format(key))
                    self.button.simulatePress()  # 按下Scroll Lock时模拟鼠标按下事件
            except AttributeError:
                pass

        def on_release(key):
            if self.button.isPressed:  # Use the global_hotkey variable here
                print('Key released: {0}'.format(key))
                self.button.simulateRelease()  # 释放Scroll Lock时模拟鼠标释放事件

        keyboard.on_press_key("scroll_lock", on_press)
        keyboard.on_release_key("scroll_lock", on_release)
        # 设置录音的参数
        self.fs = 44100  # Sample rate
        self.channels = 2  # Number of channels

        # 创建一个用于存储录音数据的列表
        self.myrecording = []

        # 创建一个录音流
        self.stream = sd.InputStream(samplerate=self.fs, channels=self.channels, callback=self.audio_callback)
        # 创建一个用于存储录音数据的列表
        self.myrecording = []
        # 添加一个状态变量，表示是否正在录音
        self.isRecording = False
        # 开始录音
        self.stream.start()
        print("Recording started...")

    def startRecording(self):
        # 清空录音数据
        self.myrecording = []
        self.isRecording = True  # 开始录音，改变状态变量的值

    def stopRecording(self):
        self.isRecording = False  # 录音结束，改变状态变量的值
        # 将录音数据写入文件
        myrecording_np = np.array(self.myrecording)
        sf.write('audio.wav', myrecording_np, self.fs)
        # 开始转录音频
        self.transcribe_audio()

    def audio_callback(self, indata, frames, time, status):
        # 如果正在录音，就将录音数据添加到列表中
        if self.isRecording:
            self.myrecording.extend(indata.tolist())

    def simulatePress(self):
        if not self.button.isPressed and not self.isRecording:  # 在模拟鼠标按下事件时，检查是否正在录音
            self.button.simulatePress()

    def simulateRelease(self):
        if self.button.isPressed and not self.isRecording:  # 在模拟鼠标释放事件时，检查是否正在录音
            self.button.simulateRelease()

    def transcribe_audio(self):
        # 创建一个新的线程来执行转录的任务
        thread = threading.Thread(target=self.transcribe_audio_thread)
        thread.start()

    def transcribe_audio_thread(self):
        wav_path = ['./audio.wav']
        start1 = time.time()
        result = self.model(wav_path)
        dur1 = time.time() - start1
        print("Transcription: ", result)
        if result and 'preds' in result[0]:
            transcription = result[0]['preds'][0]
            start2 = time.time()
            transcription = self.ct_model(transcription)[0]
            dur2 = time.time() - start2
            print("Cost time in ms: ", dur1 * 1000, dur2 * 1000)
            # Emit the signal with the transcription
            self.transcription_ready.emit(transcription)

    def update_transcription(self, transcription):
        self.textEdit.setText(transcription)
        # 将文本复制到剪贴板
        pyperclip.copy(transcription)        
        # 模拟按下Ctrl+V
        keyboard.press('ctrl')
        keyboard.press('v')
        time.sleep(0.01)
        keyboard.release('v')
        keyboard.release('ctrl')

        simulate_keyboard_input(transcription)

    # 让窗口可以拖拽
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.dragPosition = event.globalPos() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if self.dragPosition is not None:
            self.move(event.globalPos() - self.dragPosition)
            event.accept()

    # 让布局自适应大小
    def resizeEvent(self, event):
        # 让文本编辑框的大小自适应窗口大小
        self.textEdit.resize(self.width(), self.height() - self.button.height())
        # 让两个按钮的宽度自适应窗口大小，高度保持不变
        self.button.resize(self.width() // 2, self.button.height())
        self.convertButton.resize(self.width() // 2, self.convertButton.height())
        # 让输入按钮靠左，转换按钮靠右
        self.button.move(0, int(self.height() - self.button.height()))
        self.convertButton.move(self.width() // 2, int(self.height() - self.convertButton.height()))

if __name__ == "__main__":
    app = QApplication([])
    window = MyWindow()
    window.show()

    # Load and apply the stylesheet
    with open('style.css', 'r') as f:
        app.setStyleSheet(f.read())

    app.exec()