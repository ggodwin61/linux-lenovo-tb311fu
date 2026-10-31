#!/usr/bin/env python3
"""Touch camera viewer for the TB311FU vendor capture backend."""
from datetime import datetime
from pathlib import Path
import json
import struct
import sys

from PyQt6.QtCore import QProcess, QStandardPaths, Qt, QTimer
from PyQt6.QtGui import QImage, QPixmap, QTransform
from PyQt6.QtWidgets import QApplication, QLabel, QPushButton, QVBoxLayout, QHBoxLayout, QWidget


class CameraApp(QWidget):
    def __init__(self, camera=0):
        super().__init__()
        self.setWindowTitle('Camera')
        self.resize(600, 900)
        self.camera = camera
        self.rotations = {0: 90, 1: 270}
        self.rotation = self.rotations[camera]
        self.frame = QImage()
        self.frame_count = 0
        self.pending = bytearray()
        self.restart = False
        self.closing = False
        self.last_error = ''
        self.supported_cameras = [0, 1]
        config = Path('/etc/tb311fu-camera.json')
        if config.exists():
            self.supported_cameras = json.loads(config.read_text()).get('supported_cameras', [1])
        self.process = QProcess(self)
        self.process.readyReadStandardOutput.connect(self.receive)
        self.process.readyReadStandardError.connect(self.diagnostics)
        self.process.finished.connect(self.finished)
        self.status = QLabel('Starting camera...')
        self.status.setWordWrap(True)
        self.status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.view = QLabel()
        self.view.setMinimumSize(200, 300)
        self.view.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.switch = QPushButton('Switch camera')
        self.switch.clicked.connect(self.change_camera)
        self.switch.setEnabled(len(self.supported_cameras) > 1)
        if len(self.supported_cameras) == 1:
            self.switch.setToolTip('The rear camera is not supported by this Linux port yet.')
        self.shutter = QPushButton('Take photo')
        self.shutter.clicked.connect(self.take_photo)
        self.shutter.setEnabled(False)
        rotate = QPushButton('Rotate')
        rotate.clicked.connect(self.rotate)
        controls = QHBoxLayout()
        for button in (self.switch, self.shutter, rotate):
            button.setMinimumHeight(70)
            controls.addWidget(button)
        layout = QVBoxLayout(self)
        layout.addWidget(self.status)
        layout.addWidget(self.view, 1)
        layout.addLayout(controls)
        self.setStyleSheet('QWidget{background:#111;color:#eee;font-size:20px} '
                          'QPushButton{background:#303030;border-radius:12px;padding:14px} '
                          'QPushButton:pressed{background:#4e9a32} '
                          'QPushButton:disabled{color:#777}')
        self.log = Path.home() / '.cache/tb311fu-camera.log'
        self.log.parent.mkdir(parents=True, exist_ok=True)
        self.log.write_text('')
        QTimer.singleShot(0, self.start)

    def start(self):
        self.pending.clear()
        self.frame = QImage()
        self.frame_count = 0
        self.view.clear()
        self.shutter.setEnabled(False)
        self.last_error = ''
        self.status.setText('Starting front camera...' if self.camera else 'Starting rear camera...')
        self.process.start('sudo', ['-n', '/usr/bin/python3', '-I',
                                   '/usr/local/libexec/tb311fu-camera/camera-frame.py',
                                   '--camera', str(self.camera), '--preview'])

    def diagnostics(self):
        data = bytes(self.process.readAllStandardError())
        self.last_error = (self.last_error + data.decode(errors='replace'))[-8192:]
        with self.log.open('ab') as out:
            out.write(data)

    def receive(self):
        data = bytes(self.process.readAllStandardOutput())
        if self.restart or self.closing:
            return
        self.pending.extend(data)
        newest = None
        while len(self.pending) >= 4:
            length = struct.unpack_from('I', self.pending)[0]
            if not 0 < length < 8 * 1024 * 1024:
                self.status.setText('Camera communication failed')
                self.process.terminate()
                self.pending.clear()
                return
            if len(self.pending) < length + 4:
                break
            newest = bytes(self.pending[4:4+length])
            del self.pending[:4+length]
        if newest:
            image = QImage.fromData(newest, 'PPM')
            if not image.isNull():
                self.frame = image
                self.frame_count += 1
                self.render()
                self.shutter.setEnabled(True)
                self.status.setText('Front camera' if self.camera else 'Rear camera')

    def render(self):
        if not self.frame.isNull():
            image = self.frame.transformed(QTransform().rotate(self.rotation))
            if self.camera:
                image = image.mirrored(True, False)
            self.view.setPixmap(QPixmap.fromImage(image).scaled(
                self.view.size(), Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation))

    def rotate(self):
        self.rotation = (self.rotation + 90) % 360
        self.rotations[self.camera] = self.rotation
        self.render()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.render()

    def change_camera(self):
        if self.restart or self.closing:
            return
        self.camera = 1 - self.camera
        self.rotation = self.rotations[self.camera]
        self.restart = True
        self.pending.clear()
        self.frame = QImage()
        self.frame_count = 0
        self.view.clear()
        self.shutter.setEnabled(False)
        self.status.setText('Switching camera...')
        self.switch.setEnabled(False)
        self.process.terminate()
        if self.process.state() == QProcess.ProcessState.NotRunning:
            self.finished()

    def finished(self, *args):
        self.diagnostics()
        if self.closing:
            self.close()
        elif self.restart:
            self.restart = False
            self.switch.setEnabled(True)
            self.start()
        else:
            self.shutter.setEnabled(False)
            self.status.setText(self.failure_message())

    def failure_message(self):
        if 'Not enough free memory' in self.last_error or 'Cannot allocate memory' in self.last_error:
            return 'Not enough free memory. Close other apps, then reopen the camera.'
        if 'Unverified' in self.last_error:
            return 'The installed camera drivers are not supported by this app.'
        if any(text in self.last_error for text in ('This profile needs', 'Unexpected sensor ID',
                                                  'Unsupported camera driver index')):
            return 'This camera sensor is not supported yet. Try the other camera.'
        if 'password is required' in self.last_error or 'not allowed' in self.last_error:
            return 'Camera access has not been configured.'
        if 'Resource temporarily unavailable' in self.last_error:
            return 'Camera is already in use. Close the other camera app first.'
        return 'Camera stopped. Close and reopen this app to try again.'

    def take_photo(self):
        if self.frame.isNull():
            return
        directory = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.PicturesLocation)) / 'Camera'
        directory.mkdir(parents=True, exist_ok=True)
        filename = directory / (datetime.now().strftime('%Y%m%d-%H%M%S-%f') + '.jpg')
        image = self.frame.transformed(QTransform().rotate(self.rotation))
        if image.save(str(filename), 'JPEG', 95):
            self.status.setText(f'Photo saved: {filename.name}')
            return filename

    def closeEvent(self, event):
        if self.process.state() != QProcess.ProcessState.NotRunning:
            stopping = self.closing or self.restart
            self.closing = True
            self.restart = False
            if not stopping:
                self.process.terminate()
            event.ignore()
        else:
            event.accept()


if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = CameraApp()
    window.show()
    sys.exit(app.exec())
