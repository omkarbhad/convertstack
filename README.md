# 🎞️ Video to GIF Converter

A simple yet powerful desktop application to convert video files into high-quality GIFs with customizable settings. Built with **Python**, **PyQt5**, and **FFmpeg**, this tool offers flexibility and efficiency for quick GIF generation.

---

## ✨ Features

* 🎥 **Convert videos to GIF** with a few clicks
* ⏱️ **Set start time and duration** for trimmed GIFs
* 🎚️ **Adjust FPS** (frames per second) to control smoothness
* 🖼️ **Resize output** with custom width and height
* 🎨 **Configure quality level** for balance between size and clarity
* 🚀 **Optimize output** using `gifsicle`
* 📊 **Track conversion progress** in real-time
* 🌒 **Dark-themed UI** for a modern, user-friendly experience

---

## ⚙️ Prerequisites

* Python 3.7+
* [FFmpeg](https://ffmpeg.org/)
* [gifsicle](https://www.lcdf.org/gifsicle/) (for optimization)

---

## 📦 Installation

1. **Clone the repository**

   ```bash
   git clone https://github.com/omkarbhad/convertstack.git
   cd convertstack
   ```

2. **Install Python dependencies**

   ```bash
   pip install -r requirements.txt
   ```

3. **Install system tools**

   * **macOS (Homebrew)**

     ```bash
     brew install ffmpeg gifsicle
     ```

   * **Ubuntu/Debian**

     ```bash
     sudo apt-get update
     sudo apt-get install ffmpeg gifsicle
     ```

   * **Windows (Chocolatey)**

     ```cmd
     choco install ffmpeg gifsicle
     ```

---

## 🚀 Usage

1. Launch the app:

   ```bash
   python videotogif.py
   ```

2. Select your video file.

3. Customize the conversion:

   * Start time, duration
   * FPS (frames per second)
   * Output size and quality

4. Click **Convert** to generate and save the GIF.

---

## 📚 Requirements

* `PyQt5`
* `ffmpeg-python`

---

## 📝 License

Licensed under the [MIT License](LICENSE).

---

## 🤝 Contributing

Contributions are welcome! Feel free to open issues or submit pull requests to improve the app.

---

## 👨‍💻 Author

**[Omkar Bhad](https://github.com/omkarbhad)**
Built with ❤️ and Python.

