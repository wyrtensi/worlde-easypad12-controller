import sys
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QApplication
from PySide6.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve, QPoint
from PySide6.QtGui import QPainter, QPainterPath
import os
import json
import logging
from app.utils import setup_logging, ensure_app_directories
logger = setup_logging()

class NotificationWindow(QWidget):
    def __init__(self, message, theme='dark', position='bottom-right', size=(300, 100), font_size=12):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.message = message
        self.theme = theme
        self.position = position
        self.size = size
        self.font_size = font_size  # Store font size
        self.initUI()
        self.set_theme()
        self.set_position()
        self.animation = QPropertyAnimation(self, b"windowOpacity")
        self.animation.setDuration(500)
        self.animation.setStartValue(0.0)
        self.animation.setEndValue(1.0)
        self.animation.setEasingCurve(QEasingCurve.InOutQuad)
        self.animation.start()

    def initUI(self):
        layout = QVBoxLayout(self)
        self.label = QLabel(self.message)
        self.label.setAlignment(Qt.AlignCenter)
        # Apply font size to the label
        font = self.label.font()
        font.setPointSize(self.font_size)
        self.label.setFont(font)
        layout.addWidget(self.label)
        self.setFixedSize(*self.size)

    def set_theme(self):
        if self.theme == 'dark':
            self.setStyleSheet("""
                background-color: #333;
                color: white;
                border-radius: 10px;
            """)
        else:
            self.setStyleSheet("""
                background-color: #f0f0f0;
                color: black;
                border-radius: 10px;
            """)

    def set_position(self):
        screen = QApplication.primaryScreen().geometry()
        if self.position == 'bottom-right':
            x = screen.width() - self.width() - 10
            y = screen.height() - self.height() - 10
        elif self.position == 'top-right':
            x = screen.width() - self.width() - 10
            y = 10
        elif self.position == 'bottom-left':
            x = 10
            y = screen.height() - self.height() - 10
        else:  # top-left
            x = 10
            y = 10
        self.move(x, y)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(self.rect(), 10, 10)
        painter.fillPath(path, self.palette().window())

    def showEvent(self, event):
        QTimer.singleShot(5000, self.close_animation)

    def close_animation(self):
        self.animation.setStartValue(1.0)
        self.animation.setEndValue(0.0)
        self.animation.finished.connect(self.close)
        self.animation.start()

class NotificationManager:
    def __init__(self):
        # Get the config directory and set the settings file path
        config_dir, _ = ensure_app_directories()
        self.settings_file = os.path.join(config_dir, "notification_settings.json")
        # Default settings
        self.settings = {
            "music_track": True,
            "volume_adjustment": True,
            "device_change": True,
            "speech_to_text": True,
            "button_action": True,
            "input_device_changed": True,
            "playback_device_changed": True,
            "input_device_disconnected": True,
            "playback_device_disconnected": True,
            "input_device_selected": True,
            'theme': 'dark',
            'position': 'bottom-right',
            'size': (300, 100),
            'font_size': 12  # Added default font size
        }
        # Load settings from file if it exists
        if os.path.exists(self.settings_file):
            try:
                with open(self.settings_file, 'r') as f:
                    loaded_settings = json.load(f)
                    self.settings.update(loaded_settings)
            except Exception as e:
                logger.error(f"Failed to load notification settings: {e}")
        self.notifications = []

    def show_notification(self, message, notification_type):
        if self.settings.get(notification_type, True):
            notification = NotificationWindow(
                message,
                theme=self.settings['theme'],
                position=self.settings['position'],
                size=self.settings['size'],
                font_size=self.settings['font_size']  # Pass font size
            )
            notification.show()
            self.notifications.append(notification)

    def update_settings(self, settings):
        self.settings.update(settings)
        # Save settings to file
        try:
            with open(self.settings_file, 'w') as f:
                json.dump(self.settings, f, indent=4)
        except Exception as e:
            logger.error(f"Failed to save notification settings: {e}")