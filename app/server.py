import asyncio
import io
import os
import zipfile
from pathlib import Path
from typing import List, Optional, Set
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response, StreamingResponse
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
from app.history import history_manager
from app.tunnel import TunnelManager, download_tunnel_tool, get_tools_status
from app.file_picker import pick_files, pick_folder

app = FastAPI(title="PixVibe FTP - Direct High-Speed File Transmitter")

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

@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    fav_path = STATIC_DIR / "favicon.ico"
    if fav_path.exists():
        return FileResponse(str(fav_path), media_type="image/x-icon")
    return Response(status_code=404)

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

_short_url_cache: dict = {}

def shorten_url_sync(long_url: Optional[str]) -> Optional[str]:
    """Shorten public URL into clean, direct redirect without countdown or interstitial pages."""
    if not long_url:
        return None
    if long_url in _short_url_cache:
        return _short_url_cache[long_url]

    if any(h in long_url for h in ["127.0.0.1", "localhost", "192.168.", "10."]):
        return long_url

    import json
    import urllib.parse
    import urllib.request

    # Primary: spoo.me (Instant 302 redirect, no countdown, no interstitial page)
    try:
        data = urllib.parse.urlencode({"url": long_url}).encode("utf-8")
        req = urllib.request.Request(
            "https://spoo.me/",
            data=data,
            headers={"Accept": "application/json", "User-Agent": "PixVibeFTP/1.0"}
        )
        with urllib.request.urlopen(req, timeout=3.5) as resp:
            res = json.loads(resp.read().decode("utf-8"))
            short = res.get("short_url", "").replace("http://", "https://").strip()
            if short.startswith("https://"):
                _short_url_cache[long_url] = short
                return short
    except Exception:
        pass

    # Secondary fallback: cleanuri.com
    try:
        data = urllib.parse.urlencode({"url": long_url}).encode("utf-8")
        req = urllib.request.Request(
            "https://cleanuri.com/api/v1/shorten",
            data=data,
            headers={"User-Agent": "PixVibeFTP/1.0"}
        )
        with urllib.request.urlopen(req, timeout=3.5) as resp:
            res = json.loads(resp.read().decode("utf-8"))
            short = res.get("result_url", "").strip()
            if short.startswith("https://"):
                _short_url_cache[long_url] = short
                return short
    except Exception:
        pass

    return long_url

async def _async_shorten_share(share, pub_url: str):
    try:
        short = await asyncio.to_thread(shorten_url_sync, pub_url)
        if short:
            share.short_url = short
            history_manager.update_urls(share.token, public_url=pub_url, short_url=short)
    except Exception:
        pass

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(broadcast_stats_loop())

@app.on_event("shutdown")
def shutdown_event():
    tunnel_manager.stop()
    ftp_service.stop()



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
                pub_url = format_public_link(base_public, token)
                if pub_url and not share.short_url:
                    asyncio.create_task(_async_shorten_share(share, pub_url))

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
                    "public_url": pub_url,
                    "short_url": share.short_url or pub_url,
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
    paths = await asyncio.to_thread(pick_files)
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
    paths = await asyncio.to_thread(pick_folder)
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

    # Automatically generate short URL via TinyURL if public URL is available
    short_url = None
    if public_url:
        short_url = await asyncio.to_thread(shorten_url_sync, public_url)
    share.short_url = short_url or public_url

    # Record in persistent history
    files_summary = [
        {"name": f.file_name, "size": f.formatted_size, "category": f.category}
        for f in share.files
    ]
    history_manager.record_share(
        token=share.token,
        title=share.title,
        files_info=files_summary,
        total_size_str=share.formatted_size,
        total_bytes=share.total_size,
        password_protected=share.password is not None,
        public_url=public_url,
        local_url=local_url,
        short_url=share.short_url,
    )

    return {
        "token": share.token,
        "title": share.title,
        "files_count": len(share.files),
        "total_size": share.total_size,
        "formatted_size": share.formatted_size,
        "local_url": local_url,
        "public_url": public_url,
        "short_url": share.short_url or public_url,
    }

@app.post("/api/shorten")
async def shorten_url_endpoint(data: dict):
    url = data.get("url", "").strip()
    if not url:
        return {"short_url": ""}
    res = await asyncio.to_thread(shorten_url_sync, url)
    return {"short_url": res or url}

@app.delete("/api/shares/{token}")
async def delete_share(token: str):
    removed = transfer_manager.remove_share(token)
    if not removed:
        raise HTTPException(status_code=404, detail="Share not found")
    history_manager.mark_stopped(token)
    return {"status": "success", "message": "Share stopped"}

@app.get("/api/history")
async def get_history():
    active_tokens = set(transfer_manager.shares.keys())
    return history_manager.get_grouped_history(active_tokens=active_tokens)

@app.delete("/api/history/{token}")
async def delete_history_item(token: str):
    success = history_manager.delete_entry(token)
    if not success:
        raise HTTPException(status_code=404, detail="History entry not found")
    return {"status": "success"}

@app.delete("/api/history")
async def clear_history():
    history_manager.clear_all()
    return {"status": "success", "message": "History cleared"}

@app.post("/api/tunnel/toggle")
async def toggle_tunnel():
    if tunnel_manager.status in ["connected", "connecting"]:
        await asyncio.to_thread(tunnel_manager.stop)
        return {"status": "stopped", "tunnel": tunnel_manager.get_info()}
    else:
        success = await asyncio.to_thread(tunnel_manager.start)
        return {"status": "started" if success else "failed", "tunnel": tunnel_manager.get_info()}

@app.get("/api/tunnel/tools")
async def get_tunnel_tools():
    return get_tools_status()

@app.post("/api/tunnel/download-tool")
async def download_tool_endpoint(data: dict):
    tool = data.get("tool", "")
    if tool not in ["ngrok", "cloudflared"]:
        raise HTTPException(status_code=400, detail="Invalid tool name")
    res = await asyncio.to_thread(download_tunnel_tool, tool)
    return res

@app.get("/api/settings")
async def get_settings():
    return load_settings()

@app.post("/api/settings")
async def update_settings(data: dict):
    settings = load_settings()
    settings["tunnel_provider"] = data.get("tunnel_provider", settings.get("tunnel_provider", "ngrok"))
    
    ngrok_dom = data.get("ngrok_domain", "").strip()
    if ngrok_dom:
        ngrok_dom = ngrok_dom.replace("https://", "").replace("http://", "").strip().rstrip("/")
    settings["ngrok_domain"] = ngrok_dom
    settings["ngrok_authtoken"] = data.get("ngrok_authtoken", "").strip()

    settings["cf_tunnel_token"] = data.get("cf_tunnel_token", "").strip()
    settings["cf_custom_domain"] = data.get("cf_custom_domain", "").strip()
    save_settings(settings)

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

@app.post("/api/server/shutdown")
async def shutdown_server():
    def _exit_later():
        time.sleep(0.8)
        tunnel_manager.stop()
        ftp_service.stop()
        os._exit(0)

    import threading
    import time
    threading.Thread(target=_exit_later, daemon=True).start()
    return {"status": "shutting_down", "message": "Server stopped and port released successfully."}

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
