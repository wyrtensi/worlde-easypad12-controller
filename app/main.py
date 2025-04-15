import sys
import os
import threading
import asyncio
import time
from PIL import Image, ImageDraw
import json
import platform
import traceback
import logging
from PySide6 import QtWidgets, QtGui
from PySide6.QtWidgets import QFontComboBox
import PySide6.QtCore as QtCore
from PySide6.QtCore import Qt, QTimer, QThread, Signal, QModelIndex
import speech_recognition as sr
import pyautogui
import pyperclip
import pyaudio
import winrt.windows.foundation
import winrt.windows.media.control as wmc
from qasync import asyncSlot
import openai
from io import BytesIO
import tempfile
from pydub import AudioSegment
from app.midi_controller import MIDIController
from app.system_actions import SystemActions
from app.notifications import NotificationManager, NotificationWindow
from app.utils import setup_logging, get_dark_theme, load_midi_mapping, get_media_controls, load_button_config, get_action_types, save_button_config
import wave
import keyboard
import subprocess
import ctypes

# Import WebOS TV Manager if available
try:
    from app.webos_tv import webos_manager
    WEBOS_AVAILABLE = True
except ImportError:
    WEBOS_AVAILABLE = False

# Try to import win32clipboard for direct clipboard access
try:
    import win32clipboard
    import win32con
    from ctypes import Structure, c_ulong, c_ushort, POINTER, sizeof, byref
    WIN32CLIPBOARD_AVAILABLE = True
except ImportError:
    WIN32CLIPBOARD_AVAILABLE = False

# Set up logging
logger = setup_logging()

# Define app colors from theme
theme = get_dark_theme()
DARK_BG = theme["dark_bg"]
PRIMARY_COLOR = theme["primary_color"]
SECONDARY_COLOR = theme["secondary_color"]
BUTTON_ACTIVE_COLOR = theme["button_active_color"]
HIGHLIGHT_COLOR = theme["highlight_color"]
TEXT_COLOR = theme["text_color"]
CONFIGURED_BUTTON_COLOR = "#3D5A80"  # New color for buttons with saved configurations
DISABLED_COLOR = "#555555"
BORDER_RADIUS = "8px"
SHADOW_STYLE = "0px 3px 6px rgba(0, 0, 0, 0.3)"  # We'll define this but not use it as box-shadow

# Modern button style for normal buttons
BUTTON_STYLE = f"""
    QPushButton {{
        background-color: #333333;
        color: {TEXT_COLOR};
        border: none;
        border-radius: {BORDER_RADIUS};
        padding: 8px;
        font-weight: normal;
        text-align: center;
    }}
    QPushButton:hover {{
        background-color: #444444;
        border: 1px solid {HIGHLIGHT_COLOR};
    }}
    QPushButton:pressed {{
        background-color: {PRIMARY_COLOR};
        color: white;
    }}
"""

# Style for buttons with configurations
CONFIGURED_BUTTON_STYLE = f"""
    QPushButton {{
        background-color: {CONFIGURED_BUTTON_COLOR};
        color: {TEXT_COLOR};
        border: none;
        border-radius: {BORDER_RADIUS};
        padding: 8px;
        font-weight: normal;
        text-align: center;
    }}
    QPushButton:hover {{
        background-color: #4D6A90;
        border: 1px solid {HIGHLIGHT_COLOR};
    }}
    QPushButton:pressed {{
        background-color: {PRIMARY_COLOR};
        color: white;
    }}
"""

# Style for pad buttons
PAD_BUTTON_STYLE = f"""
    QPushButton {{
        background-color: #2A2A2A;
        color: {TEXT_COLOR};
        border: none;
        border-radius: {BORDER_RADIUS};
        padding: 10px;
        font-weight: normal;
        text-align: center;
    }}
    QPushButton:hover {{
        background-color: #3A3A3A;
        border: 1px solid {HIGHLIGHT_COLOR};
    }}
    QPushButton:pressed {{
        background-color: {PRIMARY_COLOR};
        color: white;
    }}
"""

# Style for configured pad buttons
CONFIGURED_PAD_BUTTON_STYLE = f"""
    QPushButton {{
        background-color: {CONFIGURED_BUTTON_COLOR};
        color: {TEXT_COLOR};
        border: none;
        border-radius: {BORDER_RADIUS};
        padding: 10px;
        font-weight: normal;
        text-align: center;
    }}
    QPushButton:hover {{
        background-color: #4D6A90;
        border: 1px solid {HIGHLIGHT_COLOR};
    }}
    QPushButton:pressed {{
        background-color: {PRIMARY_COLOR};
        color: white;
    }}
"""

# Action button style (connect, settings, etc.)
ACTION_BUTTON_STYLE = f"""
    QPushButton {{
        background-color: {PRIMARY_COLOR};
        color: {TEXT_COLOR};
        border: none;
        border-radius: {BORDER_RADIUS};
        padding: 8px 16px;
        font-weight: normal;
    }}
    QPushButton:hover {{
        background-color: {BUTTON_ACTIVE_COLOR};
        border: 1px solid {HIGHLIGHT_COLOR};
    }}
    QPushButton:pressed {{
        background-color: {SECONDARY_COLOR};
    }}
"""

# QComboBox modern style
COMBOBOX_STYLE = f"""
    QComboBox {{
        background-color: #333333;
        color: {TEXT_COLOR};
        border: 1px solid #555555;
        border-radius: {BORDER_RADIUS};
        padding: 5px;
        min-width: 6em;
    }}
    QComboBox:hover {{
        border: 1px solid {HIGHLIGHT_COLOR};
    }}
    QComboBox::drop-down {{
        subcontrol-origin: padding;
        subcontrol-position: top right;
        width: 20px;
        border-left: 1px solid #555555;
        border-top-right-radius: {BORDER_RADIUS};
        border-bottom-right-radius: {BORDER_RADIUS};
    }}
    QComboBox::down-arrow {{
        image: url(down_arrow.png);
        width: 12px;
        height: 12px;
    }}
    QComboBox QAbstractItemView {{
        background-color: #333333;
        color: {TEXT_COLOR};
        selection-background-color: {PRIMARY_COLOR};
        selection-color: white;
        border: 1px solid #555555;
    }}
"""

# QLineEdit modern style
LINEEDIT_STYLE = f"""
    QLineEdit {{
        background-color: #333333;
        color: {TEXT_COLOR};
        border: 1px solid #555555;
        border-radius: {BORDER_RADIUS};
        padding: 5px;
    }}
    QLineEdit:hover {{
        border: 1px solid {HIGHLIGHT_COLOR};
    }}
    QLineEdit:focus {{
        border: 1px solid {PRIMARY_COLOR};
    }}
"""

# QSlider modern style for vertical orientation
SLIDER_STYLE = f"""
    QSlider::groove:vertical {{
        background: #444444;
        width: 10px;
        border-radius: 5px;
    }}
    QSlider::handle:vertical {{
        background: linear-gradient(to right, #00CED1, #00BFFF);
        height: 20px;
        width: 20px;
        margin: 0 -6px;
        border-radius: 10px;
    }}
    QSlider::handle:vertical:hover {{
        background: #00FFFF;
    }}
    QSlider::add-page:vertical {{
        background: qlineargradient(x1: 0, y1: 0, x2: 0, y2: 1, 
                                  stop: 0 #FF1493, stop: 1 #8A2BE2);
        border-radius: 5px;
    }}
    QSlider::sub-page:vertical {{
        background: #444444;
        border-radius: 5px;
    }}
"""

# Disabled slider style that maintains rounded corners
DISABLED_SLIDER_STYLE = f"""
    QSlider::groove:vertical {{
        background: #444444;
        width: 8px;
        border-radius: 4px;
    }}
    QSlider::handle:vertical {{
        background: #555555;
        height: 20px;
        width: 20px;
        margin: 0 -6px;
        border-radius: 10px;
    }}
    QSlider::add-page:vertical {{
        background: #555555;
        border-radius: 4px;
    }}
    QSlider::sub-page:vertical {{
        background: #444444;
        border-radius: 4px;
    }}
"""

# Checkbox style
CHECKBOX_STYLE = f"""
    QCheckBox {{
        color: {TEXT_COLOR};
        spacing: 5px;
    }}
    QCheckBox::indicator {{
        width: 18px;
        height: 18px;
    }}
    QCheckBox::indicator:unchecked {{
        background-color: #333333;
        border: 1px solid #555555;
        border-radius: 3px;
    }}
    QCheckBox::indicator:checked {{
        background-color: {PRIMARY_COLOR};
        border: 1px solid {PRIMARY_COLOR};
        border-radius: 3px;
    }}
    QCheckBox::indicator:hover {{
        border: 1px solid {HIGHLIGHT_COLOR};
    }}
"""

# Frame style
FRAME_STYLE = f"""
    QFrame {{
        background-color: {DARK_BG};
        border-radius: {BORDER_RADIUS};
    }}
"""

# Separator style
SEPARATOR_STYLE = f"""
    QFrame[frameShape="4"] {{
        color: #444444;
        max-height: 1px;
    }}
"""

# Define SPINBOX_STYLE constant at the top with other style constants
SPINBOX_STYLE = f"""
    QSpinBox {{
        background-color: #333333;
        color: {TEXT_COLOR};
        border: 1px solid #555555;
        border-radius: {BORDER_RADIUS};
        padding: 2px;
    }}
    QSpinBox::up-button, QSpinBox::down-button {{
        background-color: #444444;
        border-radius: 2px;
    }}
"""

class MediaMonitor(QtCore.QObject):
    session_changed_signal = QtCore.Signal(object, object)

    def __init__(self, notification_manager):
        super().__init__()
        self.notification_manager = notification_manager
        self.session_manager = None
        self.current_track = None
        self.session_changed_signal.connect(self.on_session_changed_async)

    async def initialize(self):
        """Asynchronously initialize the session manager."""
        try:
            self.session_manager = await wmc.GlobalSystemMediaTransportControlsSessionManager.request_async()
            self.session_manager.add_current_session_changed(self.on_session_changed_sync)
            logger.info("MediaMonitor initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize MediaMonitor session manager: {e}")
            self.session_manager = None

    def on_session_changed_sync(self, sender, args):
        self.session_changed_signal.emit(sender, args)

    @asyncSlot()
    async def on_session_changed_async(self, sender, args):
        if self.session_manager:
            session = self.session_manager.get_current_session()
            if session:
                try:
                    media_properties = await session.try_get_media_properties_async()
                    title = media_properties.title
                    artist = media_properties.artist
                    track_info = f"{title} by {artist}"
                    if track_info != self.current_track:
                        self.current_track = track_info
                        message = f"Now playing: {track_info}"
                        self.notification_manager.show_notification(message, 'music_track')
                except Exception as e:
                    logger.error(f"Failed to get media properties: {e}")

    def stop(self):
        """Stop the MediaMonitor and clean up resources."""
        if self.session_manager:
            try:
                self.session_manager.remove_current_session_changed(self.on_session_changed_sync)
                self.session_manager = None
                logger.info("MediaMonitor stopped and resources released")
            except Exception as e:
                logger.error(f"Error stopping MediaMonitor: {e}")

class MIDIKeyboardApp(QtWidgets.QMainWindow):
    button_style_signal = QtCore.Signal(int, bool)
    message_signal = QtCore.Signal(str)
    slider_value_signal = QtCore.Signal(int)
    action_signal = QtCore.Signal(int, object)
    slider_action_signal = QtCore.Signal(int)
    notification_signal = QtCore.Signal(str, str)
    start_slider_timer_signal = QtCore.Signal()

    def __init__(self):
        super().__init__()
        self._shutting_down = False
        self.setWindowTitle("WORLDE EASYPAD.12 Controller")
        self.setMinimumSize(900, 350)  # Set minimum size
        self.resize(1300, 500)  # Set initial window size

        # Create and set window icon
        self.icon_image = Image.new('RGBA', (64, 64), (0, 0, 0, 0))
        draw = ImageDraw.Draw(self.icon_image)
        body_color = PRIMARY_COLOR
        border_color = HIGHLIGHT_COLOR
        dark_accent = "#1A1A1A"
        draw.rounded_rectangle([(8, 8), (56, 56)], radius=5, fill=body_color, outline=border_color, width=2)
        draw.rectangle([(16, 16), (24, 48)], fill=dark_accent, outline=border_color)
        draw.rectangle([(16, 32), (24, 40)], fill=HIGHLIGHT_COLOR)
        pad_positions = [(32, 16), (42, 16), (52, 16), (32, 36), (42, 36), (52, 36)]
        for x, y in pad_positions:
            draw.rectangle([(x-6, y-6), (x+6, y+6)], fill=dark_accent, outline=border_color)
            draw.line([(x-5, y-5), (x+5, y-5)], fill=HIGHLIGHT_COLOR, width=1)
            draw.line([(x-5, y-5), (x-5, y+5)], fill=HIGHLIGHT_COLOR, width=1)
        qimage = QtGui.QImage(self.icon_image.tobytes(), 64, 64, QtGui.QImage.Format_RGBA8888)
        self.setWindowIcon(QtGui.QIcon(QtGui.QPixmap.fromImage(qimage)))

        # Initialize data
        self.mapping = load_midi_mapping()
        self.button_mapping = {
            "top_row": self.mapping["layout"]["rows"][0],
            "bottom_row": self.mapping["layout"]["rows"][1],
            "left_column": self.mapping["layout"]["controls"] if "controls" in self.mapping["layout"] else [],
            "slider": self.mapping["layout"]["slider"][0] if self.mapping["layout"]["slider"] else None
        }
        self.button_config = {}
        self.p = pyaudio.PyAudio()
        self.stream = None
        self.frames = []
        self.is_button_held = False
        self.audio_segments = []
        self.current_language = None
        self.listening_thread = None
        self.active_recognition_button = None
        self.active_recognition_stop = None
        self.mic_source = None
        self.is_recognition_active = False
        self.midi_controller = MIDIController(callback=self.on_midi_message)
        self.system_actions = SystemActions(self)
        self.notification_manager = NotificationManager()
        self.media_monitor = MediaMonitor(self.notification_manager)
        QtCore.QTimer.singleShot(0, self.init_media_monitor)
        self.load_config()
        self.active_buttons = set()

        # Initialize tray icon if available
        self.tray_icon = None
        if QtWidgets.QSystemTrayIcon.isSystemTrayAvailable():
            self.setup_tray()
            QtCore.QTimer.singleShot(100, self.hide)

        # Add slider timer for debouncing
        self.slider_timer = QtCore.QTimer(self)
        self.slider_timer.setSingleShot(True)
        self.slider_timer.timeout.connect(self.apply_slider_value)
        self.last_slider_value = None

        # Create the main UI
        self.create_ui()
        self.button_style_signal.connect(self.update_button_style)
        self.message_signal.connect(self.update_message)
        self.slider_value_signal.connect(self.update_slider_value)
        self.action_signal.connect(self.execute_action_slot)
        self.slider_action_signal.connect(self.handle_slider_action)
        self.notification_signal.connect(self.show_notification_slot)
        self.start_slider_timer_signal.connect(self.start_slider_timer)

        # Schedule tasks
        QtCore.QTimer.singleShot(1000, self.auto_connect_midi)
        QtCore.QTimer.singleShot(1500, self.update_button_labels_from_config)

    def start_slider_timer(self):
        """Slot to start the slider timer in the GUI thread."""
        self.slider_timer.start(100)

    def show_notification_slot(self, message, notification_type):
        """Slot to handle notification display in the main thread."""
        logger.debug(f"Attempting to show notification: {message} ({notification_type})")
        print(f"DEBUG: Showing notification - Message: {message}, Type: {notification_type}")
        
        # Map certain notification types to the correct category
        if notification_type in ["input_device_disconnected", "input_device_selected"]:
            if "MIDI" in message:
                # This is a MIDI-specific message
                notification_type = "midi_connection"
                logger.debug(f"Remapping to midi_connection notification type")
        
        self.notification_manager.show_notification(message, notification_type)

    @asyncSlot()
    async def init_media_monitor(self):
        """Asynchronously initialize the MediaMonitor."""
        try:
            await self.media_monitor.initialize()
            if self.media_monitor.session_manager is None:
                self.message_signal.emit("Media monitoring unavailable")
        except Exception as e:
            logger.error(f"Failed to initialize MediaMonitor: {e}")
            self.message_signal.emit(f"MediaMonitor error: {str(e)}")

    def update_message(self, message):
        logger.info(message)
        if hasattr(self, 'message_label') and self.message_label:
            self.message_label.setText(message)
            QtCore.QTimer.singleShot(5000, lambda: self.message_label.setText("Ready"))

    def update_slider_value_display(self, value):
        if hasattr(self, 'slider_value_label'):
            self.slider_value_label.setText(f"{value}%")

    def on_slider_change(self, value):
        self.last_slider_value = value
        self.update_slider_value_display(value)
        self.start_slider_timer_signal.emit()

    def update_slider_value(self, value):
        self.slider_widget.blockSignals(True)
        self.slider_widget.setValue(value)
        self.update_slider_value_display(value)
        self.slider_widget.blockSignals(False)

    def execute_action_slot(self, button_id, value=None):
        self.execute_button_action(button_id, value)

    def handle_slider_action(self, value):
        # This method is kept for compatibility but won't be called directly due to debouncing
        success = self.system_actions.set_volume("set", value)
        if success:
            self.message_signal.emit(f"Volume set to {value}%")
            self.notification_manager.show_notification(f"Volume set to {value}%", 'volume_adjustment')
        else:
            self.message_signal.emit("Failed to set volume")

    def apply_slider_value(self):
        if self.midi_controller.is_connected and self.last_slider_value is not None:
            success = self.system_actions.set_volume("set", self.last_slider_value)
            if success:
                self.message_signal.emit(f"Volume set to {self.last_slider_value}%")
                self.notification_manager.show_notification(f"Volume set to {self.last_slider_value}%", 'volume_adjustment')
            else:
                self.message_signal.emit("Failed to set volume")
            self.last_slider_value = None

    def setup_tray(self):
        """Set up the system tray icon with improved menu styling"""
        qimage = QtGui.QImage(self.icon_image.tobytes(), 64, 64, QtGui.QImage.Format_RGBA8888)
        self.tray_icon = QtWidgets.QSystemTrayIcon(QtGui.QIcon(QtGui.QPixmap.fromImage(qimage)), self)
        
        # Create and style the tray menu
        tray_menu = QtWidgets.QMenu()
        tray_menu.setStyleSheet(f"""
            QMenu {{
                background-color: {DARK_BG};
                color: {TEXT_COLOR};
                border: 1px solid #444444;
                border-radius: {BORDER_RADIUS};
                padding: 5px;
            }}
            QMenu::item {{
                background-color: transparent;
                padding: 8px 20px;
                border-radius: 4px;
            }}
            QMenu::item:selected {{
                background-color: {PRIMARY_COLOR};
                color: white;
            }}
            QMenu::separator {{
                height: 1px;
                background-color: #444444;
                margin: 5px 10px;
            }}
        """)
        
        # Add app title to menu (as non-interactive item)
        app_title = QtGui.QAction("WORLDE EASYPAD.12 Controller", self)
        app_title.setEnabled(False)
        tray_menu.addAction(app_title)
        tray_menu.addSeparator()
        
        # Add standard menu items
        show_action = QtGui.QAction("Show Controller", self)
        show_action.triggered.connect(self.show_window)
        tray_menu.addAction(show_action)
        
        # Add settings submenu
        settings_menu = tray_menu.addMenu("Settings")
        settings_menu.setStyleSheet(tray_menu.styleSheet())
        
        notification_action = QtGui.QAction("Notification Settings", self)
        notification_action.triggered.connect(self.open_notification_settings)
        settings_menu.addAction(notification_action)
        
        tray_menu.addSeparator()
        
        # Add status indicators - placeholder text, will be updated by update_tray_status
        status_text = "MIDI: Checking status..."
        status_action = QtGui.QAction(status_text, self)
        status_action.setEnabled(False)
        tray_menu.addAction(status_action)
        
        tray_menu.addSeparator()
        
        # Add exit action
        exit_action = QtGui.QAction("Exit", self)
        exit_action.triggered.connect(self.exit_app)
        tray_menu.addAction(exit_action)
        
        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.activated.connect(self.on_tray_activated)
        self.tray_icon.show()
        
        # Update the status to show the real connection state
        self.update_tray_status()
        
        # Show startup notification
        self.tray_icon.showMessage(
            "WORLDE EASYPAD.12 Controller", 
            "Application is running in the system tray", 
            QtGui.QIcon(QtGui.QPixmap.fromImage(qimage)),
            3000
        )

    def show_window(self):
        self.show()
        self.activateWindow()

    def hide_to_tray(self):
        if self.tray_icon:
            self.hide()
            return True
        return False

    def exit_app(self):
        """Properly shut down the application and all its components."""
        logger.info("Initiating application shutdown...")

        if hasattr(self, '_shutting_down') and self._shutting_down:
            logger.debug("Shutdown already in progress, skipping redundant call")
            return
        self._shutting_down = True

        # Clean up WebOS TV connections first
        try:
            from app.webos_tv import webos_manager
            if webos_manager and webos_manager.loop and not webos_manager.loop.is_closed():
                logger.debug("Cleaning up WebOS TV connections")
                asyncio.run_coroutine_threadsafe(webos_manager.cleanup(), webos_manager.loop)
                # Give it a moment to disconnect
                time.sleep(0.5)
        except Exception as e:
            logger.error(f"Error cleaning up WebOS TV connections: {e}")

        if self.tray_icon:
            try:
                self.tray_icon.hide()
                self.tray_icon.setContextMenu(None)
                logger.debug("System tray icon hidden and cleaned up")
            except Exception as e:
                logger.error(f"Error hiding tray icon: {e}")

        # Rest of the cleanup code remains unchanged
        if hasattr(self, 'midi_controller') and self.midi_controller:
            try:
                if self.midi_controller.is_connected:
                    self.midi_controller.stop_monitoring()
                    self.midi_controller.disconnect()
                    logger.debug("MIDI controller monitoring stopped and disconnected")
                del self.midi_controller
            except Exception as e:
                logger.error(f"Error stopping MIDI controller: {e}")

        if hasattr(self, 'media_monitor') and self.media_monitor:
            try:
                self.media_monitor.stop()
                logger.debug("MediaMonitor stopped via stop method")
                del self.media_monitor
            except Exception as e:
                logger.error(f"Error stopping MediaMonitor: {e}")

        if hasattr(self, 'system_actions') and self.system_actions:
            try:
                self.system_actions.running = False
                if hasattr(self.system_actions, 'monitor_thread') and self.system_actions.monitor_thread.is_alive():
                    self.system_actions.monitor_thread.join(timeout=2.0)
                    if self.system_actions.monitor_thread.is_alive():
                        logger.warning("SystemActions thread did not terminate gracefully")
                    else:
                        logger.debug("SystemActions monitoring thread stopped")
                del self.system_actions
            except Exception as e:
                logger.error(f"Error stopping SystemActions: {e}")

        if hasattr(self, 'stream') and self.stream:
            try:
                if self.stream.is_active():
                    self.stream.stop_stream()
                self.stream.close()
                logger.debug("Audio stream stopped and closed")
                del self.stream
            except Exception as e:
                logger.error(f"Error closing audio stream: {e}")

        if hasattr(self, 'p') and self.p:
            try:
                self.p.terminate()
                logger.debug("PyAudio terminated")
                del self.p
            except Exception as e:
                logger.error(f"Error terminating PyAudio: {e}")

        import threading
        active_threads = threading.enumerate()
        logger.info(f"Active threads before exit: {[t.name for t in active_threads]}")

        for child in self.findChildren(QtWidgets.QDialog):
            try:
                child.close()
                logger.debug(f"Closed dialog: {child.windowTitle()}")
            except Exception as e:
                logger.error(f"Error closing dialog: {e}")

        try:
            self.button_style_signal.disconnect()
            self.message_signal.disconnect()
            self.slider_value_signal.disconnect()
            self.action_signal.disconnect()
            self.slider_action_signal.disconnect()
            self.notification_signal.disconnect()
            self.start_slider_timer_signal.disconnect()
            logger.debug("All signals disconnected")
        except Exception as e:
            logger.warning(f"Error disconnecting signals: {e}")

        try:
            QtWidgets.QApplication.quit()
            logger.info("QApplication.quit() called")
        except Exception as e:
            logger.error(f"Error during QApplication.quit(): {e}")

        sys.exit(0)

    def on_tray_activated(self, reason):
        if reason == QtWidgets.QSystemTrayIcon.DoubleClick:
            self.show_window()

    def closeEvent(self, event):
        if QtWidgets.QSystemTrayIcon.isSystemTrayAvailable() and self.tray_icon:
            self.hide()
            event.ignore()
        else:
            self.exit_app()
            event.accept()

    def create_ui(self):
        central_widget = QtWidgets.QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QtWidgets.QVBoxLayout(central_widget)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(15)

        # Status bar at the top
        status_frame = QtWidgets.QFrame()
        status_frame.setStyleSheet(FRAME_STYLE)
        status_frame.setMinimumHeight(50)
        status_layout = QtWidgets.QHBoxLayout(status_frame)
        status_layout.setContentsMargins(15, 5, 15, 5)
        
        # Status indicator with colored dot
        self.status_indicator = QtWidgets.QFrame()
        self.status_indicator.setFixedSize(12, 12)
        self.status_indicator.setStyleSheet(f"background-color: {'#4CAF50' if self.midi_controller.is_connected else '#F44336'}; border-radius: 6px;")
        
        self.status_label = QtWidgets.QLabel("MIDI Device: Not Connected")
        self.status_label.setStyleSheet(f"color: {TEXT_COLOR}; font-weight: bold;")
        
        status_left_layout = QtWidgets.QHBoxLayout()
        status_left_layout.setSpacing(8)
        status_left_layout.addWidget(self.status_indicator)
        status_left_layout.addWidget(self.status_label)
        
        status_layout.addLayout(status_left_layout)

        right_buttons_frame = QtWidgets.QFrame()
        right_buttons_layout = QtWidgets.QHBoxLayout(right_buttons_frame)
        right_buttons_layout.setSpacing(10)
        
        if QtWidgets.QSystemTrayIcon.isSystemTrayAvailable():
            minimize_button = QtWidgets.QPushButton("Hide to Tray")
            minimize_button.setStyleSheet(ACTION_BUTTON_STYLE.replace(PRIMARY_COLOR, SECONDARY_COLOR))
            minimize_button.clicked.connect(self.hide_to_tray)
            right_buttons_layout.addWidget(minimize_button)
            
        self.connect_button = QtWidgets.QPushButton("Disconnect" if self.midi_controller.is_connected else "Connect")
        self.connect_button.setStyleSheet(ACTION_BUTTON_STYLE)
        self.connect_button.clicked.connect(self.disconnect_midi if self.midi_controller.is_connected else self.connect_to_midi)
        right_buttons_layout.addWidget(self.connect_button)
        
        notification_settings_button = QtWidgets.QPushButton("Notification Settings")
        notification_settings_button.setStyleSheet(ACTION_BUTTON_STYLE.replace(PRIMARY_COLOR, SECONDARY_COLOR))
        notification_settings_button.clicked.connect(self.open_notification_settings)
        right_buttons_layout.addWidget(notification_settings_button)
        
        status_layout.addWidget(right_buttons_frame, alignment=QtCore.Qt.AlignRight)
        main_layout.addWidget(status_frame)

        # Separator
        separator = QtWidgets.QFrame()
        separator.setFrameShape(QtWidgets.QFrame.HLine)
        separator.setStyleSheet(SEPARATOR_STYLE)
        main_layout.addWidget(separator)

        # Keyboard layout - with stretch factors for responsiveness
        keyboard_frame = QtWidgets.QFrame()
        keyboard_frame.setStyleSheet(FRAME_STYLE)
        keyboard_layout = QtWidgets.QHBoxLayout(keyboard_frame)
        keyboard_layout.setSpacing(20)
        main_layout.addWidget(keyboard_frame, 1)  # Add stretch factor

        # Left section - Small buttons (3-8, 1-2)
        self.button_widgets = {}
        left_section = QtWidgets.QFrame()
        left_section.setMinimumWidth(230)
        left_layout = QtWidgets.QVBoxLayout(left_section)
        left_layout.setSpacing(10)

        # Row 1 (Buttons 3, 4, 5)
        button_row_1 = QtWidgets.QFrame()
        button_row_1_layout = QtWidgets.QHBoxLayout(button_row_1)
        button_row_1_layout.setSpacing(10)
        for button_id in [3, 4, 5]:
            button = QtWidgets.QPushButton(self.mapping['button_names'][str(button_id)])
            button.setMinimumSize(60, 40)
            button.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
            button.setStyleSheet(BUTTON_STYLE)
            button.clicked.connect(lambda checked, bid=button_id: self.show_button_config(bid))
            button_row_1_layout.addWidget(button)
            self.button_widgets[button_id] = button
        left_layout.addWidget(button_row_1)

        # Row 2 (Buttons 6, 7, 8)
        button_row_2 = QtWidgets.QFrame()
        button_row_2_layout = QtWidgets.QHBoxLayout(button_row_2)
        button_row_2_layout.setSpacing(10)
        for button_id in [6, 7, 8]:
            button = QtWidgets.QPushButton(self.mapping['button_names'][str(button_id)])
            button.setMinimumSize(60, 40)
            button.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
            button.setStyleSheet(BUTTON_STYLE)
            button.clicked.connect(lambda checked, bid=button_id: self.show_button_config(bid))
            button_row_2_layout.addWidget(button)
            self.button_widgets[button_id] = button
        left_layout.addWidget(button_row_2)

        # Row 3 (Buttons 1, 2)
        button_row_3 = QtWidgets.QFrame()
        button_row_3_layout = QtWidgets.QHBoxLayout(button_row_3)
        button_row_3_layout.setSpacing(10)
        button_row_3_layout.addStretch(1)
        for button_id in [1, 2]:
            button = QtWidgets.QPushButton(self.mapping['button_names'][str(button_id)])
            button.setMinimumSize(60, 40)
            button.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
            button.setStyleSheet(BUTTON_STYLE)
            button.clicked.connect(lambda checked, bid=button_id: self.show_button_config(bid))
            button_row_3_layout.addWidget(button)
            self.button_widgets[button_id] = button
        button_row_3_layout.addStretch(1)
        left_layout.addWidget(button_row_3)
        keyboard_layout.addWidget(left_section, 2)  # Add stretch factor for width distribution

        # Slider section - with improved visual appearance
        slider_frame = QtWidgets.QFrame()
        slider_frame.setMinimumWidth(80)
        slider_layout = QtWidgets.QVBoxLayout(slider_frame)
        slider_layout.setAlignment(QtCore.Qt.AlignCenter)
        
        self.slider_label = QtWidgets.QLabel("SLIDER")
        self.slider_label.setStyleSheet(f"color: {TEXT_COLOR}; font-weight: bold; font-size: 11pt;")
        self.slider_label.setAlignment(QtCore.Qt.AlignCenter)
        slider_layout.addWidget(self.slider_label)
        
        try:
            config_path = os.path.join(os.path.dirname(__file__), "config", "slider_config.json")
            if os.path.exists(config_path):
                with open(config_path, 'r') as f:
                    slider_config = json.load(f)
                    initial_state = slider_config.get("enabled", True)
            else:
                initial_state = True
        except Exception as e:
            logger.error(f"Failed to load slider state: {e}")
            initial_state = True
            
        self.slider_enabled_checkbox = QtWidgets.QCheckBox("Enable")
        self.slider_enabled_checkbox.setChecked(initial_state)
        self.slider_enabled_checkbox.stateChanged.connect(self.toggle_slider)
        self.slider_enabled_checkbox.setStyleSheet(CHECKBOX_STYLE)
        slider_layout.addWidget(self.slider_enabled_checkbox, alignment=QtCore.Qt.AlignCenter)
        
        slider_container = QtWidgets.QFrame()
        slider_container.setMinimumSize(50, 160)
        slider_container.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Expanding)
        slider_container.setStyleSheet(f"""
            background-color: #1A1A1A; 
            border: 2px solid #333333; 
            border-radius: {BORDER_RADIUS};
        """)
        
        slider_container_layout = QtWidgets.QVBoxLayout(slider_container)
        slider_id = self.mapping["layout"]["slider"][0]
        self.slider_widget = QtWidgets.QSlider(QtCore.Qt.Vertical)
        self.slider_widget.setRange(0, 100)
        self.slider_widget.setValue(0)
        self.slider_widget.setStyleSheet(SLIDER_STYLE)
        
        self.slider_widget.valueChanged.connect(self.on_slider_change)
        if not initial_state:
            self.slider_widget.setStyleSheet(DISABLED_SLIDER_STYLE)
            self.slider_widget.setEnabled(False)
            
        slider_container_layout.addWidget(self.slider_widget)
        slider_layout.addWidget(slider_container, 1)  # Add stretch factor
        
        # Add slider value label
        self.slider_value_label = QtWidgets.QLabel("0%")
        self.slider_value_label.setStyleSheet(f"color: {TEXT_COLOR}; font-size: 10pt; margin-top: 5px;")
        self.slider_value_label.setAlignment(QtCore.Qt.AlignCenter)
        slider_layout.addWidget(self.slider_value_label)
        
        keyboard_layout.addWidget(slider_frame, 1)  # Add stretch factor

        # Right section - Pad buttons (40-51) with improved grid layout
        pads_frame = QtWidgets.QFrame()
        pads_layout = QtWidgets.QGridLayout(pads_frame)
        pads_layout.setSpacing(12)
        
        for row in range(2):
            for col in range(6):
                button_id = 40 + col + (row * 6)
                pad_button = QtWidgets.QPushButton(f"Pad {col+1 + row*6}\nButton {button_id}")
                pad_button.setMinimumSize(80, 80)
                pad_button.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
                pad_button.setStyleSheet(PAD_BUTTON_STYLE)
                pad_button.clicked.connect(lambda checked, bid=button_id: self.show_button_config(bid))
                pads_layout.addWidget(pad_button, row, col)
                self.button_widgets[button_id] = pad_button

        keyboard_layout.addWidget(pads_frame, 7)  # Add stretch factor

        # Message area at the bottom with status icons
        message_frame = QtWidgets.QFrame()
        message_frame.setStyleSheet(f"""
            QFrame {{
                background-color: #222222; 
                border-radius: {BORDER_RADIUS};
                padding: 2px;
            }}
        """)
        message_frame.setMinimumHeight(40)
        message_layout = QtWidgets.QHBoxLayout(message_frame)
        message_layout.setContentsMargins(15, 5, 15, 5)
        
        status_icon = QtWidgets.QLabel()
        status_icon.setFixedSize(16, 16)
        status_pixmap = QtGui.QPixmap(16, 16)
        status_pixmap.fill(QtGui.QColor("#4CAF50"))  # Green status
        status_icon.setPixmap(status_pixmap)
        message_layout.addWidget(status_icon)
        
        self.message_label = QtWidgets.QLabel("Ready")
        self.message_label.setStyleSheet(f"color: {TEXT_COLOR}; font-size: 10pt;")
        message_layout.addWidget(self.message_label)
        message_layout.addStretch()
        
        main_layout.addWidget(message_frame)

    def update_button_labels_from_config(self):
        if not self.button_config:
            return
        for button_id, config in self.button_config.items():
            try:
                button_id = int(button_id)
                action_type = config.get("action_type")
                name = config.get("name", f"Button {button_id}")
                if action_type:
                    action_types = get_action_types()
                    display_action = action_types.get(action_type, {}).get("name", action_type)
                    self.update_button_label(button_id, display_action, name)
            except Exception as e:
                logger.error(f"Error updating button {button_id} label: {e}")

    def update_button_label(self, button_id, action_type, description):
        button_id = int(button_id)
        short_desc = description if description else action_type
        widget = self.button_widgets.get(button_id)
        if widget:
            if isinstance(widget, QtWidgets.QPushButton):
                button_name = self.mapping["button_names"].get(str(button_id), f"Button {button_id}")
                if 40 <= button_id <= 51:
                    pad_num = button_id - 39
                    widget.setText(f"Pad {pad_num}\n{short_desc}")
                    widget.setStyleSheet(CONFIGURED_PAD_BUTTON_STYLE)
                else:
                    widget.setText(f"{button_name}\n{short_desc}")
                    widget.setStyleSheet(CONFIGURED_BUTTON_STYLE)

    def auto_connect_midi(self):
        logger.info("Attempting to auto-connect to MIDI device")
        success, message = self.midi_controller.find_easypad()
        if success:
            logger.info(f"Auto-connected to MIDI device: {self.midi_controller.port_name}")
            self.status_label.setText(f"MIDI Device: {self.midi_controller.port_name}")
            self.status_indicator.setStyleSheet(f"background-color: #4CAF50; border-radius: 6px;") # Green for connected
            self.connect_button.setText("Disconnect")
            try:
                self.connect_button.clicked.disconnect()
            except Exception:
                pass
            self.connect_button.clicked.connect(self.disconnect_midi)
            self.midi_controller.start_monitoring()
            self.message_signal.emit("Connected to MIDI device")
            self.system_actions.set_midi_port(self.midi_controller.port_name)
            # Update tray to show connected status
            self.update_tray_status()
        else:
            logger.warning(f"Failed to auto-connect: {message}")
            self.message_signal.emit("MIDI device not found. Connect manually.")

    def connect_to_midi(self):
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle("Connect to MIDI Device")
        dialog.setMinimumSize(450, 300)
        
        # Apply modern styling to the dialog
        dialog.setStyleSheet(f"""
            QDialog {{
                background-color: {DARK_BG};
                border-radius: {BORDER_RADIUS};
            }}
        """)
        
        # Main layout with proper margins
        layout = QtWidgets.QVBoxLayout(dialog)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)
        
        # Title label
        title_label = QtWidgets.QLabel("Connect to MIDI Device")
        title_label.setStyleSheet(f"color: {TEXT_COLOR}; font-size: 16px; font-weight: bold;")
        title_label.setAlignment(QtCore.Qt.AlignCenter)
        layout.addWidget(title_label)
        
        # Separator
        separator = QtWidgets.QFrame()
        separator.setFrameShape(QtWidgets.QFrame.HLine)
        separator.setStyleSheet(SEPARATOR_STYLE)
        layout.addWidget(separator)
        
        # Content area with card-like appearance
        content_card = QtWidgets.QFrame()
        content_card.setStyleSheet(f"""
            QFrame {{
                background-color: #222222;
                border-radius: {BORDER_RADIUS};
                padding: 15px;
            }}
        """)
        card_layout = QtWidgets.QVBoxLayout(content_card)
        card_layout.setSpacing(15)
        
        # Get available MIDI devices
        available_ports = self.midi_controller.get_available_ports()
        logger.info(f"Available MIDI ports for manual connection: {available_ports}")
        
        device_label = QtWidgets.QLabel("Select MIDI Device:")
        device_label.setStyleSheet(f"color: {TEXT_COLOR}; font-weight: bold;")
        card_layout.addWidget(device_label)
        
        if available_ports:
            # Device selection combo box
            device_combo = QtWidgets.QComboBox()
            device_combo.addItems(available_ports)
            device_combo.setStyleSheet(COMBOBOX_STYLE)
            card_layout.addWidget(device_combo)
            
            # Device info label (placeholder for future device details)
            info_label = QtWidgets.QLabel("Connect to use this device with the application")
            info_label.setStyleSheet(f"color: {TEXT_COLOR}; font-style: italic;")
            card_layout.addWidget(info_label)
            
            # Add some space
            card_layout.addStretch()
            
            # Button container with nicer layout
            button_container = QtWidgets.QFrame()
            button_layout = QtWidgets.QHBoxLayout(button_container)
            button_layout.setContentsMargins(0, 10, 0, 0)
            
            # Cancel button
            cancel_btn = QtWidgets.QPushButton("Cancel")
            cancel_btn.setStyleSheet(ACTION_BUTTON_STYLE.replace(PRIMARY_COLOR, "#555555"))
            cancel_btn.clicked.connect(dialog.reject)
            
            # Connect button
            connect_btn = QtWidgets.QPushButton("Connect")
            connect_btn.setStyleSheet(ACTION_BUTTON_STYLE)
            connect_btn.clicked.connect(lambda: self.finalize_connection(dialog, device_combo.currentText()))
            
            button_layout.addWidget(cancel_btn)
            button_layout.addStretch()
            button_layout.addWidget(connect_btn)
            
            card_layout.addWidget(button_container)
        else:
            # No devices found message
            no_devices_label = QtWidgets.QLabel("No MIDI devices found")
            no_devices_label.setStyleSheet(f"color: {TEXT_COLOR}; text-align: center;")
            no_devices_label.setAlignment(QtCore.Qt.AlignCenter)
            card_layout.addWidget(no_devices_label)
            
            # Info about what to do
            help_label = QtWidgets.QLabel("Please connect a MIDI device to your computer and try again")
            help_label.setStyleSheet(f"color: {TEXT_COLOR}; font-style: italic;")
            help_label.setAlignment(QtCore.Qt.AlignCenter)
            card_layout.addWidget(help_label)
            
            card_layout.addStretch()
            
            # Close button
            close_btn = QtWidgets.QPushButton("Close")
            close_btn.setStyleSheet(ACTION_BUTTON_STYLE)
            close_btn.clicked.connect(dialog.reject)
            card_layout.addWidget(close_btn)
        
        layout.addWidget(content_card)
        dialog.exec_()

    def update_tray_status(self):
        """Update the tray icon menu to reflect current MIDI connection status"""
        if not hasattr(self, 'tray_icon') or not self.tray_icon:
            return
            
        # Get the current menu
        menu = self.tray_icon.contextMenu()
        if not menu:
            return
            
        # Find and update the status action
        actions = menu.actions()
        for action in actions:
            if action.text().startswith("MIDI:"):
                # Update the status text
                status_text = f"MIDI: {'Connected - ' + self.midi_controller.port_name if self.midi_controller.is_connected else 'Disconnected'}"
                action.setText(status_text)
                break
                
        # Refresh menu
        self.tray_icon.setContextMenu(menu)

    def finalize_connection(self, dialog, port_name):
        success, message = self.midi_controller.connect_to_device(port_name=port_name)
        if success:
            self.status_label.setText(f"MIDI Device: {port_name}")
            self.status_indicator.setStyleSheet(f"background-color: #4CAF50; border-radius: 6px;") # Green for connected
            self.connect_button.setText("Disconnect")
            self.connect_button.clicked.disconnect()
            self.connect_button.clicked.connect(self.disconnect_midi)
            self.midi_controller.start_monitoring()
            self.message_signal.emit(f"Connected to {port_name}")
            self.system_actions.set_midi_port(port_name)
            # Update tray status to show connected
            self.update_tray_status()
        else:
            self.message_signal.emit(f"Connection failed: {message}")
        dialog.accept()

    def disconnect_midi(self):
        success, message = self.midi_controller.disconnect()
        if success:
            self.status_label.setText("MIDI Device: Not Connected")
            self.status_indicator.setStyleSheet(f"background-color: #F44336; border-radius: 6px;") # Red for disconnected
            self.connect_button.setText("Connect")
            self.connect_button.clicked.disconnect()
            self.connect_button.clicked.connect(self.connect_to_midi)
            self.message_signal.emit("Disconnected from MIDI device")
            self.system_actions.set_midi_port(None)
            # Update tray status to show disconnected
            self.update_tray_status()
        else:
            self.message_signal.emit(f"Disconnection failed: {message}")

    def on_midi_message(self, message, timestamp=None):
        try:
            logger.debug(f"MIDI message: {message}; timestamp: {timestamp}")
            if isinstance(message, list) and len(message) >= 3:
                status_byte = message[0]
                data1 = message[1]
                data2 = message[2]
                
                # Note On (press) for pads (buttons 40-51)
                if 144 <= status_byte <= 159 and data2 > 0:
                    note = data1
                    button_id = None
                    for row in self.mapping["layout"]["rows"]:
                        if note in row:
                            button_id = note
                            break
                    if button_id is None and "controls" in self.mapping["layout"]:
                        if note in self.mapping["layout"]["controls"]:
                            button_id = note
                    if button_id is not None:
                        config = self.button_config.get(str(button_id))
                        if config and config.get('action_type') == 'speech_to_text' and config.get('enabled', True):
                            language = config['action_data'].get('language', 'en-US')
                            self.start_speech_recognition(button_id, language)
                        elif config and config.get('action_type') == 'ask_chatgpt' and config.get('enabled', True):
                            self.start_chatgpt(button_id, config['action_data'])
                        else:
                            self.action_signal.emit(button_id, None)
                        if button_id in self.button_widgets:
                            self.button_style_signal.emit(button_id, True)
                
                # Note Off (release) for pads (buttons 40-51)
                elif (128 <= status_byte <= 143) or (144 <= status_byte <= 159 and data2 == 0):
                    note = data1
                    button_id = note
                    if str(button_id) in self.button_config:
                        action_type = self.button_config[str(button_id)].get('action_type')
                        if action_type == 'speech_to_text':
                            self.stop_speech_recognition(button_id)
                        elif action_type == 'ask_chatgpt':
                            self.stop_chatgpt(button_id)
                    if button_id in self.button_widgets:
                        self.button_style_signal.emit(button_id, False)
                
                # Control Change (buttons 1-8 and slider)
                elif 176 <= status_byte <= 191:
                    control = data1
                    value = data2
                    control_to_button = {44: 8, 45: 4, 46: 7, 47: 3, 48: 5, 49: 6}
                    if control in control_to_button:
                        button_id = control_to_button[control]
                        config = self.button_config.get(str(button_id))
                        if config and config.get('action_type') == 'speech_to_text' and config.get('enabled', True):
                            if value > 0:
                                language = config['action_data'].get('language', 'en-US')
                                self.start_speech_recognition(button_id, language)
                            else:
                                self.stop_speech_recognition(button_id)
                        elif config and config.get('action_type') == 'ask_chatgpt' and config.get('enabled', True):
                            if value > 0:
                                self.start_chatgpt(button_id, config['action_data'])
                            else:
                                self.stop_chatgpt(button_id)
                        else:
                            if value > 0:
                                self.action_signal.emit(button_id, None)
                        if button_id in self.button_widgets:
                            self.button_style_signal.emit(button_id, value > 0)
                    elif control == 9:
                        if not self.slider_enabled_checkbox.isChecked():
                            logger.debug("Slider is disabled, ignoring MIDI message")
                            return
                        normalized_value = int((value / 127) * 100)
                        self.slider_value_signal.emit(normalized_value)
                        self.last_slider_value = normalized_value
                        self.start_slider_timer_signal.emit()  # Emit signal instead of starting timer
            
            elif hasattr(message, 'type'):
                if message.type == 'note_on' and message.velocity > 0:
                    note = message.note
                    button_id = None
                    for row in self.mapping["layout"]["rows"]:
                        if note in row:
                            button_id = note
                            break
                    if button_id is None and "controls" in self.mapping["layout"]:
                        if note in self.mapping["layout"]["controls"]:
                            button_id = note
                    if button_id is not None:
                        config = self.button_config.get(str(button_id))
                        if config and config.get('action_type') == 'speech_to_text' and config.get('enabled', True):
                            language = config['action_data'].get('language', 'en-US')
                            self.start_speech_recognition(button_id, language)
                        else:
                            self.action_signal.emit(button_id, None)
                        if button_id in self.button_widgets:
                            self.button_style_signal.emit(button_id, True)
                elif message.type == 'note_off' or (message.type == 'note_on' and message.velocity == 0):
                    note = message.note
                    button_id = note
                    if str(button_id) in self.button_config and self.button_config[str(button_id)].get('action_type') == 'speech_to_text':
                        self.stop_speech_recognition(button_id)
                    if button_id in self.button_widgets:
                        self.button_style_signal.emit(button_id, False)
                elif message.type == 'control_change':
                    control = message.control
                    value = message.value
                    control_to_button = {44: 8, 45: 4, 46: 7, 47: 3, 48: 5, 49: 6}
                    if control in control_to_button:
                        button_id = control_to_button[control]
                        config = self.button_config.get(str(button_id))
                        if config and config.get('action_type') == 'speech_to_text' and config.get('enabled', True):
                            if value > 0:
                                language = config['action_data'].get('language', 'en-US')
                                self.start_speech_recognition(button_id, language)
                            else:
                                self.stop_speech_recognition(button_id)
                        elif config and config.get('action_type') == 'ask_chatgpt' and config.get('enabled', True):
                            if value > 0:
                                self.start_chatgpt(button_id, config['action_data'])
                            else:
                                self.stop_chatgpt(button_id)
                        else:
                            if value > 0:
                                self.action_signal.emit(button_id, None)
                        if button_id in self.button_widgets:
                            self.button_style_signal.emit(button_id, value > 0)
                    elif control == 9:
                        if not self.slider_enabled_checkbox.isChecked():
                            logger.debug("Slider is disabled, ignoring MIDI message")
                            return
                        normalized_value = int((value / 127) * 100)
                        self.slider_value_signal.emit(normalized_value)
                        self.last_slider_value = normalized_value
                        self.start_slider_timer_signal.emit()  # Emit signal instead of starting timer
        except Exception as e:
            logger.error(f"Error handling MIDI message: {e}")
            self.message_signal.emit(f"MIDI error: {e}")

    def start_speech_recognition(self, button_id, language):
        if self.is_button_held:
            self.stop_speech_recognition(self.active_recognition_button)
        self.is_button_held = True
        self.current_language = language
        self.active_recognition_button = button_id
        self.frames = []

        def callback(in_data, frame_count, time_info, status):
            if self.is_button_held:
                self.frames.append(in_data)
                return (in_data, pyaudio.paContinue)
            return (in_data, pyaudio.paComplete)

        self.stream = self.p.open(format=pyaudio.paInt16, channels=1, rate=44100, input=True, frames_per_buffer=1024, stream_callback=callback)
        self.stream.start_stream()
        self.message_signal.emit("Listening for speech...")
        logger.info("Emitting notification signal: Speech recognition started")
        self.notification_signal.emit("Speech recognition started", 'speech_to_text')
        
    def start_chatgpt(self, button_id, config):
        if self.is_button_held:
            # Stop any ongoing recording
            if self.button_config.get(str(self.active_recognition_button), {}).get('action_type') == 'speech_to_text':
                self.stop_speech_recognition(self.active_recognition_button)
            elif self.button_config.get(str(self.active_recognition_button), {}).get('action_type') == 'ask_chatgpt':
                self.stop_chatgpt(self.active_recognition_button)
                
        self.is_button_held = True
        self.active_recognition_button = button_id
        self.chatgpt_config = config
        self.frames = []

        def callback(in_data, frame_count, time_info, status):
            if self.is_button_held:
                self.frames.append(in_data)
                return (in_data, pyaudio.paContinue)
            return (in_data, pyaudio.paComplete)

        self.stream = self.p.open(format=pyaudio.paInt16, channels=1, rate=44100, input=True, frames_per_buffer=1024, stream_callback=callback)
        self.stream.start_stream()
        self.message_signal.emit("ChatGPT is listening...")
        logger.info("Emitting notification signal: ChatGPT is listening")
        self.notification_signal.emit("ChatGPT is listening...", 'ask_chatgpt')

    def stop_speech_recognition(self, button_id):
        if self.active_recognition_button == button_id and self.is_button_held:
            self.is_button_held = False
            self.stream.stop_stream()
            self.stream.close()
            audio_data = b''.join(self.frames)
            if audio_data:
                threading.Thread(target=self.recognize_speech, args=(audio_data, self.current_language)).start()
            self.active_recognition_button = None
            self.current_language = None
            self.message_signal.emit("Speech recognition stopped")
            logger.info("Emitting notification signal: Speech recognition stopped")
            self.notification_signal.emit("Speech recognition stopped", 'speech_to_text')
            
    def stop_chatgpt(self, button_id):
        if self.active_recognition_button == button_id and self.is_button_held:
            self.is_button_held = False
            self.stream.stop_stream()
            self.stream.close()
            audio_data = b''.join(self.frames)
            config = self.chatgpt_config
            if audio_data:
                threading.Thread(target=self.ask_chatgpt, args=(audio_data, config)).start()
            self.active_recognition_button = None
            self.chatgpt_config = None
            self.message_signal.emit("ChatGPT listening finished")
            logger.info("Emitting notification signal: ChatGPT listening finished")
            self.notification_signal.emit("ChatGPT listening finished", 'ask_chatgpt')

    def recognize_speech(self, audio_data, language):
        try:
            audio_segment = sr.AudioData(audio_data, 44100, 2)
            recognizer = sr.Recognizer()
            text = recognizer.recognize_google(audio_segment, language=language)
            logging.info(f"Recognized text: {text}")
            
            # WINDOWS DIRECT CLIPBOARD API METHOD (most reliable on Windows)
            if WIN32CLIPBOARD_AVAILABLE and platform.system() == "Windows":
                try:
                    logging.info("Using Win32 clipboard API for paste operation")
                    
                    # Save original clipboard content
                    original_clipboard_data = None
                    win32clipboard.OpenClipboard()
                    if win32clipboard.IsClipboardFormatAvailable(win32con.CF_UNICODETEXT):
                        original_clipboard_data = win32clipboard.GetClipboardData(win32con.CF_UNICODETEXT)
                    win32clipboard.EmptyClipboard()
                    
                    # Set new clipboard content
                    win32clipboard.SetClipboardText(text, win32con.CF_UNICODETEXT)
                    win32clipboard.CloseClipboard()
                    
                    time.sleep(0.2)  # Give time for clipboard to register
                    
                    # Try to paste using SendInput for most reliable input
                    try:
                        # Define the input structure for VK_CONTROL and V key
                        KEYEVENTF_KEYDOWN = 0x0000
                        KEYEVENTF_KEYUP = 0x0002
                        
                        # Input type constants
                        INPUT_KEYBOARD = 1
                        
                        class KeyboardInput(Structure):
                            _fields_ = [
                                ("wVk", c_ushort),
                                ("wScan", c_ushort),
                                ("dwFlags", c_ulong),
                                ("time", c_ulong),
                                ("dwExtraInfo", POINTER(c_ulong))
                            ]
                        
                        class HardwareInput(Structure):
                            _fields_ = [
                                ("uMsg", c_ulong),
                                ("wParamL", c_ushort),
                                ("wParamH", c_ushort)
                            ]
                        
                        class MouseInput(Structure):
                            _fields_ = [
                                ("dx", c_ulong),
                                ("dy", c_ulong),
                                ("mouseData", c_ulong),
                                ("dwFlags", c_ulong),
                                ("time", c_ulong),
                                ("dwExtraInfo", POINTER(c_ulong))
                            ]
                        
                        class InputUnion(ctypes.Union):
                            _fields_ = [
                                ("ki", KeyboardInput),
                                ("mi", MouseInput),
                                ("hi", HardwareInput)
                            ]
                        
                        class Input(Structure):
                            _fields_ = [
                                ("type", c_ulong),
                                ("ii", InputUnion)
                            ]
                        
                        # Create input array for Ctrl+V sequence
                        inputs = (Input * 4)()
                        
                        # VK_CONTROL down
                        inputs[0].type = INPUT_KEYBOARD
                        inputs[0].ii.ki.wVk = 0x11  # VK_CONTROL
                        inputs[0].ii.ki.dwFlags = KEYEVENTF_KEYDOWN
                        
                        # V key down
                        inputs[1].type = INPUT_KEYBOARD
                        inputs[1].ii.ki.wVk = 0x56  # V key
                        inputs[1].ii.ki.dwFlags = KEYEVENTF_KEYDOWN
                        
                        # V key up
                        inputs[2].type = INPUT_KEYBOARD
                        inputs[2].ii.ki.wVk = 0x56  # V key
                        inputs[2].ii.ki.dwFlags = KEYEVENTF_KEYUP
                        
                        # VK_CONTROL up
                        inputs[3].type = INPUT_KEYBOARD
                        inputs[3].ii.ki.wVk = 0x11  # VK_CONTROL
                        inputs[3].ii.ki.dwFlags = KEYEVENTF_KEYUP
                        
                        # Send input
                        ctypes.windll.user32.SendInput(4, byref(inputs), sizeof(Input))
                        time.sleep(0.3)
                        logging.info("Pasted using direct SendInput Windows API")
                        
                        # Add a space after pasting
                        time.sleep(0.1)
                        pyautogui.press('space')
                        
                        # Restore original clipboard
                        time.sleep(0.3)
                        win32clipboard.OpenClipboard()
                        win32clipboard.EmptyClipboard()
                        if original_clipboard_data:
                            win32clipboard.SetClipboardText(original_clipboard_data, win32con.CF_UNICODETEXT)
                        win32clipboard.CloseClipboard()
                        
                        return
                    except Exception as win32_err:
                        logging.warning(f"SendInput failed: {win32_err}, trying fallback paste method")
                        
                    # Try another Windows-specific method with UI Automation
                    try:
                        # Use Windows UI Automation API to paste if available
                        cmd = 'powershell -command "[Windows.UI.Input.KeyboardInput,Windows.UI]::SendAcceleratorKey(17, 86)"'
                        subprocess.run(cmd, shell=True, capture_output=True)
                        time.sleep(0.3)
                        logging.info("Pasted with Windows UI Automation API")
                        
                        # Add a space after pasting
                        time.sleep(0.1)
                        pyautogui.press('space')
                        
                        # Restore original clipboard
                        time.sleep(0.3)
                        win32clipboard.OpenClipboard()
                        win32clipboard.EmptyClipboard()
                        if original_clipboard_data:
                            win32clipboard.SetClipboardText(original_clipboard_data, win32con.CF_UNICODETEXT)
                        win32clipboard.CloseClipboard()
                        
                        return
                    except Exception as automation_err:
                        logging.warning(f"Windows UI Automation paste failed: {automation_err}")
                        
                except Exception as win32_err:
                    logging.warning(f"Direct Win32 clipboard method failed: {win32_err}")
                    # Continue to other methods
            
            # FALLBACK METHODS
            
            # Save original clipboard content
            try:
                original_clipboard = pyperclip.paste()
            except Exception as clip_err:
                logging.warning(f"Failed to get original clipboard: {clip_err}")
                original_clipboard = ""
            
            # Copy recognized text to clipboard
            try:
                pyperclip.copy(text)
                time.sleep(0.5)  # Increased wait time for clipboard
            except Exception as copy_err:
                logging.warning(f"Failed to copy to clipboard: {copy_err}")
            
            # Try multiple paste methods
            paste_success = False
            
            # Method 1: pyautogui hotkey
            if not paste_success:
                try:
                    pyautogui.hotkey('ctrl', 'v')
                    time.sleep(0.3)
                    paste_success = True
                    logging.info("Pasted text using pyautogui hotkey")
                except Exception as paste_err:
                    logging.warning(f"pyautogui paste failed: {paste_err}")
            
            # Method 2: keyDown/keyUp approach
            if not paste_success:
                try:
                    pyautogui.keyDown('ctrl')
                    time.sleep(0.1)
                    pyautogui.press('v')
                    time.sleep(0.1)
                    pyautogui.keyUp('ctrl')
                    time.sleep(0.3)
                    paste_success = True
                    logging.info("Pasted text using keyDown/keyUp method")
                except Exception as paste_err2:
                    logging.warning(f"keyDown/keyUp paste failed: {paste_err2}")
            
            # Method 3: keyboard module
            if not paste_success:
                try:
                    import keyboard
                    keyboard.press_and_release('ctrl+v')
                    time.sleep(0.3)
                    paste_success = True
                    logging.info("Pasted text using keyboard module")
                except Exception as kb_err:
                    logging.warning(f"keyboard module paste failed: {kb_err}")
            
            # Method 4: Windows-specific SendKeys
            if not paste_success and os.name == 'nt':
                try:
                    cmd = 'powershell -command "$wshell = New-Object -ComObject wscript.shell; $wshell.SendKeys(\'^v\')"'
                    subprocess.run(cmd, shell=True)
                    time.sleep(0.5)
                    paste_success = True
                    logging.info("Pasted text using PowerShell SendKeys")
                except Exception as ps_err:
                    logging.warning(f"PowerShell SendKeys paste failed: {ps_err}")
            
            # Add a space after pasting if any method succeeded
            if paste_success:
                time.sleep(0.1)
                pyautogui.press('space')
            
            # Restore original clipboard
            try:
                time.sleep(0.3)
                pyperclip.copy(original_clipboard)
            except Exception as restore_err:
                logging.warning(f"Failed to restore clipboard: {restore_err}")
                
        except sr.UnknownValueError:
            logging.warning("Could not understand audio")
        except sr.RequestError as e:
            logging.error(f"Speech recognition error: {e}")
        except Exception as e:
            logging.error(f"Unexpected error in speech recognition: {e}")
            
    def ask_chatgpt(self, audio_data, config):
        """Process speech through Whisper and send to ChatGPT"""
        try:
            # Extract configuration
            api_key = config.get("api_key", "")
            model = config.get("model", "gpt-4o")
            language = config.get("language", "en-US")
            system_prompt = config.get("system_prompt", "You are a helpful assistant.")
            
            if not api_key:
                self.message_signal.emit("Error: No API key provided")
                self.notification_signal.emit("Error: No API key provided", "ask_chatgpt")
                return
                
            # Configure OpenAI client
            client = openai.OpenAI(
                api_key=api_key,
                base_url="https://api.openai.com/v1"  # Ensure the official API endpoint is used
            )
            
            # Show processing notification
            self.message_signal.emit(f"Processing speech and waiting for {model} response...")
            self.notification_signal.emit(f"Processing speech and waiting for {model} response...", "ask_chatgpt")
            
            # Generate a unique temporary filename
            temp_dir = tempfile.gettempdir()
            temp_filename = os.path.join(temp_dir, f"chatgpt_audio_{int(time.time())}.wav")
            
            try:
                # Create a proper WAV file with headers
                with wave.open(temp_filename, 'wb') as wf:
                    wf.setnchannels(1)  # Mono audio
                    wf.setsampwidth(2)  # 16-bit audio (2 bytes)
                    wf.setframerate(44100)  # Sample rate
                    wf.writeframes(audio_data)
                
                # Make sure the file is properly closed before opening it again
                time.sleep(0.1)
                
                # Use the WAV file for the API request
                with open(temp_filename, 'rb') as audio_file:
                    # Use the Whisper API to convert speech to text
                    whisper_response = client.audio.transcriptions.create(
                        model="whisper-1",
                        file=audio_file,
                        language=language[:2] if language else None  # Only use language code, e.g., "en" from "en-US"
                    )
                    
                    transcribed_text = whisper_response.text
                    logger.info(f"Whisper transcription: {transcribed_text}")
                    
                    if not transcribed_text:
                        self.message_signal.emit("No speech detected")
                        self.notification_signal.emit("No speech detected", "ask_chatgpt")
                        return
                    
                # Make sure audio file handle is closed before attempting to delete
                time.sleep(0.1)
                
                # Log the model being used to help with debugging
                logger.info(f"Using OpenAI model: {model}")
                        
                # Now, send transcribed text to ChatGPT
                logger.info(f"Sending request to ChatGPT with model: {model}, system prompt: {system_prompt[:50]}...")
                
                chat_response = client.chat.completions.create(
                    model=model,  # Explicitly use the selected model
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": transcribed_text}
                    ]
                )
                
                # Log the actual model used in the response
                model_used = chat_response.model
                logger.info(f"Actual model used in response: {model_used}")
                if model != model_used:
                    logger.warning(f"Model mismatch! Requested: {model}, Received: {model_used}")
                
                # Extract the response
                chatgpt_response = chat_response.choices[0].message.content
                
                # WINDOWS DIRECT CLIPBOARD API METHOD (most reliable on Windows)
                if WIN32CLIPBOARD_AVAILABLE and platform.system() == "Windows":
                    try:
                        logger.info("Using Win32 clipboard API for paste operation")
                        
                        # Save original clipboard content
                        original_clipboard_data = None
                        win32clipboard.OpenClipboard()
                        if win32clipboard.IsClipboardFormatAvailable(win32con.CF_UNICODETEXT):
                            original_clipboard_data = win32clipboard.GetClipboardData(win32con.CF_UNICODETEXT)
                        win32clipboard.EmptyClipboard()
                        
                        # Set new clipboard content
                        win32clipboard.SetClipboardText(chatgpt_response, win32con.CF_UNICODETEXT)
                        win32clipboard.CloseClipboard()
                        
                        time.sleep(0.5)  # Increased time for clipboard to register
                        
                        # Try both keybd_event and multiple other methods for better reliability
                        # Method 1: Use keybd_event (simpler and often more reliable)
                        try:
                            # Define the input constants
                            KEYEVENTF_KEYDOWN = 0x0000
                            KEYEVENTF_KEYUP = 0x0002
                            
                            # Direct Windows API approach
                            ctypes.windll.user32.keybd_event(0x11, 0, KEYEVENTF_KEYDOWN, 0)  # Ctrl down
                            time.sleep(0.05)
                            ctypes.windll.user32.keybd_event(0x56, 0, KEYEVENTF_KEYDOWN, 0)  # V down
                            time.sleep(0.05)
                            ctypes.windll.user32.keybd_event(0x56, 0, KEYEVENTF_KEYUP, 0)    # V up
                            time.sleep(0.05)
                            ctypes.windll.user32.keybd_event(0x11, 0, KEYEVENTF_KEYUP, 0)    # Ctrl up
                            
                            time.sleep(0.5)  # Longer delay to ensure paste completes
                            logger.info("Pasted using direct keybd_event Windows API")
                            
                            # Restore original clipboard
                            time.sleep(0.5)  # Increased delay before restoring clipboard
                            win32clipboard.OpenClipboard()
                            win32clipboard.EmptyClipboard()
                            if original_clipboard_data:
                                win32clipboard.SetClipboardText(original_clipboard_data, win32con.CF_UNICODETEXT)
                            win32clipboard.CloseClipboard()
                            
                            # Log success
                            self.message_signal.emit(f"Model {model_used} response received and pasted")
                            self.notification_signal.emit(f"Model {model_used} response received", "ask_chatgpt")
                            return
                        except Exception as win32_err:
                            logger.warning(f"keybd_event failed: {win32_err}, trying fallback paste method")
                            
                        # Method 2: PowerShell SendKeys approach
                        try:
                            # Use Windows PowerShell to send keystrokes
                            cmd = 'powershell -command "$wshell = New-Object -ComObject wscript.shell; $wshell.SendKeys(\'^v\')"'
                            subprocess.run(cmd, shell=True, capture_output=True)
                            time.sleep(0.5)  # Longer delay
                            logger.info("Pasted with PowerShell SendKeys")
                            
                            # Restore original clipboard
                            time.sleep(0.5)
                            win32clipboard.OpenClipboard()
                            win32clipboard.EmptyClipboard()
                            if original_clipboard_data:
                                win32clipboard.SetClipboardText(original_clipboard_data, win32con.CF_UNICODETEXT)
                            win32clipboard.CloseClipboard()
                            
                            # Log success
                            self.message_signal.emit(f"Model {model_used} response received and pasted")
                            self.notification_signal.emit(f"Model {model_used} response received", "ask_chatgpt")
                            return
                        except Exception as automation_err:
                            logger.warning(f"PowerShell SendKeys paste failed: {automation_err}")
                            
                    except Exception as win32_err:
                        logger.warning(f"Direct Win32 clipboard method failed: {win32_err}")
                        # Continue to other methods

                # Save original clipboard content
                try:
                    original_clipboard = pyperclip.paste()
                except Exception as clip_err:
                    logger.warning(f"Failed to get original clipboard: {clip_err}")
                    original_clipboard = ""
                
                # Copy response to clipboard and paste it
                try:
                    pyperclip.copy(chatgpt_response)
                    time.sleep(0.7)  # Increased delay for clipboard operations
                except Exception as copy_err:
                    logger.warning(f"Failed to copy to clipboard: {copy_err}")
                
                # Try multiple paste methods
                paste_success = False
                
                # Method 1: pyautogui hotkey
                if not paste_success:
                    try:
                        pyautogui.hotkey('ctrl', 'v')
                        time.sleep(0.5)  # Increased delay
                        paste_success = True
                        logger.info("Pasted text using pyautogui hotkey")
                    except Exception as paste_err:
                        logger.warning(f"pyautogui paste failed: {paste_err}")
                
                # Method 2: keyDown/keyUp approach
                if not paste_success:
                    try:
                        pyautogui.keyDown('ctrl')
                        time.sleep(0.2)  # Increased delay
                        pyautogui.press('v')
                        time.sleep(0.2)  # Increased delay
                        pyautogui.keyUp('ctrl')
                        time.sleep(0.5)  # Increased delay
                        paste_success = True
                        logger.info("Pasted text using keyDown/keyUp method")
                    except Exception as paste_err2:
                        logger.warning(f"keyDown/keyUp paste failed: {paste_err2}")
                
                # Method 3: keyboard module
                if not paste_success and 'keyboard' in sys.modules:
                    try:
                        import keyboard
                        keyboard.press_and_release('ctrl+v')
                        time.sleep(0.5)  # Increased delay
                        paste_success = True
                        logger.info("Pasted text using keyboard module")
                    except Exception as kb_err:
                        logger.warning(f"keyboard module paste failed: {kb_err}")
                
                # Method 4: Windows-specific SendKeys
                if not paste_success and os.name == 'nt':
                    try:
                        cmd = 'powershell -command "$wshell = New-Object -ComObject wscript.shell; $wshell.SendKeys(\'^v\')"'
                        subprocess.run(cmd, shell=True)
                        time.sleep(0.7)  # Increased delay
                        paste_success = True
                        logger.info("Pasted text using PowerShell SendKeys")
                    except Exception as ps_err:
                        logger.warning(f"PowerShell SendKeys paste failed: {ps_err}")
                
                # Restore original clipboard
                try:
                    time.sleep(0.5)  # Increased delay
                    pyperclip.copy(original_clipboard)
                except Exception as restore_err:
                    logger.warning(f"Failed to restore clipboard: {restore_err}")
                
                # Log success
                paste_result = "and pasted" if paste_success else "but paste failed"
                self.message_signal.emit(f"Model {model_used} response received {paste_result}")
                self.notification_signal.emit(f"Model {model_used} response received", "ask_chatgpt")
                    
            finally:
                # Clean up the temporary file with multiple attempts
                for attempt in range(3):
                    try:
                        if os.path.exists(temp_filename):
                            os.close(os.open(temp_filename, os.O_RDONLY))  # Ensure file is closed
                            time.sleep(0.2)  # Allow time for file handle to be released
                            os.unlink(temp_filename)
                            break
                    except Exception as e:
                        if attempt < 2:  # Don't log error on first two attempts
                            time.sleep(0.5)  # Wait longer before next attempt
                        else:
                            logger.error(f"Error removing temporary file (attempt {attempt+1}): {e}")
                            # If we can't delete now, mark for deletion on reboot (Windows-specific)
                            try:
                                if os.name == 'nt' and os.path.exists(temp_filename):
                                    import ctypes
                                    ctypes.windll.kernel32.MoveFileExW(temp_filename, None, 4)  # MOVEFILE_DELAY_UNTIL_REBOOT
                            except:
                                pass
                
        except openai.APIError as e:
            error_message = f"OpenAI API error: {str(e)}"
            logger.error(error_message)
            self.message_signal.emit(error_message)
            self.notification_signal.emit(error_message, "ask_chatgpt")
                
        except Exception as e:
            error_message = f"Error in ChatGPT processing: {str(e)}"
            logger.error(error_message)
            self.message_signal.emit(error_message)
            self.notification_signal.emit(error_message, "ask_chatgpt")

    def update_button_style(self, button_id, is_pressed):
        """Update button appearance based on pressed state and configuration"""
        widget = self.button_widgets.get(button_id)
        if not widget:
            return
            
        config = self.button_config.get(str(button_id))
        is_configured = config and config.get("action_type")
        is_enabled = config.get("enabled", True) if config else True
        is_pad = button_id >= 40
        
        if is_pressed and is_enabled:
            # Active pressed style
            widget.setStyleSheet(f"""
                QPushButton {{
                    background-color: {PRIMARY_COLOR};
                    color: {TEXT_COLOR};
                    border: none;
                    border-radius: {BORDER_RADIUS};
                    padding: {10 if is_pad else 8}px;
                    font-weight: bold;
                }}
            """)
        elif is_configured and is_enabled:
            # Configured and enabled button
            widget.setStyleSheet(CONFIGURED_PAD_BUTTON_STYLE if is_pad else CONFIGURED_BUTTON_STYLE)
        elif is_configured and not is_enabled:
            # Configured but disabled
            widget.setStyleSheet(f"""
                QPushButton {{
                    background-color: #444444;
                    color: #777777;
                    border: none;
                    border-radius: {BORDER_RADIUS};
                    padding: {10 if is_pad else 8}px;
                    font-weight: normal;
                }}
            """)
        else:
            # Unconfigured button
            widget.setStyleSheet(PAD_BUTTON_STYLE if is_pad else BUTTON_STYLE)

    def highlight_button(self, button_id, is_active):
        """Highlight a button temporarily to indicate activity"""
        widget = self.button_widgets.get(int(button_id))
        if not widget:
            logger.warning(f"Button ID {button_id} not found in button widgets")
            return
            
        if isinstance(widget, QtWidgets.QPushButton):
            if is_active:
                widget.setStyleSheet(f"""
                    QPushButton {{
                    background-color: {PRIMARY_COLOR};
                    color: {TEXT_COLOR};
                        border: none;
                        border-radius: {BORDER_RADIUS};
                        padding: {10 if button_id >= 40 else 8}px;
                        font-weight: bold;
                    }}
                """)
                self.active_buttons.add(button_id)
            else:
                config = self.button_config.get(str(button_id))
                is_configured = config and config.get("action_type")
                is_enabled = config.get("enabled", True) if config else True
                is_pad = button_id >= 40
                
                if is_configured and is_enabled:
                    widget.setStyleSheet(CONFIGURED_PAD_BUTTON_STYLE if is_pad else CONFIGURED_BUTTON_STYLE)
                else:
                    widget.setStyleSheet(PAD_BUTTON_STYLE if is_pad else BUTTON_STYLE)
                    
                if button_id in self.active_buttons:
                    self.active_buttons.remove(button_id)

    def flash_button(self, button):
        """Create a quick flash animation for button feedback"""
        if isinstance(button, QtWidgets.QPushButton):
            original_style = button.styleSheet()
            is_pad = "Pad" in button.text()
            
            button.setStyleSheet(f"""
                QPushButton {{
                    background-color: {HIGHLIGHT_COLOR};
                    color: #000000;
                    border: none;
                    border-radius: {BORDER_RADIUS};
                    padding: {10 if is_pad else 8}px;
                    font-weight: bold;
                }}
            """)
            
            # Use animation for smoother effect
            fade_animation = QtCore.QPropertyAnimation(button, b"styleSheet")
            fade_animation.setDuration(300)
            fade_animation.setStartValue(button.styleSheet())
            fade_animation.setEndValue(original_style)
            fade_animation.start()

    def reset_button_style(self, button_id):
        """Reset a button to its original style (without highlight)"""
        if button_id not in self.buttons:
            return
            
        widget = self.buttons[button_id]
        
        # Determine if this is a pad button
        is_pad = button_id in self.large_buttons
        
        # Check if button is configured
        is_configured = button_id in self.config
        is_enabled = True
        if is_configured and "enabled" in self.config[button_id]:
            is_enabled = self.config[button_id]["enabled"]
            
        if is_configured and is_enabled:
            widget.setStyleSheet(CONFIGURED_PAD_BUTTON_STYLE if is_pad else CONFIGURED_BUTTON_STYLE)
        else:
            widget.setStyleSheet(PAD_BUTTON_STYLE if is_pad else BUTTON_STYLE)

    def toggle_slider(self):
        """Toggle slider visibility and enable/disable"""
        if not hasattr(self, 'slider_widget'):
            return
            
        # Toggle visibility by enabling/disabling
        if self.slider_widget.isEnabled():
            self.slider_widget.setStyleSheet("""
                QSlider {
                    background: transparent;
                }
                QSlider::groove:horizontal {
                    background: #444444;
                    height: 4px;
                    border-radius: 2px;
                }
                QSlider::handle:horizontal {
                    background: #666666;
                    width: 16px;
                    height: 16px;
                    margin: -6px 0;
                    border-radius: 8px;
                }
            """)
            self.slider_widget.setEnabled(False)
            self.slider_value_label.setText("0%")
            self.message_signal.emit("Slider disabled")
        else:
            self.slider_widget.setStyleSheet(SLIDER_STYLE)
            self.slider_widget.setEnabled(True)
            if hasattr(self, '_previous_slider_value'):
                self.slider_widget.setValue(self._previous_slider_value)
                self.update_slider_value_display(self._previous_slider_value)
            else:
                self.update_slider_value_display(0)

    def open_notification_settings(self):
        dialog = NotificationSettingsDialog(self, self.notification_manager)
        dialog.exec_()

    def show_button_config(self, button_id):
        dialog = ButtonConfigDialog(self, button_id)
        dialog.exec_()

    def resizeEvent(self, event):
        """Handle window resize event to reposition buttons"""
        super().resizeEvent(event)
        
        # Update button positions based on new window size
        window_width = self.width()
        window_height = self.height()
        
        # Scale buttons based on window size, but not too small
        if hasattr(self, 'button_size') and self.button_size > 0:
            button_size = min(window_width // 5, window_height // 5)
            button_size = max(button_size, 40)  # Minimum size
            
            # Only update if significant change
            if abs(button_size - self.button_size) > 5:
                self.button_size = button_size
                
                # Update all buttons
                for button_id, button in self.buttons.items():
                    if button_id in self.large_buttons:
                        button.setFixedSize(button_size * 2, button_size)
                    else:
                        button.setFixedSize(button_size, button_size)
                        
                # Set font size proportional to button size
                if window_width < 600:
                    font = self.font()
                    font.setPointSize(8)
                    self.setFont(font)
                else:
                    font = self.font()
                    font.setPointSize(9)
                    self.setFont(font)

    def execute_button_action(self, button_id, value=None):
        button_id_str = str(button_id)
        config = self.button_config.get(button_id_str)
        if config and config.get("action_type"):
            if not config.get("enabled", True):
                logger.info(f"Button {button_id} is disabled")
                self.message_signal.emit(f"Button {button_id} is disabled")
                return False
            action_type = config["action_type"]
            action_data = config.get("action_data", {})
            logger.info(f"Executing action for button {button_id}: {action_type} - {action_data}")
            try:
                if action_type == "volume" and value is not None:
                    action_data = action_data.copy()
                    action_data["action"] = "set"
                    action_data["value"] = value
                    result = self.system_actions.execute_action(action_type, action_data)
                    if result:
                        logger.info(f"Volume set to {value}%")
                    else:
                        logger.error(f"Failed to set volume to {value}%")
                    return result
                result = self.system_actions.execute_action(action_type, action_data)
                if result:
                    action_desc = config.get("name", f"Button {button_id}")
                    logger.info(f"Action successful for {action_desc}")
                    if action_type not in ["speech_to_text", "ask_chatgpt", "media", "audio_device"]:
                        self.notification_manager.show_notification(f"Action applied: {action_desc}", 'button_action')
                    return True
                else:
                    logger.error(f"Action execution failed for button {button_id}")
                    self.message_signal.emit(f"Action failed for Button {button_id}")
                    return False
            except Exception as e:
                logger.error(f"Error executing action for button {button_id}: {e}")
                self.message_signal.emit(f"Error: {str(e)}")
                return False
        else:
            logger.info(f"Button {button_id} has no assigned action")
            self.message_signal.emit(f"Button {button_id} has no assigned action")
            return False

    def load_config(self):
        try:
            configs = self.system_actions.load_button_configs()
            self.button_config = configs.get("buttons", configs)
            logger.info(f"Loaded configuration with {len(self.button_config)} button settings")
            self.message_signal.emit("Configuration loaded successfully")
            return True
        except Exception as e:
            logger.error(f"Error loading configuration: {e}")
            self.message_signal.emit(f"Error loading configuration: {e}")
            return False

class ButtonConfigDialog(QtWidgets.QDialog):
    def __init__(self, parent, button_id):
        super().__init__(parent)
        self.parent = parent
        self.button_id = button_id
        self.setWindowTitle(f"Configure {parent.mapping['button_names'].get(str(button_id), f'Button {button_id}')}")
        self.setMinimumSize(620, 520)
        self.current_config = load_button_config(button_id)
        
        # Enhanced dialog styling with modern, rounded design
        self.setStyleSheet(f"""
            QDialog {{
                background-color: {DARK_BG};
                border-radius: {BORDER_RADIUS};
            }}
            QFrame.card {{
                background-color: #222222;
                border-radius: {BORDER_RADIUS};
                border: 1px solid #333333;
                padding: 15px;
                margin-bottom: 12px;
            }}
            QLabel.header {{
                color: {TEXT_COLOR};
                font-size: 15px;
                font-weight: bold;
                margin-bottom: 8px;
            }}
            QLabel.subheader {{
                color: {TEXT_COLOR};
                font-weight: bold;
            }}
            QLabel.description {{
                color: rgba(255, 255, 255, 0.7);
                font-size: 13px;
            }}
            QLabel.section-title {{
                color: {TEXT_COLOR};
                font-size: 14px;
                font-weight: bold;
                padding-left: 5px;
                border-left: 3px solid {PRIMARY_COLOR};
            }}
            QToolTip {{
                background-color: #303030;
                color: white;
                border: 1px solid {PRIMARY_COLOR};
                border-radius: 4px;
                padding: 5px;
            }}
            QPushButton {{
                border-radius: {BORDER_RADIUS};
            }}
            QScrollArea {{
                border: none;
                background-color: transparent;
            }}
            QScrollBar:vertical {{
                background: #2A2A2A;
                width: 8px;
                margin: 0px;
                border-radius: 4px;
            }}
            QScrollBar::handle:vertical {{
                background: #555555;
                min-height: 20px;
                border-radius: 4px;
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                border: none;
                background: none;
            }}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
                background: none;
            }}
        """)
        
        # Main layout
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        # Modern header with gradient background
        header_card = QtWidgets.QFrame()
        header_card.setObjectName("headerCard")
        header_card.setStyleSheet(f"""
            #headerCard {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, 
                                          stop:0 {PRIMARY_COLOR}, stop:1 {SECONDARY_COLOR});
                border-radius: {BORDER_RADIUS};
                padding: 15px;
            }}
        """)
        header_layout = QtWidgets.QHBoxLayout(header_card)
        
        # Icon with specific styling
        icon_label = QtWidgets.QLabel()
        icon_label.setFixedSize(48, 48)
        # Different colors based on button_id
        hue = (button_id * 40) % 360
        icon_bg_color = f"hsla({hue}, 70%, 50%, 0.8)"
        icon_label.setStyleSheet(f"""
            background-color: {icon_bg_color};
            border-radius: 24px;
            color: white;
            font-size: 22px;
            font-weight: bold;
            border: 2px solid rgba(255, 255, 255, 0.3);
        """)
        icon_label.setText(str(button_id))
        icon_label.setAlignment(QtCore.Qt.AlignCenter)
        
        # Create a semi-transparent light background for text
        text_container = QtWidgets.QFrame()
        text_container.setObjectName("textContainer")
        text_container.setStyleSheet("""
            #textContainer {
                background-color: rgba(255, 255, 255, 0.18);
                border-radius: 6px;
                padding: 8px 12px;
            }
        """)
        text_layout = QtWidgets.QVBoxLayout(text_container)
        text_layout.setContentsMargins(12, 8, 12, 8)
        text_layout.setSpacing(4)
        
        # Button info with clearer hierarchy
        button_name = parent.mapping['button_names'].get(str(button_id), f'Button {button_id}')
        title_label = QtWidgets.QLabel(f"Configure {button_name}")
        title_label.setStyleSheet("color: white; font-size: 18px; font-weight: bold; letter-spacing: 0.5px;")
        
        subtitle_label = QtWidgets.QLabel("Set up this button's behavior when pressed")
        subtitle_label.setStyleSheet("color: rgba(255, 255, 255, 0.9); font-size: 13px;")
        
        text_layout.addWidget(title_label)
        text_layout.addWidget(subtitle_label)
        
        header_layout.addWidget(icon_label)
        header_layout.addWidget(text_container, 1)
        
        layout.addWidget(header_card)
        
        # Create a scroll area for all content
        scroll_area = QtWidgets.QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QtWidgets.QFrame.NoFrame)
        
        content_widget = QtWidgets.QWidget()
        content_layout = QtWidgets.QVBoxLayout(content_widget)
        content_layout.setContentsMargins(5, 5, 5, 5)
        content_layout.setSpacing(15)
        
        # ===== BUTTON NAME SECTION =====
        name_card = QtWidgets.QFrame()
        name_card.setProperty("class", "card")
        name_layout = QtWidgets.QHBoxLayout(name_card)
        name_layout.setContentsMargins(15, 15, 15, 15)
        
        name_left = QtWidgets.QVBoxLayout()
        name_title = QtWidgets.QLabel("Button Name")
        name_title.setProperty("class", "section-title")
        name_description = QtWidgets.QLabel("Give this button a descriptive name")
        name_description.setProperty("class", "description")
        name_left.addWidget(name_title)
        name_left.addWidget(name_description)
        
        self.button_name_entry = QtWidgets.QLineEdit()
        self.button_name_entry.setText(self.current_config.get("name", f"Button {button_id}"))
        self.button_name_entry.setStyleSheet(LINEEDIT_STYLE + """
            padding: 10px;
            font-size: 13px;
        """)
        self.button_name_entry.setPlaceholderText("Enter a name for this button")
        self.button_name_entry.setMinimumWidth(250)
        
        name_layout.addLayout(name_left)
        name_layout.addWidget(self.button_name_entry, 1)
        
        content_layout.addWidget(name_card)
        
        # ===== ACTION SECTION =====
        action_card = QtWidgets.QFrame()
        action_card.setProperty("class", "card")
        action_layout = QtWidgets.QVBoxLayout(action_card)
        action_layout.setContentsMargins(15, 15, 15, 15)
        action_layout.setSpacing(15)
        
        action_title = QtWidgets.QLabel("Button Action")
        action_title.setProperty("class", "section-title")
        action_description = QtWidgets.QLabel("What happens when this button is pressed?")
        action_description.setProperty("class", "description")
        
        action_layout.addWidget(action_title)
        action_layout.addWidget(action_description)
        
        # Action type selection with icon grid
        action_types = get_action_types()
        
        self.display_to_internal = {}
        
        # Set up action icons for display
        action_type_icons = {
            'app': "🚀",
            'toggle_app': "⚡",
            'web': "🌐",
            'volume': "🔊",
            'media': "▶️",
            'shortcut': "⌨️",
            'audio_device': "🔈",
            'command': "💻",
            'powershell': "🔷",
            'text': "📝",
            'speech_to_text': "🎤",
            'ask_chatgpt': "🤖",
            'text_to_speech': "🔊",
            'wake_on_lan': "📡",
            'webos_tv': "📺"
        }
        
        # Create a grid of action type buttons
        types_grid = QtWidgets.QGridLayout()
        types_grid.setContentsMargins(0, 10, 0, 10)
        types_grid.setHorizontalSpacing(10)
        types_grid.setVerticalSpacing(10)
        
        selected_type = self.current_config.get("action_type", "app")
        self.action_type_buttons = {}
        
        row, col = 0, 0
        max_cols = 4
        
        for key, info in action_types.items():
            button = QtWidgets.QPushButton()
            is_selected = (key == selected_type)
            
            # Set button style
            button.setCheckable(True)
            button.setChecked(is_selected)
            button.setStyleSheet(f"""
                QPushButton {{
                    background-color: #2d2d2d;
                    border: 1px solid #3d3d3d;
                    border-radius: {BORDER_RADIUS};
                    color: {TEXT_COLOR};
                    text-align: left;
                    padding: 8px;
                    min-height: 70px;
                }}
                QPushButton:checked {{
                    background-color: #3a3a3a;
                    border: 2px solid {PRIMARY_COLOR};
                }}
                QPushButton:hover {{
                    background-color: #333333;
                    border: 1px solid #555555;
                }}
            """)
            
            # Create layout for button content
            btn_layout = QtWidgets.QVBoxLayout(button)
            btn_layout.setContentsMargins(8, 5, 8, 5)
            btn_layout.setSpacing(5)
            
            # Add icon and text
            icon_text = QtWidgets.QLabel(action_type_icons.get(key, ""))
            icon_text.setStyleSheet("font-size: 18px; background-color: transparent; border: none;")
            
            name_text = QtWidgets.QLabel(info['name'])
            name_text.setStyleSheet("font-weight: bold; font-size: 13px; background-color: transparent; border: none;")
            name_text.setWordWrap(True)
            name_text.setAlignment(QtCore.Qt.AlignCenter)
            
            btn_layout.addWidget(icon_text, 0, QtCore.Qt.AlignCenter)
            btn_layout.addWidget(name_text, 0, QtCore.Qt.AlignCenter)
            
            # Connect button to action
            button.clicked.connect(lambda checked, k=key: self.select_action_type(k))
            self.action_type_buttons[key] = button
            
            types_grid.addWidget(button, row, col)
            
            col += 1
            if col >= max_cols:
                col = 0
                row += 1
        
        action_layout.addLayout(types_grid)
        
        # Create container for action form
        self.action_form_container = QtWidgets.QFrame()
        self.action_form_container.setObjectName("actionFormContainer")
        self.action_form_container.setStyleSheet(f"""
            #actionFormContainer {{
                background-color: #1E1E1E;
                border-radius: {BORDER_RADIUS};
                padding: 12px;
                border: 1px solid #2A2A2A;
            }}
        """)
        self.action_form_layout = QtWidgets.QVBoxLayout(self.action_form_container)
        self.action_form_layout.setContentsMargins(10, 10, 10, 10)
        self.action_form_layout.setSpacing(12)
        
        action_layout.addWidget(self.action_form_container)
        content_layout.addWidget(action_card)
        
        # ===== STATUS SECTION =====
        status_card = QtWidgets.QFrame()
        status_card.setProperty("class", "card")
        status_layout = QtWidgets.QHBoxLayout(status_card)
        status_layout.setContentsMargins(15, 15, 15, 15)
        
        status_title = QtWidgets.QLabel("Button Status")
        status_title.setProperty("class", "section-title")
        
        self.enabled_check = QtWidgets.QCheckBox("Enable this button")
        self.enabled_check.setChecked(self.current_config.get("enabled", True))
        self.enabled_check.setStyleSheet(CHECKBOX_STYLE + """
            font-size: 14px;
            padding: 8px;
        """)
        self.enabled_check.setToolTip("When unchecked, this button will not respond to presses")
        
        status_layout.addWidget(status_title)
        status_layout.addStretch()
        status_layout.addWidget(self.enabled_check)
        
        content_layout.addWidget(status_card)
        
        # Add stretch to push everything up
        content_layout.addStretch()
        
        scroll_area.setWidget(content_widget)
        layout.addWidget(scroll_area, 1)  # Add stretch factor
        
        # Action buttons at bottom
        button_section = QtWidgets.QFrame()
        button_section.setObjectName("buttonSection")
        button_section.setStyleSheet(f"""
            #buttonSection {{
                background-color: transparent;
                border-top: 1px solid #333333;
                padding-top: 12px;
            }}
        """)
        button_layout = QtWidgets.QHBoxLayout(button_section)
        button_layout.setContentsMargins(0, 10, 0, 0)
        
        test_button = QtWidgets.QPushButton("Test")
        test_button.setStyleSheet(ACTION_BUTTON_STYLE.replace(PRIMARY_COLOR, SECONDARY_COLOR) + """
            padding: 10px 18px;
            font-weight: bold;
            border-radius: {BORDER_RADIUS};
        """)
        test_button.setToolTip("Test this button's action without saving")
        test_button.clicked.connect(self.test_action)
        
        cancel_button = QtWidgets.QPushButton("Cancel")
        cancel_button.setStyleSheet(ACTION_BUTTON_STYLE.replace(PRIMARY_COLOR, "#555555") + """
            padding: 10px 18px;
            border-radius: {BORDER_RADIUS};
        """)
        cancel_button.clicked.connect(self.reject)
        
        save_button = QtWidgets.QPushButton("Save")
        save_button.setStyleSheet(ACTION_BUTTON_STYLE + """
            padding: 10px 18px;
            font-weight: bold;
            border-radius: {BORDER_RADIUS};
        """)
        save_button.setToolTip("Save this button configuration")
        save_button.clicked.connect(self.save_config)
        
        button_layout.addWidget(test_button)
        button_layout.addStretch()
        button_layout.addWidget(cancel_button)
        button_layout.addWidget(save_button)
        
        layout.addWidget(button_section)
        
        # Initialize form
        self.form_widgets = {}
        # Store current combo box selection as hidden data
        self.action_type_combo = QtWidgets.QComboBox()
        for key, info in action_types.items():
            self.action_type_combo.addItem(info['name'], key)
        
        # Set initial value
        if self.current_config.get("action_type"):
            index = self.action_type_combo.findData(self.current_config["action_type"])
            if index >= 0:
                self.action_type_combo.setCurrentIndex(index)
                
        # Initialize form with current action type
        self.select_action_type(selected_type)

    def select_action_type(self, action_type):
        # Update all buttons
        for key, button in self.action_type_buttons.items():
            button.setChecked(key == action_type)
        
        # Update hidden combo box 
        index = self.action_type_combo.findData(action_type)
        if index >= 0:
            self.action_type_combo.setCurrentIndex(index)
        
        # Update the form
        self.update_action_form()
        
    def update_action_form(self):
        # Clear existing form
        while self.action_form_layout.count():
            item = self.action_form_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        
        self.form_widgets = {}
        action_type = self.action_type_combo.currentData()
        existing_data = self.current_config.get('action_data', {}) if self.current_config.get('action_type') == action_type else {}
        
        # Create form title
        form_title = QtWidgets.QLabel(get_action_types()[action_type]['name'] + " Configuration")
        form_title.setStyleSheet(f"color: {TEXT_COLOR}; font-weight: bold; font-size: 14px; margin-bottom: 8px;")
        self.action_form_layout.addWidget(form_title)
        
        # Add a separator
        separator = QtWidgets.QFrame()
        separator.setFrameShape(QtWidgets.QFrame.HLine)
        separator.setStyleSheet(f"background-color: #333333; max-height: 1px; margin-bottom: 10px;")
        self.action_form_layout.addWidget(separator)
        
        # Common field styling
        field_style = """
            QLabel {
                color: #CCCCCC;
                font-size: 13px;
            }
        """
        
        if action_type == "app" or action_type == "toggle_app":
            # Application path with browse button
            path_frame = QtWidgets.QFrame()
            path_layout = QtWidgets.QHBoxLayout(path_frame)
            path_layout.setContentsMargins(0, 0, 0, 0)
            
            path_label = QtWidgets.QLabel("Application Path:")
            path_label.setStyleSheet(f"color: {TEXT_COLOR};")
            path_label.setMinimumWidth(100)
            
            self.form_widgets["path"] = QtWidgets.QLineEdit(existing_data.get("path", ""))
            self.form_widgets["path"].setStyleSheet(LINEEDIT_STYLE)
            self.form_widgets["path"].setToolTip("Path to the application executable")
            self.form_widgets["path"].setPlaceholderText("Enter application path or browse...")
            
            browse_button = QtWidgets.QPushButton("Browse")
            browse_button.setStyleSheet(ACTION_BUTTON_STYLE.replace(PRIMARY_COLOR, SECONDARY_COLOR))
            browse_button.clicked.connect(lambda: self.browse_file(self.form_widgets["path"]))
            
            path_layout.addWidget(path_label)
            path_layout.addWidget(self.form_widgets["path"])
            path_layout.addWidget(browse_button)
            
            self.action_form_layout.addWidget(path_frame)
            
            # Arguments
            args_frame = QtWidgets.QFrame()
            args_layout = QtWidgets.QHBoxLayout(args_frame)
            args_layout.setContentsMargins(0, 0, 0, 0)
            
            args_label = QtWidgets.QLabel("Arguments:")
            args_label.setStyleSheet(f"color: {TEXT_COLOR};")
            args_label.setMinimumWidth(100)
            
            self.form_widgets["args"] = QtWidgets.QLineEdit(existing_data.get("args", ""))
            self.form_widgets["args"].setStyleSheet(LINEEDIT_STYLE)
            self.form_widgets["args"].setToolTip("Command line arguments to pass to the application")
            self.form_widgets["args"].setPlaceholderText("Command line arguments (optional)")
            
            args_layout.addWidget(args_label)
            args_layout.addWidget(self.form_widgets["args"])
            
            self.action_form_layout.addWidget(args_frame)
            
        elif action_type == "web":
            # URL
            url_frame = QtWidgets.QFrame()
            url_layout = QtWidgets.QHBoxLayout(url_frame)
            url_layout.setContentsMargins(0, 0, 0, 0)
            
            url_label = QtWidgets.QLabel("URL:")
            url_label.setStyleSheet(f"color: {TEXT_COLOR};")
            url_label.setMinimumWidth(100)
            
            self.form_widgets["url"] = QtWidgets.QLineEdit(existing_data.get("url", "https://"))
            self.form_widgets["url"].setStyleSheet(LINEEDIT_STYLE)
            self.form_widgets["url"].setToolTip("Web address to open in default browser")
            self.form_widgets["url"].setPlaceholderText("https://example.com")
            
            url_layout.addWidget(url_label)
            url_layout.addWidget(self.form_widgets["url"])
            
            self.action_form_layout.addWidget(url_frame)
            
        elif action_type == "volume":
            action_frame = QtWidgets.QFrame()
            action_frame.setStyleSheet("background-color: #252525; border-radius: 6px; padding: 10px;")
            action_layout = QtWidgets.QVBoxLayout(action_frame)
            action_layout.setSpacing(10)
            
            # Header with icon
            header_layout = QtWidgets.QHBoxLayout()
            header_icon = QtWidgets.QLabel("🔊")
            header_icon.setStyleSheet("font-size: 16px;")
            header_text = QtWidgets.QLabel("Volume Control")
            header_text.setStyleSheet("font-weight: bold; color: #CCCCCC;")
            header_layout.addWidget(header_icon)
            header_layout.addWidget(header_text)
            header_layout.addStretch()
            action_layout.addLayout(header_layout)
            
            # Control type
            control_layout = QtWidgets.QHBoxLayout()
            action_label = QtWidgets.QLabel("Action:")
            action_label.setStyleSheet(f"color: {TEXT_COLOR};")
            
            self.form_widgets["action"] = QtWidgets.QComboBox()
            self.form_widgets["action"].setStyleSheet(COMBOBOX_STYLE)
            actions = ["increase", "decrease", "mute", "unmute", "set"]
            self.form_widgets["action"].addItems(actions)
            self.form_widgets["action"].setCurrentText(existing_data.get("action", "increase"))
            
            control_layout.addWidget(action_label)
            control_layout.addWidget(self.form_widgets["action"])
            action_layout.addLayout(control_layout)
            
            # Help text
            note_label = QtWidgets.QLabel("Note: For slider control, the action will be 'set'")
            note_label.setStyleSheet("color: #888888; font-style: italic; font-size: 12px;")
            action_layout.addWidget(note_label)
            
            self.action_form_layout.addWidget(action_frame)
            
        elif action_type == "media":
            media_frame = QtWidgets.QFrame()
            media_frame.setStyleSheet("background-color: #252525; border-radius: 6px; padding: 10px;")
            media_layout = QtWidgets.QVBoxLayout(media_frame)
            media_layout.setSpacing(10)
            
            # Header with icon
            header_layout = QtWidgets.QHBoxLayout()
            header_icon = QtWidgets.QLabel("▶️")
            header_icon.setStyleSheet("font-size: 16px;")
            header_text = QtWidgets.QLabel("Media Control")
            header_text.setStyleSheet("font-weight: bold; color: #CCCCCC;")
            header_layout.addWidget(header_icon)
            header_layout.addWidget(header_text)
            header_layout.addStretch()
            media_layout.addLayout(header_layout)
            
            control_layout = QtWidgets.QHBoxLayout()
            media_label = QtWidgets.QLabel("Control:")
            media_label.setStyleSheet(f"color: {TEXT_COLOR};")
            
            self.form_widgets["media"] = QtWidgets.QComboBox()
            self.form_widgets["media"].setStyleSheet(COMBOBOX_STYLE)
            media_controls = get_media_controls()
            self.media_map = {control["name"]: key for key, control in media_controls.items()}
            self.form_widgets["media"].addItems(self.media_map.keys())
            existing_control = existing_data.get("control", "play_pause")
            display_value = next((k for k, v in self.media_map.items() if v == existing_control), "Play/Pause")
            self.form_widgets["media"].setCurrentText(display_value)
            
            control_layout.addWidget(media_label)
            control_layout.addWidget(self.form_widgets["media"])
            media_layout.addLayout(control_layout)
            
            self.action_form_layout.addWidget(media_frame)
            
        elif action_type == "shortcut":
            shortcut_frame = QtWidgets.QFrame()
            shortcut_frame.setStyleSheet("background-color: #252525; border-radius: 6px; padding: 10px;")
            shortcut_layout = QtWidgets.QVBoxLayout(shortcut_frame)
            shortcut_layout.setSpacing(10)
            
            # Header with icon
            header_layout = QtWidgets.QHBoxLayout()
            header_icon = QtWidgets.QLabel("⌨️")
            header_icon.setStyleSheet("font-size: 16px;")
            header_text = QtWidgets.QLabel("Keyboard Shortcut")
            header_text.setStyleSheet("font-weight: bold; color: #CCCCCC;")
            header_layout.addWidget(header_icon)
            header_layout.addWidget(header_text)
            header_layout.addStretch()
            shortcut_layout.addLayout(header_layout)
            
            # Shortcut input
            input_layout = QtWidgets.QHBoxLayout()
            shortcut_label = QtWidgets.QLabel("Shortcut:")
            shortcut_label.setStyleSheet(f"color: {TEXT_COLOR};")
            
            self.form_widgets["shortcut"] = QtWidgets.QLineEdit(existing_data.get("shortcut", ""))
            self.form_widgets["shortcut"].setStyleSheet(LINEEDIT_STYLE)
            self.form_widgets["shortcut"].setPlaceholderText("e.g. ctrl+c, alt+tab, win+r")
            
            input_layout.addWidget(shortcut_label)
            input_layout.addWidget(self.form_widgets["shortcut"])
            shortcut_layout.addLayout(input_layout)
            
            # Help text
            help_label = QtWidgets.QLabel("Examples: ctrl+c, alt+tab, win+r")
            help_label.setStyleSheet("color: #888888; font-style: italic; font-size: 12px;")
            shortcut_layout.addWidget(help_label)
            
            self.action_form_layout.addWidget(shortcut_frame)
            
        elif action_type == "audio_device":
            device_frame = QtWidgets.QFrame()
            device_frame.setStyleSheet("background-color: #252525; border-radius: 6px; padding: 10px;")
            device_layout = QtWidgets.QVBoxLayout(device_frame)
            device_layout.setSpacing(10)
            
            # Header with icon
            header_layout = QtWidgets.QHBoxLayout()
            header_icon = QtWidgets.QLabel("🎧")
            header_icon.setStyleSheet("font-size: 16px;")
            header_text = QtWidgets.QLabel("Audio Device")
            header_text.setStyleSheet("font-weight: bold; color: #CCCCCC;")
            header_layout.addWidget(header_icon)
            header_layout.addWidget(header_text)
            header_layout.addStretch()
            device_layout.addLayout(header_layout)
            
            # Multiple device list section
            device_list_container = QtWidgets.QWidget()
            device_list_layout = QtWidgets.QVBoxLayout(device_list_container)
            device_list_layout.setContentsMargins(0, 0, 0, 0)
            device_list_layout.setSpacing(8)
            
            # Label for device list
            devices_label = QtWidgets.QLabel("Device Names:")
            devices_label.setStyleSheet(f"color: {TEXT_COLOR}; font-weight: bold;")
            device_list_layout.addWidget(devices_label)
            
            # Help text
            help_label = QtWidgets.QLabel("Enter part of device name. If multiple devices are specified, button will cycle through them in order.")
            help_label.setStyleSheet("color: #888888; font-style: italic; font-size: 12px;")
            help_label.setWordWrap(True)
            device_list_layout.addWidget(help_label)
            
            # Container for device entries
            entries_container = QtWidgets.QWidget()
            entries_layout = QtWidgets.QVBoxLayout(entries_container)
            entries_layout.setContentsMargins(0, 0, 0, 0)
            entries_layout.setSpacing(5)
            
            # Load existing device names or create a default entry
            device_names = []
            if isinstance(existing_data.get("device_names"), list):
                device_names = existing_data["device_names"]
            elif existing_data.get("device_name"):
                device_names = [existing_data["device_name"]]
                
            # Ensure we have at least one entry
            if not device_names:
                device_names = [""]
                
            # Function to create a new device entry
            def create_device_entry(name="", index=None):
                entry_frame = QtWidgets.QFrame()
                entry_frame.setStyleSheet("background-color: #2A2A2A; border-radius: 4px; padding: 4px;")
                entry_layout = QtWidgets.QHBoxLayout(entry_frame)
                entry_layout.setContentsMargins(5, 5, 5, 5)
                
                # Create line edit for device name
                device_edit = QtWidgets.QLineEdit(name)
                device_edit.setStyleSheet(LINEEDIT_STYLE)
                device_edit.setPlaceholderText("Enter part of device name")
                
                # Store in form widgets with a unique key
                entry_id = len(self.form_widgets.get("device_entries", []))
                if "device_entries" not in self.form_widgets:
                    self.form_widgets["device_entries"] = []
                self.form_widgets["device_entries"].append(device_edit)
                
                # Remove button
                remove_btn = QtWidgets.QPushButton("×")
                remove_btn.setFixedSize(28, 28)
                remove_btn.setStyleSheet("""
                    QPushButton {
                        background-color: #444444;
                        color: #CCCCCC;
                        border: none;
                        border-radius: 14px;
                        font-weight: bold;
                        font-size: 16px;
                    }
                    QPushButton:hover {
                        background-color: #555555;
                        color: #FFFFFF;
                    }
                """)
                remove_btn.setToolTip("Remove this device")
                
                # Only enable remove if we have more than one entry
                remove_btn.setEnabled(len(self.form_widgets.get("device_entries", [])) > 1)
                
                # Function to remove this entry
                def remove_entry():
                    # Remove from layout and form widgets
                    if entry_frame in entries_layout.parent().findChildren(QtWidgets.QFrame):
                        entries_layout.removeWidget(entry_frame)
                        entry_frame.deleteLater()
                        
                        # Update form widgets
                        if device_edit in self.form_widgets["device_entries"]:
                            self.form_widgets["device_entries"].remove(device_edit)
                            
                            # Update remove buttons state
                            for btn in entries_container.findChildren(QtWidgets.QPushButton):
                                btn.setEnabled(len(self.form_widgets["device_entries"]) > 1)
                
                remove_btn.clicked.connect(remove_entry)
                
                # Add to layout
                entry_layout.addWidget(device_edit)
                entry_layout.addWidget(remove_btn)
                entries_layout.addWidget(entry_frame)
                
                return entry_frame
            
            # Add existing entries
            for device_name in device_names:
                create_device_entry(device_name)
                
            # Add button for new entries
            add_btn = QtWidgets.QPushButton("Add Device")
            add_btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {SECONDARY_COLOR};
                    color: {TEXT_COLOR};
                    border: none;
                    border-radius: 4px;
                    padding: 5px 10px;
                }}
                QPushButton:hover {{
                    background-color: {PRIMARY_COLOR};
                }}
            """)
            
            # Function to add a new entry
            def add_new_entry():
                create_device_entry()
                
                # Enable all remove buttons since we now have multiple entries
                for btn in entries_container.findChildren(QtWidgets.QPushButton):
                    btn.setEnabled(True)
            
            add_btn.clicked.connect(add_new_entry)
            
            # Add everything to device list container
            device_list_layout.addWidget(entries_container)
            device_list_layout.addWidget(add_btn)
            
            # Add container to main layout
            device_layout.addWidget(device_list_container)
            
            self.action_form_layout.addWidget(device_frame)
            
        elif action_type in ["command", "powershell"]:
            commands_frame = QtWidgets.QFrame()
            commands_frame.setStyleSheet("background-color: #252525; border-radius: 6px; padding: 10px;")
            commands_layout = QtWidgets.QVBoxLayout(commands_frame)
            commands_layout.setSpacing(10)
            
            # Header with icon
            header_layout = QtWidgets.QHBoxLayout()
            header_icon = QtWidgets.QLabel("💻" if action_type == "command" else "🖥️")
            header_icon.setStyleSheet("font-size: 16px;")
            header_text = QtWidgets.QLabel(f"{'PowerShell' if action_type == 'powershell' else 'Command Line'} Commands")
            header_text.setStyleSheet("font-weight: bold; color: #CCCCCC;")
            header_layout.addWidget(header_icon)
            header_layout.addWidget(header_text)
            header_layout.addStretch()
            commands_layout.addLayout(header_layout)
            
            # Commands (up to 3)
            commands_list = (existing_data.get("commands", []) + [{}] * 3)[:3]
            for i in range(3):
                cmd_card = QtWidgets.QFrame()
                cmd_card.setStyleSheet("background-color: #2A2A2A; border-radius: 5px; padding: 8px;")
                cmd_layout = QtWidgets.QVBoxLayout(cmd_card)
                cmd_layout.setSpacing(8)
                
                # Command header with number and delay
                header_layout = QtWidgets.QHBoxLayout()
                cmd_number = QtWidgets.QLabel(f"Command {i+1}")
                cmd_number.setStyleSheet("color: #CCCCCC; font-weight: bold;")
                
                delay_layout = QtWidgets.QHBoxLayout()
                delay_label = QtWidgets.QLabel("Delay (ms):")
                delay_label.setStyleSheet("color: #CCCCCC;")
                
                self.form_widgets[f"delay_{i}"] = QtWidgets.QLineEdit(str(commands_list[i].get("delay_ms", 0)))
                self.form_widgets[f"delay_{i}"].setStyleSheet(LINEEDIT_STYLE)
                self.form_widgets[f"delay_{i}"].setFixedWidth(80)
                self.form_widgets[f"delay_{i}"].setValidator(QtGui.QIntValidator(0, 10000))
                
                delay_layout.addWidget(delay_label)
                delay_layout.addWidget(self.form_widgets[f"delay_{i}"])
                
                header_layout.addWidget(cmd_number)
                header_layout.addStretch()
                header_layout.addLayout(delay_layout)
                cmd_layout.addLayout(header_layout)
                
                # Command input field
                self.form_widgets[f"command_{i}"] = QtWidgets.QLineEdit(commands_list[i].get("command", ""))
                self.form_widgets[f"command_{i}"].setStyleSheet(LINEEDIT_STYLE)
                self.form_widgets[f"command_{i}"].setPlaceholderText(f"{'PS' if action_type == 'powershell' else 'CMD'} command {i+1}")
                
                cmd_layout.addWidget(self.form_widgets[f"command_{i}"])
                commands_layout.addWidget(cmd_card)
            
            self.action_form_layout.addWidget(commands_frame)
            
        elif action_type == "text":
            text_frame = QtWidgets.QFrame()
            text_frame.setStyleSheet("background-color: #252525; border-radius: 6px; padding: 10px;")
            text_layout = QtWidgets.QVBoxLayout(text_frame)
            text_layout.setSpacing(10)
            
            # Header with icon
            header_layout = QtWidgets.QHBoxLayout()
            header_icon = QtWidgets.QLabel("📝")
            header_icon.setStyleSheet("font-size: 16px;")
            header_text = QtWidgets.QLabel("Text Input")
            header_text.setStyleSheet("font-weight: bold; color: #CCCCCC;")
            header_layout.addWidget(header_icon)
            header_layout.addWidget(header_text)
            header_layout.addStretch()
            text_layout.addLayout(header_layout)
            
            # Text input label
            text_label = QtWidgets.QLabel("Text to Type:")
            text_label.setStyleSheet(f"color: {TEXT_COLOR};")
            text_layout.addWidget(text_label)
            
            # Replace QLineEdit with QTextEdit for a larger text input area
            self.form_widgets["text"] = QtWidgets.QTextEdit()
            self.form_widgets["text"].setText(existing_data.get("text", ""))
            self.form_widgets["text"].setStyleSheet(f"""
                background-color: #333333;
                color: {TEXT_COLOR};
                border: 1px solid #555555;
                border-radius: 4px;
                padding: 8px;
                font-size: 13px;
            """)
            self.form_widgets["text"].setPlaceholderText("Enter text to be typed")
            self.form_widgets["text"].setMinimumHeight(100)  # Set a taller height
            text_layout.addWidget(self.form_widgets["text"])
            
            # Description
            desc_label = QtWidgets.QLabel("This text will be typed automatically when the button is pressed")
            desc_label.setStyleSheet("color: #888888; font-style: italic; font-size: 12px;")
            desc_label.setWordWrap(True)
            text_layout.addWidget(desc_label)
            
            self.action_form_layout.addWidget(text_frame)
            
        elif action_type == "speech_to_text":
            speech_frame = QtWidgets.QFrame()
            speech_frame.setStyleSheet("background-color: #252525; border-radius: 6px; padding: 10px;")
            speech_layout = QtWidgets.QVBoxLayout(speech_frame)
            speech_layout.setSpacing(10)
            
            # Header with icon
            header_layout = QtWidgets.QHBoxLayout()
            header_icon = QtWidgets.QLabel("🎤")
            header_icon.setStyleSheet("font-size: 16px;")
            header_text = QtWidgets.QLabel("Speech Recognition")
            header_text.setStyleSheet("font-weight: bold; color: #CCCCCC;")
            header_layout.addWidget(header_icon)
            header_layout.addWidget(header_text)
            header_layout.addStretch()
            speech_layout.addLayout(header_layout)
            
            # Language selection
            lang_layout = QtWidgets.QHBoxLayout()
            lang_label = QtWidgets.QLabel("Language:")
            lang_label.setStyleSheet(f"color: {TEXT_COLOR};")
            
            self.form_widgets["language"] = QtWidgets.QComboBox()
            self.form_widgets["language"].setStyleSheet(COMBOBOX_STYLE)
            languages = {
                "English (US)": "en-US",
                "English (UK)": "en-GB",
                "English (Australia)": "en-AU",
                "English (Canada)": "en-CA",
                "English (India)": "en-IN",
                "Russian": "ru-RU",
                "Spanish (Spain)": "es-ES",
                "Spanish (Mexico)": "es-MX",
                "Spanish (US)": "es-US",
                "French (France)": "fr-FR",
                "French (Canada)": "fr-CA",
                "German": "de-DE",
                "Italian": "it-IT",
                "Portuguese (Brazil)": "pt-BR",
                "Portuguese (Portugal)": "pt-PT",
                "Japanese": "ja-JP",
                "Korean": "ko-KR",
                "Chinese (Mandarin)": "zh-CN",
                "Chinese (Taiwan)": "zh-TW",
                "Chinese (Cantonese)": "zh-HK",
                "Arabic": "ar-SA",
                "Dutch": "nl-NL",
                "Swedish": "sv-SE",
                "Danish": "da-DK",
                "Finnish": "fi-FI",
                "Polish": "pl-PL",
                "Greek": "el-GR",
                "Hindi": "hi-IN",
                "Turkish": "tr-TR",
                "Vietnamese": "vi-VN",
                "Thai": "th-TH",
                "Indonesian": "id-ID",
                "Ukrainian": "uk-UA"
            }
            self.language_map = languages
            self.form_widgets["language"].addItems(languages.keys())
            language_code = existing_data.get("language", "en-US")
            display_lang = next((k for k, v in languages.items() if v == language_code), "English (US)")
            self.form_widgets["language"].setCurrentText(display_lang)
            
            lang_layout.addWidget(lang_label)
            lang_layout.addWidget(self.form_widgets["language"])
            speech_layout.addLayout(lang_layout)
            
            # Help text
            help_label = QtWidgets.QLabel("Hold button to record speech, release to convert to text")
            help_label.setStyleSheet("color: #888888; font-style: italic; font-size: 12px;")
            speech_layout.addWidget(help_label)
            
            self.action_form_layout.addWidget(speech_frame)
        
        elif action_type == "ask_chatgpt":
            chatgpt_frame = QtWidgets.QFrame()
            chatgpt_frame.setStyleSheet("background-color: #252525; border-radius: 6px; padding: 10px;")
            chatgpt_layout = QtWidgets.QVBoxLayout(chatgpt_frame)
            chatgpt_layout.setSpacing(10)
            
            # Header with icon
            header_layout = QtWidgets.QHBoxLayout()
            header_icon = QtWidgets.QLabel("🤖")
            header_icon.setStyleSheet("font-size: 16px;")
            header_text = QtWidgets.QLabel("Ask ChatGPT")
            header_text.setStyleSheet("font-weight: bold; color: #CCCCCC;")
            header_layout.addWidget(header_icon)
            header_layout.addWidget(header_text)
            header_layout.addStretch()
            chatgpt_layout.addLayout(header_layout)
            
            # API Key
            api_key_layout = QtWidgets.QHBoxLayout()
            api_key_label = QtWidgets.QLabel("API Key:")
            api_key_label.setStyleSheet(f"color: {TEXT_COLOR};")
            
            self.form_widgets["api_key"] = QtWidgets.QLineEdit(existing_data.get("api_key", ""))
            self.form_widgets["api_key"].setStyleSheet(LINEEDIT_STYLE)
            self.form_widgets["api_key"].setPlaceholderText("Enter your OpenAI API key")
            self.form_widgets["api_key"].setEchoMode(QtWidgets.QLineEdit.Password)
            
            api_key_layout.addWidget(api_key_label)
            api_key_layout.addWidget(self.form_widgets["api_key"])
            chatgpt_layout.addLayout(api_key_layout)
            
            # Model selection
            model_layout = QtWidgets.QHBoxLayout()
            model_label = QtWidgets.QLabel("Model:")
            model_label.setStyleSheet(f"color: {TEXT_COLOR};")
            
            self.form_widgets["model"] = QtWidgets.QComboBox()
            self.form_widgets["model"].setStyleSheet(COMBOBOX_STYLE)
            models = ["gpt-4o", "gpt-4o-mini", "gpt-4", "gpt-3.5-turbo", "gpt-4.1", "gpt-4.1-mini", "gpt-4.1-nano"]
            model_display_names = {
                "gpt-4o": "GPT-4o",
                "gpt-4o-mini": "GPT-4o Mini",
                "gpt-4": "GPT-4",
                "gpt-3.5-turbo": "GPT-3.5 Turbo",
                "gpt-4.1": "GPT-4.1",
                "gpt-4.1-mini": "GPT-4.1 Mini",
                "gpt-4.1-nano": "GPT-4.1 Nano"
            }
            
            for model_id in models:
                self.form_widgets["model"].addItem(model_display_names[model_id], model_id)
            
            current_model = existing_data.get("model", "gpt-4o")
            for i in range(self.form_widgets["model"].count()):
                if self.form_widgets["model"].itemData(i) == current_model:
                    self.form_widgets["model"].setCurrentIndex(i)
                    break
            
            model_layout.addWidget(model_label)
            model_layout.addWidget(self.form_widgets["model"])
            chatgpt_layout.addLayout(model_layout)
            
            # Language selection
            lang_layout = QtWidgets.QHBoxLayout()
            lang_label = QtWidgets.QLabel("Language:")
            lang_label.setStyleSheet(f"color: {TEXT_COLOR};")
            
            self.form_widgets["language_chatgpt"] = QtWidgets.QComboBox()
            self.form_widgets["language_chatgpt"].setStyleSheet(COMBOBOX_STYLE)
            languages = {
                "English (US)": "en-US",
                "English (UK)": "en-GB", 
                "English (Australia)": "en-AU",
                "English (Canada)": "en-CA",
                "English (India)": "en-IN",
                "Russian": "ru-RU",
                "Spanish (Spain)": "es-ES",
                "Spanish (Mexico)": "es-MX",
                "Spanish (US)": "es-US",
                "French (France)": "fr-FR",
                "French (Canada)": "fr-CA",
                "German": "de-DE",
                "Italian": "it-IT",
                "Portuguese (Brazil)": "pt-BR",
                "Portuguese (Portugal)": "pt-PT",
                "Japanese": "ja-JP",
                "Korean": "ko-KR",
                "Chinese (Mandarin)": "zh-CN",
                "Chinese (Taiwan)": "zh-TW",
                "Chinese (Cantonese)": "zh-HK",
                "Arabic": "ar-SA",
                "Dutch": "nl-NL",
                "Swedish": "sv-SE",
                "Danish": "da-DK",
                "Finnish": "fi-FI",
                "Polish": "pl-PL",
                "Greek": "el-GR",
                "Hindi": "hi-IN",
                "Turkish": "tr-TR",
                "Vietnamese": "vi-VN",
                "Thai": "th-TH",
                "Indonesian": "id-ID",
                "Ukrainian": "uk-UA"
            }
            self.language_map_chatgpt = languages
            self.form_widgets["language_chatgpt"].addItems(languages.keys())
            language_code = existing_data.get("language", "en-US")
            display_lang = next((k for k, v in languages.items() if v == language_code), "English (US)")
            self.form_widgets["language_chatgpt"].setCurrentText(display_lang)
            
            lang_layout.addWidget(lang_label)
            lang_layout.addWidget(self.form_widgets["language_chatgpt"])
            chatgpt_layout.addLayout(lang_layout)
            
            # System prompt
            system_layout = QtWidgets.QVBoxLayout()
            system_label = QtWidgets.QLabel("System Prompt:")
            system_label.setStyleSheet(f"color: {TEXT_COLOR};")
            
            self.form_widgets["system_prompt"] = QtWidgets.QTextEdit(existing_data.get("system_prompt", "You are a helpful assistant."))
            self.form_widgets["system_prompt"].setStyleSheet("""
                background-color: #303030;
                color: #CCCCCC;
                border: 1px solid #444444;
                border-radius: 4px;
                padding: 5px;
            """)
            self.form_widgets["system_prompt"].setFixedHeight(80)
            
            system_layout.addWidget(system_label)
            system_layout.addWidget(self.form_widgets["system_prompt"])
            chatgpt_layout.addLayout(system_layout)
            
            # Help text
            help_label = QtWidgets.QLabel("Hold button to record speech, release to send to ChatGPT and paste response")
            help_label.setStyleSheet("color: #888888; font-style: italic; font-size: 12px;")
            chatgpt_layout.addWidget(help_label)
            
            self.action_form_layout.addWidget(chatgpt_frame)
                      
        elif action_type == "text_to_speech":
            # Import the TTS manager to check its availability
            from app.text_to_speech import tts_manager, YANDEX_TTS_AVAILABLE
            
            tts_frame = QtWidgets.QFrame()
            tts_frame.setStyleSheet("background-color: #252525; border-radius: 6px; padding: 10px;")
            tts_layout = QtWidgets.QVBoxLayout(tts_frame)
            tts_layout.setSpacing(10)
            
            # Header with icon
            header_layout = QtWidgets.QHBoxLayout()
            header_icon = QtWidgets.QLabel("🔊")
            header_icon.setStyleSheet("font-size: 16px;")
            header_text = QtWidgets.QLabel("Text to Speech")
            header_text.setStyleSheet("font-weight: bold; color: #CCCCCC;")
            header_layout.addWidget(header_icon)
            header_layout.addWidget(header_text)
            header_layout.addStretch()
            tts_layout.addLayout(header_layout)
            
            if YANDEX_TTS_AVAILABLE:
                # Language selection
                language_layout = QtWidgets.QHBoxLayout()
                language_label = QtWidgets.QLabel("Language:")
                language_label.setMinimumWidth(100)
                language_label.setStyleSheet(f"color: {TEXT_COLOR};")
                
                self.form_widgets["language"] = QtWidgets.QComboBox()
                self.form_widgets["language"].setStyleSheet(COMBOBOX_STYLE)
                
                # Add languages from TTS manager
                languages = tts_manager.get_language_list()
                for code, name in languages.items():
                    self.form_widgets["language"].addItem(name, code)
                
                # Set current language
                current_language = existing_data.get("language", "auto")
                for i in range(self.form_widgets["language"].count()):
                    if self.form_widgets["language"].itemData(i) == current_language:
                        self.form_widgets["language"].setCurrentIndex(i)
                        break
                
                language_layout.addWidget(language_label)
                language_layout.addWidget(self.form_widgets["language"])
                tts_layout.addLayout(language_layout)
                
                # Voice selection (depends on language)
                voice_layout = QtWidgets.QHBoxLayout()
                voice_label = QtWidgets.QLabel("Voice:")
                voice_label.setMinimumWidth(100)
                voice_label.setStyleSheet(f"color: {TEXT_COLOR};")
                
                self.form_widgets["voice"] = QtWidgets.QComboBox()
                self.form_widgets["voice"].setStyleSheet(COMBOBOX_STYLE)
                
                # Update voice options when language changes
                def update_voices():
                    lang_code = self.form_widgets["language"].currentData()
                    self.form_widgets["voice"].clear()
                    voices = tts_manager.get_voice_list(lang_code)
                    for code, name in voices.items():
                        self.form_widgets["voice"].addItem(name, code)
                    
                    # Try to restore previous voice selection
                    current_voice = existing_data.get("voice", "auto")
                    for i in range(self.form_widgets["voice"].count()):
                        if self.form_widgets["voice"].itemData(i) == current_voice:
                            self.form_widgets["voice"].setCurrentIndex(i)
                            break
                
                # Connect language change to voice update
                self.form_widgets["language"].currentIndexChanged.connect(update_voices)
                
                # Initialize voices
                update_voices()
                
                voice_layout.addWidget(voice_label)
                voice_layout.addWidget(self.form_widgets["voice"])
                tts_layout.addLayout(voice_layout)
                
                # Voice mood
                mood_layout = QtWidgets.QHBoxLayout()
                mood_label = QtWidgets.QLabel("Voice Mood:")
                mood_label.setMinimumWidth(100)
                mood_label.setStyleSheet(f"color: {TEXT_COLOR};")
                
                self.form_widgets["mood"] = QtWidgets.QComboBox()
                self.form_widgets["mood"].setStyleSheet(COMBOBOX_STYLE)
                
                # Add moods
                moods = tts_manager.get_mood_list()
                for code, name in moods.items():
                    self.form_widgets["mood"].addItem(name, code)
                
                # Set current mood
                current_mood = existing_data.get("mood", "neutral")
                for i in range(self.form_widgets["mood"].count()):
                    if self.form_widgets["mood"].itemData(i) == current_mood:
                        self.form_widgets["mood"].setCurrentIndex(i)
                        break
                
                mood_layout.addWidget(mood_label)
                mood_layout.addWidget(self.form_widgets["mood"])
                tts_layout.addLayout(mood_layout)
                
                # Audio frequency
                freq_layout = QtWidgets.QHBoxLayout()
                freq_label = QtWidgets.QLabel("Audio Quality:")
                freq_label.setMinimumWidth(100)
                freq_label.setStyleSheet(f"color: {TEXT_COLOR};")
                
                self.form_widgets["frequency"] = QtWidgets.QComboBox()
                self.form_widgets["frequency"].setStyleSheet(COMBOBOX_STYLE)
                
                # Add frequencies
                frequencies = tts_manager.get_frequency_list()
                for code, name in frequencies.items():
                    self.form_widgets["frequency"].addItem(name, code)
                
                # Set current frequency
                current_freq = existing_data.get("frequency", "24000")
                for i in range(self.form_widgets["frequency"].count()):
                    if self.form_widgets["frequency"].itemData(i) == current_freq:
                        self.form_widgets["frequency"].setCurrentIndex(i)
                        break
                
                freq_layout.addWidget(freq_label)
                freq_layout.addWidget(self.form_widgets["frequency"])
                tts_layout.addLayout(freq_layout)
                
                # Text source
                source_layout = QtWidgets.QHBoxLayout()
                source_label = QtWidgets.QLabel("Text Source:")
                source_label.setMinimumWidth(100)
                source_label.setStyleSheet(f"color: {TEXT_COLOR};")
                
                self.form_widgets["text_source"] = QtWidgets.QComboBox()
                self.form_widgets["text_source"].setStyleSheet(COMBOBOX_STYLE)
                self.form_widgets["text_source"].addItem("Clipboard", "clipboard")
                self.form_widgets["text_source"].addItem("Selection (auto-copy)", "selection")
                # could add more sources in the future
                
                # Set current source
                current_source = existing_data.get("text_source", "clipboard")
                for i in range(self.form_widgets["text_source"].count()):
                    if self.form_widgets["text_source"].itemData(i) == current_source:
                        self.form_widgets["text_source"].setCurrentIndex(i)
                        break
                
                source_layout.addWidget(source_label)
                source_layout.addWidget(self.form_widgets["text_source"])
                tts_layout.addLayout(source_layout)
                
                # Instructions
                help_label = QtWidgets.QLabel(
                    "When button is pressed, the text will be spoken using "
                    "the Yandex Text-to-Speech engine. You can choose between two text sources:\n"
                    "- Clipboard: uses text that's already in your clipboard\n"
                    "- Selection: automatically copies currently selected text first"
                )
                help_label.setWordWrap(True)
                help_label.setStyleSheet("color: #888888; font-style: italic; font-size: 12px;")
                tts_layout.addWidget(help_label)
                
            else:
                # Show error if TTS not available
                error_label = QtWidgets.QLabel(
                    "The Yandex Text-to-Speech engine is not available. "
                    "Please install it with 'pip install yandex-tts-free'."
                )
                error_label.setWordWrap(True)
                error_label.setStyleSheet("color: #ff6666; font-style: italic;")
                tts_layout.addWidget(error_label)
            
            self.action_form_layout.addWidget(tts_frame)
        
        elif action_type == "wake_on_lan":
            # Create a styled frame for the Wake-on-LAN configuration
            wol_frame = QtWidgets.QFrame()
            wol_frame.setStyleSheet("background-color: #252525; border-radius: 6px; padding: 10px;")
            wol_layout = QtWidgets.QVBoxLayout(wol_frame)
            wol_layout.setSpacing(10)
            
            # Header with icon
            header_layout = QtWidgets.QHBoxLayout()
            header_icon = QtWidgets.QLabel("⚡")
            header_icon.setStyleSheet("font-size: 16px;")
            header_text = QtWidgets.QLabel("Wake On LAN")
            header_text.setStyleSheet("font-weight: bold; color: #CCCCCC;")
            header_layout.addWidget(header_icon)
            header_layout.addWidget(header_text)
            header_layout.addStretch()
            wol_layout.addLayout(header_layout)
            
            # MAC Address field
            mac_layout = QtWidgets.QHBoxLayout()
            mac_label = QtWidgets.QLabel("MAC Address:")
            mac_label.setStyleSheet(f"color: {TEXT_COLOR};")
            
            self.form_widgets["mac_address"] = QtWidgets.QLineEdit(existing_data.get("mac_address", ""))
            self.form_widgets["mac_address"].setStyleSheet(LINEEDIT_STYLE)
            self.form_widgets["mac_address"].setPlaceholderText("00:11:22:33:44:55")
            self.form_widgets["mac_address"].setToolTip("MAC address of the device to wake up (e.g. 00:11:22:33:44:55)")
            
            mac_layout.addWidget(mac_label)
            mac_layout.addWidget(self.form_widgets["mac_address"])
            wol_layout.addLayout(mac_layout)
            
            # IP Address field (subnet broadcast)
            ip_layout = QtWidgets.QHBoxLayout()
            ip_label = QtWidgets.QLabel("IP Address:")
            ip_label.setStyleSheet(f"color: {TEXT_COLOR};")
            
            self.form_widgets["ip_address"] = QtWidgets.QLineEdit(existing_data.get("ip_address", "255.255.255.255"))
            self.form_widgets["ip_address"].setStyleSheet(LINEEDIT_STYLE)
            self.form_widgets["ip_address"].setPlaceholderText("255.255.255.255")
            self.form_widgets["ip_address"].setToolTip("IP address to send the packet to (default broadcast: 255.255.255.255)")
            
            ip_layout.addWidget(ip_label)
            ip_layout.addWidget(self.form_widgets["ip_address"])
            wol_layout.addLayout(ip_layout)
            
            # Port field (optional)
            port_layout = QtWidgets.QHBoxLayout()
            port_label = QtWidgets.QLabel("Port (Optional):")
            port_label.setStyleSheet(f"color: {TEXT_COLOR};")
            
            self.form_widgets["port"] = QtWidgets.QLineEdit(str(existing_data.get("port", "")))
            self.form_widgets["port"].setStyleSheet(LINEEDIT_STYLE)
            self.form_widgets["port"].setPlaceholderText("Leave empty for default (9)")
            self.form_widgets["port"].setToolTip("Optional: UDP port to send the magic packet (default: 9)")
            self.form_widgets["port"].setMaximumWidth(200)
            
            port_layout.addWidget(port_label)
            port_layout.addWidget(self.form_widgets["port"])
            port_layout.addStretch()
            wol_layout.addLayout(port_layout)
            
            # Help text
            help_text = QtWidgets.QLabel(
                "Wake On LAN sends a 'magic packet' to wake up a device on your network. "
                "The target device must have Wake-on-LAN enabled in its BIOS/UEFI settings."
            )
            help_text.setStyleSheet("color: #888888; font-style: italic; font-size: 12px;")
            help_text.setWordWrap(True)
            wol_layout.addWidget(help_text)
            
            self.action_form_layout.addWidget(wol_frame)
        
        elif action_type == "webos_tv":
            # Create a styled frame for the WebOS TV control configuration
            webos_frame = QtWidgets.QFrame()
            webos_frame.setStyleSheet("background-color: #252525; border-radius: 6px; padding: 10px;")
            webos_layout = QtWidgets.QVBoxLayout(webos_frame)
            webos_layout.setSpacing(10)
            
            # Header with icon
            header_layout = QtWidgets.QHBoxLayout()
            header_icon = QtWidgets.QLabel("📺")
            header_icon.setStyleSheet("font-size: 16px;")
            header_text = QtWidgets.QLabel("WebOS TV Control")
            header_text.setStyleSheet("font-weight: bold; color: #CCCCCC;")
            header_layout.addWidget(header_icon)
            header_layout.addWidget(header_text)
            header_layout.addStretch()
            webos_layout.addLayout(header_layout)
            
            # IP Address field
            ip_layout = QtWidgets.QHBoxLayout()
            ip_label = QtWidgets.QLabel("TV IP Address:")
            ip_label.setStyleSheet(f"color: {TEXT_COLOR};")
            
            # Get saved TVs if WebOS module is available
            saved_tvs = {}
            if WEBOS_AVAILABLE:
                try:
                    saved_tvs = webos_manager.get_known_tvs()
                except Exception as e:
                    logger.error(f"Error getting known TVs: {e}")
            
            # If we have saved TVs, show a dropdown with them
            if saved_tvs:
                self.form_widgets["ip"] = QtWidgets.QComboBox()
                self.form_widgets["ip"].setStyleSheet(COMBOBOX_STYLE)
                self.form_widgets["ip"].addItem("New TV...", "")
                
                # Add saved TVs to dropdown
                selected_index = 0
                selected_ip = existing_data.get("ip", "")
                idx = 1
                
                for tv_ip, tv_name in saved_tvs.items():
                    self.form_widgets["ip"].addItem(f"{tv_name} ({tv_ip})", tv_ip)
                    if tv_ip == selected_ip:
                        selected_index = idx
                    idx += 1
                
                # Select the previously saved TV if it exists
                self.form_widgets["ip"].setCurrentIndex(selected_index)
                
                # Add custom IP field that shows when "New TV..." is selected
                custom_ip_layout = QtWidgets.QHBoxLayout()
                self.form_widgets["custom_ip"] = QtWidgets.QLineEdit()
                self.form_widgets["custom_ip"].setStyleSheet(LINEEDIT_STYLE)
                self.form_widgets["custom_ip"].setPlaceholderText("192.168.1.x")
                self.form_widgets["custom_ip"].setToolTip("IP address of your LG WebOS TV")
                
                if selected_index == 0:
                    self.form_widgets["custom_ip"].setText(selected_ip)
                
                custom_ip_layout.addWidget(QtWidgets.QLabel("   "))  # Indent
                custom_ip_layout.addWidget(self.form_widgets["custom_ip"])
                
                # Connect selection change to update custom IP visibility
                def update_custom_ip_visibility():
                    self.form_widgets["custom_ip"].setVisible(self.form_widgets["ip"].currentIndex() == 0)
                
                self.form_widgets["ip"].currentIndexChanged.connect(update_custom_ip_visibility)
                # Set initial visibility
                self.form_widgets["custom_ip"].setVisible(selected_index == 0)
            else:
                # Simple IP input field if no saved TVs
                self.form_widgets["ip"] = QtWidgets.QLineEdit(existing_data.get("ip", ""))
                self.form_widgets["ip"].setStyleSheet(LINEEDIT_STYLE)
                self.form_widgets["ip"].setPlaceholderText("192.168.1.x")
                self.form_widgets["ip"].setToolTip("IP address of your LG WebOS TV")
            
            ip_layout.addWidget(ip_label)
            ip_layout.addWidget(self.form_widgets["ip"])
            webos_layout.addLayout(ip_layout)
            
            if saved_tvs:
                webos_layout.addLayout(custom_ip_layout)
            
            # Connection status and Connect button
            status_layout = QtWidgets.QHBoxLayout()
            self.form_widgets["connection_status"] = QtWidgets.QLabel("Status: Not connected")
            self.form_widgets["connection_status"].setStyleSheet("color: #888888;")
            
            self.form_widgets["connect_button"] = QtWidgets.QPushButton("Connect")
            self.form_widgets["connect_button"].setStyleSheet(ACTION_BUTTON_STYLE)
            self.form_widgets["connect_button"].clicked.connect(self.connect_to_webos_tv)
            
            status_layout.addWidget(self.form_widgets["connection_status"])
            status_layout.addStretch()
            status_layout.addWidget(self.form_widgets["connect_button"])
            webos_layout.addLayout(status_layout)
            
            # Add separator
            separator = QtWidgets.QFrame()
            separator.setFrameShape(QtWidgets.QFrame.HLine)
            separator.setFrameStyle(QtWidgets.QFrame.Sunken)
            separator.setStyleSheet("background-color: #333333; max-height: 1px;")
            webos_layout.addWidget(separator)
            
            # Command section
            command_layout = QtWidgets.QVBoxLayout()
            command_label = QtWidgets.QLabel("Command:")
            command_label.setStyleSheet(f"color: {TEXT_COLOR}; font-weight: bold;")
            command_layout.addWidget(command_label)
            
            # Command category selection
            category_layout = QtWidgets.QHBoxLayout()
            category_label = QtWidgets.QLabel("Category:")
            category_label.setStyleSheet(f"color: {TEXT_COLOR};")
            
            self.form_widgets["command_category"] = QtWidgets.QComboBox()
            self.form_widgets["command_category"].setStyleSheet(COMBOBOX_STYLE)
            self.form_widgets["command_category"].addItem("Built-in Commands", "builtin")
            self.form_widgets["command_category"].addItem("Custom Command", "custom")
            
            category_layout.addWidget(category_label)
            category_layout.addWidget(self.form_widgets["command_category"])
            command_layout.addLayout(category_layout)
            
            # Command selection (for built-in commands)
            self.form_widgets["command"] = QtWidgets.QComboBox()
            self.form_widgets["command"].setStyleSheet(COMBOBOX_STYLE)
            
            # Get available commands if WebOS module is available
            if WEBOS_AVAILABLE:
                commands = webos_manager.get_command_list()
                for cmd_name, cmd_info in commands.items():
                    self.form_widgets["command"].addItem(f"{cmd_name}: {cmd_info['description']}", cmd_info['command'])
                    
                # Select the saved command if it exists
                saved_command = existing_data.get("command", "")
                for i in range(self.form_widgets["command"].count()):
                    if self.form_widgets["command"].itemData(i) == saved_command:
                        self.form_widgets["command"].setCurrentIndex(i)
                        break
            
            # Custom command input
            self.form_widgets["custom_command"] = QtWidgets.QLineEdit(existing_data.get("command", ""))
            self.form_widgets["custom_command"].setStyleSheet(LINEEDIT_STYLE)
            self.form_widgets["custom_command"].setPlaceholderText("e.g. button/HOME, media.controls/play, launcher/netflix")
            
            # Function to toggle visibility based on category selection
            def update_command_inputs():
                is_custom = self.form_widgets["command_category"].currentData() == "custom"
                self.form_widgets["command"].setVisible(not is_custom)
                self.form_widgets["custom_command"].setVisible(is_custom)
            
            # Set initial category based on existing data
            if "command" in existing_data:
                # Check if the command matches any built-in command
                command_found = False
                if WEBOS_AVAILABLE:
                    for i in range(self.form_widgets["command"].count()):
                        if self.form_widgets["command"].itemData(i) == existing_data["command"]:
                            command_found = True
                            self.form_widgets["command_category"].setCurrentIndex(0)  # Built-in
                            break
                
                # If not found or if webos isn't available, assume custom
                if not command_found:
                    self.form_widgets["command_category"].setCurrentIndex(1)  # Custom
                    self.form_widgets["custom_command"].setText(existing_data["command"])
            
            # Connect category change to update visibility
            self.form_widgets["command_category"].currentIndexChanged.connect(update_command_inputs)
            
            # Add command widgets to layout
            command_layout.addWidget(self.form_widgets["command"])
            command_layout.addWidget(self.form_widgets["custom_command"])
            
            # Set initial visibility based on category
            update_command_inputs()
            
            webos_layout.addLayout(command_layout)
            
            # Help text
            help_text = QtWidgets.QLabel(
                "Control an LG TV with WebOS. First connect to save the pairing key, then select a command to send. "
                "The TV will auto-connect in the future when this button is pressed."
            )
            help_text.setStyleSheet("color: #888888; font-style: italic; font-size: 12px;")
            help_text.setWordWrap(True)
            webos_layout.addWidget(help_text)
            
            self.action_form_layout.addWidget(webos_frame)
            
            # Check connection status if we have an IP
            if isinstance(self.form_widgets.get("ip"), QtWidgets.QComboBox):
                ip = self.form_widgets["ip"].currentData()
                if ip:
                    self.check_webos_connection_status(ip)
            else:
                ip = self.form_widgets.get("ip", QtWidgets.QLineEdit()).text().strip()
                if ip:
                    self.check_webos_connection_status(ip)
        
        # Add default message for unknown action types
        else:
            logger.warning(f"Unknown action type: {action_type}")
            self.message_signal.emit(f"Unknown action type: {action_type}")
        
        # Add stretch to ensure everything aligns to the top
        self.action_form_layout.addStretch()

    def get_action_data(self):
        """Get action data from the form based on selected action type"""
        action_type = self.action_type_combo.currentData()
        action_data = {}
        if action_type == "app" or action_type == "toggle_app":
            return {
                "path": self.form_widgets.get("path", QtWidgets.QLineEdit()).text(),
                "args": self.form_widgets.get("args", QtWidgets.QLineEdit()).text(),
            }
            
        elif action_type == "web":
            return {
                "url": self.form_widgets.get("url", QtWidgets.QLineEdit()).text(),
            }
            
        elif action_type == "volume":
            return {
                "action": self.form_widgets.get("action", QtWidgets.QComboBox()).currentText(),
                "value": None,  # Value will be set when used with a slider
            }
            
        elif action_type == "media":
            media_display = self.form_widgets.get("media", QtWidgets.QComboBox()).currentText()
            return {
                "control": self.media_map.get(media_display, "play_pause"),
            }
            
        elif action_type == "shortcut":
            return {
                "shortcut": self.form_widgets.get("shortcut", QtWidgets.QLineEdit()).text(),
            }
            
        elif action_type == "audio_device":
            device_entries = self.form_widgets.get("device_entries", [])
            device_names = [entry.text() for entry in device_entries if entry.text().strip()]
            
            # If no devices are specified, return empty device_name to toggle between all
            if not device_names:
                return {
                    "device_name": "",
                }
            
            # If only one device, use the original format for backward compatibility
            if len(device_names) == 1:
                return {
                    "device_name": device_names[0],
                }
            
            # Multiple devices - use new format with list
            return {
                "device_names": device_names,
                "device_name": device_names[0],  # For backwards compatibility
            }
            
        elif action_type == "text":
            return {
                "text": self.form_widgets.get("text", QtWidgets.QTextEdit()).toPlainText(),
            }
            
        elif action_type == "command" or action_type == "powershell":
            commands = []
            for i in range(3):
                command = self.form_widgets.get(f"command_{i}", QtWidgets.QLineEdit()).text()
                if command:
                    try:
                        delay = int(self.form_widgets.get(f"delay_{i}", QtWidgets.QLineEdit()).text() or "0")
                    except ValueError:
                        delay = 0
                        
                    commands.append({
                        "command": command,
                        "delay_ms": delay
                    })
            return {
                "commands": commands,
            }
            
        elif action_type == "speech_to_text":
            language_display = self.form_widgets.get("language", QtWidgets.QComboBox()).currentText()
            return {
                "language": self.language_map.get(language_display, "en-US"),
            }
            
        elif action_type == "ask_chatgpt":
                action_data["api_key"] = self.form_widgets.get("api_key", QtWidgets.QLineEdit()).text()
                model_combobox = self.form_widgets.get("model", QtWidgets.QComboBox())
                model_index = model_combobox.currentIndex()
                action_data["model"] = model_combobox.itemData(model_index)
                action_data["language"] = self.language_map_chatgpt.get(self.form_widgets.get("language_chatgpt", QtWidgets.QComboBox()).currentText(), "en-US")
                action_data["system_prompt"] = self.form_widgets.get("system_prompt", QtWidgets.QTextEdit()).toPlainText()
                return action_data
            
        elif action_type == "text_to_speech":
            return {
                "language": self.form_widgets.get("language", QtWidgets.QComboBox()).currentData(),
                "voice": self.form_widgets.get("voice", QtWidgets.QComboBox()).currentData(),
                "mood": self.form_widgets.get("mood", QtWidgets.QComboBox()).currentData(),
                "frequency": self.form_widgets.get("frequency", QtWidgets.QComboBox()).currentData(),
                "text_source": self.form_widgets.get("text_source", QtWidgets.QComboBox()).currentData(),
            }
            
        elif action_type == "wake_on_lan":
            action_data = {
                "mac_address": self.form_widgets.get("mac_address", QtWidgets.QLineEdit()).text(),
                "ip_address": self.form_widgets.get("ip_address", QtWidgets.QLineEdit()).text()
            }
            
            # Only add port if it's specified
            port_text = self.form_widgets.get("port", QtWidgets.QLineEdit()).text().strip()
            if port_text:
                try:
                    port = int(port_text)
                    action_data["port"] = port
                except ValueError:
                    # If conversion fails, don't include port
                    pass
                    
            return action_data
        
        elif action_type == "webos_tv":
            # Get IP address based on widget type
            if hasattr(self, "form_widgets") and isinstance(self.form_widgets.get("ip"), QtWidgets.QComboBox):
                if self.form_widgets["ip"].currentIndex() == 0:  # "New TV..." option
                    ip = self.form_widgets.get("custom_ip", QtWidgets.QLineEdit()).text().strip()
                else:
                    ip = self.form_widgets["ip"].currentData()
            else:
                # Check the type of the widget to handle it correctly
                ip_widget = self.form_widgets.get("ip")
                if isinstance(ip_widget, QtWidgets.QComboBox):
                    if ip_widget.currentIndex() == 0:
                        ip = self.form_widgets.get("custom_ip", QtWidgets.QLineEdit()).text().strip()
                    else:
                        ip = ip_widget.currentData()
                elif isinstance(ip_widget, QtWidgets.QLineEdit):
                    ip = ip_widget.text().strip()
                else:
                    # Fallback case
                    ip = ""
                    logger.warning(f"Unexpected widget type for IP in get_action_data: {type(ip_widget)}")
            
            # Get command based on category selection
            command = ""
            if self.form_widgets.get("command_category", QtWidgets.QComboBox()).currentData() == "custom":
                command = self.form_widgets.get("custom_command", QtWidgets.QLineEdit()).text().strip()
            else:
                command_widget = self.form_widgets.get("command", QtWidgets.QComboBox())
                if command_widget and command_widget.currentData():
                    command = command_widget.currentData()
            
            return {
                "ip": ip,
                "command": command
            }
        
        # Default - empty data
        return {}

    def browse_file(self, entry):
        file_path = QtWidgets.QFileDialog.getOpenFileName(self, "Select Application", "", "Executable files (*.exe);;All files (*.*);;Shortcut files (*.lnk)")[0]
        if file_path:
            entry.setText(file_path)
            
    def save_config(self):
        # Keep existing functionality
        button_name = self.button_name_entry.text().strip()
        self.parent.mapping['button_names'][str(self.button_id)] = button_name
        action_type = self.action_type_combo.currentData()
        is_enabled = self.enabled_check.isChecked()
        
        # Create config
        config = {
            "name": button_name,
            "action_type": action_type,
            "action_data": self.get_action_data(),
            "enabled": is_enabled
        }
        
        # Save button config to file
        save_button_config(self.button_id, config)
        
        # IMPORTANT: Update in-memory button config to fix issue with newly saved configs not working until restart
        self.parent.button_config[str(self.button_id)] = config
        
        # Update button label in main window
        self.parent.update_button_label(self.button_id, action_type, button_name)
        
        self.accept()
        
    def test_action(self):
        # Keep existing functionality
        action_type = self.action_type_combo.currentData()
        action_data = self.get_action_data()
        
        # Prepare value for executing the action
        value = None
        if action_type == "speech_to_text":
            value = action_data
        
        # Execute the action
        self.parent.execute_button_action(self.button_id, value)
        
    def connect_to_webos_tv(self):
        """Connect to WebOS TV during configuration"""
        if not WEBOS_AVAILABLE:
            QtWidgets.QMessageBox.warning(
                self, 
                "Module Not Available", 
                "WebOS TV module is not available. Install aiowebostv with 'pip install aiowebostv'"
            )
            return
            
        # Get IP address
        if hasattr(self.form_widgets, "ip") and isinstance(self.form_widgets.get("ip"), QtWidgets.QComboBox):
            if self.form_widgets["ip"].currentIndex() == 0:  # "New TV..." option
                ip = self.form_widgets.get("custom_ip", QtWidgets.QLineEdit()).text().strip()
            else:
                ip = self.form_widgets["ip"].currentData()
        else:
            # Check the type of the widget to handle it correctly
            ip_widget = self.form_widgets.get("ip")
            if isinstance(ip_widget, QtWidgets.QComboBox):
                if ip_widget.currentIndex() == 0:
                    ip = self.form_widgets.get("custom_ip", QtWidgets.QLineEdit()).text().strip()
                else:
                    ip = ip_widget.currentData()
            elif isinstance(ip_widget, QtWidgets.QLineEdit):
                ip = ip_widget.text().strip()
            else:
                # Fallback case
                ip = ""
                logger.warning(f"Unexpected widget type for IP: {type(ip_widget)}")
            
        if not ip:
            QtWidgets.QMessageBox.warning(
                self, 
                "Missing IP Address", 
                "Please enter the IP address of your LG TV."
            )
            return
            
        # Update status
        self.form_widgets["connection_status"].setText("Status: Connecting...")
        self.form_widgets["connection_status"].setStyleSheet("color: #FFA500;")  # Orange
        self.form_widgets["connect_button"].setEnabled(False)
        
        # Create a progress dialog
        progress = QtWidgets.QProgressDialog("Connecting to TV...", "Cancel", 0, 0, self)
        progress.setWindowTitle("Connecting")
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(500)  # Show after 500ms
        progress.setCancelButton(None)  # No cancel button
        progress.setMinimumWidth(300)
        
        # Run connection in a thread
        def connect_thread():
            try:
                success = False
                key = None
                
                def run_async():
                    async def async_connect():
                        nonlocal success, key
                        try:
                            # Try to get saved client key
                            client_key = None
                            if ip in webos_manager.config:
                                client_key = webos_manager.config[ip].get("client_key")
                                
                            # Connect to TV
                            connect_success, new_key = await webos_manager.connect(ip, client_key)
                            success = connect_success
                            key = new_key
                        except Exception as e:
                            logger.error(f"Error connecting to WebOS TV: {e}")
                            success = False
                    
                    # Create and run event loop
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    try:
                        loop.run_until_complete(async_connect())
                    finally:
                        loop.close()
                
                run_async()
                
                # Update UI on main thread
                QtCore.QMetaObject.invokeMethod(
                    self, "webos_connection_complete", 
                    Qt.QueuedConnection, 
                    QtCore.Q_ARG(bool, success),
                    QtCore.Q_ARG(str, ip),
                    QtCore.Q_ARG(str, key or "")
                )
                
            except Exception as e:
                logger.error(f"Error in WebOS TV connection thread: {e}")
                # Update UI on failure
                QtCore.QMetaObject.invokeMethod(
                    self, "webos_connection_complete", 
                    Qt.QueuedConnection, 
                    QtCore.Q_ARG(bool, False),
                    QtCore.Q_ARG(str, ip),
                    QtCore.Q_ARG(str, "")
                )
                
            # Close progress dialog
            QtCore.QMetaObject.invokeMethod(
                progress, "close", 
                Qt.QueuedConnection
            )
        
        # Start the thread
        threading.Thread(target=connect_thread).start()
    
    @QtCore.Slot(bool, str, str)
    def webos_connection_complete(self, success, ip, key):
        """Handle WebOS TV connection completion"""
        self.form_widgets["connect_button"].setEnabled(True)
        
        if success:
            self.form_widgets["connection_status"].setText("Status: Connected ✅")
            self.form_widgets["connection_status"].setStyleSheet("color: #50fa7b;")  # Green
            
            # Show success message
            tv_name = webos_manager.config.get(ip, {}).get("name", f"LG TV ({ip})")
            QtWidgets.QMessageBox.information(
                self, 
                "Connection Successful", 
                f"Successfully connected to {tv_name}.\n\nYour TV has been paired and will auto-connect when you use this button."
            )
            
            # If we were using the combobox and this was a new TV, refresh the list
            if hasattr(self.form_widgets, "ip") and isinstance(self.form_widgets.get("ip"), QtWidgets.QComboBox):
                # Temporarily block signals
                self.form_widgets["ip"].blockSignals(True)
                
                # Save current selection and custom IP
                was_custom = self.form_widgets["ip"].currentIndex() == 0
                custom_ip = self.form_widgets["custom_ip"].text().strip()
                
                # Refresh TV list
                self.form_widgets["ip"].clear()
                self.form_widgets["ip"].addItem("New TV...", "")
                
                # Get updated TV list
                saved_tvs = webos_manager.get_known_tvs()
                selected_index = 0
                
                # Add saved TVs
                idx = 1
                for tv_ip, tv_name in saved_tvs.items():
                    self.form_widgets["ip"].addItem(f"{tv_name} ({tv_ip})", tv_ip)
                    if tv_ip == ip:
                        selected_index = idx
                    idx += 1
                    
                # Restore selection
                if was_custom and ip not in saved_tvs:
                    self.form_widgets["ip"].setCurrentIndex(0)
                    self.form_widgets["custom_ip"].setText(custom_ip)
                else:
                    self.form_widgets["ip"].setCurrentIndex(selected_index)
                    
                # Restore signals
                self.form_widgets["ip"].blockSignals(False)
                
                # Force update of custom IP visibility
                if hasattr(self.form_widgets, "custom_ip"):
                    visible = self.form_widgets["ip"].currentIndex() == 0
                    self.form_widgets["custom_ip"].setVisible(visible)
        else:
            self.form_widgets["connection_status"].setText("Status: Connection failed ❌")
            self.form_widgets["connection_status"].setStyleSheet("color: #ff5555;")  # Red
            
            # Show error message
            QtWidgets.QMessageBox.warning(
                self, 
                "Connection Failed", 
                f"Failed to connect to TV at {ip}.\n\nPlease make sure:\n- The TV is powered on\n- The TV is connected to your network\n- The IP address is correct\n- The TV is running WebOS"
            )
    
    def check_webos_connection_status(self, ip):
        """Check WebOS TV connection status for an existing configuration"""
        if not WEBOS_AVAILABLE or not ip:
            return
            
        # Get current status
        status = webos_manager.get_connection_status(ip)
        
        # Update status display
        if status == "connected":
            self.form_widgets["connection_status"].setText("Status: Connected ✅")
            self.form_widgets["connection_status"].setStyleSheet("color: #50fa7b;")  # Green
        elif status == "connecting":
            self.form_widgets["connection_status"].setText("Status: Connecting...")
            self.form_widgets["connection_status"].setStyleSheet("color: #FFA500;")  # Orange
        elif status == "error":
            self.form_widgets["connection_status"].setText("Status: Connection error ❌")
            self.form_widgets["connection_status"].setStyleSheet("color: #ff5555;")  # Red
        else:
            self.form_widgets["connection_status"].setText("Status: Not connected")
            self.form_widgets["connection_status"].setStyleSheet("color: #888888;")  # Gray

class NotificationSettingsDialog(QtWidgets.QDialog):
    def __init__(self, parent, notification_manager):
        super().__init__(parent)
        self.parent = parent
        self.notification_manager = notification_manager
        self.setWindowTitle("Notification Settings")
        self.setMinimumSize(520, 500)
        
        # Enhanced dialog styling with modern, rounded design - matching ButtonConfigDialog
        self.setStyleSheet(f"""
            QDialog {{
                background-color: {DARK_BG};
                border-radius: {BORDER_RADIUS};
            }}
            QFrame.card {{
                background-color: #222222;
                border-radius: {BORDER_RADIUS};
                border: 1px solid #333333;
                padding: 15px;
                margin-bottom: 12px;
            }}
            QLabel.header {{
                color: {TEXT_COLOR};
                font-size: 15px;
                font-weight: bold;
                margin-bottom: 8px;
            }}
            QLabel.subheader {{
                color: {TEXT_COLOR};
                font-weight: bold;
            }}
            QLabel.description {{
                color: rgba(255, 255, 255, 0.7);
                font-size: 13px;
            }}
            QLabel.section-title {{
                color: {TEXT_COLOR};
                font-size: 14px;
                font-weight: bold;
                padding-left: 5px;
                border-left: 3px solid {PRIMARY_COLOR};
            }}
            QToolTip {{
                background-color: #303030;
                color: white;
                border: 1px solid {PRIMARY_COLOR};
                border-radius: 4px;
                padding: 5px;
            }}
            QPushButton {{
                border-radius: {BORDER_RADIUS}
            }}
            QScrollArea {{
                border: none;
                background-color: transparent;
            }}
            QScrollBar:vertical {{
                background: #2A2A2A;
                width: 8px;
                margin: 0px;
                border-radius: 4px;
            }}
            QScrollBar::handle:vertical {{
                background: #555555;
                min-height: 20px;
                border-radius: 4px;
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                border: none;
                background: none;
            }}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
                background: none;
            }}
        """)
        
        # Main layout
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        # Modern header with gradient background
        header_card = QtWidgets.QFrame()
        header_card.setObjectName("headerCard")
        header_card.setStyleSheet(f"""
            #headerCard {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, 
                                          stop:0 {PRIMARY_COLOR}, stop:1 {SECONDARY_COLOR});
                border-radius: {BORDER_RADIUS};
                padding: 15px;
            }}
        """)
        header_layout = QtWidgets.QHBoxLayout(header_card)
        
        # Icon with specific styling
        icon_label = QtWidgets.QLabel()
        icon_label.setFixedSize(48, 48)
        icon_bg_color = f"hsla(210, 70%, 50%, 0.8)"
        icon_label.setStyleSheet(f"""
            background-color: {icon_bg_color};
            border-radius: 24px;
            color: white;
            font-size: 22px;
            font-weight: bold;
            border: 2px solid rgba(255, 255, 255, 0.3);
        """)
        icon_label.setText("🔔")
        icon_label.setAlignment(QtCore.Qt.AlignCenter)
        
        # Create a semi-transparent light background for text
        text_container = QtWidgets.QFrame()
        text_container.setObjectName("textContainer")
        text_container.setStyleSheet("""
            #textContainer {
                background-color: rgba(255, 255, 255, 0.18);
                border-radius: 6px;
                padding: 8px 12px;
            }
        """)
        text_layout = QtWidgets.QVBoxLayout(text_container)
        text_layout.setContentsMargins(12, 8, 12, 8)
        text_layout.setSpacing(4)
        
        # Header text
        title_label = QtWidgets.QLabel("Notification Settings")
        title_label.setStyleSheet("color: white; font-size: 18px; font-weight: bold; letter-spacing: 0.5px;")
        
        subtitle_label = QtWidgets.QLabel("Customize how notifications appear and behave")
        subtitle_label.setStyleSheet("color: rgba(255, 255, 255, 0.9); font-size: 13px;")
        
        text_layout.addWidget(title_label)
        text_layout.addWidget(subtitle_label)
        
        header_layout.addWidget(icon_label)
        header_layout.addWidget(text_container, 1)
        
        layout.addWidget(header_card)
        
        # Content area with tabs for better organization
        self.tab_widget = QtWidgets.QTabWidget()
        self.tab_widget.setStyleSheet(f"""
            QTabWidget::pane {{
                border: 1px solid #333333;
                background-color: #222222;
                border-radius: {BORDER_RADIUS};
            }}
            QTabBar::tab {{
                background-color: #333333;
                color: {TEXT_COLOR};
                border-top-left-radius: 4px;
                border-top-right-radius: 4px;
                padding: 8px 12px;
                margin-right: 2px;
            }}
            QTabBar::tab:selected {{
                background-color: #444444;
                border-bottom: 2px solid {PRIMARY_COLOR};
            }}
            QTabBar::tab:hover {{
                background-color: #3a3a3a;
            }}
        """)
        
        # Create tabs
        self.general_tab = QtWidgets.QWidget()
        self.appearance_tab = QtWidgets.QWidget()
        self.theme_tab = QtWidgets.QWidget()
        
        self.tab_widget.addTab(self.general_tab, "General")
        self.tab_widget.addTab(self.appearance_tab, "Appearance")
        self.tab_widget.addTab(self.theme_tab, "Theme")
        
        # Set up each tab's content
        self.setup_general_tab()
        self.setup_appearance_tab()
        self.setup_theme_tab()
        
        layout.addWidget(self.tab_widget, 1)  # Add stretch factor
        
        # Action buttons at bottom with improved styling
        button_section = QtWidgets.QFrame()
        button_section.setObjectName("buttonSection")
        button_section.setStyleSheet(f"""
            #buttonSection {{
                background-color: transparent;
                border-top: 1px solid #333333;
                padding-top: 12px;
            }}
        """)
        button_layout = QtWidgets.QHBoxLayout(button_section)
        button_layout.setContentsMargins(0, 10, 0, 0)
        
        cancel_button = QtWidgets.QPushButton("Cancel")
        cancel_button.setStyleSheet(ACTION_BUTTON_STYLE.replace(PRIMARY_COLOR, "#555555") + """
            padding: 10px 18px;
            border-radius: {BORDER_RADIUS};
        """)
        cancel_button.clicked.connect(self.reject)
        
        preview_button = QtWidgets.QPushButton("Preview")
        preview_button.setStyleSheet(ACTION_BUTTON_STYLE.replace(PRIMARY_COLOR, SECONDARY_COLOR) + """
            padding: 10px 18px;
            font-weight: bold;
            border-radius: {BORDER_RADIUS};
        """)
        preview_button.setToolTip("Preview notification with current settings")
        preview_button.clicked.connect(self.show_preview)
        
        save_button = QtWidgets.QPushButton("Save Settings")
        save_button.setStyleSheet(ACTION_BUTTON_STYLE + """
            padding: 10px 18px;
            font-weight: bold;
            border-radius: {BORDER_RADIUS};
        """)
        save_button.setToolTip("Save notification settings")
        save_button.clicked.connect(self.save_settings)
        
        button_layout.addWidget(cancel_button)
        button_layout.addStretch()
        button_layout.addWidget(preview_button)
        button_layout.addWidget(save_button)
        
        layout.addWidget(button_section)
    
    def setup_general_tab(self):
        """Set up the general tab with notification types and enable/disable option"""
        layout = QtWidgets.QVBoxLayout(self.general_tab)
        layout.setContentsMargins(10, 15, 10, 15)
        layout.setSpacing(15)
        
        # Enable/disable notifications in a nice card
        enable_card = QtWidgets.QFrame()
        enable_card.setObjectName("enableCard")
        enable_card.setProperty("class", "card")
        enable_layout = QtWidgets.QVBoxLayout(enable_card)
        
        # Section title
        enable_title = QtWidgets.QLabel("Notification Status")
        enable_title.setProperty("class", "subheader")
        enable_layout.addWidget(enable_title)
        
        # Enable checkbox with improved styling
        self.enable_check = QtWidgets.QCheckBox("Enable Notifications")
        self.enable_check.setChecked(self.notification_manager.settings.get("enabled", True))
        self.enable_check.setStyleSheet(CHECKBOX_STYLE + """
            QCheckBox {
                padding: 5px;
                font-size: 13px;
            }
        """)
        self.enable_check.stateChanged.connect(self.update_notification_state)
        enable_layout.addWidget(self.enable_check)
        
        # Description
        enable_desc = QtWidgets.QLabel("Turn notifications on or off globally")
        enable_desc.setProperty("class", "description")
        enable_layout.addWidget(enable_desc)
        
        layout.addWidget(enable_card)
        
        # Notification types section in a card
        types_card = QtWidgets.QFrame()
        types_card.setObjectName("typesCard")
        types_card.setProperty("class", "card")
        types_layout = QtWidgets.QVBoxLayout(types_card)
        
        # Section title
        type_title = QtWidgets.QLabel("Notification Types")
        type_title.setProperty("class", "subheader")
        types_layout.addWidget(type_title)
        
        # Description
        types_desc = QtWidgets.QLabel("Select which notifications you want to see")
        types_desc.setProperty("class", "description")
        types_layout.addWidget(types_desc)
        
        # Use a grid layout for checkboxes to save space
        types_grid = QtWidgets.QGridLayout()
        types_grid.setHorizontalSpacing(15)
        types_grid.setVerticalSpacing(8)
        types_grid.setContentsMargins(0, 10, 0, 0)
        
        # Notification type checkboxes
        self.type_checkboxes = {}
        notification_types = [
            ("button_action", "Button Actions"), 
            ("volume_adjustment", "Volume Changes"),
            ("audio_device", "Audio Device Connection"),
            ("midi_connection", "MIDI Connection"),
            ("speech_to_text", "Speech Recognition"),
            ("ask_chatgpt", "Ask ChatGPT"),
            ("music_track", "Music Tracks"),
            ("play_pause_track", "Play/Pause Status")
        ]
        
        for i, (type_id, type_name) in enumerate(notification_types):
            row, col = i // 2, i % 2
            checkbox = QtWidgets.QCheckBox(type_name)
            # Handle legacy 'midi_connection' -> 'audio_device'
            is_checked = False
            if type_id == "audio_device":
                is_checked = self.notification_manager.settings.get("types", {}).get("audio_device", True)
            else:
                is_checked = self.notification_manager.settings.get("types", {}).get(type_id, True)
            checkbox.setChecked(is_checked)
            checkbox.setStyleSheet(CHECKBOX_STYLE + """
                QCheckBox {
                    padding: 5px;
                    font-size: 13px;
                }
            """)
            self.type_checkboxes[type_id] = checkbox
            types_grid.addWidget(checkbox, row, col)
        
        types_layout.addLayout(types_grid)
        layout.addWidget(types_card)
        layout.addStretch()
    
    def setup_appearance_tab(self):
        """Set up the appearance tab with notification position and size settings"""
        layout = QtWidgets.QVBoxLayout(self.appearance_tab)
        layout.setContentsMargins(10, 15, 10, 15)
        layout.setSpacing(15)

        # Position and Duration settings in a card
        position_card = QtWidgets.QFrame()
        position_card.setObjectName("positionCard")
        position_card.setProperty("class", "card")
        position_layout = QtWidgets.QVBoxLayout(position_card)
        
        # Section title
        position_title = QtWidgets.QLabel("Placement & Timing")
        position_title.setProperty("class", "subheader")
        position_layout.addWidget(position_title)
        
        # Description
        position_desc = QtWidgets.QLabel("Configure where notifications appear and how long they stay visible")
        position_desc.setProperty("class", "description")
        position_layout.addWidget(position_desc)
        
        # Create a grid for appearance settings
        appearance_grid = QtWidgets.QGridLayout()
        appearance_grid.setHorizontalSpacing(15)
        appearance_grid.setVerticalSpacing(15)
        appearance_grid.setContentsMargins(0, 10, 0, 0)
        appearance_grid.setColumnStretch(1, 1)  # Make the second column stretch

        # Position selector with modern styling
        position_label = QtWidgets.QLabel("Position:")
        position_label.setStyleSheet(f"color: {TEXT_COLOR};")
        
        self.position_combo = QtWidgets.QComboBox()
        self.position_combo.addItems(["Top Left", "Top Right", "Bottom Left", "Bottom Right"])
        self.position_combo.setStyleSheet(COMBOBOX_STYLE)
        
        # Get current position and set the combo box
        position_value = self.notification_manager.settings.get("position", "top_right")
        position_value = str(position_value).lower() if isinstance(position_value, (str, int)) else "top_right"
        
        if "top_left" in position_value:
            self.position_combo.setCurrentIndex(0)
        elif "top_right" in position_value:
            self.position_combo.setCurrentIndex(1)
        elif "bottom_left" in position_value:
            self.position_combo.setCurrentIndex(2)
        elif "bottom_right" in position_value:
            self.position_combo.setCurrentIndex(3)
        
        appearance_grid.addWidget(position_label, 0, 0)
        appearance_grid.addWidget(self.position_combo, 0, 1)
        
        # Duration selector with modern styling
        duration_label = QtWidgets.QLabel("Duration:")
        duration_label.setStyleSheet(f"color: {TEXT_COLOR};")
        
        duration_frame = QtWidgets.QFrame()
        duration_layout = QtWidgets.QVBoxLayout(duration_frame)
        duration_layout.setContentsMargins(0, 0, 0, 0)
        duration_layout.setSpacing(5)
        
        self.duration_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.duration_slider.setMinimum(1)
        self.duration_slider.setMaximum(15)
        self.duration_slider.setValue(self.notification_manager.settings.get("duration", 5))
        self.duration_slider.setTickPosition(QtWidgets.QSlider.TicksBelow)
        self.duration_slider.setTickInterval(1)
        self.duration_slider.setStyleSheet(f"""
            QSlider::groove:horizontal {{
                border: 1px solid #555555;
                height: 8px;
                background: #333333;
                border-radius: 4px;
            }}
            QSlider::handle:horizontal {{
                background: {PRIMARY_COLOR};
                border: 1px solid #777777;
                width: 16px;
                margin: -4px 0;
                border-radius: 8px;
            }}
            QSlider::handle:horizontal:hover {{
                background: {BUTTON_ACTIVE_COLOR};
            }}
            QSlider::sub-page:horizontal {{
                background: {SECONDARY_COLOR};
                border-radius: 4px;
            }}
        """)
        self.duration_slider.valueChanged.connect(self.update_duration_label)
        
        self.duration_value = QtWidgets.QLabel(f"{self.duration_slider.value()} seconds")
        self.duration_value.setStyleSheet("color: #AAAAAA; font-size: 12px; padding-top: 4px;")
        self.duration_value.setAlignment(QtCore.Qt.AlignCenter)
        
        duration_layout.addWidget(self.duration_slider)
        duration_layout.addWidget(self.duration_value)
        
        appearance_grid.addWidget(duration_label, 1, 0)
        appearance_grid.addWidget(duration_frame, 1, 1)
        
        position_layout.addLayout(appearance_grid)
        layout.addWidget(position_card)

        # Font & Display Settings in a card
        font_card = QtWidgets.QFrame()
        font_card.setObjectName("fontCard")
        font_card.setProperty("class", "card")
        font_layout = QtWidgets.QVBoxLayout(font_card)
        
        # Section title
        font_title = QtWidgets.QLabel("Font & Display")
        font_title.setProperty("class", "subheader")
        font_layout.addWidget(font_title)
        
        # Description
        font_desc = QtWidgets.QLabel("Configure text size and notification dimensions")
        font_desc.setProperty("class", "description")
        font_layout.addWidget(font_desc)
        
        # Font & size grid
        font_grid = QtWidgets.QGridLayout()
        font_grid.setHorizontalSpacing(15)
        font_grid.setVerticalSpacing(15)
        font_grid.setContentsMargins(0, 10, 0, 0)
        font_grid.setColumnStretch(1, 1)  # Make the second column stretch
        
        # Font size with modern styling
        font_size_label = QtWidgets.QLabel("Font Size:")
        font_size_label.setStyleSheet(f"color: {TEXT_COLOR};")
        
        font_size_frame = QtWidgets.QFrame()
        font_size_layout = QtWidgets.QHBoxLayout(font_size_frame)
        font_size_layout.setContentsMargins(0, 0, 0, 0)
        
        self.font_size_combo = QtWidgets.QComboBox()
        self.font_size_combo.addItems(["Custom"])
        self.font_size_combo.setStyleSheet(COMBOBOX_STYLE)
        
        # Get current font size and set the SpinBox value
        font_size_value = self.notification_manager.settings.get("font_size", 12)
        
        # Custom font size input - always visible now
        self.custom_font_size = QtWidgets.QSpinBox()
        self.custom_font_size.setMinimum(6)
        self.custom_font_size.setMaximum(36)
        self.custom_font_size.setValue(font_size_value)
        self.custom_font_size.setStyleSheet(SPINBOX_STYLE)
        self.custom_font_size.setVisible(True)
        
        font_size_layout.addWidget(self.font_size_combo, 1)
        font_size_layout.addWidget(self.custom_font_size)
        
        font_grid.addWidget(font_size_label, 0, 0)
        font_grid.addWidget(font_size_frame, 0, 1)
        
        # Notification Size
        size_label = QtWidgets.QLabel("Notification Size:")
        size_label.setStyleSheet(f"color: {TEXT_COLOR};")
        
        size_frame = QtWidgets.QFrame()
        size_layout = QtWidgets.QHBoxLayout(size_frame)
        size_layout.setContentsMargins(0, 0, 0, 0)
        
        width_label = QtWidgets.QLabel("Width:")
        width_label.setStyleSheet(f"color: {TEXT_COLOR};")
        
        self.width_spin = QtWidgets.QSpinBox()
        self.width_spin.setMinimum(100)
        self.width_spin.setMaximum(1000)
        self.width_spin.setStyleSheet(SPINBOX_STYLE)
        
        height_label = QtWidgets.QLabel("Height:")
        height_label.setStyleSheet(f"color: {TEXT_COLOR};")
        
        self.height_spin = QtWidgets.QSpinBox()
        self.height_spin.setMinimum(30)  # Set minimum height to 30
        self.height_spin.setMaximum(600)  # Allow larger notifications
        
        # Get current size and set the values
        current_size = self.notification_manager.settings.get("size", [300, 100])
        
        if isinstance(current_size, (list, tuple)) and len(current_size) >= 2:
            try:
                self.width_spin.setValue(int(current_size[0]))
                self.height_spin.setValue(int(current_size[1]))
            except (ValueError, TypeError):
                self.width_spin.setValue(300)
                self.height_spin.setValue(100)
        else:
            self.width_spin.setValue(300)
            self.height_spin.setValue(100)
            
        self.height_spin.setStyleSheet(SPINBOX_STYLE)
        
        size_layout.addWidget(width_label)
        size_layout.addWidget(self.width_spin)
        size_layout.addWidget(height_label)
        size_layout.addWidget(self.height_spin)
        
        font_grid.addWidget(size_label, 1, 0)
        font_grid.addWidget(size_frame, 1, 1)

        font_layout.addLayout(font_grid)
        layout.addWidget(font_card)
        layout.addStretch()
    
    def on_font_size_changed(self, index):
        """No longer needed as custom font size is always visible"""
        pass
    
    def setup_theme_tab(self):
        """Set up the theme tab with customization options"""
        layout = QtWidgets.QVBoxLayout(self.theme_tab)
        layout.setContentsMargins(10, 15, 10, 15)
        layout.setSpacing(15)
        
        # Create a scroll area to handle lots of theme options
        scroll_area = QtWidgets.QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QtWidgets.QFrame.NoFrame)
        scroll_area.setStyleSheet(f"background-color: {DARK_BG};")
        
        content_widget = QtWidgets.QWidget()
        content_layout = QtWidgets.QVBoxLayout(content_widget)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(15)
        
        # Font settings in a card
        font_card = QtWidgets.QFrame()
        font_card.setObjectName("fontSettingsCard")
        font_card.setProperty("class", "card")
        font_layout = QtWidgets.QVBoxLayout(font_card)
        
        # Section title
        font_title = QtWidgets.QLabel("Font Settings")
        font_title.setProperty("class", "subheader")
        font_layout.addWidget(font_title)
        
        # Description
        font_desc = QtWidgets.QLabel("Customize notification text appearance")
        font_desc.setProperty("class", "description")
        font_layout.addWidget(font_desc)
        
        # Font settings grid
        font_grid = QtWidgets.QGridLayout()
        font_grid.setHorizontalSpacing(15)
        font_grid.setVerticalSpacing(10)
        font_grid.setContentsMargins(0, 10, 0, 0)
        
        # Font family selector with improved styling
        font_family_label = QtWidgets.QLabel("Font Family:")
        font_family_label.setStyleSheet(f"color: {TEXT_COLOR};")
        
        # Replace QComboBox with QFontComboBox to show all system fonts
        self.font_family_combo = QtWidgets.QFontComboBox()
        self.font_family_combo.setStyleSheet(COMBOBOX_STYLE)
        
        # Add "System Default" option at the beginning
        current_fonts = [self.font_family_combo.itemText(i) for i in range(self.font_family_combo.count())]
        self.font_family_combo.insertItem(0, "System Default")
            
        # Set current font family if available
        theme_settings = self.notification_manager.settings.get("theme_settings", {})
        font_family = theme_settings.get("font_family", "")
        if font_family:
            index = self.font_family_combo.findText(font_family)
            if index >= 0:
                self.font_family_combo.setCurrentIndex(index)
        else:
            self.font_family_combo.setCurrentIndex(0)  # Default to "System Default"
        
        font_grid.addWidget(font_family_label, 0, 0)
        font_grid.addWidget(self.font_family_combo, 0, 1)
        
        # Font weight selector with improved styling
        font_weight_label = QtWidgets.QLabel("Font Weight:")
        font_weight_label.setStyleSheet(f"color: {TEXT_COLOR};")
        
        self.font_weight_combo = QtWidgets.QComboBox()
        self.font_weight_combo.addItems(["Normal", "Bold", "Light"])
        self.font_weight_combo.setStyleSheet(COMBOBOX_STYLE)
        
        # Set current font weight if available
        font_weight = theme_settings.get("font_weight", "normal").lower()
        if font_weight == "bold":
            self.font_weight_combo.setCurrentIndex(1)
        elif font_weight == "light":
            self.font_weight_combo.setCurrentIndex(2)
        else:
            self.font_weight_combo.setCurrentIndex(0)
            
        font_grid.addWidget(font_weight_label, 1, 0)
        font_grid.addWidget(self.font_weight_combo, 1, 1)
        
        # Add single line text option with improved styling
        single_line_label = QtWidgets.QLabel("Text Display:")
        single_line_label.setStyleSheet(f"color: {TEXT_COLOR};")
        
        self.single_line_check = QtWidgets.QCheckBox("Single Line Text (no wrapping)")
        self.single_line_check.setStyleSheet(CHECKBOX_STYLE + """
            QCheckBox {
                padding: 5px;
                font-size: 13px;
            }
        """)
        self.single_line_check.setChecked(theme_settings.get("single_line_text", False))
        
        font_grid.addWidget(single_line_label, 2, 0)
        font_grid.addWidget(self.single_line_check, 2, 1)
        
        # Click to dismiss
        dismiss_label = QtWidgets.QLabel("Interaction:")
        dismiss_label.setStyleSheet(f"color: {TEXT_COLOR};")
        
        self.click_dismiss_check = QtWidgets.QCheckBox("Click to Dismiss")
        self.click_dismiss_check.setStyleSheet(CHECKBOX_STYLE + """
            QCheckBox {
                padding: 5px;
                font-size: 13px;
            }
        """)
        self.click_dismiss_check.setChecked(theme_settings.get("click_dismiss", True))
        
        font_grid.addWidget(dismiss_label, 3, 0)
        font_grid.addWidget(self.click_dismiss_check, 3, 1)
        
        font_layout.addLayout(font_grid)
        content_layout.addWidget(font_card)
        
        # Color settings in a card
        color_card = QtWidgets.QFrame()
        color_card.setObjectName("colorSettingsCard")
        color_card.setProperty("class", "card")
        color_layout = QtWidgets.QVBoxLayout(color_card)
        
        # Section title
        color_title = QtWidgets.QLabel("Color Settings")
        color_title.setProperty("class", "subheader")
        color_layout.addWidget(color_title)
        
        # Description
        color_desc = QtWidgets.QLabel("Customize notification colors")
        color_desc.setProperty("class", "description")
        color_layout.addWidget(color_desc)
        
        # Color grid
        color_grid = QtWidgets.QGridLayout()
        color_grid.setHorizontalSpacing(15)
        color_grid.setVerticalSpacing(10)
        color_grid.setContentsMargins(0, 10, 0, 0)
        
        # Text color with improved styling
        self.text_color_label = QtWidgets.QLabel("Text Color:")
        self.text_color_label.setStyleSheet(f"color: {TEXT_COLOR};")
        
        text_color_frame = QtWidgets.QFrame()
        text_color_layout = QtWidgets.QHBoxLayout(text_color_frame)
        text_color_layout.setContentsMargins(0, 0, 0, 0)
        
        self.text_color_button = QtWidgets.QPushButton()
        self.text_color_button.setFixedSize(30, 24)
        text_color = theme_settings.get("text_color", "#FFFFFF")
        self.text_color_button.setStyleSheet(f"background-color: {text_color}; border: 1px solid #555555; border-radius: 3px;")
        self.text_color_button.clicked.connect(lambda: self.pick_color("text_color"))
        
        self.text_color_value = QtWidgets.QLineEdit(text_color)
        self.text_color_value.setStyleSheet(LINEEDIT_STYLE)
        self.text_color_value.textChanged.connect(lambda t: self.text_color_button.setStyleSheet(f"background-color: {t}; border: 1px solid #555555;"))
        
        text_color_layout.addWidget(self.text_color_button)
        text_color_layout.addWidget(self.text_color_value)
        
        color_grid.addWidget(self.text_color_label, 1, 0)
        color_grid.addWidget(text_color_frame, 1, 1)
        
        # Background style
        bg_style_label = QtWidgets.QLabel("Background Style:")
        bg_style_label.setStyleSheet(f"color: {TEXT_COLOR};")
        
        self.bg_style_combo = QtWidgets.QComboBox()
        self.bg_style_combo.addItems(["Solid Color", "Gradient", "Transparent"])
        self.bg_style_combo.setStyleSheet(COMBOBOX_STYLE)
        self.bg_style_combo.currentIndexChanged.connect(self.update_theme_visibility)
        
        # Set current background style
        bg_style = theme_settings.get("bg_style", "solid").lower()
        if bg_style == "gradient":
            self.bg_style_combo.setCurrentIndex(1)
        elif bg_style == "transparent":
            self.bg_style_combo.setCurrentIndex(2)
        else:
            self.bg_style_combo.setCurrentIndex(0)
            
        color_grid.addWidget(bg_style_label, 0, 0)
        color_grid.addWidget(self.bg_style_combo, 0, 1)
        
        # Background color with improved styling
        self.bg_color_label = QtWidgets.QLabel("Background Color:")
        self.bg_color_label.setStyleSheet(f"color: {TEXT_COLOR};")
        
        bg_color_frame = QtWidgets.QFrame()
        bg_color_layout = QtWidgets.QHBoxLayout(bg_color_frame)
        bg_color_layout.setContentsMargins(0, 0, 0, 0)
        
        self.bg_color_button = QtWidgets.QPushButton()
        self.bg_color_button.setFixedSize(30, 24)
        bg_color = theme_settings.get("bg_color", "#333333")
        self.bg_color_button.setStyleSheet(f"background-color: {bg_color}; border: 1px solid #555555; border-radius: 3px;")
        self.bg_color_button.clicked.connect(lambda: self.pick_color("bg_color"))
        
        self.bg_color_value = QtWidgets.QLineEdit(bg_color)
        self.bg_color_value.setStyleSheet(LINEEDIT_STYLE)
        self.bg_color_value.textChanged.connect(lambda t: self.bg_color_button.setStyleSheet(f"background-color: {t}; border: 1px solid #555555; border-radius: 3px;"))
        
        bg_color_layout.addWidget(self.bg_color_button)
        bg_color_layout.addWidget(self.bg_color_value)
        
        color_grid.addWidget(self.bg_color_label, 2, 0)
        color_grid.addWidget(bg_color_frame, 2, 1)
        
        # Gradient color (end color) with improved styling
        self.gradient_color_label = QtWidgets.QLabel("Gradient Color:")
        self.gradient_color_label.setStyleSheet(f"color: {TEXT_COLOR};")
        
        gradient_color_frame = QtWidgets.QFrame()
        gradient_color_layout = QtWidgets.QHBoxLayout(gradient_color_frame)
        gradient_color_layout.setContentsMargins(0, 0, 0, 0)
        
        self.gradient_color_button = QtWidgets.QPushButton()
        self.gradient_color_button.setFixedSize(30, 24)
        gradient_color = theme_settings.get("gradient_color", "#222222")
        self.gradient_color_button.setStyleSheet(f"background-color: {gradient_color}; border: 1px solid #555555; border-radius: 3px;")
        self.gradient_color_button.clicked.connect(lambda: self.pick_color("gradient_color"))
        
        self.gradient_color_value = QtWidgets.QLineEdit(gradient_color)
        self.gradient_color_value.setStyleSheet(LINEEDIT_STYLE)
        self.gradient_color_value.textChanged.connect(lambda t: self.gradient_color_button.setStyleSheet(f"background-color: {t}; border: 1px solid #555555; border-radius: 3px;"))
        
        gradient_color_layout.addWidget(self.gradient_color_button)
        gradient_color_layout.addWidget(self.gradient_color_value)
        
        color_grid.addWidget(self.gradient_color_label, 3, 0)
        color_grid.addWidget(gradient_color_frame, 3, 1)
        
        # Progress bar color with improved styling
        self.progress_color_label = QtWidgets.QLabel("Progress Bar Color:")
        self.progress_color_label.setStyleSheet(f"color: {TEXT_COLOR};")
        
        progress_color_frame = QtWidgets.QFrame()
        progress_color_layout = QtWidgets.QHBoxLayout(progress_color_frame)
        progress_color_layout.setContentsMargins(0, 0, 0, 0)
        
        self.progress_color_button = QtWidgets.QPushButton()
        self.progress_color_button.setFixedSize(30, 24)
        progress_color = theme_settings.get("progress_color", PRIMARY_COLOR)
        self.progress_color_button.setStyleSheet(f"background-color: {progress_color}; border: 1px solid #555555; border-radius: 3px;")
        self.progress_color_button.clicked.connect(lambda: self.pick_color("progress_color"))
        
        self.progress_color_value = QtWidgets.QLineEdit(progress_color)
        self.progress_color_value.setStyleSheet(LINEEDIT_STYLE)
        self.progress_color_value.textChanged.connect(lambda t: self.progress_color_button.setStyleSheet(f"background-color: {t}; border: 1px solid #555555; border-radius: 3px;"))
        
        progress_color_layout.addWidget(self.progress_color_button)
        progress_color_layout.addWidget(self.progress_color_value)
        
        # Change grid position from 4,0/4,1 to 5,0/5,1 to avoid collision with text color
        color_grid.addWidget(self.progress_color_label, 5, 0)
        color_grid.addWidget(progress_color_frame, 5, 1)
        
        color_layout.addLayout(color_grid)
        content_layout.addWidget(color_card)
        
        # Container settings in a card
        container_card = QtWidgets.QFrame()
        container_card.setObjectName("containerSettingsCard")
        container_card.setProperty("class", "card")
        container_layout = QtWidgets.QVBoxLayout(container_card)
        
        # Section title
        container_title = QtWidgets.QLabel("Container Settings")
        container_title.setProperty("class", "subheader")
        container_layout.addWidget(container_title)
        
        # Description
        container_desc = QtWidgets.QLabel("Configure the notification container appearance")
        container_desc.setProperty("class", "description")
        container_layout.addWidget(container_desc)
        
        # Container grid
        container_grid = QtWidgets.QGridLayout()
        container_grid.setHorizontalSpacing(15)
        container_grid.setVerticalSpacing(10)
        container_grid.setContentsMargins(0, 10, 0, 0)
        
        # Show container option
        container_show_label = QtWidgets.QLabel("Container:")
        container_show_label.setStyleSheet(f"color: {TEXT_COLOR};")
        
        self.show_container_check = QtWidgets.QCheckBox("Show Container")
        self.show_container_check.setStyleSheet(CHECKBOX_STYLE + """
            QCheckBox {
                padding: 5px;
                font-size: 13px;
            }
        """)
        self.show_container_check.setChecked(theme_settings.get("show_container", True))
        self.show_container_check.stateChanged.connect(self.update_container_color_state)
        
        container_grid.addWidget(container_show_label, 0, 0)
        container_grid.addWidget(self.show_container_check, 0, 1)
        
        # Container color
        self.container_color_label = QtWidgets.QLabel("Container Color:")
        self.container_color_label.setStyleSheet(f"color: {TEXT_COLOR};")
        
        container_color_frame = QtWidgets.QFrame()
        container_color_layout = QtWidgets.QHBoxLayout(container_color_frame)
        container_color_layout.setContentsMargins(0, 0, 0, 0)
        
        self.container_color_button = QtWidgets.QPushButton()
        self.container_color_button.setFixedSize(30, 24)
        container_color = theme_settings.get("container_color", "#444444")
        self.container_color_button.setStyleSheet(f"background-color: {container_color}; border: 1px solid #555555; border-radius: 3px;")
        self.container_color_button.clicked.connect(lambda: self.pick_color("container_color"))
        
        self.container_color_value = QtWidgets.QLineEdit(container_color)
        self.container_color_value.setStyleSheet(LINEEDIT_STYLE)
        self.container_color_value.textChanged.connect(lambda t: self.container_color_button.setStyleSheet(f"background-color: {t}; border: 1px solid #555555; border-radius: 3px;"))
        
        container_color_layout.addWidget(self.container_color_button)
        container_color_layout.addWidget(self.container_color_value)
        
        container_grid.addWidget(self.container_color_label, 1, 0)
        container_grid.addWidget(container_color_frame, 1, 1)
        
        # Rounded corners with improved styling
        rounded_label = QtWidgets.QLabel("Corners:")
        rounded_label.setStyleSheet(f"color: {TEXT_COLOR};")
        
        self.rounded_check = QtWidgets.QCheckBox("Rounded Corners")
        self.rounded_check.setStyleSheet(CHECKBOX_STYLE + """
            QCheckBox {
                padding: 5px;
                font-size: 13px;
            }
        """)
        self.rounded_check.setChecked(theme_settings.get("rounded_corners", True))
        
        container_grid.addWidget(rounded_label, 2, 0)
        container_grid.addWidget(self.rounded_check, 2, 1)
        
        # Border radius
        self.border_radius_label = QtWidgets.QLabel("Border Radius:")
        self.border_radius_label.setStyleSheet(f"color: {TEXT_COLOR};")
        
        self.border_radius_spin = QtWidgets.QSpinBox()
        self.border_radius_spin.setMinimum(0)
        self.border_radius_spin.setMaximum(20)
        self.border_radius_spin.setValue(theme_settings.get("border_radius", 5))
        self.border_radius_spin.setStyleSheet(SPINBOX_STYLE)
        
        container_grid.addWidget(self.border_radius_label, 3, 0)
        container_grid.addWidget(self.border_radius_spin, 3, 1)
        
        # Progress bar option
        progress_label = QtWidgets.QLabel("Progress Bar:")
        progress_label.setStyleSheet(f"color: {TEXT_COLOR};")
        
        self.show_progress_check = QtWidgets.QCheckBox("Show Progress Bar")
        self.show_progress_check.setStyleSheet(CHECKBOX_STYLE + """
            QCheckBox {
                padding: 5px;
                font-size: 13px;
            }
        """)
        self.show_progress_check.setChecked(theme_settings.get("show_progress", True))
        
        container_grid.addWidget(progress_label, 4, 0)
        container_grid.addWidget(self.show_progress_check, 4, 1)
        
        container_layout.addLayout(container_grid)
        content_layout.addWidget(container_card)
        
        # Reset to defaults button
        reset_button = QtWidgets.QPushButton("Reset Theme to Defaults")
        reset_button.setStyleSheet(ACTION_BUTTON_STYLE.replace(PRIMARY_COLOR, SECONDARY_COLOR) + """
            padding: 8px 16px;
            margin-top: 10px;
            border-radius: {BORDER_RADIUS};
        """)
        reset_button.clicked.connect(self.reset_theme_defaults)
        
        content_layout.addWidget(reset_button, 0, QtCore.Qt.AlignRight)
        content_layout.addStretch()
        
        scroll_area.setWidget(content_widget)
        layout.addWidget(scroll_area)
        
        # Update visibility of fields based on background style
        self.update_theme_visibility()
        
        # Initialize container color state
        self.update_container_color_state(self.show_container_check.isChecked())
    
    def update_container_color_state(self, state):
        """Enable or disable container color fields based on the show container checkbox"""
        is_enabled = bool(state)
        self.container_color_label.setEnabled(is_enabled)
        self.container_color_button.setEnabled(is_enabled)
        self.container_color_value.setEnabled(is_enabled)

    def update_theme_visibility(self):
        """Show/hide fields based on selected background style"""
        # Get current background style
        index = self.bg_style_combo.currentIndex()
        is_solid = index == 0      # Solid color
        is_gradient = index == 1   # Gradient
        is_transparent = index == 2  # Transparent

        # Update gradient controls visibility
        self.gradient_color_label.setVisible(is_gradient)
        self.gradient_color_button.setEnabled(is_gradient)
        self.gradient_color_button.parentWidget().setVisible(is_gradient)
        self.gradient_color_value.setEnabled(is_gradient)
        
        # Update background color controls visibility
        self.bg_color_label.setVisible(not is_transparent)
        self.bg_color_button.setEnabled(not is_transparent)
        self.bg_color_button.parentWidget().setVisible(not is_transparent)
        self.bg_color_value.setEnabled(not is_transparent)
        
        # Ensure text color controls are always visible
        self.text_color_label.setVisible(True)
        self.text_color_button.setEnabled(True)
        self.text_color_button.parentWidget().setVisible(True)
        self.text_color_value.setEnabled(True)
    
    def update_notification_state(self):
        """Enable or disable notification checkboxes based on main toggle"""
        enabled = self.enable_check.isChecked()
        for checkbox in self.type_checkboxes.values():
            checkbox.setEnabled(enabled)
    
    def update_duration_label(self, value):
        """Update the label showing notification duration"""
        self.duration_value.setText(f"{value} seconds")
    
    def pick_color(self, color_type):
        """Open a color picker dialog and update the corresponding color field"""
        current_color = None
        if color_type == "bg_color":
            current_color = self.bg_color_value.text()
        elif color_type == "gradient_color":
            current_color = self.gradient_color_value.text()
        elif color_type == "container_color":
            current_color = self.container_color_value.text()
        elif color_type == "text_color":
            current_color = self.text_color_value.text()
        elif color_type == "progress_color":
            current_color = self.progress_color_value.text()
        
        if current_color:
            try:
                current_color = QtGui.QColor(current_color)
            except:
                current_color = QtGui.QColor("#333333")
        else:
            current_color = QtGui.QColor("#333333")
        
        color_dialog = QtWidgets.QColorDialog(current_color, self)
        color_dialog.setStyleSheet(f"""
            QColorDialog {{
                background-color: {DARK_BG};
                color: {TEXT_COLOR};
            }}
            QPushButton {{
                background-color: {PRIMARY_COLOR};
                color: {TEXT_COLOR};
                border: none;
                border-radius: {BORDER_RADIUS};
                padding: 10px 18px;
                font-weight: bold;
                min-width: 80px;
            }}
            QPushButton:hover {{
                background-color: {BUTTON_ACTIVE_COLOR};
                border: 1px solid {HIGHLIGHT_COLOR};
            }}
            QPushButton:pressed {{
                background-color: {SECONDARY_COLOR};
            }}
            QPushButton[text="Cancel"] {{
                background-color: #555555;
            }}
        """)
        if color_dialog.exec_():
            selected_color = color_dialog.selectedColor().name()
            if color_type == "bg_color":
                self.bg_color_value.setText(selected_color)
                self.bg_color_button.setStyleSheet(f"background-color: {selected_color}; border: 1px solid #555555; border-radius: 3px;")
            elif color_type == "gradient_color":
                self.gradient_color_value.setText(selected_color)
                self.gradient_color_button.setStyleSheet(f"background-color: {selected_color}; border: 1px solid #555555; border-radius: 3px;")
            elif color_type == "container_color":
                self.container_color_value.setText(selected_color)
                self.container_color_button.setStyleSheet(f"background-color: {selected_color}; border: 1px solid #555555; border-radius: 3px;")
            elif color_type == "text_color":
                self.text_color_value.setText(selected_color)
                self.text_color_button.setStyleSheet(f"background-color: {selected_color}; border: 1px solid #555555; border-radius: 3px;")
            elif color_type == "progress_color":
                self.progress_color_value.setText(selected_color)
                self.progress_color_button.setStyleSheet(f"background-color: {selected_color}; border: 1px solid #555555; border-radius: 3px;")
    
    def reset_theme_defaults(self):
        """Reset theme settings to defaults"""
        # Default theme values
        self.bg_style_combo.setCurrentIndex(0)  # Solid color
        self.bg_color_value.setText("#333333")
        self.gradient_color_value.setText("#222222")
        self.container_color_value.setText("#444444")
        self.text_color_value.setText("#FFFFFF")
        self.progress_color_value.setText(PRIMARY_COLOR)
        self.rounded_check.setChecked(True)
        self.click_dismiss_check.setChecked(True)
        self.show_container_check.setChecked(True)
        self.show_progress_check.setChecked(True)
        self.border_radius_spin.setValue(5)
        self.font_family_combo.setCurrentIndex(0)  # System default
        self.font_weight_combo.setCurrentIndex(0)  # Normal
        self.single_line_check.setChecked(False)  # Default to multi-line (word wrap enabled)
        
        # Update color buttons based on the default values
        self.bg_color_button.setStyleSheet(f"background-color: #333333; border: 1px solid #555555; border-radius: 3px;")
        self.gradient_color_button.setStyleSheet(f"background-color: #222222; border: 1px solid #555555; border-radius: 3px;")
        self.container_color_button.setStyleSheet(f"background-color: #444444; border: 1px solid #555555; border-radius: 3px;")
        self.text_color_button.setStyleSheet(f"background-color: #FFFFFF; border: 1px solid #555555; border-radius: 3px;")
        self.progress_color_button.setStyleSheet(f"background-color: {PRIMARY_COLOR}; border: 1px solid #555555; border-radius: 3px;")
        
        # Update visibility based on the defaults
        self.update_theme_visibility()
        self.update_container_color_state(True)
    
    def apply_current_settings(self):
        """Collect current settings from all controls"""
        # Notification types
        types = {}
        for notification_type, checkbox in self.type_checkboxes.items():
            types[notification_type] = checkbox.isChecked()
        
        # Font Size - Always use custom size now
        font_size = self.custom_font_size.value()
            
        # Position
        position_idx = self.position_combo.currentIndex()
        if position_idx == 0:
            position = "top_left"
        elif position_idx == 1:
            position = "top_right"
        elif position_idx == 2:
            position = "bottom_left"
        else:
            position = "bottom_right"
            
        # Size
        size = [self.width_spin.value(), self.height_spin.value()]
        
        # Duration
        duration = self.duration_slider.value()
        
        # Theme settings
        bg_style_idx = self.bg_style_combo.currentIndex()
        bg_style = "solid"
        if bg_style_idx == 1:
            bg_style = "gradient"
        elif bg_style_idx == 2:
            bg_style = "transparent"
            
        # Get container setting directly from the checkbox
        show_container = self.show_container_check.isChecked()
        
        # Create theme settings object - ensure show_container is explicitly included
        theme_settings = {
            "bg_style": bg_style,
            "bg_color": self.bg_color_value.text(),
            "gradient_color": self.gradient_color_value.text(),
            "container_color": self.container_color_value.text(),
            "text_color": self.text_color_value.text(),
            "progress_color": self.progress_color_value.text(),
            "rounded_corners": self.rounded_check.isChecked(),
            "click_dismiss": self.click_dismiss_check.isChecked(),
            "show_container": show_container,
            "show_progress": self.show_progress_check.isChecked(),
            "border_radius": self.border_radius_spin.value(),
            "font_family": self.font_family_combo.currentText() if self.font_family_combo.currentText() != "System Default" else "",
            "font_weight": self.font_weight_combo.currentText().lower(),
            "single_line_text": self.single_line_check.isChecked()
        }
        
        # Log the show_container setting for debugging
        logger.debug(f"apply_current_settings: show_container={show_container}, bg_style={bg_style}")
        
        settings = {
            "enabled": self.enable_check.isChecked(),
            "types": types,
            "font_size": font_size,
            "position": position,
            "size": size,
            "duration": duration,
            "theme_settings": theme_settings
        }
        
        return settings
        
    def show_preview(self):
        """Show a preview notification with current settings"""
        # Apply current settings without saving to file
        settings = self.apply_current_settings()
        
        # Store original settings to restore later
        original_settings = self.notification_manager.settings.copy()
        
        try:
            # Apply settings temporarily
            self.notification_manager.update_settings(settings)
            
            # Show preview notification
            preview_message = "This is a preview notification"
            self.notification_manager.show_notification(
                preview_message,
                notification_type="preview"
            )
            
            # Restore original settings
            self.notification_manager.settings = original_settings
        except Exception as e:
            logger.error(f"Failed to show preview: {e}")
            # Ensure original settings are restored even if an error occurs
            self.notification_manager.settings = original_settings
    
    def save_settings(self):
        """Save settings and close dialog"""
        settings = self.apply_current_settings()
        
        try:
            # Apply settings to notification manager
            self.notification_manager.update_settings(settings)
            
            # Print for debugging - will show in logs
            show_container = settings.get('theme_settings', {}).get('show_container', True)
            logger.debug(f"Saving show_container setting: {show_container}")
            
            # Save to file
            settings_dir = os.path.join(os.path.dirname(__file__), "config")
            os.makedirs(settings_dir, exist_ok=True)
            settings_path = os.path.join(settings_dir, "notification_settings.json")
            with open(settings_path, 'w') as f:
                json.dump(settings, f, indent=4)
            logger.info("Notification settings saved to file")
            self.accept()
        except Exception as e:
            logger.error(f"Failed to save notification settings: {e}")
            QtWidgets.QMessageBox.critical(
                self, 
                "Error Saving Settings", 
                f"Failed to save notification settings: {str(e)}"
            )

# Create and show main window
if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    
    # Set application-wide style
    app.setStyle("Fusion")  # Use Fusion style as a base
    
    # Set global stylesheet for common widgets
    app.setStyleSheet(f"""
        QWidget {{
            background-color: {DARK_BG};
            color: {TEXT_COLOR};
            font-family: 'Segoe UI', Arial, sans-serif;
        }}
        
        QPushButton {{
            background-color: {SECONDARY_COLOR};
            color: {TEXT_COLOR};
            border: none;
            border-radius: {BORDER_RADIUS};
            padding: 8px 16px;
            font-weight: normal;
        }}
        
        QPushButton:hover {{
            background-color: {PRIMARY_COLOR};
        }}
        
        QPushButton:pressed {{
            background-color: {BUTTON_ACTIVE_COLOR};
        }}
        
        QScrollBar:vertical {{
            background: #2A2A2A;
            width: 12px;
            margin: 0px;
            border-radius: 6px;
        }}
        
        QScrollBar::handle:vertical {{
            background: #555555;
            min-height: 20px;
            border-radius: 6px;
        }}
        
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
            border: none;
            background: none;
        }}
        
        QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
            background: none;
        }}
        
        QMessageBox {{
            background-color: {DARK_BG};
        }}
        
        QMessageBox QLabel {{
            color: {TEXT_COLOR};
        }}
        
        QMessageBox QPushButton {{
            background-color: {PRIMARY_COLOR};
            color: {TEXT_COLOR};
            border-radius: {BORDER_RADIUS};
            padding: 8px 16px;
            min-width: 80px;
        }}
    """)
    
    window = MIDIKeyboardApp()
    window.show()
    
    # Start event loop
    sys.exit(app.exec_())