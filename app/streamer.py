import os
import re
from typing import AsyncGenerator
from starlette.requests import Request
from starlette.responses import StreamingResponse, Response
from app.config import CHUNK_SIZE
from app.transfer_manager import ShareItem, transfer_manager

def parse_range_header(range_header: str, file_size: int):
    """
    Parses HTTP Range header e.g. 'bytes=100-200' or 'bytes=500-'
    Returns (start_byte, end_byte)
    """
    match = re.match(r"^bytes=(\d+)-(\d+)?$", range_header.strip())
    if not match:
        return 0, file_size - 1

    start_str, end_str = match.groups()
    start = int(start_str) if start_str else 0
    end = int(end_str) if end_str else file_size - 1

    # Clamp ranges to file bounds
    start = max(0, min(start, file_size - 1))
    end = max(start, min(end, file_size - 1))
    return start, end

async def file_chunk_generator(
    file_path: str,
    start: int,
    end: int,
    transfer_id: str,
    chunk_size: int = CHUNK_SIZE
) -> AsyncGenerator[bytes, None]:
    """
    Streams chunks of a file directly from disk, reporting progress to transfer_manager.
    """
    bytes_remaining = (end - start) + 1

    try:
        with open(file_path, "rb") as f:
            f.seek(start)
            while bytes_remaining > 0:
                current_chunk_size = min(chunk_size, bytes_remaining)
                data = f.read(current_chunk_size)
                if not data:
                    break
                bytes_sent = len(data)
                bytes_remaining -= bytes_sent
                transfer_manager.update_transfer(transfer_id, bytes_sent)
                yield data
    finally:
        transfer_manager.end_transfer(transfer_id)

def create_streaming_response(request: Request, share: ShareItem, client_ip: str) -> Response:
    """
    Builds a high-speed HTTP response with RFC 7233 Range support for resume capability.
    """
    file_size = share.file_size
    range_header = request.headers.get("Range")

    headers = {
        "Accept-Ranges": "bytes",
        "Content-Disposition": f'attachment; filename="{share.file_name}"',
        "Content-Type": "application/octet-stream",
        "Cache-Control": "no-cache",
    }

    if range_header:
        start, end = parse_range_header(range_header, file_size)
        content_length = (end - start) + 1
        headers["Content-Range"] = f"bytes {start}-{end}/{file_size}"
        headers["Content-Length"] = str(content_length)

        transfer = transfer_manager.start_transfer(
            token=share.token,
            client_ip=client_ip,
            start_byte=start,
            end_byte=end
        )

        return StreamingResponse(
            file_chunk_generator(share.file_path, start, end, transfer.transfer_id),
            status_code=206,
            headers=headers,
        )
    else:
        # Full file download
        headers["Content-Length"] = str(file_size)
        transfer = transfer_manager.start_transfer(
            token=share.token,
            client_ip=client_ip,
            start_byte=0,
            end_byte=file_size - 1
        )

        return StreamingResponse(
            file_chunk_generator(share.file_path, 0, file_size - 1, transfer.transfer_id),
            status_code=200,
            headers=headers,
        )
