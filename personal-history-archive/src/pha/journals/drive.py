"""Google Drive access with the read-only scope.

Only ``drive.readonly`` is ever requested, and a stored token carrying any
other scope is refused. Files are downloaded into the local cache; nothing in
Drive is modified.
"""

from __future__ import annotations

import io
import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

log = logging.getLogger("pha.drive")

SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]
FOLDER_MIME = "application/vnd.google-apps.folder"
SHORTCUT_MIME = "application/vnd.google-apps.shortcut"
PDF_MIME = "application/pdf"
FIELDS = (
    "nextPageToken, files(id, name, mimeType, md5Checksum, size, createdTime, "
    "modifiedTime, webViewLink, shortcutDetails)"
)


@dataclass
class DriveFile:
    id: str
    name: str
    folder_path: list[str]
    md5: str | None
    size: int | None
    created_time: str | None
    modified_time: str | None
    web_view_link: str

    @property
    def display_path(self) -> str:
        return "/".join([*self.folder_path, self.name])


def get_service(client_secret_file: Path, token_file: Path) -> Any:
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build
    except ImportError as exc:  # pragma: no cover - optional extra
        raise RuntimeError("Google Drive access needs the 'drive' extra: pip install -e '.[drive]'") from exc

    creds = None
    if token_file.exists():
        # Check the stored scopes directly: passing SCOPES to the loader would
        # silently replace them.
        granted = set(json.loads(token_file.read_text()).get("scopes") or [])
        if granted != set(SCOPES):
            raise RuntimeError(
                f"Stored token {token_file} has scopes {sorted(granted)}; only drive.readonly "
                "is allowed. Delete the token file and authenticate again."
            )
        creds = Credentials.from_authorized_user_file(str(token_file), SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not client_secret_file.exists():
                raise RuntimeError(
                    f"OAuth client file not found: {client_secret_file}. See README "
                    "'Google Drive setup'."
                )
            flow = InstalledAppFlow.from_client_secrets_file(str(client_secret_file), SCOPES)
            creds = flow.run_local_server(port=0, open_browser=True)
        token_file.parent.mkdir(parents=True, exist_ok=True)
        token_file.write_text(creds.to_json())
        os.chmod(token_file, 0o600)
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def _list(service: Any, query: str) -> Iterator[dict[str, Any]]:
    token = None
    while True:
        resp = (
            service.files()
            .list(
                q=query,
                fields=FIELDS,
                pageSize=200,
                pageToken=token,
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
            )
            .execute()
        )
        yield from resp.get("files", [])
        token = resp.get("nextPageToken")
        if not token:
            return


def find_folders(service: Any, name: str) -> list[dict[str, Any]]:
    escaped = name.replace("\\", "\\\\").replace("'", "\\'")
    return list(_list(service, f"name = '{escaped}' and mimeType = '{FOLDER_MIME}' and trashed = false"))


def walk_pdfs(service: Any, folder_id: str, path: list[str] | None = None, _seen: set[str] | None = None) -> Iterator[DriveFile]:
    """Recursively yield PDFs under a folder, following shortcuts."""
    path = path or []
    seen = _seen if _seen is not None else set()
    if folder_id in seen:
        return
    seen.add(folder_id)
    for f in _list(service, f"'{folder_id}' in parents and trashed = false"):
        mime, fid = f["mimeType"], f["id"]
        if mime == SHORTCUT_MIME:
            details = f.get("shortcutDetails") or {}
            mime, fid = details.get("targetMimeType"), details.get("targetId")
            if fid and mime == PDF_MIME:
                target = service.files().get(
                    fileId=fid, fields="id, name, md5Checksum, size, createdTime, modifiedTime, webViewLink",
                    supportsAllDrives=True,
                ).execute()
                f = {**target, "mimeType": PDF_MIME}
        if mime == FOLDER_MIME and fid:
            yield from walk_pdfs(service, fid, [*path, f["name"]], seen)
        elif mime == PDF_MIME or f["name"].lower().endswith(".pdf"):
            yield DriveFile(
                id=f["id"],
                name=f["name"],
                folder_path=path,
                md5=f.get("md5Checksum"),
                size=int(f["size"]) if f.get("size") else None,
                created_time=f.get("createdTime"),
                modified_time=f.get("modifiedTime"),
                web_view_link=f.get("webViewLink") or f"https://drive.google.com/file/d/{f['id']}/view",
            )


def download(service: Any, file_id: str, dest: Path) -> Path:
    from googleapiclient.http import MediaIoBaseDownload

    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".partial")
    request = service.files().get_media(fileId=file_id, supportsAllDrives=True)
    with io.FileIO(tmp, "wb") as fh:
        downloader = MediaIoBaseDownload(fh, request, chunksize=8 * 1024 * 1024)
        done = False
        while not done:
            _, done = downloader.next_chunk()
    tmp.replace(dest)
    return dest
