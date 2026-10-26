"""
Tofu (2026-10-25, https://github.com/tofu-gallery/bracket): team and tournament logos kept in the database.

Bracket saves an uploaded logo as a file under static/ on the server's disk. Tofu's hosting keeps no disk across a
restart or a deploy, so the upload routes also save each logo in the table tofu_logos, and `serve_logo` answers
<API_PREFIX>/static/<folder>/<file> from the file when this server has it, else from that table. The table is created by
the start's schema step (`create_logo_table`, called by bracket/utils/tofu_schema.py). The upload routes refuse a file
over 5 MB (`read_logo`). A logo's row is deleted as soon as nothing names it any more: right after a team's or
tournament's logo is replaced or removed, and after a team or tournament is deleted (`delete_logo`); anything those miss
is deleted at the next start (`delete_unused_logos`). See TOFU.md.
"""

import re
from pathlib import Path

import aiofiles.os
from sqlalchemy import Connection, text
from starlette.datastructures import UploadFile
from starlette.exceptions import HTTPException
from starlette.responses import FileResponse, Response

from bracket.database import database

# The folders under static/ the upload routes write to, and the table and column that name a logo in each.
LOGO_FOLDERS = {"team-logos": "teams", "tournament-logos": "tournaments"}
# The upload routes name each logo `<uuid4><extension>`, with the extension one of these.
LOGO_FILENAME = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\.(png|jpg|jpeg)$")
MEDIA_TYPES = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg"}
# The largest logo the server takes: 5 MB, the limit the frontend's upload box already has
# (frontend/src/components/utils/file_upload.tsx).
MAX_LOGO_BYTES = 5 * 1024**2


def create_logo_table(connection: Connection) -> None:
    """On the schema step's connection, inside its transaction and its lock (bracket/utils/tofu_schema.py)."""
    connection.execute(
        text(
            "CREATE TABLE IF NOT EXISTS tofu_logos ("
            " folder TEXT NOT NULL,"
            " filename TEXT NOT NULL,"
            " content BYTEA NOT NULL,"
            " created TIMESTAMPTZ NOT NULL DEFAULT now(),"
            " PRIMARY KEY (folder, filename))"
        )
    )


async def read_logo(file: UploadFile) -> bytes:
    """An uploaded logo's bytes. A file over MAX_LOGO_BYTES is refused (413) before anything is written or saved."""
    content = await file.read(MAX_LOGO_BYTES + 1)
    if len(content) > MAX_LOGO_BYTES:
        raise HTTPException(413, "The logo is larger than 5 MB")
    return content


async def save_logo(folder: str, filename: str, content: bytes) -> None:
    await database.execute(
        "INSERT INTO tofu_logos (folder, filename, content) VALUES (:folder, :filename, :content)"
        " ON CONFLICT (folder, filename) DO UPDATE SET content = EXCLUDED.content",
        values={"folder": folder, "filename": filename, "content": content},
    )


async def delete_logo(folder: str, filename: str | None) -> None:
    """
    One logo's row, once no team or tournament names it: the logo a team or tournament just stopped naming (replaced or
    removed), or the logo of a team or tournament just deleted.
    """
    if filename is None:
        return
    await database.execute(
        "DELETE FROM tofu_logos AS l WHERE l.folder = :folder AND l.filename = :filename"
        f" AND NOT EXISTS (SELECT 1 FROM {LOGO_FOLDERS[folder]} AS t WHERE t.logo_path = l.filename)",
        values={"folder": folder, "filename": filename},
    )


async def delete_unused_logos() -> None:
    """
    Logos no team or tournament names, which `delete_logo` missed (for example a server stopped between saving a new
    logo and naming it). An hour's grace keeps a logo whose upload is still being recorded.
    """
    for folder, table in LOGO_FOLDERS.items():
        await database.execute(
            "DELETE FROM tofu_logos AS l WHERE l.folder = :folder"
            " AND l.created < now() - interval '1 hour'"
            f" AND NOT EXISTS (SELECT 1 FROM {table} AS t WHERE t.logo_path = l.filename)",
            values={"folder": folder},
        )


async def serve_logo(folder: str, filename: str) -> Response:
    if folder not in LOGO_FOLDERS or not LOGO_FILENAME.match(filename):
        raise HTTPException(404, "Not Found")

    path = Path("static") / folder / filename
    if await aiofiles.os.path.isfile(path):
        return FileResponse(path)

    content = await database.fetch_val(
        "SELECT content FROM tofu_logos WHERE folder = :folder AND filename = :filename",
        values={"folder": folder, "filename": filename},
    )
    if content is None:
        raise HTTPException(404, "Not Found")

    # A logo's file name is new at every upload, so its content never changes.
    return Response(
        bytes(content),
        media_type=MEDIA_TYPES[filename.rsplit(".", 1)[1]],
        headers={"Cache-Control": "public, max-age=86400"},
    )
