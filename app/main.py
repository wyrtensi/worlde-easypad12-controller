import os
import sys
import threading
import time
from PIL import Image, ImageDraw
import PySide6.QtWidgets as QtWidgets
import PySide6.QtGui as QtGui
import PySide6.QtCore as QtCore
import json
import logging
import speech_recognition as sr
import pyautogui
import pyperclip
import pyaudio
import winrt.windows.foundation
import winrt.windows.media.control as wmc
from qasync import asyncSlot
from app.midi_controller import MIDIController
from app.system_actions import SystemActions
from app.notifications import NotificationManager, NotificationWindow
from app.utils import setup_logging, get_dark_theme, load_midi_mapping, get_media_controls, load_button_config, get_action_types, save_button_config

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
    start_slider_timer_signal = QtCore.Signal()  # New signal for timer

    def __init__(self):
        super().__init__()
        self._shutting_down = False
        self.setWindowTitle("WORLDE EASYPAD.12 Controller")
        self.setFixedSize(1000, 350)

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

        # Initialize tray icon if available
        self.tray_icon = None
        if QtWidgets.QSystemTrayIcon.isSystemTrayAvailable():
            self.setup_tray()
            QtCore.QTimer.singleShot(100, self.hide)

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
        self.start_slider_timer_signal.connect(self.start_slider_timer)  # Connect new signal

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

    def update_slider_value(self, value):
        self.slider_widget.blockSignals(True)
        self.slider_widget.setValue(value)
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
        qimage = QtGui.QImage(self.icon_image.tobytes(), 64, 64, QtGui.QImage.Format_RGBA8888)
        self.tray_icon = QtWidgets.QSystemTrayIcon(QtGui.QIcon(QtGui.QPixmap.fromImage(qimage)), self)
        tray_menu = QtWidgets.QMenu()
        show_action = tray_menu.addAction("Show")
        show_action.triggered.connect(self.show_window)
        exit_action = tray_menu.addAction("Exit")
        exit_action.triggered.connect(self.exit_app)
        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.activated.connect(self.on_tray_activated)
        self.tray_icon.show()

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

        if self.tray_icon:
            try:
                self.tray_icon.hide()
                self.tray_icon.setContextMenu(None)
                logger.debug("System tray icon hidden and cleaned up")
            except Exception as e:
                logger.error(f"Error hiding tray icon: {e}")

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
            self.start_slider_timer_signal.disconnect()  # Disconnect new signal
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

        # Status bar at the top
        status_frame = QtWidgets.QFrame()
        status_frame.setFixedHeight(40)
        status_layout = QtWidgets.QHBoxLayout(status_frame)
        status_layout.setContentsMargins(10, 0, 10, 0)
        self.status_label = QtWidgets.QLabel("MIDI Device: Not Connected")
        self.status_label.setStyleSheet(f"color: {TEXT_COLOR};")
        status_layout.addWidget(self.status_label)

        right_buttons_frame = QtWidgets.QFrame()
        right_buttons_layout = QtWidgets.QHBoxLayout(right_buttons_frame)
        right_buttons_layout.setSpacing(10)
        if QtWidgets.QSystemTrayIcon.isSystemTrayAvailable():
            minimize_button = QtWidgets.QPushButton("Hide to Tray")
            minimize_button.setStyleSheet(f"""
                background-color: {SECONDARY_COLOR};
                color: {TEXT_COLOR};
                border: none;
                padding: 5px 10px;
                border-radius: 5px;
            """)
            minimize_button.clicked.connect(self.hide_to_tray)
            right_buttons_layout.addWidget(minimize_button)
        self.connect_button = QtWidgets.QPushButton("Disconnect" if self.midi_controller.is_connected else "Connect")
        self.connect_button.setStyleSheet(f"""
            background-color: {PRIMARY_COLOR};
            color: {TEXT_COLOR};
            border: none;
            padding: 5px 10px;
            border-radius: 5px;
        """)
        self.connect_button.clicked.connect(self.disconnect_midi if self.midi_controller.is_connected else self.connect_to_midi)
        right_buttons_layout.addWidget(self.connect_button)
        notification_settings_button = QtWidgets.QPushButton("Notification Settings")
        notification_settings_button.setStyleSheet(f"""
            background-color: {SECONDARY_COLOR};
            color: {TEXT_COLOR};
            border: none;
            padding: 5px 10px;
            border-radius: 5px;
        """)
        notification_settings_button.clicked.connect(self.open_notification_settings)
        right_buttons_layout.addWidget(notification_settings_button)
        status_layout.addWidget(right_buttons_frame, alignment=QtCore.Qt.AlignRight)
        main_layout.addWidget(status_frame)

        # Separator
        separator = QtWidgets.QFrame()
        separator.setFrameShape(QtWidgets.QFrame.HLine)
        separator.setStyleSheet(f"color: {SECONDARY_COLOR};")
        main_layout.addWidget(separator)

        # Keyboard layout
        keyboard_frame = QtWidgets.QFrame()
        keyboard_layout = QtWidgets.QHBoxLayout(keyboard_frame)
        keyboard_layout.setSpacing(30)
        main_layout.addWidget(keyboard_frame)

        # Left section - Small buttons (3-8, 1-2)
        self.button_widgets = {}
        left_section = QtWidgets.QFrame()
        left_section.setFixedWidth(230)
        left_layout = QtWidgets.QVBoxLayout(left_section)
        left_layout.setSpacing(10)

        # Row 1 (Buttons 3, 4, 5)
        button_row_1 = QtWidgets.QFrame()
        button_row_1_layout = QtWidgets.QHBoxLayout(button_row_1)
        button_row_1_layout.setSpacing(5)
        for button_id in [3, 4, 5]:
            button = QtWidgets.QPushButton(self.mapping['button_names'][str(button_id)])
            button.setFixedSize(60, 40)
            button.setStyleSheet(f"""
                background-color: #333333;
                color: {TEXT_COLOR};
                border: 1px solid #555555;
                border-radius: 5px;
            """)
            button.clicked.connect(lambda checked, bid=button_id: self.show_button_config(bid))
            button_row_1_layout.addWidget(button)
            self.button_widgets[button_id] = button
        left_layout.addWidget(button_row_1)

        # Row 2 (Buttons 6, 7, 8)
        button_row_2 = QtWidgets.QFrame()
        button_row_2_layout = QtWidgets.QHBoxLayout(button_row_2)
        button_row_2_layout.setSpacing(5)
        for button_id in [6, 7, 8]:
            button = QtWidgets.QPushButton(self.mapping['button_names'][str(button_id)])
            button.setFixedSize(60, 40)
            button.setStyleSheet(f"""
                background-color: #333333;
                color: {TEXT_COLOR};
                border: 1px solid #555555;
                border-radius: 5px;
            """)
            button.clicked.connect(lambda checked, bid=button_id: self.show_button_config(bid))
            button_row_2_layout.addWidget(button)
            self.button_widgets[button_id] = button
        left_layout.addWidget(button_row_2)

        # Row 3 (Buttons 1, 2)
        button_row_3 = QtWidgets.QFrame()
        button_row_3_layout = QtWidgets.QHBoxLayout(button_row_3)
        button_row_3_layout.setSpacing(5)
        button_row_3_layout.addStretch(1)
        for button_id in [1, 2]:
            button = QtWidgets.QPushButton(self.mapping['button_names'][str(button_id)])
            button.setFixedSize(60, 40)
            button.setStyleSheet(f"""
                background-color: #333333;
                color: {TEXT_COLOR};
                border: 1px solid #555555;
                border-radius: 5px;
            """)
            button.clicked.connect(lambda checked, bid=button_id: self.show_button_config(bid))
            button_row_3_layout.addWidget(button)
            self.button_widgets[button_id] = button
        button_row_3_layout.addStretch(1)
        left_layout.addWidget(button_row_3)
        keyboard_layout.addWidget(left_section)

        # Slider section
        slider_frame = QtWidgets.QFrame()
        slider_frame.setFixedWidth(60)
        slider_layout = QtWidgets.QVBoxLayout(slider_frame)
        self.slider_label = QtWidgets.QLabel("SLIDER")
        self.slider_label.setStyleSheet(f"color: {TEXT_COLOR};")
        slider_layout.addWidget(self.slider_label, alignment=QtCore.Qt.AlignCenter)
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
        self.slider_enabled_checkbox.setStyleSheet(f"color: {TEXT_COLOR};")
        slider_layout.addWidget(self.slider_enabled_checkbox, alignment=QtCore.Qt.AlignCenter)
        slider_container = QtWidgets.QFrame()
        slider_container.setFixedSize(40, 140)
        slider_container.setStyleSheet(f"background-color: #1A1A1A; border: 2px solid #555555; border-radius: 5px;")
        slider_container_layout = QtWidgets.QVBoxLayout(slider_container)
        slider_id = self.mapping["layout"]["slider"][0]
        self.slider_widget = QtWidgets.QSlider(QtCore.Qt.Vertical)
        self.slider_widget.setRange(0, 100)
        self.slider_widget.setValue(0)
        self.slider_widget.setStyleSheet("""
            QSlider::groove:vertical {
                background: #FF1493;
                width: 8px;
                border-radius: 4px;
            }
            QSlider::handle:vertical {
                background: #00CED1;
                height: 20px;
                width: 20px;
                margin: 0 -6px;
                border-radius: 10px;
            }
            QSlider::handle:vertical:hover {
                background: #00FFFF;
            }
        """)
        self.slider_widget.valueChanged.connect(self.on_slider_change)
        if not initial_state:
            self.slider_widget.setStyleSheet("""
                QSlider::groove:vertical { background: #444444; width: 8px; border-radius: 4px; }
                QSlider::handle:vertical { background: #555555; height: 20px; width: 20px; margin: 0 -6px; border-radius: 10px; }
            """)
            self.slider_widget.setEnabled(False)
        slider_container_layout.addWidget(self.slider_widget)
        slider_layout.addWidget(slider_container, alignment=QtCore.Qt.AlignCenter)
        keyboard_layout.addWidget(slider_frame)

        # Right section - Pad buttons (40-51)
        pads_frame = QtWidgets.QFrame()
        pads_layout = QtWidgets.QGridLayout(pads_frame)
        pads_layout.setSpacing(10)
        for row in range(2):
            for col in range(6):
                button_id = 40 + col + (row * 6)
                pad_button = QtWidgets.QPushButton(f"Pad {col+1 + row*6}\nButton {button_id}")
                pad_button.setFixedSize(80, 80)
                pad_button.setStyleSheet(f"""
                    background-color: #2A2A2A;
                    color: {TEXT_COLOR};
                    border: 2px solid #555555;
                    border-radius: 5px;
                """)
                pad_button.clicked.connect(lambda checked, bid=button_id: self.show_button_config(bid))
                pads_layout.addWidget(pad_button, row, col)
                self.button_widgets[button_id] = pad_button
        keyboard_layout.addWidget(pads_frame)

        # Message area at the bottom
        message_frame = QtWidgets.QFrame()
        message_frame.setFixedHeight(30)
        message_layout = QtWidgets.QHBoxLayout(message_frame)
        message_layout.setContentsMargins(10, 0, 0, 0)
        self.message_label = QtWidgets.QLabel("Ready")
        self.message_label.setStyleSheet(f"color: {TEXT_COLOR};")
        message_layout.addWidget(self.message_label)
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

    def auto_connect_midi(self):
        logger.info("Attempting to auto-connect to MIDI device")
        success, message = self.midi_controller.find_easypad()
        if success:
            logger.info(f"Auto-connected to MIDI device: {self.midi_controller.port_name}")
            self.status_label.setText(f"MIDI Device: {self.midi_controller.port_name}")
            self.connect_button.setText("Disconnect")
            self.connect_button.clicked.disconnect()
            self.connect_button.clicked.connect(self.disconnect_midi)
            self.midi_controller.start_monitoring()
            self.message_signal.emit("Connected to MIDI device")
            self.system_actions.set_midi_port(self.midi_controller.port_name)
        else:
            logger.warning(f"Failed to auto-connect: {message}")
            self.message_signal.emit("MIDI device not found. Connect manually.")

    def connect_to_midi(self):
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle("Connect to MIDI Device")
        dialog.setFixedSize(400, 300)
        layout = QtWidgets.QVBoxLayout(dialog)
        layout.addWidget(QtWidgets.QLabel("Select MIDI Device:"))
        available_ports = self.midi_controller.get_available_ports()
        logger.info(f"Available MIDI ports for manual connection: {available_ports}")
        if available_ports:
            device_combo = QtWidgets.QComboBox()
            device_combo.addItems(available_ports)
            layout.addWidget(device_combo)
            connect_btn = QtWidgets.QPushButton("Connect")
            connect_btn.setStyleSheet(f"background-color: {PRIMARY_COLOR}; color: {TEXT_COLOR}; border-radius: 5px;")
            connect_btn.clicked.connect(lambda: self.finalize_connection(dialog, device_combo.currentText()))
            layout.addWidget(connect_btn)
        else:
            layout.addWidget(QtWidgets.QLabel("No MIDI devices found"))
            close_btn = QtWidgets.QPushButton("Close")
            close_btn.setStyleSheet(f"background-color: {PRIMARY_COLOR}; color: {TEXT_COLOR}; border-radius: 5px;")
            close_btn.clicked.connect(dialog.reject)
            layout.addWidget(close_btn)
        layout.addStretch()
        dialog.exec_()

    def finalize_connection(self, dialog, port_name):
        success, message = self.midi_controller.connect_to_device(port_name=port_name)
        if success:
            self.status_label.setText(f"MIDI Device: {port_name}")
            self.connect_button.setText("Disconnect")
            self.connect_button.clicked.disconnect()
            self.connect_button.clicked.connect(self.disconnect_midi)
            self.midi_controller.start_monitoring()
            self.message_signal.emit(f"Connected to {port_name}")
            self.system_actions.set_midi_port(port_name)
        else:
            self.message_signal.emit(f"Connection failed: {message}")
        dialog.accept()

    def disconnect_midi(self):
        success, message = self.midi_controller.disconnect()
        if success:
            self.status_label.setText("MIDI Device: Not Connected")
            self.connect_button.setText("Connect")
            self.connect_button.clicked.disconnect()
            self.connect_button.clicked.connect(self.connect_to_midi)
            self.message_signal.emit("Disconnected from MIDI device")
            self.system_actions.set_midi_port(None)
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
                        else:
                            self.action_signal.emit(button_id, None)
                        if button_id in self.button_widgets:
                            self.button_style_signal.emit(button_id, True)
                
                # Note Off (release) for pads (buttons 40-51)
                elif (128 <= status_byte <= 143) or (144 <= status_byte <= 159 and data2 == 0):
                    note = data1
                    button_id = note
                    if str(button_id) in self.button_config and self.button_config[str(button_id)].get('action_type') == 'speech_to_text':
                        self.stop_speech_recognition(button_id)
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

    def on_slider_change(self, value):
        self.last_slider_value = value
        self.start_slider_timer_signal.emit()  # Emit signal instead of starting timer

    def highlight_button(self, button_id, is_active):
        widget = self.button_widgets.get(int(button_id))
        if not widget:
            logger.warning(f"Button ID {button_id} not found in button widgets")
            return
        if isinstance(widget, QtWidgets.QPushButton):
            if is_active:
                widget.setStyleSheet(f"""
                    background-color: {PRIMARY_COLOR};
                    color: {TEXT_COLOR};
                    border: 1px solid #555555;
                    border-radius: 5px;
                    font: {widget.font().toString()};
                """)
                self.active_buttons.add(button_id)
            else:
                original_bg = "#333333" if button_id < 40 else "#2A2A2A"
                widget.setStyleSheet(f"""
                    background-color: {original_bg};
                    color: {TEXT_COLOR};
                    border: {'1px' if button_id < 40 else '2px'} solid #555555;
                    border-radius: 5px;
                    font: {widget.font().toString()};
                """)
                if button_id in self.active_buttons:
                    self.active_buttons.remove(button_id)

    def flash_button(self, button):
        if isinstance(button, QtWidgets.QPushButton):
            original_style = button.styleSheet()
            button.setStyleSheet(f"""
                background-color: {PRIMARY_COLOR};
                color: {TEXT_COLOR};
                border: 1px solid #555555;
                border-radius: 5px;
            """)
            timer = QtCore.QTimer(self)
            timer.setSingleShot(True)
            timer.timeout.connect(lambda: button.setStyleSheet(original_style))
            timer.start(100)

    def reset_button_style(self, button_id):
        widget = self.button_widgets.get(button_id)
        if widget:
            original_bg = "#333333" if button_id < 40 else "#2A2A2A"
            border_width = '1px' if button_id < 40 else '2px'
            widget.setStyleSheet(f"""
                background-color: {original_bg};
                color: {TEXT_COLOR};
                border: {border_width} solid #555555;
                border-radius: 5px;
            """)

    def update_button_style(self, button_id, is_pressed):
        widget = self.button_widgets.get(button_id)
        if widget:
            config = self.button_config.get(str(button_id))
            if config and config.get("enabled", True):
                if is_pressed:
                    widget.setStyleSheet(f"""
                        background-color: {PRIMARY_COLOR};
                        color: {TEXT_COLOR};
                        border: {'1px' if button_id < 40 else '2px'} solid #555555;
                        border-radius: 5px;
                    """)
                else:
                    widget.setStyleSheet(f"""
                        background-color: #444444;
                        color: {TEXT_COLOR};
                        border: {'1px' if button_id < 40 else '2px'} solid #555555;
                        border-radius: 5px;
                    """)
            else:
                original_bg = "#333333" if button_id < 40 else "#2A2A2A"
                widget.setStyleSheet(f"""
                    background-color: {original_bg};
                    color: {TEXT_COLOR};
                    border: {'1px' if button_id < 40 else '2px'} solid #555555;
                    border-radius: 5px;
                """)

    def set_button_pressed_style(self, button_id):
        widget = self.button_widgets.get(button_id)
        if widget:
            widget.setStyleSheet(f"""
                background-color: {PRIMARY_COLOR};
                color: {TEXT_COLOR};
                border: {'1px' if button_id < 40 else '2px'} solid #555555;
                border-radius: 5px;
            """)

    def show_button_config(self, button_id):
        dialog = ButtonConfigDialog(self, button_id)
        dialog.exec_()

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
                else:
                    widget.setText(f"{button_name}\n{short_desc}")
                widget.setStyleSheet(f"""
                    background-color: #444444;
                    color: {TEXT_COLOR};
                    border: {'1px' if button_id < 40 else '2px'} solid #555555;
                    border-radius: 5px;
                    font: {widget.font().toString()};
                """)

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
                    if action_type not in ["speech_to_text", "media", "audio_device"]:
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

    def recognize_speech(self, audio_data, language):
        try:
            audio_segment = sr.AudioData(audio_data, 44100, 2)
            recognizer = sr.Recognizer()
            text = recognizer.recognize_google(audio_segment, language=language)
            logging.info(f"Recognized text: {text}")
            pyperclip.copy(text)
            time.sleep(0.1)
            pyautogui.hotkey('ctrl', 'v')
            time.sleep(0.1)
            pyautogui.press('space')
        except sr.UnknownValueError:
            logging.warning("Could not understand audio")
        except sr.RequestError as e:
            logging.error(f"Speech recognition error: {e}")
        except Exception as e:
            logging.error(f"Unexpected error in speech recognition: {e}")

    def toggle_slider(self):
        enabled = self.slider_enabled_checkbox.isChecked()
        try:
            config_path = os.path.join(os.path.dirname(__file__), "config", "slider_config.json")
            os.makedirs(os.path.dirname(config_path), exist_ok=True)
            with open(config_path, 'w') as f:
                json.dump({"enabled": enabled}, f)
        except Exception as e:
            logger.error(f"Failed to save slider state: {e}")
        if not enabled:
            self._previous_slider_value = self.slider_widget.value()
            self.slider_widget.setValue(0)
            self.slider_widget.setStyleSheet("""
                QSlider::groove:vertical { background: #444444; width: 8px; border-radius: 4px; }
                QSlider::handle:vertical { background: #555555; height: 20px; width: 20px; margin: 0 -6px; border-radius: 10px; }
            """)
            self.slider_widget.setEnabled(False)
            self.message_signal.emit("Slider disabled")
        else:
            self.slider_widget.setStyleSheet("""
                QSlider::groove:vertical { background: #FF1493; width: 8px; border-radius: 4px; }
                QSlider::handle:vertical { background: #00CED1; height: 20px; width: 20px; margin: 0 -6px; border-radius: 10px; }
                QSlider::handle:vertical:hover { background: #00FFFF; }
            """)
            self.slider_widget.setEnabled(True)
            if hasattr(self, '_previous_slider_value'):
                self.slider_widget.setValue(self._previous_slider_value)
                self.system_actions.set_volume("set", self._previous_slider_value)
            self.message_signal.emit("Slider enabled")

    def open_notification_settings(self):
        dialog = NotificationSettingsDialog(self, self.notification_manager)
        dialog.exec_()

class ButtonConfigDialog(QtWidgets.QDialog):
    def __init__(self, parent, button_id):
        super().__init__(parent)
        self.parent = parent
        self.button_id = button_id
        self.setWindowTitle(f"Configure {parent.mapping['button_names'].get(str(button_id), f'Button {button_id}')}")
        self.setFixedSize(500, 450)
        self.current_config = load_button_config(button_id)
        layout = QtWidgets.QVBoxLayout(self)

        # Button name
        name_frame = QtWidgets.QFrame()
        name_layout = QtWidgets.QHBoxLayout(name_frame)
        name_label = QtWidgets.QLabel("Button Name:")
        self.button_name_entry = QtWidgets.QLineEdit()
        self.button_name_entry.setText(self.current_config.get("name", f"Button {button_id}"))
        name_layout.addWidget(name_label)
        name_layout.addWidget(self.button_name_entry)
        layout.addWidget(name_frame)

        # Action type
        action_type_frame = QtWidgets.QFrame()
        action_type_layout = QtWidgets.QHBoxLayout(action_type_frame)
        action_type_label = QtWidgets.QLabel("Action Type:")
        self.action_type_combo = QtWidgets.QComboBox()
        action_types = get_action_types()
        self.display_to_internal = {}
        for key, info in action_types.items():
            self.action_type_combo.addItem(info["name"], key)
            self.display_to_internal[info["name"]] = key
        if self.current_config.get("action_type"):
            index = self.action_type_combo.findData(self.current_config["action_type"])
            if index >= 0:
                self.action_type_combo.setCurrentIndex(index)
        self.action_type_combo.currentIndexChanged.connect(self.update_action_form)
        action_type_layout.addWidget(action_type_label)
        action_type_layout.addWidget(self.action_type_combo)
        layout.addWidget(action_type_frame)

        # Action form frame with a single layout
        self.action_form_widget = QtWidgets.QWidget()
        self.action_form_layout = QtWidgets.QVBoxLayout(self.action_form_widget)
        layout.addWidget(self.action_form_widget)
        self.form_widgets = {}
        self.update_action_form()

        # Enabled checkbox
        self.enabled_check = QtWidgets.QCheckBox("Enabled")
        self.enabled_check.setChecked(self.current_config.get("enabled", True))
        layout.addWidget(self.enabled_check)

        # Buttons
        button_frame = QtWidgets.QFrame()
        button_layout = QtWidgets.QHBoxLayout(button_frame)
        save_button = QtWidgets.QPushButton("Save")
        save_button.setStyleSheet(f"background-color: {PRIMARY_COLOR}; color: {TEXT_COLOR}; border-radius: 5px; padding: 10px 20px;")
        save_button.clicked.connect(self.save_config)
        cancel_button = QtWidgets.QPushButton("Cancel")
        cancel_button.setStyleSheet(f"background-color: #555555; color: {TEXT_COLOR}; border-radius: 5px; padding: 10px 20px;")
        cancel_button.clicked.connect(self.reject)
        button_layout.addStretch()
        button_layout.addWidget(cancel_button)
        button_layout.addWidget(save_button)
        layout.addWidget(button_frame)

    def update_action_form(self):
        while self.action_form_layout.count():
            item = self.action_form_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.form_widgets = {}
        action_type = self.action_type_combo.currentData()
        existing_data = self.current_config.get('action_data', {}) if self.current_config.get('action_type') == action_type else {}
        if action_type == "app" or action_type == "toggle_app":
            path_frame = QtWidgets.QFrame()
            path_layout = QtWidgets.QHBoxLayout(path_frame)
            path_label = QtWidgets.QLabel("Application Path:")
            self.form_widgets["path"] = QtWidgets.QLineEdit(existing_data.get("path", ""))
            browse_button = QtWidgets.QPushButton("Browse")
            browse_button.clicked.connect(lambda: self.browse_file(self.form_widgets["path"]))
            path_layout.addWidget(path_label)
            path_layout.addWidget(self.form_widgets["path"])
            path_layout.addWidget(browse_button)
            self.action_form_layout.addWidget(path_frame)
            args_frame = QtWidgets.QFrame()
            args_layout = QtWidgets.QHBoxLayout(args_frame)
            args_label = QtWidgets.QLabel("Arguments (optional):")
            self.form_widgets["args"] = QtWidgets.QLineEdit(existing_data.get("args", ""))
            args_layout.addWidget(args_label)
            args_layout.addWidget(self.form_widgets["args"])
            self.action_form_layout.addWidget(args_frame)
            self.action_form_layout.addWidget(QtWidgets.QLabel("* Application Path is required", styleSheet="color: orange;"))
        elif action_type == "web":
            url_frame = QtWidgets.QFrame()
            url_layout = QtWidgets.QHBoxLayout(url_frame)
            url_label = QtWidgets.QLabel("Website URL:")
            self.form_widgets["url"] = QtWidgets.QLineEdit(existing_data.get("url", ""))
            url_layout.addWidget(url_label)
            url_layout.addWidget(self.form_widgets["url"])
            self.action_form_layout.addWidget(url_frame)
            self.action_form_layout.addWidget(QtWidgets.QLabel("* URL is required (e.g., https://www.example.com)", styleSheet="color: orange;"))
        elif action_type == "volume":
            action_frame = QtWidgets.QFrame()
            action_layout = QtWidgets.QHBoxLayout(action_frame)
            action_label = QtWidgets.QLabel("Action:")
            self.form_widgets["action"] = QtWidgets.QComboBox()
            actions = ["increase", "decrease", "mute", "unmute", "set"]
            self.form_widgets["action"].addItems(actions)
            self.form_widgets["action"].setCurrentText(existing_data.get("action", "increase"))
            action_layout.addWidget(action_label)
            action_layout.addWidget(self.form_widgets["action"])
            self.action_form_layout.addWidget(action_frame)
            self.action_form_layout.addWidget(QtWidgets.QLabel("Note: For slider control, the action will be 'set'", styleSheet="color: gray;"))
        elif action_type == "media":
            media_frame = QtWidgets.QFrame()
            media_layout = QtWidgets.QHBoxLayout(media_frame)
            media_label = QtWidgets.QLabel("Control:")
            self.form_widgets["media"] = QtWidgets.QComboBox()
            media_controls = get_media_controls()
            self.media_map = {control["name"]: key for key, control in media_controls.items()}
            self.form_widgets["media"].addItems(self.media_map.keys())
            existing_control = existing_data.get("control", "play_pause")
            display_value = next((k for k, v in self.media_map.items() if v == existing_control), "Play/Pause")
            self.form_widgets["media"].setCurrentText(display_value)
            media_layout.addWidget(media_label)
            media_layout.addWidget(self.form_widgets["media"])
            self.action_form_layout.addWidget(media_frame)
        elif action_type == "shortcut":
            shortcut_frame = QtWidgets.QFrame()
            shortcut_layout = QtWidgets.QHBoxLayout(shortcut_frame)
            shortcut_label = QtWidgets.QLabel("Shortcut:")
            self.form_widgets["shortcut"] = QtWidgets.QLineEdit(existing_data.get("shortcut", ""))
            shortcut_layout.addWidget(shortcut_label)
            shortcut_layout.addWidget(self.form_widgets["shortcut"])
            self.action_form_layout.addWidget(shortcut_frame)
            self.action_form_layout.addWidget(QtWidgets.QLabel("Examples: ctrl+c, alt+tab, win+r", styleSheet="color: gray;"))
        elif action_type == "audio_device":
            device_frame = QtWidgets.QFrame()
            device_layout = QtWidgets.QHBoxLayout(device_frame)
            device_label = QtWidgets.QLabel("Device Name:")
            self.form_widgets["device_name"] = QtWidgets.QLineEdit(existing_data.get("device_name", ""))
            device_layout.addWidget(device_label)
            device_layout.addWidget(self.form_widgets["device_name"])
            self.action_form_layout.addWidget(device_frame)
            self.action_form_layout.addWidget(QtWidgets.QLabel("Leave empty to toggle; enter name to switch", styleSheet="color: gray;"))
        elif action_type in ["command", "powershell"]:
            commands_list = (existing_data.get("commands", []) + [{}] * 3)[:3]
            for i in range(3):
                cmd_frame = QtWidgets.QFrame()
                cmd_layout = QtWidgets.QHBoxLayout(cmd_frame)
                cmd_label = QtWidgets.QLabel(f"{'PS ' if action_type == 'powershell' else ''}Command {i+1}:")
                self.form_widgets[f"command_{i}"] = QtWidgets.QLineEdit(commands_list[i].get("command", ""))
                delay_label = QtWidgets.QLabel("Delay (ms):")
                self.form_widgets[f"delay_{i}"] = QtWidgets.QLineEdit(str(commands_list[i].get("delay_ms", 0)))
                self.form_widgets[f"delay_{i}"].setFixedWidth(50)
                cmd_layout.addWidget(cmd_label)
                cmd_layout.addWidget(self.form_widgets[f"command_{i}"])
                cmd_layout.addWidget(delay_label)
                cmd_layout.addWidget(self.form_widgets[f"delay_{i}"])
                self.action_form_layout.addWidget(cmd_frame)
            self.action_form_layout.addWidget(QtWidgets.QLabel(f"Enter up to 3 {'PowerShell ' if action_type == 'powershell' else ''}commands", styleSheet="color: gray;"))
        elif action_type == "text":
            text_frame = QtWidgets.QFrame()
            text_layout = QtWidgets.QHBoxLayout(text_frame)
            text_label = QtWidgets.QLabel("Text to Type:")
            self.form_widgets["text"] = QtWidgets.QLineEdit(existing_data.get("text", ""))
            text_layout.addWidget(text_label)
            text_layout.addWidget(self.form_widgets["text"])
            self.action_form_layout.addWidget(text_frame)
        elif action_type == "speech_to_text":
            lang_frame = QtWidgets.QFrame()
            lang_layout = QtWidgets.QHBoxLayout(lang_frame)
            lang_label = QtWidgets.QLabel("Language:")
            self.form_widgets["language"] = QtWidgets.QComboBox()
            languages = {"English": "en-US", "Russian": "ru-RU", "Combined (Experimental)": "ru-RU,en-US"}
            self.language_map = languages
            self.form_widgets["language"].addItems(languages.keys())
            language_code = existing_data.get("language", "en-US")
            display_lang = next((k for k, v in languages.items() if v == language_code), "English")
            self.form_widgets["language"].setCurrentText(display_lang)
            lang_layout.addWidget(lang_label)
            lang_layout.addWidget(self.form_widgets["language"])
            self.action_form_layout.addWidget(lang_frame)
            self.action_form_layout.addWidget(QtWidgets.QLabel("Hold button to type speech", styleSheet="color: gray;"))
        self.action_form_layout.addStretch()

    def save_config(self):
        from app.utils import save_button_config
        action_type = self.action_type_combo.currentData()
        action_data = self.get_action_data()
        name = self.button_name_entry.text()
        enabled = self.enabled_check.isChecked()
        
        config = {
            "action_type": action_type,
            "action_data": action_data,
            "name": name,
            "enabled": enabled
        }
        if save_button_config(self.button_id, config):
            action_types = get_action_types()
            display_action = action_types.get(action_type, {}).get("name", action_type)
            self.parent.update_button_label(self.button_id, display_action, name)
            self.parent.load_config()
            self.accept()
        else:
            QtWidgets.QMessageBox.warning(self, "Error", "Failed to save configuration")

    def get_action_data(self):
        action_type = self.action_type_combo.currentData()
        action_data = {}
        
        if action_type in ["app", "toggle_app"]:
            action_data["path"] = self.form_widgets.get("path", QtWidgets.QLineEdit()).text()
            action_data["args"] = self.form_widgets.get("args", QtWidgets.QLineEdit()).text()
        elif action_type == "web":
            action_data["url"] = self.form_widgets.get("url", QtWidgets.QLineEdit()).text()
        elif action_type == "volume":
            action_data["action"] = self.form_widgets.get("action", QtWidgets.QComboBox()).currentText()
        elif action_type == "media":
            action_data["control"] = self.media_map.get(self.form_widgets.get("media", QtWidgets.QComboBox()).currentText(), "play_pause")
        elif action_type == "shortcut":
            action_data["shortcut"] = self.form_widgets.get("shortcut", QtWidgets.QLineEdit()).text()
        elif action_type == "audio_device":
            action_data["device_name"] = self.form_widgets.get("device_name", QtWidgets.QLineEdit()).text()
        elif action_type in ["command", "powershell"]:
            commands = []
            for i in range(3):
                cmd = self.form_widgets.get(f"command_{i}", QtWidgets.QLineEdit()).text()
                delay = self.form_widgets.get(f"delay_{i}", QtWidgets.QLineEdit()).text()
                if cmd:
                    commands.append({"command": cmd, "delay_ms": int(delay) if delay.isdigit() else 0})
            action_data["commands"] = commands
        elif action_type == "text":
            action_data["text"] = self.form_widgets.get("text", QtWidgets.QLineEdit()).text()
        elif action_type == "speech_to_text":
            action_data["language"] = self.language_map.get(self.form_widgets.get("language", QtWidgets.QComboBox()).currentText(), "en-US")
        
        return action_data

    def browse_file(self, entry):
        file_path = QtWidgets.QFileDialog.getOpenFileName(self, "Select Application", "", "Executable files (*.exe);;All files (*.*);;Shortcut files (*.lnk)")[0]
        if file_path:
            entry.setText(file_path)

class NotificationSettingsDialog(QtWidgets.QDialog):
    def __init__(self, parent, notification_manager):
        super().__init__(parent)
        self.notification_manager = notification_manager
        self.setWindowTitle("Notification Settings")
        self.setFixedSize(400, 350)
        layout = QtWidgets.QVBoxLayout(self)

        self.music_track_check = QtWidgets.QCheckBox("Music Track Changes")
        self.music_track_check.setChecked(self.notification_manager.settings['music_track'])
        layout.addWidget(self.music_track_check)

        self.volume_adjustment_check = QtWidgets.QCheckBox("Volume Adjustments")
        self.volume_adjustment_check.setChecked(self.notification_manager.settings['volume_adjustment'])
        layout.addWidget(self.volume_adjustment_check)

        self.device_change_check = QtWidgets.QCheckBox("Device Changes")
        self.device_change_check.setChecked(self.notification_manager.settings['device_change'])
        layout.addWidget(self.device_change_check)

        self.speech_to_text_check = QtWidgets.QCheckBox("Speech-to-Text Status")
        self.speech_to_text_check.setChecked(self.notification_manager.settings['speech_to_text'])
        layout.addWidget(self.speech_to_text_check)

        self.button_action_check = QtWidgets.QCheckBox("Button Actions")
        self.button_action_check.setChecked(self.notification_manager.settings['button_action'])
        layout.addWidget(self.button_action_check)

        theme_frame = QtWidgets.QFrame()
        theme_layout = QtWidgets.QHBoxLayout(theme_frame)
        theme_label = QtWidgets.QLabel("Theme:")
        self.theme_combo = QtWidgets.QComboBox()
        self.theme_combo.addItems(["dark", "light"])
        self.theme_combo.setCurrentText(self.notification_manager.settings['theme'])
        theme_layout.addWidget(theme_label)
        theme_layout.addWidget(self.theme_combo)
        layout.addWidget(theme_frame)

        position_frame = QtWidgets.QFrame()
        position_layout = QtWidgets.QHBoxLayout(position_frame)
        position_label = QtWidgets.QLabel("Position:")
        self.position_combo = QtWidgets.QComboBox()
        self.position_combo.addItems(["bottom-right", "top-right", "bottom-left", "top-left"])
        self.position_combo.setCurrentText(self.notification_manager.settings['position'])
        position_layout.addWidget(position_label)
        position_layout.addWidget(self.position_combo)
        layout.addWidget(position_frame)

        size_frame = QtWidgets.QFrame()
        size_layout = QtWidgets.QHBoxLayout(size_frame)
        size_label = QtWidgets.QLabel("Size (width x height):")
        self.width_spin = QtWidgets.QSpinBox()
        self.width_spin.setRange(100, 500)
        self.width_spin.setValue(self.notification_manager.settings['size'][0])
        self.height_spin = QtWidgets.QSpinBox()
        self.height_spin.setRange(50, 200)
        self.height_spin.setValue(self.notification_manager.settings['size'][1])
        size_layout.addWidget(size_label)
        size_layout.addWidget(self.width_spin)
        size_layout.addWidget(self.height_spin)
        layout.addWidget(size_frame)

        font_size_frame = QtWidgets.QFrame()
        font_size_layout = QtWidgets.QHBoxLayout(font_size_frame)
        font_size_label = QtWidgets.QLabel("Font Size:")
        self.font_size_spin = QtWidgets.QSpinBox()
        self.font_size_spin.setRange(8, 24)
        self.font_size_spin.setValue(self.notification_manager.settings['font_size'])
        font_size_layout.addWidget(font_size_label)
        font_size_layout.addWidget(self.font_size_spin)
        layout.addWidget(font_size_frame)

        save_button = QtWidgets.QPushButton("Save")
        save_button.setStyleSheet(f"background-color: {PRIMARY_COLOR}; color: {TEXT_COLOR}; border-radius: 5px; padding: 10px 20px;")
        save_button.clicked.connect(self.save_settings)
        layout.addWidget(save_button)

    def save_settings(self):
        settings = {
            'music_track': self.music_track_check.isChecked(),
            'volume_adjustment': self.volume_adjustment_check.isChecked(),
            'device_change': self.device_change_check.isChecked(),
            'speech_to_text': self.speech_to_text_check.isChecked(),
            'button_action': self.button_action_check.isChecked(),
            'theme': self.theme_combo.currentText(),
            'position': self.position_combo.currentText(),
            'size': (self.width_spin.value(), self.height_spin.value()),
            'font_size': self.font_size_spin.value()
        }
        self.notification_manager.update_settings(settings)
        self.accept()

if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    app.setStyleSheet(f"""
        QtWidgets.QWidget {{ background-color: {DARK_BG}; }}
        QtWidgets.QPushButton:hover {{ background-color: {BUTTON_ACTIVE_COLOR}; }}
    """)
    window = MIDIKeyboardApp()
    window.show()
    sys.exit(app.exec_())