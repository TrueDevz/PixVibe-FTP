import asyncio
import io
import os
import zipfile
from pathlib import Path
from typing import List, Optional, Set
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, Response, StreamingResponse
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
from app.transfer_manager import (
    detect_file_category,
    format_bytes,
    get_content_type,
    transfer_manager,
)
from app.tunnel import TunnelManager

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
tunnel_manager = TunnelManager(port=DEFAULT_PORT)
active_websockets: Set[WebSocket] = set()

def format_public_link(base_url: Optional[str], token: str) -> Optional[str]:
    if not base_url:
        return None
    url = f"{base_url}/d/{token}"
    if "ngrok" in base_url:
        url += "?ngrok-skip-browser-warning=true"
    return url

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(broadcast_stats_loop())

@app.on_event("shutdown")
def shutdown_event():
    tunnel_manager.stop()
    ftp_service.stop()

# Native file dialogs in thread
def _native_multi_file_picker() -> List[str]:
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        files = filedialog.askopenfilenames(
            title="Select Files to Share (Hold Ctrl or Shift to select multiple)"
        )
        root.destroy()
        return list(files) if files else []
    except Exception as e:
        print(f"Error in file dialog: {e}")
        return []

def _native_folder_picker() -> List[str]:
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        folder = filedialog.askdirectory(title="Select Entire Folder to Share")
        root.destroy()
        if not folder:
            return []
        
        file_list = []
        for root_dir, _, filenames in os.walk(folder):
            for filename in filenames:
                file_list.append(os.path.join(root_dir, filename))
        return file_list
    except Exception as e:
        print(f"Error in folder dialog: {e}")
        return []

# Background WebSocket broadcaster for live dashboard updates
async def broadcast_stats_loop():
    while True:
        if active_websockets:
            stats = transfer_manager.get_stats()
            stats["tunnel"] = tunnel_manager.get_info()
            stats["ftp"] = ftp_service.get_info()
            stats["local_ip"] = get_local_ip()
            stats["port"] = tunnel_manager.port

            base_public = tunnel_manager.public_url
            base_local = f"http://{stats['local_ip']}:{stats['port']}"

            shares_list = []
            for token, share in transfer_manager.shares.items():
                shares_list.append({
                    "token": token,
                    "title": share.title,
                    "files_count": len(share.files),
                    "files": [
                        {
                            "file_id": f.file_id,
                            "file_name": f.file_name,
                            "file_size": f.file_size,
                            "formatted_size": f.formatted_size,
                            "category": f.category,
                        }
                        for f in share.files
                    ],
                    "total_size": share.total_size,
                    "formatted_size": share.formatted_size,
                    "password_protected": share.password is not None,
                    "download_count": share.download_count,
                    "total_bytes_sent_gb": round(share.total_bytes_sent / (1024**3), 2),
                    "local_url": f"{base_local}/d/{token}",
                    "public_url": format_public_link(base_public, token),
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

@app.get("/about", response_class=HTMLResponse)
async def about_view(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="about.html",
        context={},
    )

@app.post("/api/select-files")
async def select_files_dialog():
    paths = await asyncio.to_thread(_native_multi_file_picker)
    if not paths:
        return {"status": "cancelled", "files": []}

    results = []
    total_bytes = 0
    for p_str in paths:
        p = Path(p_str)
        if p.is_file():
            size = p.stat().st_size
            total_bytes += size
            mime = get_content_type(p.name)
            cat = detect_file_category(p.name, mime)
            results.append({
                "file_path": str(p),
                "file_name": p.name,
                "file_size": size,
                "formatted_size": format_bytes(size),
                "category": cat,
            })

    return {
        "status": "selected",
        "files": results,
        "total_files": len(results),
        "total_bytes": total_bytes,
        "formatted_total_size": format_bytes(total_bytes),
    }

@app.post("/api/select-folder")
async def select_folder_dialog():
    paths = await asyncio.to_thread(_native_folder_picker)
    if not paths:
        return {"status": "cancelled", "files": []}

    results = []
    total_bytes = 0
    for p_str in paths:
        p = Path(p_str)
        if p.is_file():
            size = p.stat().st_size
            total_bytes += size
            mime = get_content_type(p.name)
            cat = detect_file_category(p.name, mime)
            results.append({
                "file_path": str(p),
                "file_name": p.name,
                "file_size": size,
                "formatted_size": format_bytes(size),
                "category": cat,
            })

    return {
        "status": "selected",
        "files": results,
        "total_files": len(results),
        "total_bytes": total_bytes,
        "formatted_total_size": format_bytes(total_bytes),
    }

@app.post("/api/share")
async def create_share(data: dict):
    # Support both "file_paths" list or single legacy "file_path"
    file_paths = data.get("file_paths")
    if not file_paths and data.get("file_path"):
        file_paths = [data.get("file_path")]

    password = data.get("password")
    title = data.get("title")
    enable_tunnel = data.get("enable_tunnel", True)

    if not file_paths:
        raise HTTPException(status_code=400, detail="No files provided to share")

    share = transfer_manager.add_share(file_paths, password, title)

    if enable_tunnel and tunnel_manager.status != "connected":
        await asyncio.to_thread(tunnel_manager.start)

    local_ip = get_local_ip()
    port = tunnel_manager.port
    local_url = f"http://{local_ip}:{port}/d/{share.token}"
    public_url = format_public_link(tunnel_manager.public_url, share.token)

    return {
        "token": share.token,
        "title": share.title,
        "files_count": len(share.files),
        "total_size": share.total_size,
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
    settings["tunnel_provider"] = data.get("tunnel_provider", settings.get("tunnel_provider", "ngrok"))
    settings["ngrok_domain"] = data.get("ngrok_domain", settings.get("ngrok_domain", "")).strip()
    settings["cf_tunnel_token"] = data.get("cf_tunnel_token", settings.get("cf_tunnel_token", "")).strip()
    settings["cf_custom_domain"] = data.get("cf_custom_domain", settings.get("cf_custom_domain", "")).strip()
    save_settings(settings)

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
            await websocket.receive_text()
    except WebSocketDisconnect:
        active_websockets.discard(websocket)
    except Exception:
        active_websockets.discard(websocket)

# --- RECIPIENT DOWNLOAD & PREVIEW ROUTES ---

@app.get("/d/{token}", response_class=HTMLResponse)
async def recipient_view(request: Request, token: str, key: Optional[str] = None):
    share = transfer_manager.get_share(token)
    if not share:
        return HTMLResponse(
            "<html><body style='background:#0f172a;color:#f8fafc;font-family:sans-serif;text-align:center;padding:100px;'>"
            "<h1>❌ Link Expired or Not Found</h1><p>The host may have stopped sharing this file.</p></body></html>",
            status_code=404
        )

    is_authenticated = True
    if share.password:
        is_authenticated = (key == share.password)

    return templates.TemplateResponse(
        request=request,
        name="download.html",
        context={
            "token": token,
            "title": share.title,
            "files": share.files,
            "files_count": len(share.files),
            "total_size": share.total_size,
            "formatted_size": share.formatted_size,
            "requires_password": share.password is not None,
            "is_authenticated": is_authenticated,
            "provided_key": key or "",
        },
    )

@app.get("/d/{token}/preview/{file_id}")
async def preview_file(request: Request, token: str, file_id: str, key: Optional[str] = None):
    share = transfer_manager.get_share(token)
    if not share:
        raise HTTPException(status_code=404, detail="File share expired or invalid")

    if share.password and key != share.password:
        raise HTTPException(status_code=401, detail="Invalid password")

    file_entry = share.get_file(file_id)
    if not file_entry or not os.path.isfile(file_entry.file_path):
        raise HTTPException(status_code=404, detail="Source file not found")

    client_ip = request.headers.get("cf-connecting-ip") or (request.client.host if request.client else "unknown")
    return create_streaming_response(request, share, file_entry, client_ip, inline=True)

@app.get("/d/{token}/download/{file_id}")
async def download_single_file(request: Request, token: str, file_id: str, key: Optional[str] = None):
    share = transfer_manager.get_share(token)
    if not share:
        raise HTTPException(status_code=404, detail="File share expired or invalid")

    if share.password and key != share.password:
        raise HTTPException(status_code=401, detail="Invalid password")

    file_entry = share.get_file(file_id)
    if not file_entry or not os.path.isfile(file_entry.file_path):
        raise HTTPException(status_code=404, detail="Source file not found")

    client_ip = request.headers.get("cf-connecting-ip") or (request.client.host if request.client else "unknown")
    return create_streaming_response(request, share, file_entry, client_ip, inline=False)

@app.get("/d/{token}/download")
async def download_default_file(request: Request, token: str, key: Optional[str] = None):
    share = transfer_manager.get_share(token)
    if not share or not share.files:
        raise HTTPException(status_code=404, detail="File share expired or invalid")

    first_file = share.get_first_file()
    return await download_single_file(request, token, first_file.file_id, key)

@app.get("/d/{token}/download-all")
async def download_all_zip(request: Request, token: str, key: Optional[str] = None):
    share = transfer_manager.get_share(token)
    if not share or not share.files:
        raise HTTPException(status_code=404, detail="File share expired or invalid")

    if share.password and key != share.password:
        raise HTTPException(status_code=401, detail="Invalid password")

    # Fast in-memory / streamed zip
    def zip_generator():
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for f_entry in share.files:
                if os.path.isfile(f_entry.file_path):
                    zf.write(f_entry.file_path, arcname=f_entry.file_name)
        buf.seek(0)
        yield buf.getvalue()

    headers = {
        "Content-Disposition": f'attachment; filename="{share.title}.zip"',
        "Content-Type": "application/zip",
    }
    return StreamingResponse(zip_generator(), headers=headers)

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
