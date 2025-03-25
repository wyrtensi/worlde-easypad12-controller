import os
import sys
import threading
import time
import customtkinter as ctk
from PIL import Image, ImageTk, ImageDraw
from app.midi_controller import MIDIController
from app.system_actions import SystemActions
from app.utils import setup_logging, get_dark_theme, load_midi_mapping, get_media_controls, load_button_config, get_action_types, save_button_config
import tkinter as tk
import json
import logging

logger = logging.getLogger(__name__)

# Try to import system tray modules
try:
    import pystray
    from pystray import MenuItem as item
    TRAY_AVAILABLE = True
except ImportError:
    TRAY_AVAILABLE = False
    print("pystray not available, system tray functionality disabled")

# Set up logging
logger = setup_logging()

# Set CustomTkinter appearance mode and color theme
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

# Define app colors from theme
theme = get_dark_theme()
DARK_BG = theme["dark_bg"]
PRIMARY_COLOR = theme["primary_color"]
SECONDARY_COLOR = theme["secondary_color"]
BUTTON_ACTIVE_COLOR = theme["button_active_color"]
HIGHLIGHT_COLOR = theme["highlight_color"]
TEXT_COLOR = theme["text_color"]

class MIDIKeyboardApp(ctk.CTk):
    def __init__(self):
        """Initialize the app"""
        # Setup window
        super().__init__()
        self.title("WORLDE EASYPAD.12 Controller")
        self.geometry("1000x340")
        self.minsize(1000, 350)
        self.maxsize(1000, 350)
        
        # Create a cool MIDI controller icon
        self.icon_image = Image.new('RGBA', (64, 64), (0, 0, 0, 0))  # Transparent background
        draw = ImageDraw.Draw(self.icon_image)
        
        # Draw main controller body
        body_color = PRIMARY_COLOR
        border_color = HIGHLIGHT_COLOR
        dark_accent = "#1A1A1A"
        
        # Main body (rectangle with rounded corners)
        draw.rounded_rectangle(
            [(8, 8), (56, 56)],
            radius=5,
            fill=body_color,
            outline=border_color,
            width=2
        )
        
        # Draw slider
        draw.rectangle(
            [(16, 16), (24, 48)],
            fill=dark_accent,
            outline=border_color
        )
        draw.rectangle(
            [(16, 32), (24, 40)],
            fill=HIGHLIGHT_COLOR
        )
        
        # Draw pad matrix (2x3)
        pad_positions = [
            (32, 16), (42, 16), (52, 16),  # Top row
            (32, 36), (42, 36), (52, 36)   # Bottom row
        ]
        
        for x, y in pad_positions:
            # Draw pad background
            draw.rectangle(
                [(x-6, y-6), (x+6, y+6)],
                fill=dark_accent,
                outline=border_color
            )
            # Add highlight to make it look like a button
            draw.line([(x-5, y-5), (x+5, y-5)], fill=HIGHLIGHT_COLOR, width=1)
            draw.line([(x-5, y-5), (x-5, y+5)], fill=HIGHLIGHT_COLOR, width=1)
        
        # Convert for window icon
        self.window_icon = ImageTk.PhotoImage(self.icon_image)
        self.iconphoto(True, self.window_icon)  # Set to True to apply to all windows

        # Initialize tray icon (if available)
        self.tray_icon = None
        if TRAY_AVAILABLE:
            self.setup_tray()
            # Start minimized to tray
            self.after(100, self.hide_to_tray)
        
        # Initialize data
        self.mapping = load_midi_mapping()
        
        # Create simplified mapping for buttons
        # This makes it easier to handle button presses using consistent button IDs
        self.button_mapping = {
            "top_row": self.mapping["layout"]["rows"][0],
            "bottom_row": self.mapping["layout"]["rows"][1],
            "left_column": self.mapping["layout"]["controls"] if "controls" in self.mapping["layout"] else [],
            "slider": self.mapping["layout"]["slider"][0] if self.mapping["layout"]["slider"] else None
        }
        
        # Initialize button config
        self.button_config = {}
        
        # Initialize speech recognition tracking
        self.active_recognition_button = None
        self.active_recognition_stop = None
        self.mic_source = None
        self.is_recognition_active = False
        
        # Initialize controllers
        self.midi_controller = MIDIController(callback=self.on_midi_message)
        self.system_actions = SystemActions()
        
        # Load button configuration
        self.load_config()
        
        # Track active/pressed buttons
        self.active_buttons = set()
        
        # Create the main UI
        self.create_ui()
        
        # Connect to MIDI device if available
        self.after(1000, self.auto_connect_midi)
        
        # Update button labels from saved config
        self.after(1500, self.update_button_labels_from_config)
        
        # Bind close event to minimize to tray if available
        self.protocol("WM_DELETE_WINDOW", self.on_close)
    
    def create_default_icon(self):
        """Create a default icon for the app if none exists"""
        try:
            # Ensure assets directory exists
            assets_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "app", "assets")
            os.makedirs(assets_dir, exist_ok=True)
            
            # Create a simple colored square icon with PIL
            self.icon_image = Image.new('RGBA', (64, 64), color=PRIMARY_COLOR)
            
            # Save a copy to file system for window icon
            self.icon_image.save(self.icon_path, format='PNG')
            
            # Convert to PhotoImage for window icon
            self.window_icon = ImageTk.PhotoImage(self.icon_image)
            
            # Set window icon
            self.iconphoto(True, self.window_icon)
            
        except Exception as e:
            logger.error(f"Failed to create default icon: {e}")
    
    def setup_tray(self):
        """Set up system tray icon and menu"""
        try:
            # Use the same icon image created in __init__
            self.tray_icon = pystray.Icon(
                "midi_controller",
                icon=self.icon_image,  # Use the same PIL Image object
                title="WORLDE EASYPAD.12 Controller"
            )
            
            # Create menu
            self.tray_icon.menu = pystray.Menu(
                item('Show', self.show_window),
                item('Exit', self.exit_app)
            )
            
            # Set double-click action to show window
            self.tray_icon.on_double_click = self.show_window
            
            # Start tray icon in separate thread
            tray_thread = threading.Thread(target=self.tray_icon.run)
            tray_thread.daemon = True
            tray_thread.start()
            
        except Exception as e:
            logger.error(f"Failed to setup system tray: {e}")
            self.tray_icon = None
    
    def show_window(self, icon=None, item=None):
        """Show the main window from tray"""
        self.deiconify()
        self.lift()
        self.focus_force()
    
    def hide_to_tray(self):
        """Hide the window to system tray"""
        if self.tray_icon:
            self.withdraw()
            return True
        return False
    
    def exit_app(self, icon=None, item=None):
        """Exit the application completely"""
        if self.tray_icon:
            self.tray_icon.stop()
        self.quit()
    
    def on_close(self):
        """Handle window close event - minimize to tray if available"""
        if TRAY_AVAILABLE and self.hide_to_tray():
            self.show_message("App minimized to system tray")
        else:
            self.exit_app()
    
    def create_ui(self):
        # Create main frame
        self.main_frame = ctk.CTkFrame(self, fg_color=DARK_BG)
        self.main_frame.pack(fill="both", expand=True, padx=20, pady=20)
        
        # Status bar at the top
        self.status_frame = ctk.CTkFrame(self.main_frame, fg_color=DARK_BG, height=40)
        self.status_frame.pack(fill="x", pady=(0, 10))
        
        self.status_label = ctk.CTkLabel(
            self.status_frame,
            text="MIDI Device: Not Connected",
            text_color=TEXT_COLOR,
            font=("Roboto", 12)
        )
        self.status_label.pack(side="left", padx=(10, 0))
        
        # Right side buttons in the status bar
        self.right_buttons_frame = ctk.CTkFrame(self.status_frame, fg_color=DARK_BG)
        self.right_buttons_frame.pack(side="right", padx=(0, 10))
        
        # Minimize to tray button (if available)
        if TRAY_AVAILABLE:
            self.minimize_button = ctk.CTkButton(
                self.right_buttons_frame,
                text="Hide to Tray",
                command=self.hide_to_tray,
                fg_color=SECONDARY_COLOR,
                hover_color="#008080",
                text_color=TEXT_COLOR,
                width=100
            )
            self.minimize_button.pack(side="left", padx=(0, 10))
        
        self.connect_button = ctk.CTkButton(
            self.right_buttons_frame,
            text="Connect",
            command=self.connect_to_midi,
            fg_color=PRIMARY_COLOR,
            hover_color=BUTTON_ACTIVE_COLOR,
            text_color=TEXT_COLOR,
            width=100
        )
        self.connect_button.pack(side="left", padx=(0, 0))
        
        # Create horizontal separator
        separator = ctk.CTkFrame(self.main_frame, height=2, fg_color=SECONDARY_COLOR)
        separator.pack(fill="x", pady=(0, 20))
        
        # Create the keyboard layout
        self.keyboard_frame = ctk.CTkFrame(self.main_frame, fg_color=DARK_BG)
        self.keyboard_frame.pack(fill="both", expand=True)
        
        # Load the MIDI mapping
        self.button_widgets = {}
        
        # LEFT SECTION - Small buttons (3-8, 1-2)
        self.left_section = ctk.CTkFrame(self.keyboard_frame, fg_color=DARK_BG, width=230)
        self.left_section.pack(side="left", padx=(20, 30), fill="y")
        self.left_section.pack_propagate(False)  # Prevent shrinking
        
        # Create a container to center button rows vertically
        left_center_frame = ctk.CTkFrame(self.left_section, fg_color=DARK_BG)
        left_center_frame.pack(expand=True, fill="both", pady=20)
        
        # Row 1 (Buttons 3, 4, 5)
        button_row_1 = ctk.CTkFrame(left_center_frame, fg_color=DARK_BG)
        button_row_1.pack(fill="x", pady=5)
        button_row_1.columnconfigure(0, weight=1)
        button_row_1.columnconfigure(1, weight=1)
        button_row_1.columnconfigure(2, weight=1)
        
        # Button 3
        button_id = 3
        button3 = ctk.CTkButton(
            button_row_1,
            text=f"{self.mapping['button_names'][str(button_id)]}",
            width=60,
            height=40,
            fg_color="#333333",
            border_width=1,
            border_color="#555555",
            hover_color=PRIMARY_COLOR,
            text_color=TEXT_COLOR,
            font=("Roboto", 10),
            command=lambda bid=button_id: self.show_button_config(bid)
        )
        button3.grid(row=0, column=0, padx=(0, 5), sticky="ew")
        self.button_widgets[button_id] = button3
        
        # Button 4
        button_id = 4
        button4 = ctk.CTkButton(
            button_row_1,
            text=f"{self.mapping['button_names'][str(button_id)]}",
            width=60,
            height=40,
            fg_color="#333333",
            border_width=1,
            border_color="#555555",
            hover_color=PRIMARY_COLOR,
            text_color=TEXT_COLOR,
            font=("Roboto", 10),
            command=lambda bid=button_id: self.show_button_config(bid)
        )
        button4.grid(row=0, column=1, padx=5, sticky="ew")
        self.button_widgets[button_id] = button4
        
        # Button 5
        button_id = 5
        button5 = ctk.CTkButton(
            button_row_1,
            text=f"{self.mapping['button_names'][str(button_id)]}",
            width=60,
            height=40,
            fg_color="#333333",
            border_width=1,
            border_color="#555555",
            hover_color=PRIMARY_COLOR,
            text_color=TEXT_COLOR,
            font=("Roboto", 10),
            command=lambda bid=button_id: self.show_button_config(bid)
        )
        button5.grid(row=0, column=2, padx=(5, 0), sticky="ew")
        self.button_widgets[button_id] = button5
        
        # Row 2 (Buttons 6, 7, 8)
        button_row_2 = ctk.CTkFrame(left_center_frame, fg_color=DARK_BG)
        button_row_2.pack(fill="x", pady=8)
        button_row_2.columnconfigure(0, weight=1)
        button_row_2.columnconfigure(1, weight=1)
        button_row_2.columnconfigure(2, weight=1)
        
        # Button 6
        button_id = 6
        button6 = ctk.CTkButton(
            button_row_2,
            text=f"{self.mapping['button_names'][str(button_id)]}",
            width=60,
            height=40,
            fg_color="#333333",
            border_width=1,
            border_color="#555555",
            hover_color=PRIMARY_COLOR,
            text_color=TEXT_COLOR,
            font=("Roboto", 10),
            command=lambda bid=button_id: self.show_button_config(bid)
        )
        button6.grid(row=0, column=0, padx=(0, 5), sticky="ew")
        self.button_widgets[button_id] = button6
        
        # Button 7
        button_id = 7
        button7 = ctk.CTkButton(
            button_row_2,
            text=f"{self.mapping['button_names'][str(button_id)]}",
            width=60,
            height=40,
            fg_color="#333333",
            border_width=1,
            border_color="#555555",
            hover_color=PRIMARY_COLOR,
            text_color=TEXT_COLOR,
            font=("Roboto", 10),
            command=lambda bid=button_id: self.show_button_config(bid)
        )
        button7.grid(row=0, column=1, padx=5, sticky="ew")
        self.button_widgets[button_id] = button7
        
        # Button 8
        button_id = 8
        button8 = ctk.CTkButton(
            button_row_2,
            text=f"{self.mapping['button_names'][str(button_id)]}",
            width=60,
            height=40,
            fg_color="#333333",
            border_width=1,
            border_color="#555555",
            hover_color=PRIMARY_COLOR,
            text_color=TEXT_COLOR,
            font=("Roboto", 10),
            command=lambda bid=button_id: self.show_button_config(bid)
        )
        button8.grid(row=0, column=2, padx=(5, 0), sticky="ew")
        self.button_widgets[button_id] = button8
        
        # Row 3 (Buttons 1, 2)
        button_row_3 = ctk.CTkFrame(left_center_frame, fg_color=DARK_BG)
        button_row_3.pack(fill="x", pady=8)
        button_row_3.columnconfigure(0, weight=1)
        button_row_3.columnconfigure(1, weight=1)
        
        # Button 1
        button_id = 1
        button1 = ctk.CTkButton(
            button_row_3,
            text=f"{self.mapping['button_names'][str(button_id)]}",
            width=60,
            height=40,
            fg_color="#333333",
            border_width=1,
            border_color="#555555",
            hover_color=PRIMARY_COLOR,
            text_color=TEXT_COLOR,
            font=("Roboto", 10),
            command=lambda bid=button_id: self.show_button_config(bid)
        )
        button1.grid(row=0, column=0, padx=(0, 5), sticky="ew")
        self.button_widgets[button_id] = button1
        
        # Button 2
        button_id = 2
        button2 = ctk.CTkButton(
            button_row_3,
            text=f"{self.mapping['button_names'][str(button_id)]}",
            width=60,
            height=40,
            fg_color="#333333",
            border_width=1,
            border_color="#555555",
            hover_color=PRIMARY_COLOR,
            text_color=TEXT_COLOR,
            font=("Roboto", 10),
            command=lambda bid=button_id: self.show_button_config(bid)
        )
        button2.grid(row=0, column=1, padx=(5, 0), sticky="ew")
        self.button_widgets[button_id] = button2
        
        # SLIDER SECTION
        self.slider_frame = ctk.CTkFrame(self.keyboard_frame, fg_color=DARK_BG, width=60)
        self.slider_frame.pack(side="left", padx=(0, 30), fill="y")
        self.slider_frame.pack_propagate(False)  # Prevent shrinking
        
        # Create a container to center the slider vertically
        slider_center_frame = ctk.CTkFrame(self.slider_frame, fg_color=DARK_BG)
        slider_center_frame.pack(expand=True, fill="both", pady=20)
        
        # Label for slider
        self.slider_label = ctk.CTkLabel(
            slider_center_frame,
            text="SLIDER",
            text_color=TEXT_COLOR,
            font=("Roboto", 12, "bold")
        )
        self.slider_label.pack(side="top", pady=(0, 5))  # Reduced bottom padding
        
        # Load saved slider state
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

        # Create checkbox with loaded state
        self.slider_enabled_var = ctk.BooleanVar(value=initial_state)
        self.slider_enabled_checkbox = ctk.CTkCheckBox(
            slider_center_frame,
            text="Enable",
            variable=self.slider_enabled_var,
            command=self.toggle_slider,
            width=20,
            height=20,
            checkbox_width=16,
            checkbox_height=16,
            fg_color=PRIMARY_COLOR,
            hover_color=BUTTON_ACTIVE_COLOR,
            border_color="#555555",
            text_color=TEXT_COLOR,
            font=("Roboto", 10)
        )
        self.slider_enabled_checkbox.pack(side="top", pady=(0, 15))
        
        # Create slider container with border to look more like a MIDI keyboard slider
        slider_container = ctk.CTkFrame(
            slider_center_frame,
            fg_color="#1A1A1A",
            border_width=2,
            border_color="#555555",
            width=40,
            height=200
        )
        slider_container.pack(side="top", pady=(0, 10))
        slider_container.pack_propagate(False)  # Prevent shrinking
        
        # Create actual slider widget
        slider_id = self.mapping["layout"]["slider"][0]
        self.slider_widget = ctk.CTkSlider(
            slider_container,
            from_=100,
            to=0,
            orientation="vertical",
            height=380,
            width=20,
            progress_color="#FF1493",  # Hot pink color for the track
            button_color="#00CED1",   # Turquoise color for the knob
            button_hover_color="#00FFFF",
            command=self.on_slider_change
        )
        self.slider_widget.pack(side="top", pady=10, padx=10)
        self.slider_widget.set(0)  # Initialize to 0
        self.button_widgets[slider_id] = self.slider_widget  # Add slider to button widgets
        
        # Apply initial state to slider if disabled
        if not initial_state:
            self.slider_widget.configure(
                button_color="#555555",
                progress_color="#444444",
                state="disabled"
            )
        
        # RIGHT SECTION - Main pad layout (6 buttons top row, 6 buttons bottom row)
        self.pads_frame = ctk.CTkFrame(self.keyboard_frame, fg_color=DARK_BG)
        self.pads_frame.pack(side="left", fill="both", expand=True, padx=(0, 20))
        
        # Container to center the pads horizontally
        pads_center_frame = ctk.CTkFrame(self.pads_frame, fg_color=DARK_BG)
        pads_center_frame.pack(fill="both", expand=True, padx=10, pady=10)
        
        # Configure grid layout for better spacing
        pads_center_frame.grid_columnconfigure((0, 1, 2, 3, 4, 5), weight=1, uniform="pads")
        pads_center_frame.grid_rowconfigure(0, weight=1, uniform="rows")
        pads_center_frame.grid_rowconfigure(1, weight=1, uniform="rows")
        
        # Create pads using grid layout instead of pack
        # Top row of pads - Buttons 40-45 (Pads 1-6)
        for i, button_id in enumerate(range(40, 46)):
            pad_frame = ctk.CTkFrame(
                pads_center_frame,
                fg_color="#2A2A2A",
                border_width=2,
                border_color="#555555",
                width=60,
                height=60,
                corner_radius=50
            )
            pad_frame.grid(row=0, column=i, padx=8, pady=10, sticky="nsew")
            pad_frame.grid_propagate(False)  # Prevent shrinking
            
            pad_label = ctk.CTkLabel(
                pad_frame,
                text=f"Pad {i+1}\nButton {button_id}",
                fg_color="transparent",
                text_color=TEXT_COLOR,
                font=("Roboto", 12)
            )
            pad_label.pack(expand=True, fill="both")
            pad_label.bind("<Button-1>", lambda event, bid=button_id: self.show_button_config(bid))
            
            self.button_widgets[button_id] = pad_frame
        
        # Bottom row of pads - Buttons 46-51 (Pads 7-12)
        for i, button_id in enumerate(range(46, 52)):
            pad_frame = ctk.CTkFrame(
                pads_center_frame,
                fg_color="#2A2A2A",
                border_width=2,
                border_color="#555555",
                width=60,
                height=60,
                corner_radius=3
            )
            pad_frame.grid(row=1, column=i, padx=8, pady=10, sticky="nsew")
            pad_frame.grid_propagate(False)  # Prevent shrinking
            
            pad_label = ctk.CTkLabel(
                pad_frame,
                text=f"Pad {i+7}\nButton {button_id}",
                fg_color="transparent",
                text_color=TEXT_COLOR,
                font=("Roboto", 12)
            )
            pad_label.pack(expand=True, fill="both")
            pad_label.bind("<Button-1>", lambda event, bid=button_id: self.show_button_config(bid))
            
            self.button_widgets[button_id] = pad_frame
        
        # Bottom area for status messages
        self.message_frame = ctk.CTkFrame(self.main_frame, fg_color=DARK_BG, height=30)
        self.message_frame.pack(fill="x", pady=(20, 0))
        
        self.message_label = ctk.CTkLabel(
            self.message_frame,
            text="Ready",
            text_color=TEXT_COLOR,
            font=("Roboto", 12)
        )
        self.message_label.pack(side="left", padx=(10, 0))
    
    def update_button_labels_from_config(self):
        """Update button labels based on loaded configuration"""
        if not self.button_config:
            return
        
        # Loop through each configuration and update the label
        for button_id, config in self.button_config.items():
            try:
                button_id = int(button_id)  # Convert string ID to integer
                action_type = config.get("action_type")
                name = config.get("name", f"Button {button_id}")
                
                # Get display name for action type
                if action_type:
                    action_types = get_action_types()
                    display_action = action_types.get(action_type, {}).get("name", action_type)
                    
                    # Update the button label
                    self.update_button_label(button_id, display_action, name)
            except Exception as e:
                logger.error(f"Error updating button {button_id} label: {e}")
    
    def auto_connect_midi(self):
        """Try to automatically connect to the WORLDE EASYPAD.12"""
        logger.info("Attempting to auto-connect to MIDI device")
        success, message = self.midi_controller.find_easypad()
        if success:
            logger.info(f"Auto-connected to MIDI device: {self.midi_controller.port_name}")
            self.status_label.configure(text=f"MIDI Device: {self.midi_controller.port_name}")
            self.connect_button.configure(text="Disconnect", command=self.disconnect_midi)
            self.midi_controller.start_monitoring()
            self.show_message("Connected to MIDI device")
        else:
            logger.warning(f"Failed to auto-connect: {message}")
            self.show_message("MIDI device not found. Connect manually.")
    
    def connect_to_midi(self):
        """Open a dialog to connect to a MIDI device"""
        # Create a dialog to select MIDI device
        dialog = ctk.CTkToplevel(self)
        dialog.title("Connect to MIDI Device")
        dialog.geometry("400x300")
        dialog.transient(self)
        dialog.grab_set()
        
        # Get available ports
        available_ports = self.midi_controller.get_available_ports()
        
        # Create a listbox for selection
        label = ctk.CTkLabel(dialog, text="Select MIDI Device:")
        label.pack(pady=(20, 10))
        
        if available_ports:
            device_var = ctk.StringVar(value=available_ports[0])
            device_option = ctk.CTkOptionMenu(
                dialog, 
                values=available_ports,
                variable=device_var,
                dynamic_resizing=False,
                width=300
            )
            device_option.pack(pady=10)
            
            # Connect button
            connect_btn = ctk.CTkButton(
                dialog,
                text="Connect",
                fg_color=PRIMARY_COLOR,
                hover_color=BUTTON_ACTIVE_COLOR,
                command=lambda: self.finalize_connection(dialog, device_var.get())
            )
            connect_btn.pack(pady=20)
        else:
            no_devices = ctk.CTkLabel(dialog, text="No MIDI devices found")
            no_devices.pack(pady=40)
            
            # Close button
            close_btn = ctk.CTkButton(
                dialog,
                text="Close",
                fg_color=PRIMARY_COLOR,
                hover_color=BUTTON_ACTIVE_COLOR,
                command=dialog.destroy
            )
            close_btn.pack(pady=20)
    
    def finalize_connection(self, dialog, port_name):
        """Connect to the selected MIDI device and close the dialog"""
        success, message = self.midi_controller.connect_to_device(port_name=port_name)
        if success:
            self.status_label.configure(text=f"MIDI Device: {port_name}")
            self.connect_button.configure(text="Disconnect", command=self.disconnect_midi)
            self.midi_controller.start_monitoring()
            self.show_message(f"Connected to {port_name}")
        else:
            self.show_message(f"Connection failed: {message}")
        
        dialog.destroy()
    
    def disconnect_midi(self):
        """Disconnect from the current MIDI device"""
        success, message = self.midi_controller.disconnect()
        if success:
            self.status_label.configure(text="MIDI Device: Not Connected")
            self.connect_button.configure(text="Connect", command=self.connect_to_midi)
            self.show_message("Disconnected from MIDI device")
        else:
            self.show_message(f"Disconnection failed: {message}")
    
    def on_midi_message(self, message, timestamp=None):
        """Handle MIDI message and trigger action based on mapping"""
        try:
            # Log all MIDI data for debugging
            logger.debug(f"MIDI message: {message}; timestamp: {timestamp}")
            
            # Handle raw MIDI message format [status_byte, data1, data2]
            if isinstance(message, list) and len(message) >= 3:
                status_byte = message[0]
                data1 = message[1]  # Note number or control number
                data2 = message[2]  # Velocity or control value
                
                # Check if this is a Note On message (144-159)
                if 144 <= status_byte <= 159 and data2 > 0:
                    note = data1
                    velocity = data2
                    logger.debug(f"Note ON: {note} with velocity {velocity}")
                    
                    # Convert note to button ID based on our mapping
                    button_id = None
                    
                    # Check rows for matches
                    for row_idx, row in enumerate(self.mapping["layout"]["rows"]):
                        if note in row:
                            button_id = note
                            break
                    
                    # Check controls for matches
                    if button_id is None and "controls" in self.mapping["layout"]:
                        controls = self.mapping["layout"]["controls"]
                        if note in controls:
                            button_id = note
                    
                    # If we found a mapping, handle it
                    if button_id is not None:
                        config = self.button_config.get(str(button_id))
                        if config and config.get('action_type') == 'speech_to_text' and config.get('enabled', True):
                            language = config['action_data'].get('language', 'en-US')
                            self.start_speech_recognition(button_id, language)
                        else:
                            # Execute button action for other types
                            self.execute_button_action(button_id)
                        
                        # Change button color briefly for feedback
                        if button_id in self.button_widgets:
                            button = self.button_widgets[button_id]
                            self.flash_button(button)
                
                # Check if this is a Note Off message (128-143) or Note On with velocity 0
                elif (128 <= status_byte <= 143) or (144 <= status_byte <= 159 and data2 == 0):
                    note = data1
                    button_id = note
                    if str(button_id) in self.button_config and self.button_config[str(button_id)].get('action_type') == 'speech_to_text':
                        self.stop_speech_recognition(button_id)
                
                # Check if this is a Control Change message (176-191)
                elif 176 <= status_byte <= 191:
                    control = data1
                    value = data2
                    logger.debug(f"Control change: {control} with value {value}")
                    
                    # Map control numbers to specific buttons
                    control_to_button = {
                        44: 8,  # Button 8
                        45: 4,  # Button 4
                        46: 7,  # Button 7
                        47: 3,  # Button 3
                        48: 5,  # Button 5
                        49: 6   # Button 6
                    }
                    
                    # Handle buttons 3-8 (control numbers 44-49)
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
                                # Execute button action for other types
                                self.execute_button_action(button_id)
                                # Change button color briefly for feedback
                                if button_id in self.button_widgets:
                                    button = self.button_widgets[button_id]
                                    self.flash_button(button)
                    
                    # Check if it's the slider (control 9)
                    elif control == 9:
                        # First check if slider is enabled
                        if not self.slider_enabled_var.get():
                            logger.debug("Slider is disabled, ignoring MIDI message")
                            return
                            
                        # This is the physical slider on the MIDI controller
                        normalized_value = int((value / 127) * 100)
                        
                        # Update slider UI if enabled
                        if hasattr(self, 'slider_widget'):
                            self.slider_widget.set(normalized_value)
                        
                        # Execute slider action
                        slider_id = "sliderA"
                        if str(slider_id) in self.button_config:
                            self.execute_button_action(slider_id, normalized_value)
                        else:
                            # Default volume control if no specific config
                            success = self.system_actions.set_volume("set", normalized_value)
                            if success:
                                self.show_message(f"Volume set to {normalized_value}%")
                            else:
                                self.show_message("Failed to set volume")
                    
                    # Check for other mapped controls in the slider list
                    elif "slider" in self.mapping["layout"] and self.mapping["layout"]["slider"]:
                        slider_controls = self.mapping["layout"]["slider"]
                        for slider_id in slider_controls:
                            if str(control) == str(slider_id):
                                # Normalize to 0-100
                                normalized_value = int((value / 127) * 100)
                                
                                # Update slider UI
                                if hasattr(self, 'slider_widget'):
                                    self.slider_widget.set(normalized_value)
                                
                                # Execute slider action
                                if str(slider_id) in self.button_config:
                                    self.execute_button_action(slider_id, normalized_value)
            
            # Handle mido message format
            elif hasattr(message, 'type'):
                if message.type == 'note_on' and message.velocity > 0:
                    note = message.note
                    velocity = message.velocity
                    logger.debug(f"Note ON: {note} with velocity {velocity}")
                    
                    button_id = None
                    
                    for row_idx, row in enumerate(self.mapping["layout"]["rows"]):
                        if note in row:
                            button_id = note
                            break
                    
                    if button_id is None and "controls" in self.mapping["layout"]:
                        controls = self.mapping["layout"]["controls"]
                        if note in controls:
                            button_id = note
                    
                    if button_id is not None:
                        config = self.button_config.get(str(button_id))
                        if config and config.get('action_type') == 'speech_to_text' and config.get('enabled', True):
                            language = config['action_data'].get('language', 'en-US')
                            self.start_speech_recognition(button_id, language)
                        else:
                            self.execute_button_action(button_id)
                        
                        if button_id in self.button_widgets:
                            button = self.button_widgets[button_id]
                            self.flash_button(button)
                
                elif message.type == 'note_off' or (message.type == 'note_on' and message.velocity == 0):
                    note = message.note
                    button_id = note
                    if str(button_id) in self.button_config and self.button_config[str(button_id)].get('action_type') == 'speech_to_text':
                        self.stop_speech_recognition(button_id)
                
                elif message.type == 'control_change':
                    control = message.control
                    value = message.value
                    logger.debug(f"Control change: {control} with value {value}")
                    
                    control_to_button = {
                        44: 8, 45: 4, 46: 7, 47: 3, 48: 5, 49: 6
                    }
                    
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
                                self.execute_button_action(button_id)
                                if button_id in self.button_widgets:
                                    button = self.button_widgets[button_id]
                                    self.flash_button(button)
                    
                    elif control == 9:
                        if not self.slider_enabled_var.get():
                            logger.debug("Slider is disabled, ignoring MIDI message")
                            return
                            
                        normalized_value = int((value / 127) * 100)
                        
                        if hasattr(self, 'slider_widget'):
                            self.slider_widget.set(normalized_value)
                        
                        slider_id = "sliderA"
                        if str(slider_id) in self.button_config:
                            self.execute_button_action(slider_id, normalized_value)
                        else:
                            success = self.system_actions.set_volume("set", normalized_value)
                            if success:
                                self.show_message(f"Volume set to {normalized_value}%")
                            else:
                                self.show_message("Failed to set volume")
        
        except Exception as e:
            logger.error(f"Error handling MIDI message: {e}")
            self.show_message(f"MIDI error: {e}")
    
    def handle_button_press(self, note):
        """Handle button press events"""
        # Map MIDI note to button ID
        button_id = note
        logger.info(f"Button press detected: {button_id}")
        
        # Highlight the button in the UI
        self.highlight_button(button_id, True)
        
        # Execute the assigned action for this button
        self.execute_button_action(button_id)
    
    def handle_button_release(self, note):
        """Handle button release events"""
        # Map MIDI note to button ID
        button_id = note
        
        # Remove highlight from the button
        self.highlight_button(button_id, False)
    
    def handle_slider_change(self, value):
        """Handle slider value changes"""
        # Update slider position in the UI
        self.slider_widget.set(value)
        
        # Execute slider action (e.g., volume control)
        success, message = self.system_actions.set_volume(int(value))
        if success:
            self.show_message(message)
        else:
            self.show_message(f"Error: {message}")
    
    def on_slider_change(self, value):
        """Handle slider UI changes from user interaction"""
        if self.midi_controller.is_connected:
            # Only apply changes if initiated by user (not by MIDI)
            success, message = self.system_actions.set_volume(int(value))
            if success:
                self.show_message(message)
            else:
                self.show_message(f"Error: {message}")
    
    def highlight_button(self, button_id, is_active):
        """Highlight or unhighlight a button in the UI"""
        button_id = int(button_id)  # Ensure button_id is an integer
        
        # Find the button widget
        widget = self.button_widgets.get(button_id)
        if not widget:
            logger.warning(f"Button ID {button_id} not found in button widgets")
            return
            
        # Update button appearance based on type
        if isinstance(widget, ctk.CTkFrame):  # Pad buttons (40-51)
            if is_active:
                widget.configure(fg_color=PRIMARY_COLOR)
                self.active_buttons.add(button_id)
            else:
                widget.configure(fg_color="#2A2A2A")
                if button_id in self.active_buttons:
                    self.active_buttons.remove(button_id)
        elif isinstance(widget, ctk.CTkButton):  # Control buttons (1-8)
            if is_active:
                widget.configure(fg_color=PRIMARY_COLOR)
                self.active_buttons.add(button_id)
            else:
                widget.configure(fg_color="#333333")
                if button_id in self.active_buttons:
                    self.active_buttons.remove(button_id)
        else:
            logger.warning(f"Unknown widget type for button ID {button_id}")
    
    def flash_button(self, button):
        """Flash a button to indicate it was pressed"""
        try:
            # Handle different types of button widgets
            if isinstance(button, ctk.CTkFrame):  # Pad buttons (40-51)
                original_color = button.cget("fg_color")
                button.configure(fg_color=PRIMARY_COLOR)
                # Restore original color after 100ms
                self.after(100, lambda: button.configure(fg_color=original_color))
            elif isinstance(button, ctk.CTkButton):  # Control buttons (1-8)
                original_color = button.cget("fg_color")
                button.configure(fg_color=PRIMARY_COLOR)
                # Restore original color after 100ms
                self.after(100, lambda: button.configure(fg_color=original_color))
            elif isinstance(button, ctk.CTkSlider):  # Slider
                pass  # No flash effect for slider
            else:
                logger.warning(f"Unknown widget type for flashing: {type(button)}")
        except Exception as e:
            logger.error(f"Error flashing button: {e}")
    
    def show_button_config(self, button_id):
        """Show configuration dialog for a button"""
        # Create a dialog for button configuration
        dialog = ctk.CTkToplevel(self)
        dialog.title(f"Configure {self.mapping['button_names'].get(str(button_id), f'Button {button_id}')}")
        dialog.geometry("500x450")
        dialog.transient(self)
        dialog.grab_set()
        
        # Load button configuration
        self.current_button_id = button_id
        self.current_config = load_button_config(button_id)
        
        # Main frame
        main_frame = ctk.CTkFrame(dialog, fg_color=DARK_BG)
        main_frame.pack(fill="both", expand=True, padx=20, pady=20)
        
        # Button name
        name_frame = ctk.CTkFrame(main_frame, fg_color=DARK_BG)
        name_frame.pack(fill="x", pady=(0, 15))
        
        ctk.CTkLabel(name_frame, text="Button Name:").pack(side="left", padx=(0, 10))
        
        button_name_var = ctk.StringVar(value=self.current_config.get("name", f"Button {button_id}"))
        button_name_entry = ctk.CTkEntry(name_frame, textvariable=button_name_var, width=300)
        button_name_entry.pack(side="right", fill="x", expand=True)
        
        # Action type selection
        action_type_frame = ctk.CTkFrame(main_frame, fg_color=DARK_BG)
        action_type_frame.pack(fill="x", pady=(0, 15))
        
        ctk.CTkLabel(action_type_frame, text="Action Type:").pack(side="left", padx=(0, 10))
        
        # Get action types - these should be display names
        action_types = get_action_types()
        action_type_choices = [(key, info["name"]) for key, info in action_types.items()]
        
        # Map between internal identifiers and display names
        internal_to_display = {key: name for key, name in action_type_choices}
        display_to_internal = {name: key for key, name in action_type_choices}
        
        # Set up variable to store display name
        self.action_type_var = ctk.StringVar()
        
        # Create dropdown with display names
        action_display_names = [name for _, name in action_type_choices]
        
        # Callback when action type changes
        def on_action_type_change(display_name):
            # Convert display name to internal type
            internal_type = display_to_internal.get(display_name)
            logger.debug(f"Action type changed to {display_name} (internal: {internal_type})")
            self.update_action_form(internal_type)
        
        action_dropdown = ctk.CTkOptionMenu(
            master=action_type_frame,
            values=action_display_names,
            variable=self.action_type_var,
            dynamic_resizing=False,
            width=300,

            # Main button styling
            fg_color=SECONDARY_COLOR,
            button_color=SECONDARY_COLOR,
            text_color=TEXT_COLOR,
            button_hover_color="#008080",
          
            # Dropdown container styling (available options)
            dropdown_fg_color=SECONDARY_COLOR,
            dropdown_hover_color="#008080",
            dropdown_text_color=TEXT_COLOR,

            command=on_action_type_change
        )
        action_dropdown.pack(side="right", fill="x", expand=True)

        # Set initial value if exists - convert internal action type to display name
        if self.current_config.get("action_type"):
            internal_action_type = self.current_config["action_type"]
            display_name = internal_to_display.get(internal_action_type)
            
            if display_name:
                action_dropdown.set(display_name)
                logger.debug(f"Set dropdown to {display_name} for internal type {internal_action_type}")
        
        # Create frame for action-specific form
        self.action_form_frame = ctk.CTkFrame(main_frame, fg_color=DARK_BG)
        self.action_form_frame.pack(fill="x", pady=(0, 15))
        
        # Initial action form update
        if self.current_config.get("action_type"):
            self.update_action_form(self.current_config["action_type"])
        
        # Enabled toggle
        enabled_frame = ctk.CTkFrame(main_frame, fg_color=DARK_BG)
        enabled_frame.pack(fill="x", pady=(0, 15))
        
        self.enabled_var = ctk.BooleanVar(value=self.current_config.get("enabled", True))
        enabled_checkbox = ctk.CTkCheckBox(
            enabled_frame,
            text="Enabled",
            variable=self.enabled_var,
            checkbox_width=20,
            checkbox_height=20
        )
        enabled_checkbox.pack(side="left")
        
        # Save and Cancel buttons
        button_frame = ctk.CTkFrame(main_frame, fg_color=DARK_BG)
        button_frame.pack(fill="x", pady=(20, 0))
        
        save_button = ctk.CTkButton(
            button_frame,
            text="Save",
            fg_color=PRIMARY_COLOR,
            hover_color=BUTTON_ACTIVE_COLOR,
            command=lambda: self.save_button_config(dialog, button_id)
        )
        save_button.pack(side="right", padx=5)
        
        cancel_button = ctk.CTkButton(
            button_frame,
            text="Cancel",
            fg_color="#555555",
            hover_color="#777777",
            command=dialog.destroy
        )
        cancel_button.pack(side="right", padx=5)
    
    def update_action_form(self, action_type=None):
        """Update the action form based on selected action type"""
        # Clear existing form
        for widget in self.action_form_frame.winfo_children():
            widget.destroy()
        
        self.form_values = {}
        
        # Determine which action type to use
        if not action_type:
            action_type = self.get_action_type_from_display_name(self.action_type_var.get())
        
        # Get existing data from config if editing an existing button
        existing_data = {}
        if hasattr(self, 'current_button_id') and self.current_button_id:
            button_config = self.button_config.get(str(self.current_button_id), {})
            if button_config and button_config.get('action_type') == action_type:
                existing_data = button_config.get('action_data', {})
        
        # Different form fields based on action type
        if action_type == "app":
            # Application path
            path_frame = ctk.CTkFrame(self.action_form_frame)
            path_frame.pack(fill="x", padx=10, pady=5)
            
            path_label = ctk.CTkLabel(path_frame, text="Application Path:")
            path_label.pack(side="left", padx=5)
            
            path_var = tk.StringVar(value=existing_data.get("path", ""))
            path_entry = ctk.CTkEntry(path_frame, width=200, textvariable=path_var)
            path_entry.pack(side="left", padx=5, fill="x", expand=True)
            
            browse_button = ctk.CTkButton(
                path_frame, 
                text="Browse", 
                width=70,
                command=lambda: self.browse_file(path_var)
            )
            browse_button.pack(side="right", padx=5)
            
            self.form_values["path"] = path_var
            
            # Optional arguments
            args_frame = ctk.CTkFrame(self.action_form_frame)
            args_frame.pack(fill="x", padx=10, pady=5)
            
            args_label = ctk.CTkLabel(args_frame, text="Arguments (optional):")
            args_label.pack(side="left", padx=5)
            
            args_var = tk.StringVar(value=existing_data.get("args", ""))
            args_entry = ctk.CTkEntry(args_frame, width=200, textvariable=args_var)
            args_entry.pack(side="left", padx=5, fill="x", expand=True)
            
            self.form_values["args"] = args_var
            
            # Required field indicator with help text
            required_label = ctk.CTkLabel(
                self.action_form_frame, 
                text="* Application Path is required",
                text_color="orange"
            )
            required_label.pack(fill="x", padx=10, pady=5)
            
        elif action_type == "toggle_app":
            # Application path
            path_frame = ctk.CTkFrame(self.action_form_frame)
            path_frame.pack(fill="x", padx=10, pady=5)
            
            path_label = ctk.CTkLabel(path_frame, text="Application Path:")
            path_label.pack(side="left", padx=5)
            
            path_var = tk.StringVar(value=existing_data.get("path", ""))
            path_entry = ctk.CTkEntry(path_frame, width=200, textvariable=path_var)
            path_entry.pack(side="left", padx=5, fill="x", expand=True)
            
            browse_button = ctk.CTkButton(
                path_frame, 
                text="Browse", 
                width=70,
                command=lambda: self.browse_file(path_var)
            )
            browse_button.pack(side="right", padx=5)
            
            self.form_values["path"] = path_var
            
            # Optional arguments
            args_frame = ctk.CTkFrame(self.action_form_frame)
            args_frame.pack(fill="x", padx=10, pady=5)
            
            args_label = ctk.CTkLabel(args_frame, text="Arguments (optional):")
            args_label.pack(side="left", padx=5)
            
            args_var = tk.StringVar(value=existing_data.get("args", ""))
            args_entry = ctk.CTkEntry(args_frame, width=200, textvariable=args_var)
            args_entry.pack(side="left", padx=5, fill="x", expand=True)
            
            self.form_values["args"] = args_var
            
            # Required field indicator
            required_label = ctk.CTkLabel(
                self.action_form_frame, 
                text="* Application Path is required",
                text_color="orange"
            )
            required_label.pack(fill="x", padx=10, pady=5)
            
        elif action_type == "web":
            # Website URL
            url_frame = ctk.CTkFrame(self.action_form_frame)
            url_frame.pack(fill="x", padx=10, pady=5)
            
            url_label = ctk.CTkLabel(url_frame, text="Website URL:")
            url_label.pack(side="left", padx=5)
            
            url_var = tk.StringVar(value=existing_data.get("url", ""))
            url_entry = ctk.CTkEntry(url_frame, width=200, textvariable=url_var)
            url_entry.pack(side="left", padx=5, fill="x", expand=True)
            
            self.form_values["url"] = url_var
            
            # Required field indicator
            required_label = ctk.CTkLabel(
                self.action_form_frame, 
                text="* URL is required (e.g., https://www.example.com)",
                text_color="orange"
            )
            required_label.pack(fill="x", padx=10, pady=5)
            
        elif action_type == "volume":
            # Action type (increase, decrease, mute, unmute, set)
            action_frame = ctk.CTkFrame(self.action_form_frame)
            action_frame.pack(fill="x", padx=10, pady=5)
            
            action_label = ctk.CTkLabel(action_frame, text="Action:")
            action_label.pack(side="left", padx=5)
            
            action_var = tk.StringVar()
            # Set default from existing or fall back to "increase"
            action_var.set(existing_data.get("action", "increase"))
            
            actions = ["increase", "decrease", "mute", "unmute", "set"]
            action_menu = ctk.CTkOptionMenu(
                action_frame,
                values=actions,
                variable=action_var,
                width=120
            )
            action_menu.pack(side="left", padx=5)
            
            self.form_values["action"] = action_var

            # Help text for slider
            help_label = ctk.CTkLabel(
                self.action_form_frame, 
                text="Note: For slider control, the action will automatically be 'set'",
                text_color="gray"
            )
            help_label.pack(fill="x", padx=10, pady=5)
            
        elif action_type == "media":
            # Media action
            media_frame = ctk.CTkFrame(self.action_form_frame)
            media_frame.pack(fill="x", padx=10, pady=5)
            
            media_label = ctk.CTkLabel(media_frame, text="Control:")
            media_label.pack(side="left", padx=5)
            
            media_var = tk.StringVar()
            
            # Get media controls from utils
            media_controls = get_media_controls()
            
            # Create a display-friendly mapping
            media_display = {}
            for key, control in media_controls.items():
                media_display[key] = control["name"]
            
            # Create reverse mapping for retrieving internal value
            media_internal = {v: k for k, v in media_display.items()}
            
            # Store the mapping for retrieval
            self.media_value_map = media_internal
            
            # Create dropdown with descriptive names
            media_display_values = list(media_display.values())
            
            # Get existing control value if available
            existing_control = existing_data.get("control", "play_pause")
            
            # Handle both internal value and display value formats
            if existing_control in media_display:
                # It's an internal value, get the display value
                media_var.set(media_display[existing_control])
            elif existing_control in media_internal:
                # It's already a display value
                media_var.set(existing_control)
            else:
                # Default
                media_var.set("Play/Pause")
            
            media_menu = ctk.CTkOptionMenu(
                media_frame,
                values=media_display_values,
                variable=media_var,
                width=120
            )
            media_menu.pack(side="left", padx=5)
            
            # Update the description when selection changes
            def update_media_description(*args):
                selected_display = media_var.get()
                selected_action = self.media_value_map.get(selected_display, "play_pause")
                desc = f"Controls media playback with: {selected_action}"
                description_label.configure(text=desc)
                
            media_var.trace_add("write", update_media_description)
            
            # Description label
            description_label = ctk.CTkLabel(
                self.action_form_frame,
                text=f"Controls media playback with: {media_internal.get(media_var.get(), 'play_pause')}",
                text_color="gray"
            )
            description_label.pack(fill="x", padx=10, pady=5)
            
            self.form_values["media_display"] = media_var
        
        elif action_type == "shortcut":
            # Keyboard shortcut
            shortcut_frame = ctk.CTkFrame(self.action_form_frame)
            shortcut_frame.pack(fill="x", padx=10, pady=5)
            
            shortcut_label = ctk.CTkLabel(shortcut_frame, text="Shortcut:")
            shortcut_label.pack(side="left", padx=5)
            
            shortcut_var = tk.StringVar(value=existing_data.get("shortcut", ""))
            shortcut_entry = ctk.CTkEntry(shortcut_frame, width=200, textvariable=shortcut_var)
            shortcut_entry.pack(side="left", padx=5, fill="x", expand=True)
            
            self.form_values["shortcut"] = shortcut_var
            
            # Help text
            help_frame = ctk.CTkFrame(self.action_form_frame)
            help_frame.pack(fill="x", padx=10, pady=5)
            
            help_title = ctk.CTkLabel(
                help_frame, 
                text="Shortcut format examples:",
                text_color="gray"
            )
            help_title.pack(anchor="w", padx=5, pady=2)
            
            help_keys = ctk.CTkLabel(
                help_frame,
                text="• ctrl+c, alt+tab, win+r, ctrl+shift+esc",
                text_color="gray"
            )
            help_keys.pack(anchor="w", padx=20, pady=1)
            
            help_function = ctk.CTkLabel(
                help_frame,
                text="• f1, f5, shift+f10",
                text_color="gray"
            )
            help_function.pack(anchor="w", padx=20, pady=1)
            
            help_media = ctk.CTkLabel(
                help_frame,
                text="• System-wide shortcuts may not work in all applications",
                text_color="orange"
            )
            help_media.pack(anchor="w", padx=5, pady=5)
            
        elif action_type == "audio_device":
            # Audio device
            device_frame = ctk.CTkFrame(self.action_form_frame)
            device_frame.pack(fill="x", padx=10, pady=5)
            
            device_label = ctk.CTkLabel(device_frame, text="Device Name:")
            device_label.pack(side="left", padx=5)
            
            device_var = tk.StringVar(value=existing_data.get("device_name", ""))
            device_entry = ctk.CTkEntry(device_frame, width=200, textvariable=device_var)
            device_entry.pack(side="left", padx=5, fill="x", expand=True)
            
            self.form_values["device_name"] = device_var
            
            # Help text
            help_frame = ctk.CTkFrame(self.action_form_frame)
            help_frame.pack(fill="x", padx=10, pady=5)
            
            help_title = ctk.CTkLabel(
                help_frame, 
                text="How to use:",
                text_color="gray"
            )
            help_title.pack(anchor="w", padx=5, pady=2)
            
            help_empty = ctk.CTkLabel(
                help_frame,
                text="• Leave empty to toggle between all audio devices",
                text_color="gray"
            )
            help_empty.pack(anchor="w", padx=20, pady=1)
            
            help_specific = ctk.CTkLabel(
                help_frame,
                text="• Enter partial device name to switch to a specific device",
                text_color="gray"
            )
            help_specific.pack(anchor="w", padx=20, pady=1)
            
            help_note = ctk.CTkLabel(
                help_frame,
                text="Note: Requires AudioDeviceCmdlets PowerShell module",
                text_color="orange"
            )
            help_note.pack(anchor="w", padx=5, pady=5)
        
        elif action_type == "command":
            # System commands with delays
            commands_frame = ctk.CTkFrame(self.action_form_frame)
            commands_frame.pack(fill="x", padx=10, pady=5)
    
            # Pad the commands list to exactly 3 elements
            commands_list = (existing_data.get("commands", []) + [{}]*3)[:3]
    
            for i in range(3):
                command_delay_frame = ctk.CTkFrame(commands_frame)
                command_delay_frame.pack(fill="x", pady=2)
        
                # Command label and entry
                command_label = ctk.CTkLabel(command_delay_frame, text=f"Command {i+1}:")
                command_label.pack(side="left", padx=5)
        
                command_var = tk.StringVar(value=commands_list[i].get("command", ""))
                command_entry = ctk.CTkEntry(command_delay_frame, width=200, textvariable=command_var)
                command_entry.pack(side="left", padx=5, fill="x", expand=True)
        
                # Delay label and entry
                delay_label = ctk.CTkLabel(command_delay_frame, text="Delay (ms):")
                delay_label.pack(side="left", padx=5)
        
                delay_var = tk.StringVar(value=str(commands_list[i].get("delay_ms", 0)))
                delay_entry = ctk.CTkEntry(command_delay_frame, width=50, textvariable=delay_var)
                delay_entry.pack(side="left", padx=5)
        
                # Store in form_values
                self.form_values[f"command_{i}"] = command_var
                self.form_values[f"delay_{i}"] = delay_var

            # Help text
            help_label = ctk.CTkLabel(
                self.action_form_frame, 
                text="Enter up to 3 system commands with delays (e.g., notepad.exe, ping google.com)",
                text_color="gray"
            )
            help_label.pack(fill="x", padx=10, pady=5)
            
            warning_label = ctk.CTkLabel(
                self.action_form_frame, 
                text="Warning: Be careful with system commands, they run with your privileges",
                text_color="orange"
            )
            warning_label.pack(fill="x", padx=10, pady=5)
        
        elif action_type == "text":
            # Text input
            text_frame = ctk.CTkFrame(self.action_form_frame)
            text_frame.pack(fill="x", padx=10, pady=5)
            
            text_label = ctk.CTkLabel(text_frame, text="Text to Type:")
            text_label.pack(side="left", padx=5)
            
            text_var = tk.StringVar(value=existing_data.get("text", ""))
            text_entry = ctk.CTkEntry(text_frame, width=200, textvariable=text_var)
            text_entry.pack(side="left", padx=5, fill="x", expand=True)
            
            self.form_values["text"] = text_var
            
            # Help text
            help_label = ctk.CTkLabel(
                self.action_form_frame, 
                text="The text will be typed automatically when the button is pressed",
                text_color="gray"
            )
            help_label.pack(fill="x", padx=10, pady=5)
        
        elif action_type == "powershell":
            # PowerShell commands with delays
            commands_frame = ctk.CTkFrame(self.action_form_frame)
            commands_frame.pack(fill="x", padx=10, pady=5)
    
            # Pad the commands list to exactly 3 elements
            commands_list = (existing_data.get("commands", []) + [{}]*3)[:3]
    
            for i in range(3):
                command_delay_frame = ctk.CTkFrame(commands_frame)
                command_delay_frame.pack(fill="x", pady=2)
        
                # Command label and entry
                command_label = ctk.CTkLabel(command_delay_frame, text=f"PS Command {i+1}:")
                command_label.pack(side="left", padx=5)
        
                command_var = tk.StringVar(value=commands_list[i].get("command", ""))
                command_entry = ctk.CTkEntry(command_delay_frame, width=200, textvariable=command_var)
                command_entry.pack(side="left", padx=5, fill="x", expand=True)
        
                # Delay label and entry
                delay_label = ctk.CTkLabel(command_delay_frame, text="Delay (ms):")
                delay_label.pack(side="left", padx=5)
        
                delay_var = tk.StringVar(value=str(commands_list[i].get("delay_ms", 0)))
                delay_entry = ctk.CTkEntry(command_delay_frame, width=50, textvariable=delay_var)
                delay_entry.pack(side="left", padx=5)
        
                # Store in form_values
                self.form_values[f"ps_command_{i}"] = command_var
                self.form_values[f"ps_delay_{i}"] = delay_var

            # Help text
            help_label = ctk.CTkLabel(
                self.action_form_frame, 
                text="Enter up to 3 PowerShell commands with delays (e.g., Get-Process, Get-Service)",
                text_color="gray"
            )
            help_label.pack(fill="x", padx=10, pady=5)
            
            warning_label = ctk.CTkLabel(
                self.action_form_frame, 
                text="Warning: Be careful with PowerShell commands, they run with your privileges",
                text_color="orange"
            )
            warning_label.pack(fill="x", padx=10, pady=5)
        
        elif action_type == "speech_to_text":
            # Language selection frame
            language_frame = ctk.CTkFrame(self.action_form_frame)
            language_frame.pack(fill="x", padx=10, pady=5)
            
            language_label = ctk.CTkLabel(language_frame, text="Language:")
            language_label.pack(side="left", padx=5)
            
            # Define language options
            languages = [
                ("English", "en-US"),
                ("Russian", "ru-RU"),
                ("Combined (Experimental)", "ru-RU,en-US")
            ]
            self.language_map = {lang[0]: lang[1] for lang in languages}
            self.language_display_map = {v: k for k, v in self.language_map.items()}
            
            # Get existing language or default to English
            language_code = existing_data.get("language", "en-US")
            language_display = self.language_display_map.get(language_code, "English")
            language_var = tk.StringVar(value=language_display)
            
            # Create dropdown menu
            language_menu = ctk.CTkOptionMenu(
                language_frame,
                values=[lang[0] for lang in languages],
                variable=language_var,
                width=120
            )
            language_menu.pack(side="left", padx=5)
            
            self.form_values["language_display"] = language_var
            
            # Help text
            help_label = ctk.CTkLabel(
                self.action_form_frame,
                text="Hold the button to type speech in the selected language. Combined mode is experimental.",
                text_color="gray"
            )
            help_label.pack(fill="x", padx=10, pady=5)
            
        else:
            # Unknown or unimplemented action type
            unknown_label = ctk.CTkLabel(
                self.action_form_frame, 
                text=f"Form for action type '{action_type}' not implemented yet",
                text_color="orange"
            )
            unknown_label.pack(fill="x", padx=10, pady=20)
            
            help_label = ctk.CTkLabel(
                self.action_form_frame,
                text="This feature will be available in a future update",
                text_color="gray"
            )
            help_label.pack(fill="x", padx=10, pady=5)
    
    def browse_file(self, string_var):
        """Open file browser dialog to select an application"""
        from tkinter import filedialog
        
        file_path = filedialog.askopenfilename(
            title="Select Application",
            filetypes=[("Executable files", "*.exe"), ("All files", "*.*"), ("Shortcut files", "*.lnk*")]
        )
        
        if file_path:
            string_var.set(file_path)
    
    def save_button_config(self, dialog, button_id):
        """Save button configuration"""
        display_action_type = self.action_type_var.get()
        action_data = {}
        
        # Map display name to internal action type
        action_types = get_action_types()
        action_type = None
        for key, info in action_types.items():
            if info["name"] == display_action_type:
                action_type = key
                break
                
        if not action_type:
            logger.error(f"Could not find internal action type for display name: {display_action_type}")
            self.show_message("Error: Unknown action type")
            return
            
        logger.debug(f"Saving config for action type: {action_type} ({display_action_type})")
        
        # Get button name using the StringVar instead of widget hierarchy
        button_name = ""
        for widget in dialog.winfo_children()[0].winfo_children():
            if isinstance(widget, ctk.CTkFrame) and len(widget.winfo_children()) >= 2:
                entry_widget = widget.winfo_children()[1]
                if isinstance(entry_widget, ctk.CTkEntry):
                    button_name = entry_widget.get()
                    break
        
        if not button_name:
            button_name = f"Button {button_id}"
        
        # Get action data based on action type
        if action_type == "app":
            if not self.form_values.get("path") or not self.form_values["path"].get():
                self.show_message("Error: Application path is required")
                return
                
            action_data = {
                "path": self.form_values["path"].get(),
                "args": self.form_values["args"].get()
            }
        elif action_type == "toggle_app":
            if not self.form_values.get("path") or not self.form_values["path"].get():
                self.show_message("Error: Application path is required")
                return
                
            action_data = {
                "path": self.form_values["path"].get(),
                "args": self.form_values["args"].get()
            }
        elif action_type == "web":
            if not self.form_values.get("url") or not self.form_values["url"].get():
                self.show_message("Error: URL is required")
                return
                
            action_data = {
                "url": self.form_values["url"].get()
            }
        elif action_type == "volume":
            action_data = {
                "action": self.form_values["action"].get()
            }
        elif action_type == "media":
            # Get display value from dropdown
            display_value = self.form_values["media_display"].get()
            
            # Convert display value to internal value using our mapping
            internal_value = self.media_value_map.get(display_value, "play_pause")
            
            action_data = {
                "control": internal_value
            }
            logger.debug(f"Saving media control with display: {display_value}, internal: {internal_value}")
        elif action_type == "shortcut":
            if not self.form_values.get("shortcut") or not self.form_values["shortcut"].get():
                self.show_message("Error: Shortcut is required")
                return
            
            action_data = {
                "shortcut": self.form_values["shortcut"].get()
            }
        elif action_type == "audio_device":
            action_data = {
                "device_name": self.form_values["device_name"].get()
            }
        elif action_type == "command":
            commands = []
            for i in range(3):
                command = self.form_values.get(f"command_{i}", tk.StringVar()).get().strip()
                delay_str = self.form_values.get(f"delay_{i}", tk.StringVar()).get().strip()
                if command:
                    try:
                        delay_ms = int(delay_str) if delay_str else 0
                        commands.append({"command": command, "delay_ms": delay_ms})
                    except ValueError:
                        self.show_message(f"Error: Invalid delay value for command {i+1}")
                        return
            if not commands:
                self.show_message("Error: At least one command is required")
                return
            action_data = {"commands": commands}
        elif action_type == "text":
            if not self.form_values.get("text") or not self.form_values["text"].get():
                self.show_message("Error: Text is required")
                return
            
            action_data = {
                "text": self.form_values["text"].get()
            }
        elif action_type == "powershell":
            commands = []
            for i in range(3):
                command = self.form_values.get(f"ps_command_{i}", tk.StringVar()).get().strip()
                delay_str = self.form_values.get(f"ps_delay_{i}", tk.StringVar()).get().strip()
                if command:
                    try:
                        delay_ms = int(delay_str) if delay_str else 0
                        commands.append({"command": command, "delay_ms": delay_ms})
                    except ValueError:
                        self.show_message(f"Error: Invalid delay value for PowerShell command {i+1}")
                        return
            if not commands:
                self.show_message("Error: At least one PowerShell command is required")
                return
            action_data = {"commands": commands}
        elif action_type == "speech_to_text":
            language_display = self.form_values["language_display"].get()
            language_code = self.language_map.get(language_display, "en-US")
            action_data = {
                "language": language_code
            }
        
        # Create config object
        config = {
            "action_type": action_type,
            "action_data": action_data,
            "enabled": self.enabled_var.get(),
            "name": button_name
        }
        
        # Save to file
        success = save_button_config(button_id, config)
        
        if success:
            self.button_config[str(button_id)] = config
            
            # Update button label
            self.update_button_label(button_id, display_action_type, button_name)
            
            self.show_message(f"Configuration saved for {config['name']}")
            dialog.destroy()
        else:
            self.show_message("Error saving configuration")
    
    def update_button_label(self, button_id, action_type, description):
        """Update button label to show its configured action"""
        button_id = int(button_id)  # Ensure button_id is an integer
        short_desc = description if description else action_type
        
        # Find the button widget and update it
        if button_id in self.button_widgets:
            widget = self.button_widgets[button_id]
            if widget:
                # Get the original button name
                button_name = self.mapping["button_names"].get(str(button_id), f"Button {button_id}")
                
                # Update label based on the widget type
                if isinstance(widget, ctk.CTkFrame):  # Pad buttons (40-51)
                    # Find the label inside the frame
                    for child in widget.winfo_children():
                        if isinstance(child, ctk.CTkLabel):
                            # Get the pad number based on button_id
                            pad_num = button_id - 39 if 40 <= button_id <= 45 else button_id - 39
                            # Update label with action type/description
                            child.configure(text=f"Pad {pad_num}\n{short_desc}")
                            break
                    # Change frame color to indicate it's configured
                    widget.configure(fg_color="#444444")
                elif isinstance(widget, ctk.CTkButton):  # Regular buttons (1-8)
                    # Update button text with action type/description
                    widget.configure(text=f"{button_name}\n{short_desc}")
                    # Change button color to indicate it's configured
                    widget.configure(fg_color="#444444")
                elif isinstance(widget, ctk.CTkSlider):  # Slider
                    pass  # No text to update for slider
                else:
                    logger.warning(f"Unknown widget type for button {button_id}")
        else:
            logger.warning(f"Button ID {button_id} not found in button widgets")
    
    def execute_button_action(self, button_id, value=None):
        """Execute the action assigned to a button"""
        # Convert button_id to string for dictionary lookup
        button_id_str = str(button_id)
        
        config = self.button_config.get(button_id_str)
        if not config or not config.get("action_type"):
            logger.info(f"Button {button_id} has no assigned action")
            self.show_message(f"Button {button_id} has no assigned action")
            return False
        
        # Check if the action is enabled
        if not config.get("enabled", True):
            logger.info(f"Button {button_id} is disabled")
            self.show_message(f"Button {button_id} is disabled")
            return False
        
        action_type = config["action_type"]
        action_data = config.get("action_data", {})
        
        logger.info(f"Executing action for button {button_id}: {action_type} - {action_data}")
        
        try:
            # Special handling for volume control with slider value
            if action_type == "volume" and value is not None:
                # Update action_data with the slider value
                action_data = action_data.copy()
                action_data["action"] = "set"
                action_data["value"] = value
                
                # Execute the action
                result = self.system_actions.execute_action(action_type, action_data)
                if result:
                    logger.info(f"Volume set to {value}%")
                else:
                    logger.error(f"Failed to set volume to {value}%")
                return result
            
            # For all other actions, execute them through the system_actions handler
            result = self.system_actions.execute_action(action_type, action_data)
            
            if result:
                action_desc = config.get("name", f"Button {button_id}")
                logger.info(f"Action successful for {action_desc}")
                return True
            else:
                logger.error(f"Action execution failed for button {button_id}")
                self.show_message(f"Action failed for Button {button_id}")
                return False
            
        except Exception as e:
            logger.error(f"Error executing action for button {button_id}: {e}")
            self.show_message(f"Error: {str(e)}")
            return False
    
    def load_config(self):
        """Load button configurations from saved file"""
        try:
            # Load button configs
            configs = self.system_actions.load_button_configs()
            
            # Check if we have a 'buttons' key (for legacy configs)
            if "buttons" in configs:
                self.button_config = configs["buttons"]
            else:
                self.button_config = configs
                
            logger.info(f"Loaded configuration with {len(self.button_config)} button settings")
            
            # Update button labels if configs exist
            self.update_button_labels_from_config()
            
            self.show_message("Configuration loaded successfully")
            return True
        except Exception as e:
            logger.error(f"Error loading configuration: {e}")
            self.show_message(f"Error loading configuration: {e}")
            return False
    
    def show_message(self, message):
        """Display a message in the status bar"""
        logger.info(message)
        
        # Check if message_label exists and is initialized
        if hasattr(self, 'message_label') and self.message_label:
            try:
                self.message_label.configure(text=message)
                # Schedule message to clear after 5 seconds
                self.after(5000, lambda: self.message_label.configure(text="Ready"))
            except Exception as e:
                logger.error(f"Failed to update message label: {e}")

    def start_speech_recognition(self, button_id, language):
        try:
            import speech_recognition as sr
            import pyautogui
            import pyperclip
        except ImportError as e:
            logger.error(f"Required library not installed: {e}")
            self.show_message(f"Error: Please install {e}")
            return

        # If recognition is active for this button, stop it first to reset
        if self.active_recognition_button == button_id and self.active_recognition_stop:
            self.stop_speech_recognition(button_id)

        # If recognition is active for a different button, stop it
        if self.active_recognition_button is not None and self.active_recognition_button != button_id:
            self.stop_speech_recognition(self.active_recognition_button)

        try:
            recognizer = sr.Recognizer()

            # Adjust for ambient noise with a temporary microphone
            with sr.Microphone() as temp_source:
                recognizer.adjust_for_ambient_noise(temp_source, duration=0.5)

            # Set up the microphone for this session
            self.mic_source = sr.Microphone()

            def callback(recognizer, audio):
                try:
                    text = recognizer.recognize_google(audio, language=language)
                    logger.info(f"Recognized text: {text}")
                    pyperclip.copy(text)
                    pyautogui.hotkey('ctrl', 'v')
                except sr.UnknownValueError:
                    logger.warning("Could not understand audio")
                except sr.RequestError as e:
                    logger.error(f"Speech recognition error: {e}")

            # Start listening in the background
            stop_listening = recognizer.listen_in_background(self.mic_source, callback)
            self.active_recognition_stop = stop_listening
            self.active_recognition_button = button_id
            self.show_message("Listening for speech...")
        except Exception as e:
            logger.error(f"Failed to start speech recognition: {e}")
            self.show_message(f"Error: {e}")

    def stop_speech_recognition(self, button_id):
        if self.active_recognition_button == button_id and self.active_recognition_stop is not None:
            try:
                # Stop the background listening
                self.active_recognition_stop(wait_for_stop=True)
                # Close the microphone only if it exists
                if hasattr(self, 'mic_source') and self.mic_source is not None:
                    self.mic_source.__exit__(None, None, None)
                    self.mic_source = None
                self.active_recognition_stop = None
                self.active_recognition_button = None
                self.show_message("Speech recognition stopped")
            except Exception as e:
                logger.error(f"Error stopping speech recognition: {e}")
                self.show_message(f"Error stopping speech recognition: {e}")

    def toggle_slider(self):
        """Enable or disable slider functionality"""
        # Save slider state to config
        try:
            config_path = os.path.join(os.path.dirname(__file__), "config", "slider_config.json")
            os.makedirs(os.path.dirname(config_path), exist_ok=True)
            
            with open(config_path, 'w') as f:
                json.dump({"enabled": self.slider_enabled_var.get()}, f)
        except Exception as e:
            logger.error(f"Failed to save slider state: {e}")

        if not self.slider_enabled_var.get():
            # Store current value before disabling
            self._previous_slider_value = self.slider_widget.get()
            self.slider_widget.set(0)
            self.slider_widget.configure(
                button_color="#555555",
                progress_color="#444444",
                state="disabled"
            )
            self.show_message("Slider disabled")
        else:
            # Re-enable slider and restore colors
            self.slider_widget.configure(
                button_color="#00CED1",
                progress_color="#FF1493",
                state="normal"
            )
            if hasattr(self, '_previous_slider_value'):
                self.slider_widget.set(self._previous_slider_value)
                self.system_actions.set_volume("set", int(self._previous_slider_value))
            self.show_message("Slider enabled")

if __name__ == "__main__":
    app = MIDIKeyboardApp()
    app.mainloop()