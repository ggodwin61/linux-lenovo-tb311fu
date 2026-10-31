#!/usr/bin/env python3
"""Camera capture to multi-page PDF using the verified TB311FU backend."""
from datetime import datetime
from pathlib import Path
import runpy
import sys

from PyQt6.QtCore import QIODevice, QMarginsF, QSaveFile, QStandardPaths, Qt, QRectF
from PyQt6.QtGui import QImage, QPageSize, QPainter, QPdfWriter, QTransform
from PyQt6.QtWidgets import QApplication, QFileDialog, QHBoxLayout, QLabel, QMessageBox, QPushButton

CameraApp = runpy.run_path(str(Path(__file__).with_name('camera-app.py')))['CameraApp']


def export_pdf(pages, filename):
    if not pages or any(page.isNull() for page in pages):
        raise ValueError('Add a camera page before saving.')
    output = QSaveFile(str(filename))
    if not output.open(QIODevice.OpenModeFlag.WriteOnly):
        raise OSError(output.errorString())
    writer = QPdfWriter(output)
    writer.setTitle('Scanned document')
    writer.setCreator('TB311FU Document Scanner')
    writer.setResolution(150)
    writer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
    writer.setPageMargins(QMarginsF(10, 10, 10, 10))
    painter = QPainter(writer)
    if not painter.isActive():
        output.cancelWriting()
        raise OSError('Could not start PDF export.')
    try:
        for index, image in enumerate(pages):
            if index and not writer.newPage():
                raise OSError('Could not add a PDF page.')
            area = painter.viewport()
            size = image.size().scaled(area.size(), Qt.AspectRatioMode.KeepAspectRatio)
            target = QRectF(area.x() + (area.width() - size.width()) / 2,
                            area.y() + (area.height() - size.height()) / 2,
                            size.width(), size.height())
            painter.drawImage(target, image)
    except BaseException:
        painter.end()
        output.cancelWriting()
        raise
    painter.end()
    del painter
    del writer
    if not output.commit():
        raise OSError(output.errorString())


class ScannerApp(CameraApp):
    def __init__(self):
        self.pages = []
        super().__init__(camera=0)
        self.setWindowTitle('Document Scanner')
        self.shutter.setText('Add page')
        self.count = QLabel('0 pages')
        self.count.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.remove = QPushButton('Remove last')
        self.remove.setMinimumHeight(60)
        self.remove.clicked.connect(self.remove_page)
        self.save = QPushButton('Save PDF')
        self.save.setMinimumHeight(60)
        self.save.clicked.connect(self.save_pdf)
        row = QHBoxLayout()
        row.addWidget(self.remove)
        row.addWidget(self.save)
        self.layout().addWidget(self.count)
        self.layout().addLayout(row)
        if self.supported_cameras == [1]:
            notice = QLabel('Front camera only. Rear camera support is not available yet.')
            notice.setWordWrap(True)
            self.layout().insertWidget(0, notice)
        self.update_count()

    def take_photo(self):
        if not self.frame.isNull():
            self.pages.append(self.frame.transformed(QTransform().rotate(self.rotation)).copy())
            self.update_count()

    def update_count(self):
        count = len(self.pages)
        self.count.setText(f'{count} page' if count == 1 else f'{count} pages')
        self.save.setEnabled(count > 0)
        self.remove.setEnabled(count > 0)

    def remove_page(self):
        if self.pages:
            self.pages.pop()
            self.update_count()

    def save_pdf(self):
        directory = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation)) / 'Scans'
        directory.mkdir(parents=True, exist_ok=True)
        default = directory / (datetime.now().strftime('Scan-%Y%m%d-%H%M%S') + '.pdf')
        filename, _ = QFileDialog.getSaveFileName(self, 'Save scanned document', str(default), 'PDF documents (*.pdf)')
        if not filename:
            return
        if not filename.lower().endswith('.pdf'):
            filename += '.pdf'
        try:
            export_pdf(self.pages, filename)
        except (OSError, ValueError) as error:
            QMessageBox.warning(self, 'Could not save PDF', str(error))
            return
        QMessageBox.information(self, 'PDF saved', f'Saved {len(self.pages)} page(s) to:\n{filename}')


if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = ScannerApp()
    window.show()
    sys.exit(app.exec())
