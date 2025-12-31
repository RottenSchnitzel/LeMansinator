import sys
import os
import time
from pathlib import Path
from typing import Optional
from datetime import datetime

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QCheckBox, QSlider, QSpinBox, QFileDialog,
    QGroupBox, QFrame
)
from PySide6.QtCore import QThread, Signal, QTimer, Qt, QSettings
from PySide6.QtGui import QFont

import pygame.mixer

try:
    import irsdk
    IRSDK_AVAILABLE = True
except ImportError:
    IRSDK_AVAILABLE = False
    print("Warning: irsdk not available. Install with: pip install irsdk")


class TelemetryWorker(QThread):
    connection_changed = Signal(bool)
    session_info_updated = Signal(dict) 
    grid_timer_ended = Signal()
    status_message = Signal(str)
    
    def __init__(self):
        super().__init__()
        self.ir = None
        self.running = False
        self.enabled = False
        
        self.last_session_num = -1
        self.last_session_state = -1
        self.is_connected = False
        
        self.last_session_time = -1
        self.grid_timer_triggered = False
        
        self.poll_interval = 0.1
    def run(self):
        self.running = True
        
        if not IRSDK_AVAILABLE:
            self.status_message.emit("ERROR: irsdk package not installed")
            return
        
        self.ir = irsdk.IRSDK()
        self.status_message.emit("Telemetry worker started")
        
        while self.running:
            if self.ir.startup():
                if not self.is_connected:
                    self.is_connected = True
                    self.connection_changed.emit(True)
                    self.status_message.emit("Connected to iRacing")
                
                if self.enabled:
                    self._process_telemetry()
            else:
                if self.is_connected:
                    self.is_connected = False
                    self.connection_changed.emit(False)
                    self.status_message.emit("Disconnected from iRacing")
                    self._reset_state()
            
            time.sleep(self.poll_interval)
        
        if self.ir:
            self.ir.shutdown()
        self.status_message.emit("Telemetry worker stopped")
    
    def _process_telemetry(self):
        if not self.ir.is_initialized:
            return
            
        if not self.ir.is_connected:
            return
        
        try:
            self.ir.freeze_var_buffer_latest()
        except Exception as e:
            return
        
        session_num = self.ir['SessionNum']
        session_state = self.ir['SessionState']
        
        self.ir.unfreeze_var_buffer_latest()
        
        self._check_session_change()
        
        if session_num is not None and session_num != self.last_session_num:
            if self.last_session_num != -1:
                self.status_message.emit(f"Session changed (Num: {session_num})")
                self._reset_trigger_state()
            
            self.last_session_num = session_num
        
        if session_state is not None and session_state != self.last_session_state:
            if not self.grid_timer_triggered:
                self._detect_grid_timer_end(session_state)
    
    def _check_session_change(self):
        try:
            weekend_info = self.ir['WeekendInfo']
            
            if not weekend_info:
                return
            
            track_name = weekend_info.get('TrackDisplayName', 'Unknown')
            
            session_info = self.ir['SessionInfo']
            
            if not session_info:
                return
            
            session_num = self.ir['SessionNum']
            if session_num is None:
                return
            
            sessions = session_info.get('Sessions', [])
            
            session_type = 'Unknown'
            if sessions and 0 <= session_num < len(sessions):
                current_session = sessions[session_num]
                session_type = current_session.get('SessionType', 'Unknown')
            
            session_state = self.ir['SessionState']
            if session_state is None:
                session_state = 0
            
            info = {
                'track': track_name,
                'track_short': weekend_info.get('TrackDisplayShortName', 'Unknown'),
                'session_type': session_type,
                'session_num': session_num,
                'session_state': session_state
            }
            self.session_info_updated.emit(info)
            
        except Exception as e:
            import traceback
            self.status_message.emit(f"ERROR: {e}\n{traceback.format_exc()}")
    
    def _detect_grid_timer_end(self, session_state):
        if session_state == 3 and self.last_session_state in [1, 2]:
            self.status_message.emit("Parade laps started - countdown begins")
            self.grid_timer_ended.emit()
            self.grid_timer_triggered = True
        elif session_state == 4 and self.last_session_state in [1, 2]:
            self.status_message.emit("Standing start - race begins")
            self.grid_timer_ended.emit()
            self.grid_timer_triggered = True
        
        self.last_session_state = session_state
    
    def _reset_trigger_state(self):
        self.grid_timer_triggered = False
        self.last_session_time = -1
    
    def _reset_state(self):
        self.last_session_num = -1
        self.last_session_state = -1
        self._reset_trigger_state()
    
    def stop(self):
        self.running = False
        self.wait()


class AudioManager:
    
    def __init__(self):
        pygame.mixer.init()
        self.audio_file = None
        self.volume = 0.7
        pygame.mixer.music.set_volume(self.volume)
    
    def set_audio_file(self, filepath: str) -> bool:
        try:
            if not os.path.exists(filepath):
                return False
            
            pygame.mixer.music.load(filepath)
            self.audio_file = filepath
            return True
        except Exception as e:
            print(f"Error loading audio file: {e}")
            return False
    
    def set_volume(self, volume: float):
        self.volume = max(0.0, min(1.0, volume))
        pygame.mixer.music.set_volume(self.volume)
    
    def play(self):
        if self.audio_file and os.path.exists(self.audio_file):
            try:
                pygame.mixer.music.load(self.audio_file)
                pygame.mixer.music.set_volume(self.volume)
                pygame.mixer.music.play(loops=0)
                return True
            except Exception as e:
                print(f"Error playing audio: {e}")
                return False
        return False
    
    def stop(self):
        pygame.mixer.music.stop()
    
    def is_playing(self) -> bool:
        return pygame.mixer.music.get_busy()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        
        self.settings = QSettings('iRacingLeManSound', 'LeMansTrigger')
        
        self.audio_manager = AudioManager()
        
        self.telemetry_worker = TelemetryWorker()
        self.telemetry_worker.connection_changed.connect(self.on_connection_changed)
        self.telemetry_worker.session_info_updated.connect(self.on_session_info_updated)
        self.telemetry_worker.grid_timer_ended.connect(self.on_grid_timer_ended)
        self.telemetry_worker.status_message.connect(self.on_status_message)
        
        self.is_armed = False
        self.current_track = "Unknown"
        self.current_session_type = "Unknown"
        self.is_le_mans = False
        self.trigger_state = "Idle"
        
        self.delay_timer = QTimer()
        self.delay_timer.setSingleShot(True)
        self.delay_timer.timeout.connect(self.on_delay_timeout)
        
        self.init_ui()
        
        self.load_settings()
        
        self.telemetry_worker.start()
    
    def init_ui(self):
        self.setWindowTitle("iRacing Le Mans Audio Trigger")
        self.setMinimumWidth(500)
        
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        main_layout = QVBoxLayout(central_widget)
        
        control_group = QGroupBox("Control")
        control_layout = QVBoxLayout()
        
        self.enable_checkbox = QCheckBox("Enable Trigger")
        self.enable_checkbox.setFont(QFont('Arial', 10, QFont.Bold))
        self.enable_checkbox.stateChanged.connect(self.on_enable_changed)
        control_layout.addWidget(self.enable_checkbox)
        
        control_group.setLayout(control_layout)
        main_layout.addWidget(control_group)
        
        audio_group = QGroupBox("Audio Settings")
        audio_layout = QVBoxLayout()
        
        file_layout = QHBoxLayout()
        file_layout.addWidget(QLabel("Audio File:"))
        self.file_label = QLabel("No file selected")
        self.file_label.setStyleSheet("QLabel { background-color: #2b2b2b; color: #ffffff; padding: 5px; }")
        file_layout.addWidget(self.file_label, 1)
        self.browse_button = QPushButton("Browse...")
        self.browse_button.clicked.connect(self.browse_audio_file)
        file_layout.addWidget(self.browse_button)
        audio_layout.addLayout(file_layout)
        
        volume_layout = QHBoxLayout()
        volume_layout.addWidget(QLabel("Volume:"))
        self.volume_slider = QSlider(Qt.Horizontal)
        self.volume_slider.setMinimum(0)
        self.volume_slider.setMaximum(100)
        self.volume_slider.setValue(70)
        self.volume_slider.valueChanged.connect(self.on_volume_changed)
        volume_layout.addWidget(self.volume_slider, 1)
        self.volume_label = QLabel("70%")
        self.volume_label.setMinimumWidth(40)
        volume_layout.addWidget(self.volume_label)
        audio_layout.addLayout(volume_layout)
        
        test_layout = QHBoxLayout()
        self.test_play_button = QPushButton("Test Play")
        self.test_play_button.clicked.connect(self.test_play)
        test_layout.addWidget(self.test_play_button)
        self.test_stop_button = QPushButton("Stop")
        self.test_stop_button.clicked.connect(self.test_stop)
        test_layout.addWidget(self.test_stop_button)
        test_layout.addStretch()
        audio_layout.addLayout(test_layout)
        
        audio_group.setLayout(audio_layout)
        main_layout.addWidget(audio_group)
        
        timing_group = QGroupBox("Timing Configuration")
        timing_layout = QHBoxLayout()
        
        timing_layout.addWidget(QLabel("Delay after grid timer ends:"))
        self.delay_spinbox = QSpinBox()
        self.delay_spinbox.setMinimum(0)
        self.delay_spinbox.setMaximum(300)
        self.delay_spinbox.setValue(38)
        self.delay_spinbox.setSuffix(" seconds")
        self.delay_spinbox.valueChanged.connect(self.on_delay_changed)
        timing_layout.addWidget(self.delay_spinbox)
        timing_layout.addStretch()
        
        timing_group.setLayout(timing_layout)
        main_layout.addWidget(timing_group)
        
        status_group = QGroupBox("Status")
        status_layout = QVBoxLayout()
        
        connection_layout = QHBoxLayout()
        connection_layout.addWidget(QLabel("iRacing:"))
        self.connection_label = QLabel("Disconnected")
        self.connection_label.setStyleSheet("QLabel { color: red; font-weight: bold; }")
        connection_layout.addWidget(self.connection_label)
        connection_layout.addStretch()
        status_layout.addLayout(connection_layout)
        
        track_layout = QHBoxLayout()
        track_layout.addWidget(QLabel("Track:"))
        self.track_label = QLabel("Unknown")
        track_layout.addWidget(self.track_label)
        track_layout.addStretch()
        status_layout.addLayout(track_layout)
        
        session_layout = QHBoxLayout()
        session_layout.addWidget(QLabel("Session:"))
        self.session_label = QLabel("Unknown")
        session_layout.addWidget(self.session_label)
        session_layout.addStretch()
        status_layout.addLayout(session_layout)
        
        state_layout = QHBoxLayout()
        state_layout.addWidget(QLabel("Trigger State:"))
        self.state_label = QLabel("Idle")
        self.state_label.setStyleSheet("QLabel { font-weight: bold; }")
        state_layout.addWidget(self.state_label)
        state_layout.addStretch()
        status_layout.addLayout(state_layout)
        
        separator = QFrame()
        separator.setFrameShape(QFrame.HLine)
        separator.setFrameShadow(QFrame.Sunken)
        status_layout.addWidget(separator)
        
        self.status_text = QLabel("Ready")
        self.status_text.setWordWrap(True)
        self.status_text.setStyleSheet("QLabel { padding: 5px; background-color: #2b2b2b; color: #ffffff; }")
        status_layout.addWidget(self.status_text)
        
        status_group.setLayout(status_layout)
        main_layout.addWidget(status_group)
        
        main_layout.addStretch()
    
    def on_enable_changed(self, state):
        enabled = (state == 2)
        self.telemetry_worker.enabled = enabled
        
        if enabled:
            self.telemetry_worker.grid_timer_triggered = False
            self.on_status_message("Trigger enabled - monitoring for race sessions")
            self.update_trigger_state()
        else:
            self.on_status_message("Trigger disabled")
            self.set_trigger_state("Idle")
            self.delay_timer.stop()
    
    def browse_audio_file(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Audio File",
            "",
            "Audio Files (*.wav *.mp3);;All Files (*.*)"
        )
        
        if file_path:
            if self.audio_manager.set_audio_file(file_path):
                self.file_label.setText(Path(file_path).name)
                self.file_label.setToolTip(file_path)
                self.on_status_message(f"Loaded audio file: {Path(file_path).name}")
            else:
                self.on_status_message(f"ERROR: Failed to load audio file")
    
    def on_volume_changed(self, value):
        self.volume_label.setText(f"{value}%")
        self.audio_manager.set_volume(value / 100.0)
    
    def on_delay_changed(self, value):
        pass
    
    def test_play(self):
        if self.audio_manager.play():
            self.on_status_message("Test playback started")
        else:
            self.on_status_message("ERROR: No audio file selected or playback failed")
    
    def test_stop(self):
        self.audio_manager.stop()
        self.on_status_message("Playback stopped")
    
    def on_connection_changed(self, connected):
        if connected:
            self.connection_label.setText("Connected")
            self.connection_label.setStyleSheet("QLabel { color: green; font-weight: bold; }")
        else:
            self.connection_label.setText("Disconnected")
            self.connection_label.setStyleSheet("QLabel { color: red; font-weight: bold; }")
            self.track_label.setText("Unknown")
            self.session_label.setText("Unknown")
            self.set_trigger_state("Idle")
            self.delay_timer.stop()
    
    def on_session_info_updated(self, info):
        self.current_track = info['track']
        self.current_session_type = info['session_type']
        
        self.track_label.setText(self.current_track)
        self.session_label.setText(self.current_session_type)
        
        track_lower = self.current_track.lower()
        self.is_le_mans = ('le mans' in track_lower or 'lemans' in track_lower or 
                          'circuit de la sarthe' in track_lower or 'sarthe' in track_lower)
        
        self.update_trigger_state()
    
    def on_grid_timer_ended(self):
        if self.trigger_state == "Armed":
            delay_seconds = self.delay_spinbox.value()
            
            self.on_status_message(f"Race start detected - countdown begins: {delay_seconds}s")
            
            if delay_seconds > 0:
                self.set_trigger_state("Waiting")
                self.delay_timer.start(delay_seconds * 1000)
                self.on_status_message(f"Waiting {delay_seconds} seconds before playing audio...")
            else:
                self.trigger_playback()
    
    def on_delay_timeout(self):
        self.on_status_message("Delay complete - playing audio now")
        self.trigger_playback()
    
    def trigger_playback(self):
        self.on_status_message(f"Starting playback: {self.audio_manager.audio_file}")
        
        if self.audio_manager.play():
            self.set_trigger_state("Triggered")
            self.on_status_message("Audio playback started successfully")
        else:
            self.on_status_message("ERROR: Failed to play audio - check file selection")
            self.set_trigger_state("Armed")
    
    def update_trigger_state(self):
        if not self.enable_checkbox.isChecked():
            return
        
        is_race = (self.current_session_type.lower() == 'race')
        
        if is_race and self.trigger_state in ["Idle", "Triggered"]:
            self.set_trigger_state("Armed")
            self.on_status_message(f"Trigger armed - {self.current_track} race detected")
        elif not is_race and self.trigger_state in ["Armed", "Waiting"]:
            self.set_trigger_state("Idle")
            self.delay_timer.stop()
    
    def set_trigger_state(self, state):
        self.trigger_state = state
        self.state_label.setText(state)
        
        colors = {
            "Idle": "#666666",
            "Armed": "#ff6600",
            "Waiting": "#ffaa00",
            "Triggered": "#00aa00"
        }
        color = colors.get(state, "#000000")
        self.state_label.setStyleSheet(f"QLabel {{ font-weight: bold; color: {color}; }}")
    
    def on_status_message(self, message):
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.status_text.setText(f"[{timestamp}] {message}")
    
    def load_settings(self):
        audio_file = self.settings.value('audio_file', '')
        if audio_file and os.path.exists(audio_file):
            if self.audio_manager.set_audio_file(audio_file):
                self.file_label.setText(Path(audio_file).name)
                self.file_label.setToolTip(audio_file)
        
        volume = self.settings.value('volume', 70, type=int)
        self.volume_slider.setValue(volume)
        
        delay = self.settings.value('delay', 38, type=int)
        self.delay_spinbox.setValue(delay)
        
        enabled = self.settings.value('enabled', False, type=bool)
        self.enable_checkbox.setChecked(enabled)
        self.telemetry_worker.enabled = enabled
    
    def save_settings(self):
        self.settings.setValue('audio_file', self.audio_manager.audio_file or '')
        self.settings.setValue('volume', self.volume_slider.value())
        self.settings.setValue('delay', self.delay_spinbox.value())
        self.settings.setValue('enabled', self.enable_checkbox.isChecked())
    
    def closeEvent(self, event):
        self.save_settings()
        self.telemetry_worker.stop()
        self.audio_manager.stop()
        event.accept()


def main():
    app = QApplication(sys.argv)
    
    app.setApplicationName("iRacing Le Mans Audio Trigger")
    app.setOrganizationName("iRacingLeManSound")
    app.setOrganizationDomain("github.com")
    
    app.setStyle("Fusion")
    dark_palette = """
    QWidget {
        background-color: #2b2b2b;
        color: #ffffff;
    }
    QGroupBox {
        border: 1px solid #555555;
        border-radius: 5px;
        margin-top: 10px;
        padding-top: 10px;
        font-weight: bold;
    }
    QGroupBox::title {
        subcontrol-origin: margin;
        left: 10px;
        padding: 0 5px;
    }
    QPushButton {
        background-color: #3d3d3d;
        border: 1px solid #555555;
        border-radius: 3px;
        padding: 5px 15px;
        color: #ffffff;
    }
    QPushButton:hover {
        background-color: #4d4d4d;
    }
    QPushButton:pressed {
        background-color: #2d2d2d;
    }
    QCheckBox {
        spacing: 5px;
    }
    QSlider::groove:horizontal {
        border: 1px solid #555555;
        height: 8px;
        background: #3d3d3d;
        border-radius: 4px;
    }
    QSlider::handle:horizontal {
        background: #0078d4;
        border: 1px solid #005a9e;
        width: 18px;
        margin: -5px 0;
        border-radius: 9px;
    }
    QSpinBox {
        background-color: #3d3d3d;
        border: 1px solid #555555;
        border-radius: 3px;
        padding: 3px;
    }
    QLabel {
        background-color: transparent;
    }
    QFrame[frameShape="4"] {
        color: #555555;
    }
    """
    app.setStyleSheet(dark_palette)
    
    window = MainWindow()
    window.show()
    
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
