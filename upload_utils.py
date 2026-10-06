import hashlib
from typing import Protocol


class UploadedFileLike(Protocol):
    name: str
    size: int

    def read(self, size: int = -1) -> bytes: ...

    def seek(self, offset: int, whence: int = 0) -> int: ...


def upload_key(uploaded_file: UploadedFileLike) -> str:
    """Return a stable upload identity without copying the whole file."""
    file_id = getattr(uploaded_file, "file_id", None)
    if file_id:
        return f"{uploaded_file.name}:{uploaded_file.size}:{file_id}"

    digest = hashlib.sha256()
    uploaded_file.seek(0)
    for chunk in iter(lambda: uploaded_file.read(1024 * 1024), b""):
        digest.update(chunk)
    uploaded_file.seek(0)
    return f"{uploaded_file.name}:{uploaded_file.size}:{digest.hexdigest()}"
