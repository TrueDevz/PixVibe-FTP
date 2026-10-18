import asyncio
import io
import os
from pathlib import Path
from typing import Optional, Set
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import qrcode

from app.config import (
    DEFAULT_PORT,
    STATIC_DIR,
    TEMPLATES_DIR,
    get_local_ip,
    load_settings,
    save_settings,
)
from app.ftp_server import ftp_service
from app.streamer import create_streaming_response
from app.transfer_manager import transfer_manager
from app.tunnel import CloudflareTunnelManager

app = FastAPI(title="LocalFTP - Direct High-Speed File Transfer")

# Enable CORS for local network and tunnel access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static and Templates
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# State
tunnel_manager = CloudflareTunnelManager(port=DEFAULT_PORT)
active_websockets: Set[WebSocket] = set()

@app.on_event("startup")
async def startup_event():
    # Start background websocket broadcast loop
    asyncio.create_task(broadcast_stats_loop())

@app.on_event("shutdown")
def shutdown_event():
    tunnel_manager.stop()
    ftp_service.stop()

# Native file dialog in thread
def _native_file_picker() -> Optional[str]:
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        file_path = filedialog.askopenfilename(
            title="Select File to Share (any size, up to 100+ GB)"
        )
        root.destroy()
        return file_path if file_path else None
    except Exception as e:
        print(f"Error in file dialog: {e}")
        return None

# Background WebSocket broadcaster for live dashboard updates
async def broadcast_stats_loop():
    while True:
        if active_websockets:
            stats = transfer_manager.get_stats()
            stats["tunnel"] = tunnel_manager.get_info()
            stats["ftp"] = ftp_service.get_info()
            stats["local_ip"] = get_local_ip()
            stats["port"] = tunnel_manager.port

            # Build list of active shares with their links
            base_public = tunnel_manager.public_url
            base_local = f"http://{stats['local_ip']}:{stats['port']}"

            shares_list = []
            for token, share in transfer_manager.shares.items():
                shares_list.append({
                    "token": token,
                    "file_name": share.file_name,
                    "file_path": share.file_path,
                    "file_size": share.file_size,
                    "formatted_size": share.formatted_size,
                    "password_protected": share.password is not None,
                    "download_count": share.download_count,
                    "total_bytes_sent_gb": round(share.total_bytes_sent / (1024**3), 2),
                    "local_url": f"{base_local}/d/{token}",
                    "public_url": f"{base_public}/d/{token}" if base_public else None,
                })
            stats["shares"] = shares_list

            disconnected = set()
            for ws in active_websockets:
                try:
                    await ws.send_json(stats)
                except Exception:
                    disconnected.add(ws)
            for ws in disconnected:
                active_websockets.discard(ws)
        await asyncio.sleep(0.5)

# --- SENDER DASHBOARD ROUTES ---

@app.get("/", response_class=HTMLResponse)
async def dashboard_view(request: Request):
    local_ip = get_local_ip()
    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={
            "local_ip": local_ip,
            "port": tunnel_manager.port,
            "tunnel_info": tunnel_manager.get_info(),
        },
    )

@app.post("/api/select-file")
async def select_file_dialog():
    path = await asyncio.to_thread(_native_file_picker)
    if not path:
        return {"status": "cancelled"}
    
    p = Path(path)
    if not p.is_file():
        raise HTTPException(status_code=400, detail="Invalid file selected")

    size = p.stat().st_size
    formatted_size = f"{size / (1024**3):.2f} GB" if size >= 1024**3 else f"{size / (1024**2):.2f} MB"

    return {
        "status": "selected",
        "file_path": str(p),
        "file_name": p.name,
        "file_size": size,
        "formatted_size": formatted_size,
    }

@app.post("/api/share")
async def create_share(data: dict):
    file_path = data.get("file_path")
    password = data.get("password")
    enable_tunnel = data.get("enable_tunnel", True)

    if not file_path or not os.path.isfile(file_path):
        raise HTTPException(status_code=400, detail="File does not exist")

    share = transfer_manager.add_share(file_path, password)

    # Start tunnel if requested and not running
    if enable_tunnel and tunnel_manager.status != "connected":
        await asyncio.to_thread(tunnel_manager.start)

    local_ip = get_local_ip()
    port = tunnel_manager.port
    local_url = f"http://{local_ip}:{port}/d/{share.token}"
    public_url = f"{tunnel_manager.public_url}/d/{share.token}" if tunnel_manager.public_url else None

    return {
        "token": share.token,
        "file_name": share.file_name,
        "file_size": share.file_size,
        "formatted_size": share.formatted_size,
        "local_url": local_url,
        "public_url": public_url,
    }

@app.delete("/api/shares/{token}")
async def delete_share(token: str):
    removed = transfer_manager.remove_share(token)
    if not removed:
        raise HTTPException(status_code=404, detail="Share not found")
    return {"status": "success", "message": "Share stopped"}

@app.post("/api/tunnel/toggle")
async def toggle_tunnel():
    if tunnel_manager.status in ["connected", "connecting"]:
        await asyncio.to_thread(tunnel_manager.stop)
        return {"status": "stopped", "tunnel": tunnel_manager.get_info()}
    else:
        success = await asyncio.to_thread(tunnel_manager.start)
        return {"status": "started" if success else "failed", "tunnel": tunnel_manager.get_info()}

@app.get("/api/settings")
async def get_settings():
    return load_settings()

@app.post("/api/settings")
async def update_settings(data: dict):
    settings = load_settings()
    settings["tunnel_type"] = data.get("tunnel_type", settings.get("tunnel_type", "quick"))
    settings["tunnel_token"] = data.get("tunnel_token", settings.get("tunnel_token", "")).strip()
    settings["custom_domain"] = data.get("custom_domain", settings.get("custom_domain", "")).strip()
    save_settings(settings)

    # If tunnel is active, restart with new settings
    if tunnel_manager.status in ["connected", "connecting"]:
        await asyncio.to_thread(tunnel_manager.stop)
        await asyncio.to_thread(tunnel_manager.start)

    return {"status": "saved", "settings": settings, "tunnel": tunnel_manager.get_info()}

@app.post("/api/ftp/toggle")
async def toggle_ftp():
    if ftp_service.is_running:
        ftp_service.stop()
    else:
        ftp_service.start()
    return {"status": "success", "ftp": ftp_service.get_info()}

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    active_websockets.add(websocket)
    try:
        while True:
            # Keep socket alive
            await websocket.receive_text()
    except WebSocketDisconnect:
        active_websockets.discard(websocket)
    except Exception:
        active_websockets.discard(websocket)

# --- RECIPIENT DOWNLOAD ROUTES ---

@app.get("/d/{token}", response_class=HTMLResponse)
async def recipient_view(request: Request, token: str, key: Optional[str] = None):
    share = transfer_manager.get_share(token)
    if not share:
        return HTMLResponse(
            "<html><body style='background:#0f172a;color:#f8fafc;font-family:sans-serif;text-align:center;padding:100px;'>"
            "<h1>❌ Link Expired or Not Found</h1><p>The host may have stopped sharing this file.</p></body></html>",
            status_code=404
        )

    # Check password protection
    is_authenticated = True
    if share.password:
        is_authenticated = (key == share.password)

    client_ip = request.client.host if request.client else "unknown"

    return templates.TemplateResponse(
        request=request,
        name="download.html",
        context={
            "token": token,
            "file_name": share.file_name,
            "file_size": share.file_size,
            "formatted_size": share.formatted_size,
            "requires_password": share.password is not None,
            "is_authenticated": is_authenticated,
            "provided_key": key or "",
        },
    )

@app.get("/d/{token}/download")
async def download_file(request: Request, token: str, key: Optional[str] = None):
    share = transfer_manager.get_share(token)
    if not share:
        raise HTTPException(status_code=404, detail="File share expired or invalid")

    # Password verification
    if share.password and key != share.password:
        raise HTTPException(status_code=401, detail="Invalid password")

    if not os.path.isfile(share.file_path):
        raise HTTPException(status_code=404, detail="Source file not found on host machine")

    client_ip = request.headers.get("cf-connecting-ip") or (request.client.host if request.client else "unknown")
    return create_streaming_response(request, share, client_ip)

@app.get("/d/{token}/qr")
async def generate_qr(token: str, url: str):
    qr = qrcode.QRCode(box_size=5, border=2)
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#0f172a", back_color="#ffffff")

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return Response(content=buf.getvalue(), media_type="image/png")
