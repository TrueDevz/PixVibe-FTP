# 🚀 PixVibe FTP - Direct High-Speed File Transmitter (~30GB+ Ready)

**PixVibe FTP** is a high-speed, direct PC-to-PC transmitter built to share large files and collections (videos, raw footage, datasets, images, documents) across the Internet or on your local network — **without waiting for Google Drive uploads or cloud storage limits**.

---

## 🌟 Key Features:
1. **Standalone Windows Installer (~20 MB)**:
   - Works on **any Windows PC** without installing Python or dependencies.
   - Built with Inno Setup with desktop shortcut, Start Menu shortcut, and uninstaller.
   - Saves settings and link history persistently.
2. **Tunnel Flexibility & 1-Click Binary Auto-Install**:
   - Works with **Ngrok** (custom static domain + auth token), **Cloudflare Quick Tunnel** (zero configuration), or **Cloudflare Custom Tunnel**.
   - If `ngrok.exe` or `cloudflared.exe` is not installed on the destination PC, users can install it with a single click inside **Tunnel Settings** in ~5 seconds.
3. **Multi-File & Folder Bundling**:
   - Select multiple files or entire folders at once.
   - Recipients get a beautiful collection gallery where they can browse and download only the specific files they need (or download all as a ZIP).
4. **Interactive In-Browser Media Previews**:
   - 🎥 **Videos** (MP4, MKV, WebM, MOV): Stream and seek directly inside the browser using HTML5 video with Range requests.
   - 🖼️ **Images** (JPG, PNG, WebP, GIF, SVG): Instant full-screen lightbox preview.
   - 📄 **PDFs & Documents**: Embedded PDF reader and code/text viewer.
   - 🎵 **Audio**: Built-in audio player.
5. **Optional Link Password Protection**:
   - Set an optional passkey when creating a share.
   - Protects sensitive and important files so only authorized users can view or download.
6. **Link History Grouped by Date**:
   - Persistent archive in `history.json` categorized by "Today", "Yesterday", or custom dates.
   - Copy links anytime or delete unwanted records.
7. **RFC 7233 Resume Support**:
   - Pause and resume anytime in browsers, **IDM (Internet Download Manager)**, and FDM.

---

## 📦 Installer Location:
The generated Windows installer is ready at:
```
dist_installer\PixVibeFTP-Setup-v1.0.exe  (Size: ~20.1 MB)
```
Simply copy this file to any Windows computer and double-click to install!

To rebuild the installer anytime:
```
build_installer.bat
```

---

## 🛠️ How to Run from Source:
```bash
run.bat
```
Or:
```bash
python main.py
```

---

## 👨‍💻 Developer & Studio Info:
- **Developer:** Mahesh Babu T
- **Studio:** PixVibe Studios
- **Email:** [devmahi.me@gmail.com](mailto:devmahi.me@gmail.com)
- **About Page:** Accessible at `/about` in the app.
