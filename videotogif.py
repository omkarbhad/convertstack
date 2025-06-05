from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QSlider, QFileDialog, QMessageBox, QProgressBar, QFrame,
    QCheckBox, QComboBox, QPlainTextEdit
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QTimer, QObject
import os
import sys
import subprocess
import tempfile
import atexit
import time
import logging
from typing import Optional, Dict, Any
import ffmpeg
from dataclasses import dataclass

# ─────────────────────────────────────────────────────────────────────────────
# 1) LOGGER SETUP: capture logs into a Qt signal, so the GUI can display them.
# ─────────────────────────────────────────────────────────────────────────────

class QtHandler(QObject, logging.Handler):
    log_signal = pyqtSignal(str)

    def __init__(self):
        QObject.__init__(self)
        logging.Handler.__init__(self)
        fmt = "%(asctime)s - %(levelname)s - %(message)s"
        self.setFormatter(logging.Formatter(fmt))

    def emit(self, record):
        msg = self.format(record)
        self.log_signal.emit(msg)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("video_to_gif.log"),
    ],
)
logger = logging.getLogger(__name__)
qt_handler = QtHandler()
logger.addHandler(qt_handler)

# ─────────────────────────────────────────────────────────────────────────────
# 2) ConversionProgress dataclass
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ConversionProgress:
    frame: int = 0
    total_frames: int = 0
    fps: float = 0.0
    size: int = 0
    time: float = 0.0
    bitrate: float = 0.0
    speed: float = 0.0
    percent: float = 0.0

# ─────────────────────────────────────────────────────────────────────────────
# 3) VideoToGifConverter: ffmpeg + gifsicle logic.
# ─────────────────────────────────────────────────────────────────────────────

class VideoToGifConverter:
    def __init__(self, input_path: str, output_path: str):
        self.input_path = input_path
        self.output_path = output_path
        self.start_time = 0.0
        self.duration: Optional[float] = None
        self.width: Optional[int] = None
        self.height: Optional[int] = None
        self.fps: int = 15
        self.quality: int = 10
        self.optimize: bool = True
        self._progress_callback = None
        self._should_cancel = False
        self.video_info: Optional[Dict[str, Any]] = None
        logger.info(f"Initialized VideoToGifConverter (input={input_path}, output={output_path})")

    def get_video_info(self) -> Dict[str, Any]:
        try:
            info = self._probe_video()
            if not info or 'streams' not in info:
                raise RuntimeError("No video streams found in the file")
                
            video_stream = next((s for s in info['streams'] if s['codec_type'] == 'video'), None)
            if not video_stream:
                raise RuntimeError("No video stream found in the file")

            duration = float(video_stream.get('duration', info.get('format', {}).get('duration', 0)))
            if not duration:
                raise RuntimeError("Could not determine video duration")
                
            width = int(video_stream.get('width', 0))
            height = int(video_stream.get('height', 0))
            
            fps_str = video_stream.get('r_frame_rate', '0/1')
            try:
                if '/' in fps_str:
                    num, denom = map(float, fps_str.split('/'))
                    fps = num / denom if denom != 0 else 0
                else:
                    fps = float(fps_str)
            except (ValueError, ZeroDivisionError):
                fps = 0
                
            if fps <= 0 or width <= 0 or height <= 0:
                raise RuntimeError("Invalid video parameters (fps/width/height)")
                
            video_info = {
                'duration': duration,
                'width': width,
                'height': height,
                'fps': fps,
                'codec': video_stream.get('codec_name', 'unknown'),
                'total_frames': int(duration * fps),
                'format': info.get('format', {}).get('format_long_name', 'unknown')
            }
            
            self.video_info = video_info
            return video_info
            
        except ffmpeg.Error as e:
            stderr = e.stderr.decode("utf-8", errors="replace") if e.stderr else str(e)
            logger.error(f"FFprobe error: {stderr}", exc_info=True)
            raise RuntimeError("Could not probe video file.") from e
        except Exception as e:
            logger.error(f"Error getting video info: {e}", exc_info=True)
            raise RuntimeError(f"Could not process video: {e}") from e

    def _probe_video(self) -> Dict[str, Any]:
        try:
            return ffmpeg.probe(self.input_path)
        except ffmpeg.Error as e:
            error_msg = e.stderr.decode() if e.stderr else str(e)
            logger.error(f"FFmpeg probe error: {error_msg}")
            raise RuntimeError(f"Failed to probe video: {error_msg}") from e
        except Exception as e:
            logger.error(f"Unexpected error probing video: {e}")
            raise RuntimeError(f"Failed to probe video: {e}") from e

    def set_progress_callback(self, callback):
        self._progress_callback = callback

    def _update_progress(self, frame: int, total_frames: int):
        if frame % 10 == 0 or frame == total_frames:
            percent = (frame / total_frames * 100) if total_frames > 0 else 0
            logger.info(f"Progress: {frame}/{total_frames} frames ({percent:.1f}%)")
        if self._progress_callback:
            progress = ConversionProgress(
                frame=frame,
                total_frames=total_frames,
                percent=(frame / total_frames * 100) if total_frames > 0 else 0,
            )
            self._progress_callback(progress)

    def cancel(self):
        self._should_cancel = True

    def convert_to_gif(self) -> (bool, str):
        start_time_overall = time.time()
        logger.info(f"Starting full conversion for {self.input_path}")
        logger.info(f"Will write to: {self.output_path}")
        logger.info(f"Settings → start={self.start_time}s, duration={self.duration}s, fps={self.fps}, "
                    f"width={self.width}, height={self.height}, quality={self.quality}, optimize={self.optimize}")
        if not os.path.exists(self.input_path):
            msg = f"Input file not found: {self.input_path}"
            logger.error(msg)
            raise FileNotFoundError(msg)
        try:
            if not self.video_info:
                self.get_video_info()
            duration_total = (
                min(self.video_info["duration"] - self.start_time, self.duration)
                if self.duration
                else self.video_info["duration"] - self.start_time
            )
            total_frames = int(duration_total * self.fps)
            logger.info(f"Will convert {duration_total:.2f}s (~{total_frames} frames)")
            palette_file = tempfile.NamedTemporaryFile(suffix=".png", delete=False).name
            atexit.register(lambda: os.remove(palette_file) if os.path.exists(palette_file) else None)
            logger.info(f"Generating palette → {palette_file}")
            base_palette_stream = (
                ffmpeg.input(self.input_path, ss=self.start_time, t=duration_total)
                .filter("fps", fps=self.fps)
            )
            if self.width or self.height:
                w = self.width if self.width else -1
                h = self.height if self.height else -1
                base_palette_stream = base_palette_stream.filter("scale", w, h)
            palette_stream = base_palette_stream.filter("palettegen", stats_mode="diff")
            palette_stream.output(palette_file).run(overwrite_output=True, quiet=True)
            if not os.path.isfile(palette_file):
                raise RuntimeError("Palette generation failed: no palette file created.")
            logger.info(f"Palette created (size {os.path.getsize(palette_file)/1024:.1f} KB)")
            logger.info("Applying palette to generate GIF...")
            base_video_stream = (
                ffmpeg.input(self.input_path, ss=self.start_time, t=duration_total)
                .filter("fps", fps=self.fps)
            )
            if self.width or self.height:
                w = self.width if self.width else -1
                h = self.height if self.height else -1
                base_video_stream = base_video_stream.filter("scale", w, h)
            applied = ffmpeg.filter(
                [base_video_stream, ffmpeg.input(palette_file)],
                "paletteuse",
                dither="sierra2_4a"
            )
            applied_output = applied.output(
                self.output_path,
                loop=0,
                r=self.fps,
            )
            applied_output.run(overwrite_output=True, quiet=True)
            if os.path.exists(palette_file):
                os.remove(palette_file)
                atexit.unregister(lambda: os.remove(palette_file) if os.path.exists(palette_file) else None)
            if not os.path.exists(self.output_path):
                raise RuntimeError("Output GIF was not created.")
            size_mb = os.path.getsize(self.output_path) / (1024 * 1024)
            logger.info(f"GIF written: {self.output_path} ({size_mb:.2f} MB)")
            optimization_message = ""
            if self.optimize:
                logger.info("Running GIF optimization with gifsicle...")
                success_opt, opt_msg, orig_size, new_size = self._optimize_gif()
                if success_opt:
                    optimization_message = (f"{opt_msg}  → was {orig_size/1024:.1f}KB, "
                                            f"now {new_size/1024:.1f}KB")
                    logger.info(optimization_message)
                else:
                    optimization_message = f"Optimization skipped: {opt_msg}"
                    logger.warning(optimization_message)
            if self._progress_callback and total_frames > 0:
                prog = ConversionProgress(frame=total_frames,
                                          total_frames=total_frames,
                                          percent=100.0)
                self._progress_callback(prog)
            total_time = time.time() - start_time_overall
            logger.info(f"Conversion done in {total_time:.1f} seconds.")
            return True, optimization_message
        except ffmpeg.Error as e:
            stderr = e.stderr.decode() if e.stderr else str(e)
            msg = f"FFmpeg error: {stderr}"
            logger.error(msg, exc_info=True)
            raise RuntimeError(msg)
        except Exception as e:
            msg = f"Error during conversion: {e}"
            logger.error(msg, exc_info=True)
            raise RuntimeError(msg)
        finally:
            if "palette_file" in locals() and os.path.exists(palette_file):
                try:
                    os.remove(palette_file)
                    atexit.unregister(lambda: os.remove(palette_file) if os.path.exists(palette_file) else None)
                except Exception as exc:
                    logger.warning(f"Could not delete temp palette: {exc}")

    def _optimize_gif(self) -> (bool, str, int, int):
        if not os.path.exists(self.output_path):
            msg = "Output file not found for optimization"
            logger.error(msg)
            return False, msg, 0, 0
        original_size = os.path.getsize(self.output_path)
        temp_output = self.output_path + ".temp.gif"
        logger.info(f"Optimizing GIF: {self.output_path} ({original_size/1024:.1f} KB)")
        cmd = ["gifsicle", "-O3", "--colors", "256", "--lossy=80", "-o", temp_output, self.output_path]
        logger.debug("Running command: " + " ".join(cmd))
        try:
            start_opt = time.time()
            result = subprocess.run(
                cmd, check=True, capture_output=True, text=True, timeout=300
            )
            opt_time = time.time() - start_opt
            new_size = os.path.getsize(temp_output)
            reduction = ((original_size - new_size) / original_size * 100) if original_size > 0 else 0
            logger.info(f"Optimization done in {opt_time:.1f}s → {new_size/1024:.1f} KB ({reduction:.1f}% smaller)")
            if result.stdout:
                logger.debug(f"gifsicle stdout: {result.stdout}")
            if result.stderr:
                logger.debug(f"gifsicle stderr: {result.stderr}")
            os.replace(temp_output, self.output_path)
            return True, "Optimization succeeded", original_size, new_size
        except subprocess.CalledProcessError as e:
            stderr = e.stderr if e.stderr else "Unknown error"
            msg = f"GIF optimization failed: {stderr}"
            logger.error(msg)
            if os.path.exists(temp_output):
                os.remove(temp_output)
            return False, msg, original_size, 0
        except FileNotFoundError:
            msg = "gifsicle not installed. Install via: brew install gifsicle"
            logger.warning(msg)
            return False, msg, original_size, 0
        except subprocess.TimeoutExpired:
            msg = "GIF optimization timed out after 5 minutes"
            logger.error(msg)
            if os.path.exists(temp_output):
                os.remove(temp_output)
            return False, msg, original_size, 0

# ─────────────────────────────────────────────────────────────────────────────
# 4) ConversionWorker: runs convert_to_gif() on its own thread
# ─────────────────────────────────────────────────────────────────────────────

class ConversionWorker(QThread):
    progress_updated = pyqtSignal(float, str)
    finished = pyqtSignal(bool, str)
    error = pyqtSignal(str)

    def __init__(self, converter: VideoToGifConverter):
        super().__init__()
        self.converter = converter
        self.converter.set_progress_callback(self._progress_callback)

    def _progress_callback(self, progress: ConversionProgress):
        msg = f"Converting: {progress.frame}/{progress.total_frames} frames"
        self.progress_updated.emit(progress.percent, msg)

    def run(self):
        try:
            result = self.converter.convert_to_gif()
            if isinstance(result, tuple) and len(result) == 2:
                success, optimization_message = result
                message = "Conversion completed successfully!"
                if optimization_message:
                    message += f"\n{optimization_message}"
                self.finished.emit(success, message)
            else:
                success = bool(result)
                if success:
                    self.finished.emit(True, "Conversion completed successfully!")
                else:
                    self.finished.emit(False, "Conversion was cancelled or failed.")
        except Exception as e:
            err_msg = f"Error during conversion: {e}"
            logger.error(err_msg, exc_info=True)
            self.error.emit(err_msg)

    def stop(self):
        self.converter.cancel()

# ─────────────────────────────────────────────────────────────────────────────
# 5) The GUI itself, with modified quality slider and width options
# ─────────────────────────────────────────────────────────────────────────────

class VideoToGifConverterGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Video to GIF Converter")
        self.setGeometry(100, 100, 800, 700)
        self.logger = logging.getLogger(__name__)
        self.logger.info("Initializing Video to GIF Converter GUI")
        self.default_output_dir = os.path.expanduser("~/Downloads")
        if not os.path.isdir(self.default_output_dir):
            self.default_output_dir = os.getcwd()
        self.converter: Optional[VideoToGifConverter] = None
        self.worker: Optional[ConversionWorker] = None
        self.video_info: Optional[Dict[str, Any]] = None
        self.init_ui()
        qt_handler.log_signal.connect(self.append_log)
        self.logger.info("GUI initialization complete")

    def init_ui(self):
        main_widget = QWidget(self)
        self.setCentralWidget(main_widget)
        root_layout = QVBoxLayout(main_widget)
        root_layout.setSpacing(10)
        root_layout.setContentsMargins(10, 10, 10, 10)
        self.setStyleSheet("""
            QMainWindow { background-color: #0F172A; color: #E2E8F0; font-family: 'Segoe UI', sans-serif; }
            QLabel { color: #E2E8F0; font-size: 14px; }
            QPushButton { background-color: #4F46E5; color: white; border: none; padding: 8px 16px; border-radius: 6px; font-weight: 500; }
            QPushButton:hover { background-color: #4338CA; }
            QPushButton:pressed { background-color: #3730A3; }
            QPushButton:disabled { background-color: #4B5563; color: #9CA3AF; }
            QSlider::groove:horizontal { height: 6px; background: #1E293B; border-radius: 3px; }
            QSlider::handle:horizontal { background: #E2E8F0; border: 2px solid #4F46E5; width: 16px; height: 16px; margin: -6px 0; border-radius: 8px; }
            QSlider::sub-page:horizontal { background: #4F46E5; border-radius: 3px; }
            QComboBox { background-color: #1E293B; color: #E2E8F0; border: 1px solid #334155; border-radius: 4px; padding: 5px; }
            QComboBox::drop-down { border: none; }
            QComboBox::down-arrow { image: url(:/down-arrow.png); width: 10px; height: 10px; }
            QProgressBar { border: 1px solid #334155; border-radius: 6px; text-align: center; height: 20px; background-color: #1E293B; color: #E2E8F0; }
            QProgressBar::chunk { background-color: #4F46E5; border-radius: 4px; width: 10px; margin: 1px; }
            QCheckBox { color: #E2E8F0; font-size: 14px; }
        """)
        hero = QWidget()
        hero_layout = QVBoxLayout(hero)
        hero_layout.setContentsMargins(20, 20, 20, 20)
        hero_layout.setSpacing(8)
        title = QLabel("Video to GIF Converter")
        title.setStyleSheet("color: #FFFFFF; font-size: 26px; font-weight: 700;")
        title.setAlignment(Qt.AlignCenter | Qt.AlignBottom)
        subtitle = QLabel("Convert your videos to high-quality GIFs using FFmpeg")
        subtitle.setStyleSheet("color: rgba(255,255,255,0.9); font-size: 14px;")
        subtitle.setAlignment(Qt.AlignCenter | Qt.AlignTop)
        subtitle.setWordWrap(True)
        hero_layout.addWidget(title)
        hero_layout.addWidget(subtitle)
        root_layout.addWidget(hero)
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setSpacing(10)
        content_layout.setContentsMargins(20, 20, 20, 20)
        root_layout.addWidget(content)
        input_layout = QHBoxLayout()
        self.input_label = QLabel("No video selected")
        input_button = QPushButton("Select Video")
        input_button.clicked.connect(self.select_input)
        input_layout.addWidget(self.input_label, stretch=1)
        input_layout.addWidget(input_button)
        content_layout.addLayout(input_layout)
        output_layout = QHBoxLayout()
        self.output_label = QLabel("No output selected")
        output_button = QPushButton("Select Output")
        output_button.clicked.connect(self.select_output)
        output_layout.addWidget(self.output_label, stretch=1)
        output_layout.addWidget(output_button)
        content_layout.addLayout(output_layout)
        self.video_info_label = QLabel("Video info: Not loaded")
        self.video_info_label.setWordWrap(True)
        self.video_info_label.setStyleSheet("color: #94A3B8; font-style: italic;")
        content_layout.addWidget(self.video_info_label)
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("background-color: #334155; margin: 10px 0;")
        content_layout.addWidget(sep)
        self.video_duration_label = QLabel()
        self.video_duration_label.setVisible(False)
        content_layout.addWidget(self.video_duration_label)
        start_layout = QHBoxLayout()
        self.start_label = QLabel("Start: 00:00.0")
        self.start_slider = QSlider(Qt.Horizontal)
        self.start_slider.setMinimum(0)
        self.start_slider.setSingleStep(1)
        self.start_slider.setPageStep(10)
        self.start_slider.setValue(0)
        self.start_slider.setEnabled(False)
        self.start_slider.valueChanged.connect(self.update_start_label)
        start_layout.addWidget(self.start_label)
        start_layout.addWidget(self.start_slider, stretch=1)
        content_layout.addLayout(start_layout)
        duration_layout = QHBoxLayout()
        self.clip_duration_label = QLabel("Duration: 3.0s")
        self.clip_duration_slider = QSlider(Qt.Horizontal)
        self.clip_duration_slider.setMinimum(1)
        self.clip_duration_slider.setMaximum(300)
        self.clip_duration_slider.setValue(30)
        self.clip_duration_slider.setSingleStep(1)
        self.clip_duration_slider.setPageStep(10)
        self.clip_duration_slider.setEnabled(False)
        self.clip_duration_slider.valueChanged.connect(self.update_clip_duration_label)
        duration_layout.addWidget(self.clip_duration_label)
        duration_layout.addWidget(self.clip_duration_slider, stretch=1)
        content_layout.addLayout(duration_layout)
        fps_layout = QHBoxLayout()
        self.fps_label = QLabel("FPS: 15")
        self.fps_slider = QSlider(Qt.Horizontal)
        self.fps_slider.setMinimum(1)
        self.fps_slider.setMaximum(30)
        self.fps_slider.setValue(15)
        self.fps_slider.valueChanged.connect(self.update_fps_label)
        fps_layout.addWidget(self.fps_label)
        fps_layout.addWidget(self.fps_slider, stretch=1)
        content_layout.addLayout(fps_layout)
        width_layout = QHBoxLayout()
        self.width_label = QLabel("Width: 1920px")
        self.width_combo = QComboBox()
        self.resolutions = [
            ("4K (3840px)", 3840),
            ("2K (2560px)", 2560),
            ("1080p (1920px)", 1920),
            ("900p (1600px)", 1600),
            ("720p (1280px)", 1280),
            ("540p (960px)", 960),
            ("480p (854px)", 854),
            ("360p (640px)", 640),
            ("240p (426px)", 426),
            ("144p (256px)", 256),
        ]
        for label, value in self.resolutions:
            self.width_combo.addItem(label, value)
        self.width_combo.setCurrentIndex(2)  # Default to 1080p (1920px)
        self.width_combo.currentIndexChanged.connect(self.update_width_label)
        width_layout.addWidget(self.width_label)
        width_layout.addWidget(self.width_combo, stretch=1)
        content_layout.addLayout(width_layout)
        quality_layout = QHBoxLayout()
        self.quality_label = QLabel("Quality: 10 (lower = better)")
        self.quality_slider = QSlider(Qt.Horizontal)
        self.quality_slider.setMinimum(1)
        self.quality_slider.setMaximum(31)
        self.quality_slider.setValue(10)
        self.quality_slider.setSingleStep(1)
        self.quality_slider.setPageStep(5)  # Steps of 5 for easier navigation
        self.quality_slider.setTickPosition(QSlider.TicksBelow)  # Show tick marks
        self.quality_slider.setTickInterval(5)  # Ticks at 1, 5, 10, 15, 20, 25, 30
        self.quality_slider.setInvertedAppearance(True)
        self.quality_slider.valueChanged.connect(self.update_quality_label)
        quality_layout.addWidget(self.quality_label)
        quality_layout.addWidget(self.quality_slider, stretch=1)
        content_layout.addLayout(quality_layout)
        self.optimize_check = QCheckBox("Optimize GIF with gifsicle (recommended)")
        self.optimize_check.setChecked(True)
        content_layout.addWidget(self.optimize_check)
        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setVisible(False)
        self.progress_bar.setFormat("Ready")
        content_layout.addWidget(self.progress_bar)
        self.status_label = QLabel("Ready")
        self.status_label.setAlignment(Qt.AlignCenter)
        content_layout.addWidget(self.status_label)
        button_layout = QHBoxLayout()
        self.convert_button = QPushButton("Convert")
        self.convert_button.setEnabled(False)
        self.convert_button.clicked.connect(self.start_conversion)
        button_layout.addWidget(self.convert_button)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.cancel_conversion)
        self.cancel_button.setEnabled(False)
        button_layout.addWidget(self.cancel_button)
        content_layout.addLayout(button_layout)
        self.log_output = QPlainTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setStyleSheet(
            "background-color: #1E293B; color: #E2E8F0; "
            "border: 1px solid #334155; border-radius: 4px; padding: 8px;"
        )
        self.log_output.setFixedHeight(120)
        content_layout.addWidget(self.log_output)

    def append_log(self, msg: str):
        """Append a log message to the log output widget."""
        self.log_output.appendPlainText(msg)
        # Keep the cursor at the end so the latest message is visible.
        self.log_output.verticalScrollBar().setValue(
            self.log_output.verticalScrollBar().maximum()
        )

    def select_input(self):
        options = QFileDialog.Options()
        try:
            file_path, _ = QFileDialog.getOpenFileName(
                self, "Select Video File", "", "Video Files (*.mp4 *.mov *.avi *.mkv *.webm);;All Files (*)", options=options
            )
            if not file_path:
                return
            logger.info(f"Selected video: {file_path}")
            self.input_label.setText(os.path.basename(file_path))
            self.input_label.setToolTip(file_path)
            self.status_label.setText("Analyzing video...")
            QApplication.processEvents()
            self.converter = VideoToGifConverter(file_path, "")
            info = self.converter.get_video_info()
            self.video_info = info
            duration = info["duration"]
            width = info["width"]
            height = info["height"]
            fps = info["fps"]
            codec = info["codec"].upper()
            self.video_info_label.setText(
                f"{width}x{height} • {fps:.2f} FPS • {codec} • {self.format_time(duration)}"
            )
            self.video_duration_label.setText(f"Video Duration: {self.format_time(duration)}")
            self.video_duration_label.setVisible(True)
            max_dur = int(duration * 10)
            self.start_slider.setMaximum(max_dur - 1 if max_dur > 1 else 1)
            self.start_slider.setEnabled(True)
            self.start_slider.setValue(0)
            self.update_start_label(0)
            self.clip_duration_slider.setMaximum(max_dur)
            default_dur = min(max_dur, 30)
            self.clip_duration_slider.setEnabled(True)
            self.clip_duration_slider.setValue(default_dur)
            self.update_clip_duration_label(default_dur)
            max_width = min(self.video_info["width"], 3840)  # Cap at 4K
            default_width = min(1920, max_width)  # Default to 1080p or less
            for i, (label, value) in enumerate(self.resolutions):
                if value <= max_width:
                    self.width_combo.setItemData(i, value)
                else:
                    self.width_combo.setItemData(i, None)
            for i, (label, value) in enumerate(self.resolutions):
                if value == default_width:
                    self.width_combo.setCurrentIndex(i)
                    break
            self.update_width_label()
            self.fps_slider.setValue(min(30, int(fps)))
            self.update_fps_label(self.fps_slider.value())
            self.update_quality_label(self.quality_slider.value())
            base_name = os.path.splitext(os.path.basename(file_path))[0] + ".gif"
            suggested = os.path.join(self.default_output_dir, base_name)
            self.converter.output_path = suggested
            self.output_label.setText(os.path.basename(suggested))
            self.output_label.setToolTip(suggested)
            self.status_label.setText("Ready")
            self.update_convert_button()
            logger.info(f"Loaded video info: {width}x{height}, {fps:.2f} FPS, {duration:.2f}s")
        except Exception as e:
            err = f"Could not load video: {e}"
            logger.error(err, exc_info=True)
            self.input_label.setText("No video selected")
            self.video_info_label.setText("Video info: Not loaded")
            self.video_duration_label.setVisible(False)
            self.status_label.setText("Error loading video")
            QMessageBox.critical(self, "Error Loading Video", f"{e}")
            self.converter = None
            self.video_info = None
            self.convert_button.setEnabled(False)

    def select_output(self):
        logger.info("Selecting output location...")
        suggested_name = "output.gif"
        if self.converter and self.converter.input_path:
            base = os.path.splitext(os.path.basename(self.converter.input_path))[0]
            suggested_name = f"{base}.gif"
        default_path = os.path.join(self.default_output_dir, suggested_name)
        path, _ = QFileDialog.getSaveFileName(
            self, "Save GIF As", default_path, "GIF Files (*.gif)"
        )
        if not path:
            return
        if not path.lower().endswith(".gif"):
            path += ".gif"
        out_dir = os.path.dirname(path)
        if out_dir and not os.path.exists(out_dir):
            try:
                os.makedirs(out_dir, exist_ok=True)
                logger.info(f"Created directory: {out_dir}")
            except Exception as e:
                logger.error(f"Could not create directory {out_dir}: {e}", exc_info=True)
                QMessageBox.warning(self, "Warning", f"Could not create directory:\n{e}")
                return
        if self.converter:
            self.converter.output_path = path
        self.output_label.setText(os.path.basename(path))
        self.output_label.setToolTip(path)
        self.update_convert_button()
        logger.info(f"Output set to: {path}")

    def update_start_label(self, value: int):
        start_time = value / 10.0
        self.start_label.setText(f"Start: {self.format_time(start_time)}")
        if self.video_info:
            remaining = self.video_info["duration"] - start_time
            max_val = int(remaining * 10)
            self.clip_duration_slider.setMaximum(max_val if max_val > 0 else 1)
            current_dur = self.clip_duration_slider.value() / 10.0
            if current_dur > remaining:
                self.clip_duration_slider.setValue(max_val)
        self.update_clip_duration_label(self.clip_duration_slider.value())
        self.update_convert_button()
        logger.debug(f"Start time set to {start_time}s")

    def update_clip_duration_label(self, value: int):
        dur = value / 10.0
        self.clip_duration_label.setText(f"Duration: {dur:.1f}s")
        self.update_convert_button()
        logger.debug(f"Clip duration set to {dur}s")

    def update_fps_label(self, value: int):
        self.fps_label.setText(f"FPS: {value}")
        logger.debug(f"FPS set to {value}")

    def update_width_label(self):
        value = self.width_combo.currentData()
        self.width_label.setText(f"Width: {value}px")
        logger.debug(f"Width set to {value}px")

    def update_quality_label(self, value: int):
        self.quality_label.setText(f"Quality: {value} (lower = better)")
        logger.debug(f"Quality set to {value}")

    def format_time(self, seconds: float) -> str:
        minutes = int(seconds) // 60
        sec = seconds - minutes * 60
        return f"{minutes:02}:{sec:04.1f}"

    def update_convert_button(self):
        is_enabled = (
            self.converter is not None
            and bool(getattr(self.converter, "output_path", ""))
            and (self.clip_duration_slider.value() / 10.0) > 0
        )
        self.convert_button.setEnabled(is_enabled)
        logger.debug(f"Convert button {'enabled' if is_enabled else 'disabled'}")

    def start_conversion(self):
        logger.info("User clicked Convert.")
        if not self.converter:
            msg = "No video loaded."
            logger.error(msg)
            self.status_label.setText(msg)
            return
        try:
            self.converter.start_time = self.start_slider.value() / 10.0
            self.converter.duration = self.clip_duration_slider.value() / 10.0
            self.converter.fps = self.fps_slider.value()
            self.converter.width = self.width_combo.currentData()
            self.converter.height = None
            self.converter.quality = self.quality_slider.value()
            self.converter.optimize = self.optimize_check.isChecked()
            if not getattr(self.converter, "output_path", ""):
                self.select_output()
                if not getattr(self.converter, "output_path", ""):
                    logger.warning("No output path; cancel conversion.")
                    return
            logger.info(f"Will save GIF to: {self.converter.output_path}")
            self.convert_button.setEnabled(False)
            self.cancel_button.setEnabled(True)
            self.status_label.setText("Starting conversion...")
            logger.info("Spawning ConversionWorker thread...")
            self.worker = ConversionWorker(self.converter)
            self.worker.progress_updated.connect(self.update_progress)
            self.worker.finished.connect(self.conversion_finished)
            self.worker.error.connect(self.conversion_error)
            self.worker.start()
        except Exception as e:
            msg = f"Error starting conversion: {e}"
            logger.error(msg, exc_info=True)
            self.status_label.setText("Error starting conversion")
            QMessageBox.critical(self, "Error", msg)
            self.convert_button.setEnabled(True)

    def cancel_conversion(self):
        if self.worker and self.converter:
            self.converter.cancel()
            logger.info("Cancel signal sent to converter.")
            self.cancel_button.setEnabled(False)
            self.status_label.setText("Cancelling...")

    def update_progress(self, percent: float, message: str):
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(int(percent))
        self.progress_bar.setFormat(message)
        self.progress_bar.repaint()
        QApplication.processEvents()

    def conversion_finished(self, success: bool, message: str):
        self.progress_bar.setValue(100 if success else 0)
        self.progress_bar.setFormat(message)
        self.cancel_button.setEnabled(False)
        self.update_convert_button()
        self.status_label.setText(message)
        self.worker = None
        QTimer.singleShot(2000, self.reset_progress)
        if success:
            QMessageBox.information(
                self, "Conversion Complete", f"{message}\n\nSaved to:\n{self.converter.output_path}"
            )

    def conversion_error(self, message: str):
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("Error")
        self.cancel_button.setEnabled(False)
        self.update_convert_button()
        self.status_label.setText(message)
        self.worker = None
        QTimer.singleShot(2000, self.reset_progress)
        QMessageBox.critical(self, "Conversion Error", message)

    def reset_progress(self):
        self.progress_bar.setFormat("Ready")
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(False)

    def closeEvent(self, event):
        if self.worker and self.worker.isRunning():
            self.converter.cancel()
            self.worker.wait()
        event.accept()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = VideoToGifConverterGUI()
    window.show()
    sys.exit(app.exec_())