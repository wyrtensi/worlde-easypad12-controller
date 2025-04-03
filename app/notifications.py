import sys
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QApplication, QProgressBar, QHBoxLayout, QFrame
from PySide6.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve, QPoint, QRect, QRectF
from PySide6.QtGui import QPainter, QPainterPath, QColor, QFont, QLinearGradient
import os
import json
import logging
from app.utils import setup_logging, ensure_app_directories
import traceback
logger = setup_logging()

class VolumeProgressBar(QProgressBar):
    def __init__(self, parent=None, theme_settings=None):
        super().__init__(parent)
        self.setRange(0, 100)
        self.setTextVisible(False)
        self.setFixedHeight(10)
        
        # Default style
        self.setStyleSheet("""
            QProgressBar {
                background-color: #444444;
                border-radius: 5px;
                padding: 0px;
            }
            QProgressBar::chunk {
                background-color: #1E88E5;
                border-radius: 5px;
            }
        """)
        
        # Gradient settings
        self.use_gradient = False
        self.gradient_start_color = "#104a7d"  # Default dark blue
        self.gradient_end_color = "#1E88E5"    # Default blue
        
        # Apply theme settings if provided
        if theme_settings:
            self.apply_theme(theme_settings)
    
    def setGradient(self, enabled, start_color=None, end_color=None):
        """Enable/disable gradient and set gradient colors"""
        self.use_gradient = enabled
        if start_color:
            self.gradient_start_color = start_color
        if end_color:
            self.gradient_end_color = end_color
        self.update()
    
    def apply_theme(self, theme_settings):
        """Apply theme settings to progress bar"""
        progress_color = theme_settings.get('progress_color', '#1E88E5')
        bg_color = theme_settings.get('progress_bg_color', '#444444')
        
        # Create gradient start color (darker version of progress color)
        if progress_color.startswith('#') and len(progress_color) == 7:
            # Convert hex to RGB, darken it, and convert back to hex
            r = int(progress_color[1:3], 16)
            g = int(progress_color[3:5], 16)
            b = int(progress_color[5:7], 16)
            
            # Create darker version (50% brightness - darker than before)
            r = max(0, int(r * 0.5))
            g = max(0, int(g * 0.5))
            b = max(0, int(b * 0.5))
            
            self.gradient_start_color = f"#{r:02x}{g:02x}{b:02x}"
        else:
            self.gradient_start_color = "#0A3152"  # Default darker blue
        
        self.gradient_end_color = progress_color
        self.use_gradient = True
        
        # If not using gradient, update the stylesheet
        if not self.use_gradient:
            self.setStyleSheet(f"""
                QProgressBar {{
                    background-color: {bg_color};
                    border-radius: 5px;
                    padding: 0px;
                }}
                QProgressBar::chunk {{
                    background-color: {progress_color};
                    border-radius: 5px;
                }}
            """)
        
        self.update()
    
    def paintEvent(self, event):
        if not self.use_gradient:
            # Use standard painting if gradient is disabled
            super().paintEvent(event)
            return
        
        # Custom painting for gradient effect
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        # Background
        bg_rect = self.rect()
        bg_path = QPainterPath()
        bg_path.addRoundedRect(QRectF(bg_rect), 5, 5)
        painter.fillPath(bg_path, QColor('#444444'))
        
        # Progress chunk with gradient
        progress = self.value()
        width = self.width() * progress / 100
        
        if width > 0:
            # Create gradient
            gradient = QLinearGradient(0, 0, width, 0)
            gradient.setColorAt(0, QColor(self.gradient_start_color))
            gradient.setColorAt(1, QColor(self.gradient_end_color))
            
            # Draw progress chunk with rounded corners
            prog_rect = QRectF(0, 0, width, self.height())
            prog_path = QPainterPath()
            prog_path.addRoundedRect(prog_rect, 5, 5)
            painter.fillPath(prog_path, gradient)
        
        painter.end()

class NotificationWindow(QWidget):
    def __init__(self, message, theme='dark', position='bottom-right', size=(300, 100), font_size=12, notification_type=None, theme_settings=None):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.message = message
        self.theme = theme
        self.position = position
        self.notification_type = notification_type
        self.theme_settings = theme_settings or {}  # Custom theme settings
        
        # Ensure size is a tuple of two integers
        if isinstance(size, (list, tuple)) and len(size) == 2:
            try:
                self.size = (int(size[0]), int(size[1]))
            except (ValueError, TypeError):
                self.size = (300, 100)  # Default if conversion fails
        else:
            self.size = (300, 100)  # Default for invalid size
                
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
        
        # Enable mouse tracking for click-to-dismiss
        self.setMouseTracking(True)
        self.setCursor(Qt.PointingHandCursor)  # Change cursor to indicate clickable

    def mousePressEvent(self, event):
        """Handle mouse press events to dismiss notification on click"""
        if event.button() == Qt.LeftButton:
            self.close_animation()
        super().mousePressEvent(event)

    def initUI(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)  # Reduce outer margins to maximize space
        
        # Special handling for volume adjustment notifications
        if self.notification_type == 'volume_adjustment':
            self.createVolumeNotification(layout)
        else:
            self.createStandardNotification(layout)
        
        # Ensure size values are valid for setFixedSize
        try:
            # Add a few pixels to height for text if size is very small
            width, height = self.size
            if height < 50:
                height = max(50, height + 10)  # Increase by 10px if below threshold
                self.size = (width, height)
            self.setFixedSize(self.size[0], self.size[1])
        except (TypeError, IndexError):
            self.setFixedSize(300, 100)  # Default size

    def createStandardNotification(self, layout):
        self.label = QLabel(self.message)
        self.label.setAlignment(Qt.AlignCenter)
        
        # Set word wrap based on theme settings
        single_line_text = self.theme_settings.get('single_line_text', False)
        self.label.setWordWrap(not single_line_text)  # Set word wrap to opposite of single_line_text
        
        self.label.setMinimumHeight(30)  # Ensure minimum height for text
        
        # Apply font settings
        font = self.label.font()
        
        # Apply font family if specified
        font_family = self.theme_settings.get('font_family')
        if font_family:
            font.setFamily(font_family)
        
        # Apply font size
        try:
            font_size_int = int(self.font_size) if isinstance(self.font_size, (int, str)) else 12
            font.setPointSize(font_size_int)
        except (ValueError, TypeError):
            font.setPointSize(12)
        
        # Apply font weight
        font_weight = self.theme_settings.get('font_weight', 'normal')
        if font_weight == 'bold':
            font.setBold(True)
        elif font_weight == 'light':
            font.setWeight(QFont.Light)
        
        self.label.setFont(font)
        
        # Apply text color if specified - use standalone styling without background
        text_color = self.theme_settings.get('text_color') or self.theme_settings.get('font_color')
        if text_color:
            self.label.setStyleSheet(f"color: {text_color}; background: transparent;")
        
        # Get background style
        bg_style = self.theme_settings.get('bg_style', 'solid')
        is_gradient = bg_style == 'gradient'
        
        # Always check if container should be shown
        show_container = self.theme_settings.get('show_container', True)
        
        # Log container settings
        logger.debug(f"Standard notification: show_container={show_container}, bg_style={bg_style}, single_line_text={single_line_text}")
        
        if show_container:
            # Create container frame
            container = QFrame()
            
            # Use specified container color, regardless of background style
            container_color = self.theme_settings.get('container_color', '#444444')
            
            # Apply rounded corners with custom border radius if specified
            rounded_corners = self.theme_settings.get('rounded_corners', True)
            if rounded_corners:
                # Use custom border radius if provided, otherwise default to 6px
                border_radius_value = self.theme_settings.get('border_radius', 6)
                border_radius = f"{border_radius_value}px"
            else:
                border_radius = "0px"
            
            # Use padding without margin to maximize text space
            container_style = f"""
                background-color: {container_color}; 
                border-radius: {border_radius}; 
                padding: 6px; 
                margin: 0px;
            """
            container.setStyleSheet(container_style)
            
            # Use minimal margins to maximize text space
            container_layout = QVBoxLayout(container)
            container_layout.setContentsMargins(2, 2, 2, 2)
            container_layout.setSpacing(0)  # Reduce spacing to give text more room
            container_layout.addWidget(self.label, 1, Qt.AlignCenter)  # Use stretch factor and alignment
            layout.addWidget(container)
        else:
            # No container, add the label directly to main layout
            # Force transparent background on the label when no container is used
            current_style = self.label.styleSheet()
            self.label.setStyleSheet(current_style + "; background: transparent;")
            layout.addWidget(self.label)
            
    def createVolumeNotification(self, layout):
        # Main widget and layout to hold both container and progress bar
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(3)  # Reduce spacing between text container and progress bar
        
        # Extract volume percentage from message
        try:
            volume_str = self.message.strip().lower()
            volume = int(''.join(filter(str.isdigit, volume_str)))
        except (ValueError, AttributeError):
            volume = 0
        
        # Create label for volume text
        self.label = QLabel(f"{volume}%")
        self.label.setAlignment(Qt.AlignCenter)
        
        # Set word wrap based on theme settings
        single_line_text = self.theme_settings.get('single_line_text', False)
        self.label.setWordWrap(not single_line_text)  # Set word wrap to opposite of single_line_text
        
        self.label.setMinimumHeight(25)  # Ensure minimum height for text
        
        # Apply font settings
        font = self.label.font()
        
        # Apply font family if specified
        font_family = self.theme_settings.get('font_family')
        if font_family:
            font.setFamily(font_family)
        
        # Apply font size
        try:
            font_size_int = int(self.font_size) if isinstance(self.font_size, (int, str)) else 12
            font.setPointSize(font_size_int)
        except (ValueError, TypeError):
            font.setPointSize(12)
        
        # Apply font weight
        font_weight = self.theme_settings.get('font_weight', 'normal')
        if font_weight == 'bold':
            font.setBold(True)
        elif font_weight == 'light':
            font.setWeight(QFont.Light)
        
        self.label.setFont(font)
        
        # Apply text color if specified - force transparent background
        text_color = self.theme_settings.get('text_color') or self.theme_settings.get('font_color')
        if text_color:
            self.label.setStyleSheet(f"color: {text_color}; background: transparent;")
        
        # Get background style 
        bg_style = self.theme_settings.get('bg_style', 'solid')
        is_gradient = bg_style == 'gradient'
        
        # Check if container should be shown
        show_container = self.theme_settings.get('show_container', True)
        
        # Log container settings
        logger.debug(f"Volume notification: show_container={show_container}, bg_style={bg_style}, single_line_text={single_line_text}")
            
        # Add the label to the layout - either in a container or directly
        if show_container:
            # Create container frame for text only
            container = QFrame()
            
            # Use specified container color, regardless of background style
            container_color = self.theme_settings.get('container_color', '#444444')
            
            # Apply rounded corners with custom border radius if specified
            rounded_corners = self.theme_settings.get('rounded_corners', True)
            if rounded_corners:
                # Use custom border radius if provided, otherwise default to 6px
                border_radius_value = self.theme_settings.get('border_radius', 6)
                border_radius = f"{border_radius_value}px"
            else:
                border_radius = "0px"
            
            # Minimal padding to maximize text space
            container_style = f"""
                background-color: {container_color}; 
                border-radius: {border_radius}; 
                padding: 4px; 
                margin: 0px;
            """
            container.setStyleSheet(container_style)
            
            # Container layout with minimal margins
            container_layout = QVBoxLayout(container)
            container_layout.setContentsMargins(1, 1, 1, 1)
            container_layout.setSpacing(0)  # No spacing inside container
            container_layout.addWidget(self.label, 1, Qt.AlignCenter)  # Use stretch factor and alignment
            
            # Add container with label to main layout
            main_layout.addWidget(container)
        else:
            # No container, add the label directly
            # Ensure the label has transparent background
            current_style = self.label.styleSheet()
            self.label.setStyleSheet(current_style + "; background: transparent;")
            main_layout.addWidget(self.label)
        
        # Create progress bar for volume display - make it slightly shorter for more space
        self.progress = VolumeProgressBar()
        self.progress.setFixedHeight(8)  # Reduce height from 10 to 8
        
        # Set progress bar colors from theme
        progress_color = self.theme_settings.get('progress_color', '#1E88E5')
        
        # Create a slightly darker gradient start color for better visual effect
        if progress_color.startswith('#') and len(progress_color) == 7:
            # Convert hex to RGB, darken it, and convert back to hex
            r = int(progress_color[1:3], 16)
            g = int(progress_color[3:5], 16)
            b = int(progress_color[5:7], 16)
            
            # Create darker version (50% brightness)
            r = max(0, int(r * 0.5))
            g = max(0, int(g * 0.5))
            b = max(0, int(b * 0.5))
            
            progress_start_color = f"#{r:02x}{g:02x}{b:02x}"
        else:
            progress_start_color = "#0A3152"  # Default darker blue
            
        # Enable gradient for progress bar
        self.progress.setGradient(True, progress_start_color, progress_color)
        
        # Set the value from extracted volume
        self.progress.setValue(volume)
        
        # Add progress bar directly to main layout (not in container)
        main_layout.addWidget(self.progress)
        
        # Add the main layout to the notification layout
        layout.addLayout(main_layout)

    def set_theme(self):
        # Get theme settings
        bg_style = self.theme_settings.get('bg_style', 'solid')
        bg_color = self.theme_settings.get('bg_color', '')
        gradient_start = self.theme_settings.get('gradient_color')
        use_gradient = bg_style == 'gradient' and gradient_start
        is_transparent = bg_style == 'transparent'
        
        # Set up rounded corners if specified
        rounded_corners = self.theme_settings.get('rounded_corners', True)
        if rounded_corners:
            # Use custom border radius if provided, otherwise default to 10px
            border_radius_value = self.theme_settings.get('border_radius', 10)
            border_radius = f"{border_radius_value}px"
        else:
            border_radius = "0px"
        
        # Get text color (ensure consistent use of text_color instead of font_color)
        text_color = self.theme_settings.get('text_color') or self.theme_settings.get('font_color', 'white' if self.theme == 'dark' else 'black')
        
        # Base style without background
        base_style = """
            color: %s;
            border-radius: %s;
            padding: %s;
        """ % (
            text_color,
            border_radius,
            "2px" if self.notification_type == 'volume_adjustment' else "10px"
        )
        
        # Create the style string depending on background style
        if is_transparent:
            # Transparent background
            style = "background-color: transparent; " + base_style
            self.background_gradient = False
        elif use_gradient:
            # We'll set the background gradient in the paintEvent
            self.background_gradient = True
            self.gradient_start = bg_color if bg_color else "#333333"
            self.gradient_end = gradient_start
            style = base_style  # No background-color in the style to avoid covering the gradient
        else:
            # Use solid color
            if bg_color:
                background = bg_color
            elif self.theme == 'dark':
                background = "#333"
            else:
                background = "#f0f0f0"
                
            style = "background-color: %s; %s" % (background, base_style)
            self.background_gradient = False
            
        self.setStyleSheet(style)
        self.rounded_corners = rounded_corners  # Store for paintEvent

    def set_position(self):
        screen = QApplication.primaryScreen().geometry()
        
        # Normalize position value (handle different formats like 'bottom-right' or 'bottom_right')
        position = str(self.position).lower().replace('-', '_').replace(' ', '_')
        
        # Get taskbar height for bottom positions (to avoid covering the taskbar)
        taskbar_height = self.get_taskbar_height()
        
        if position == 'bottom_right':
            x = screen.width() - self.width() - 10
            y = screen.height() - self.height() - 10 - taskbar_height
        elif position == 'top_right':
            x = screen.width() - self.width() - 10
            y = 10
        elif position == 'bottom_left':
            x = 10
            y = screen.height() - self.height() - 10 - taskbar_height
        else:  # top_left or any invalid value
            x = 10
            y = 10
        self.move(x, y)
    
    def get_taskbar_height(self):
        """Estimate the taskbar height to avoid covering it"""
        try:
            # For Windows, a typical taskbar is about 40px high
            # This is a simple estimate - for a more accurate approach, 
            # we would need to use platform-specific methods
            if sys.platform == 'win32':
                return 40
            else:
                return 0
        except Exception as e:
            logger.error(f"Error getting taskbar height: {e}")
            return 0

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        # Get border radius from theme settings
        rounded_corners = self.theme_settings.get('rounded_corners', True)
        if rounded_corners:
            border_radius_value = self.theme_settings.get('border_radius', 10)
        else:
            border_radius_value = 0
            
        if hasattr(self, 'background_gradient') and self.background_gradient:
            # Draw gradient background
            gradient = QLinearGradient(0, 0, self.width(), 0)  # Horizontal gradient
            gradient.setColorAt(0, QColor(self.gradient_start))
            gradient.setColorAt(1, QColor(self.gradient_end))
            
            path = QPainterPath()
            path.addRoundedRect(self.rect(), border_radius_value, border_radius_value)
            painter.fillPath(path, gradient)
        else:
            # Use solid color (already set in stylesheet)
            path = QPainterPath()
            path.addRoundedRect(self.rect(), border_radius_value, border_radius_value)
            painter.fillPath(path, self.palette().window())

    def showEvent(self, event):
        # Add tooltip to indicate click-to-dismiss
        self.setToolTip("Click to dismiss notification")
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
        # Default settings with unified structure
        self.settings = {
            "enabled": True,
            "types": {
                "music_track": True,
                "volume_adjustment": True,
                "audio_device": True,
                "speech_to_text": True,
                "button_action": True,
                "midi_connection": True,  # For backward compatibility
                "input_device_changed": True,
                "playback_device_changed": True,
                "input_device_disconnected": True,
                "playback_device_disconnected": True,
                "input_device_selected": True,
                "device_change": True,  # For backward compatibility
                "play_pause_track": True,  # Added for play/pause track notifications
                "ask_chatgpt": True,      # Added for ChatGPT integration
            },
            'theme': 'dark',
            'position': 'bottom-right',
            'size': (300, 100),
            'font_size': 12,
            'duration': 3,
            'theme_settings': {
                'font_family': 'Segoe UI',
                'font_weight': 'normal',
                'text_color': '',  # New format using text_color
                'font_color': '',  # Old format - kept for backward compatibility
                'bg_color': '',    # Default based on theme
                'use_gradient': False,
                'gradient_start': '#333333',
                'gradient_end': '#555555',
                'progress_bg': '',
                'progress_fill': '',
                'single_line_text': False  # Option to show text in a single line (no word wrap)
            }
        }
        # Load settings from file if it exists
        if os.path.exists(self.settings_file):
            try:
                with open(self.settings_file, 'r') as f:
                    loaded_settings = json.load(f)
                    
                    # Migrate old format to new format
                    self._migrate_old_settings(loaded_settings)
                    
                    # Merge settings properly, preserving nested dictionaries
                    if 'types' in loaded_settings:
                        self.settings['types'].update(loaded_settings['types'])
                        del loaded_settings['types']
                    
                    # Merge theme_settings if present
                    if 'theme_settings' in loaded_settings:
                        self.settings['theme_settings'].update(loaded_settings['theme_settings'])
                        del loaded_settings['theme_settings']
                    
                    # Update the non-types settings
                    self.settings.update(loaded_settings)
                    
                # Clean up and save the corrected format
                self._clean_and_save_settings()
            except Exception as e:
                logger.error(f"Failed to load notification settings: {e}")
        self.notifications = []
    
    def _migrate_old_settings(self, loaded_settings):
        """Migrate old-style settings (flat structure) to new structure (types dict)"""
        # List of notification type keys that should be in the 'types' dict
        notification_types = [
            "music_track", "volume_adjustment", "audio_device", "speech_to_text", 
            "button_action", "midi_connection", "input_device_changed", 
            "playback_device_changed", "input_device_disconnected", 
            "playback_device_disconnected", "input_device_selected", "device_change"
        ]
        
        # Move any old format settings to the types dict
        for key in notification_types:
            if key in loaded_settings and key != "types":
                if 'types' not in loaded_settings:
                    loaded_settings['types'] = {}
                loaded_settings['types'][key] = loaded_settings[key]
                del loaded_settings[key]
    
    def _clean_and_save_settings(self):
        """Remove any duplicate entries and save the cleaned settings"""
        # Clean up any root-level notification type settings
        clean_settings = {k: v for k, v in self.settings.items() 
                         if k not in ["music_track", "volume_adjustment", "audio_device", "speech_to_text", 
                                     "button_action", "midi_connection", "input_device_changed", 
                                     "playback_device_changed", "input_device_disconnected", 
                                     "playback_device_disconnected", "input_device_selected", "device_change"]}
        
        # Save cleaned settings
        try:
            with open(self.settings_file, 'w') as f:
                json.dump(clean_settings, f, indent=4)
            logger.debug("Cleaned notification settings saved")
        except Exception as e:
            logger.error(f"Failed to save cleaned notification settings: {e}")

    def show_notification(self, message, notification_type):
        # Check if notifications are enabled globally
        if not self.settings.get("enabled", True):
            logger.debug(f"Not showing notification - notifications disabled globally")
            return
            
        # Handle different notification types
        
        # MIDI-specific notification types
        midi_notification_types = [
            "midi_connection"
        ]
        
        # Audio device-related notification types (excluding MIDI)
        device_notification_types = [
            "input_device_changed", "playback_device_changed", 
            "input_device_disconnected", "playback_device_disconnected", 
            "input_device_selected", "device_change"
        ]
        
        # If this is a MIDI-related notification, check the midi_connection setting
        if notification_type in midi_notification_types:
            type_settings = self.settings.get("types", {})
            if not type_settings.get("midi_connection", True):
                logger.debug(f"Not showing {notification_type} notification - midi_connection notifications disabled")
                return
        
        # If this is a device-related notification, check the audio_device setting
        elif notification_type in device_notification_types:
            type_settings = self.settings.get("types", {})
            if not type_settings.get("audio_device", True):
                logger.debug(f"Not showing {notification_type} notification - audio_device notifications disabled")
                return
            
        # Check if this specific notification type is enabled
        type_settings = self.settings.get("types", {})
        if not type_settings.get(notification_type, True):
            logger.debug(f"Not showing {notification_type} notification - type disabled")
            return
        
        try:
            # Get theme settings
            theme_settings = self.settings.get('theme_settings', {})
            
            # Log theme settings for debugging
            logger.debug(f"Theme settings: show_container={theme_settings.get('show_container', True)}, " +
                        f"container_color={theme_settings.get('container_color', '#444444')}, " +
                        f"bg_style={theme_settings.get('bg_style', 'solid')}")
            
            notification = NotificationWindow(
                message,
                theme=self.settings.get('theme', 'dark'),
                position=self.settings.get('position', 'top_right'),
                size=self.settings.get('size', (300, 100)),
                font_size=self.settings.get('font_size', 12),
                notification_type=notification_type,
                theme_settings=theme_settings
            )
            notification.show()
            self.notifications.append(notification)
            
            # Set timer based on duration setting
            duration_ms = self.settings.get('duration', 3) * 1000
            QTimer.singleShot(duration_ms, lambda: self.close_notification(notification))
            
            logger.debug(f"Showing {notification_type} notification: {message}")
        except Exception as e:
            logger.error(f"Failed to show notification: {e}")
            logger.error(f"Exception details: {traceback.format_exc()}")

    def close_notification(self, notification):
        """Close a specific notification"""
        if notification in self.notifications:
            try:
                notification.close_animation()
                self.notifications.remove(notification)
            except Exception as e:
                logger.error(f"Error closing notification: {e}")

    def update_settings(self, settings):
        """Update notification settings while preserving existing structure"""
        # Log the incoming settings
        if 'theme_settings' in settings:
            logger.debug(f"Updating theme_settings: show_container={settings['theme_settings'].get('show_container', 'not specified')}")
        
        # Define notification types for categorization
        device_notification_types = [
            "input_device_changed", "playback_device_changed", 
            "input_device_disconnected", "playback_device_disconnected", 
            "input_device_selected", "device_change"
        ]
        
        # Ensure the device-related notification types are all controlled by the audio_device setting
        if 'types' in settings and 'audio_device' in settings['types']:
            audio_device_enabled = settings['types']['audio_device']
            
            # Update all device-related notification types to match audio_device
            for device_type in device_notification_types:
                settings['types'][device_type] = audio_device_enabled
        
        # Handle nested dictionaries separately to preserve structure
        # Handle types dictionary
        if 'types' in settings:
            self.settings.setdefault('types', {}).update(settings['types'])
            del settings['types']
            
        # Handle theme_settings dictionary
        if 'theme_settings' in settings:
            # Before updating
            logger.debug(f"Before updating, theme_settings has show_container={self.settings.get('theme_settings', {}).get('show_container', 'not present')}")
            
            # Make a deep copy of the current theme settings to ensure we don't modify the one we're iterating over
            current_theme_settings = dict(self.settings.get('theme_settings', {}))
            current_theme_settings.update(settings['theme_settings'])
            self.settings['theme_settings'] = current_theme_settings
            
            # After updating
            logger.debug(f"After updating, theme_settings has show_container={self.settings.get('theme_settings', {}).get('show_container', 'not present')}")
            
            del settings['theme_settings']
            
        # Update the rest of the settings
        self.settings.update(settings)
        
        # Create a clean copy for saving to avoid duplicate entries
        settings_to_save = {
            "enabled": self.settings.get("enabled", True),
            "types": self.settings.get("types", {}),
            "theme": self.settings.get("theme", "dark"),
            "position": self.settings.get("position", "bottom-right"),
            "size": self.settings.get("size", (300, 100)),
            "font_size": self.settings.get("font_size", 12),
            "duration": self.settings.get("duration", 3),
            "theme_settings": self.settings.get("theme_settings", {})
        }
        
        # Save settings to file
        try:
            with open(self.settings_file, 'w') as f:
                json.dump(settings_to_save, f, indent=4)
            logger.info("Notification settings saved successfully")
        except Exception as e:
            logger.error(f"Failed to save notification settings: {e}")