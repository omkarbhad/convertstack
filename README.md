# Video to GIF Converter

A simple yet powerful desktop application to convert video files to high-quality GIFs with customizable settings. Built with Python, PyQt5, and FFmpeg.

![Screenshot](screenshot.png)

## Features

- 🎥 Convert video files to GIF format
- ⚡ Customize start time and duration
- 🎚️ Adjust FPS (frames per second)
- 🖼️ Set custom dimensions (width/height)
- 🎨 Control GIF quality
- 🚀 Optimized output with gifsicle
- 📊 Real-time progress tracking
- 🎨 Dark theme UI

## Prerequisites

- Python 3.7+
- FFmpeg
- gifsicle (for optimization)

## Installation

1. Clone the repository:
   ```bash
   git clone https://github.com/omkarbhad/convertstack.git
   cd convertstack
   ```

2. Install the required Python packages:
   ```bash
   pip install -r requirements.txt
   ```

3. Install system dependencies:
   - **macOS (using Homebrew):**
     ```bash
     brew install ffmpeg gifsicle
     ```
   - **Linux (Debian/Ubuntu):**
     ```bash
     sudo apt-get update
     sudo apt-get install ffmpeg gifsicle
     ```
   - **Windows (using Chocolatey):**
     ```cmd
     choco install ffmpeg gifsicle
     ```

## Usage

1. Run the application:
   ```bash
   python videotogif.py
   ```

2. Click "Select Video" to choose a video file
3. Adjust the settings as needed:
   - Start time and duration
   - FPS (frames per second)
   - Output dimensions
   - Quality level

3. Click "Convert" to start the conversion
4. The optimized GIF will be saved to your specified location

## Requirements

- PyQt5
- ffmpeg-python

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## Author

[Your Name](https://github.com/omkarbhad)

---

Made with ❤️ and Python
