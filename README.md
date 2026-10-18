# 🚀 LocalFTP - Direct High-Speed File Transmitter (~30GB+ Ready)

**LocalFTP** is a tool built to share large files (10GB, 30GB, 100GB+) directly from your PC to anyone across the Internet or on your local network — **without uploading to Google Drive or any cloud storage**.

---

## 🌟 Why this is better than Google Drive for ~30GB files:
1. **Zero Cloud Waiting**: In Google Drive, you first upload 30GB (wait 1-2 hours), and then the recipient downloads 30GB. With LocalFTP, your PC streams the file directly to their browser/download manager!
2. **Zero Storage Limits**: No 15GB free tier limit. You can share 50GB or 100GB files directly from your hard drive (`C:`, `L:`, etc.).
3. **Resume & Accelerator Support**: Full RFC 7233 HTTP Range support. If the recipient pauses the download or their Wi-Fi flickers, it resumes seamlessly. They can also use **IDM (Internet Download Manager)** or **Aria2** to download with 8-16 parallel connections at maximum ISP speed!
4. **100% Free & Secure**: Powered by Cloudflare Quick Tunnel (`cloudflared`). Encrypted HTTPS link, no router port forwarding or configuration needed. Works even behind CGNAT / Mobile Hotspot / Jio Fiber / Airtel Fiber.

---

## 🛠️ How to Run:

Simply double-click:
```
run.bat
```
Or run in terminal:
```bash
python main.py
```

It will automatically:
1. Launch the local web server.
2. Initialize the secure Cloudflare tunnel to generate your public `trycloudflare.com` HTTPS link.
3. Open the **LocalFTP Control Dashboard** in your default web browser (`http://127.0.0.1:8000`).

---

## 📋 Features:
- **Choose File from PC**: One click opens the native Windows File Picker dialog. Select any 30GB file directly from your disk.
- **Instant Public Link**: Generates an encrypted HTTPS link to send via WhatsApp, Telegram, or Email.
- **Live Transfer Speed & Progress**: Watch real-time download speed (MB/s), bytes transferred, and progress bars as the recipient downloads.
- **Optional Password Protection**: Set an optional security key so only authorized people can download.
- **Mobile QR Code**: Recipient can scan the QR code to download directly on mobile.
- **Classic FTP Server**: Includes an optional built-in FTP server on port `2121` (accessible via FileZilla or Android file managers).
