from dotenv import load_dotenv

load_dotenv()

import os
import shutil
import uuid
from pathlib import Path
from functools import lru_cache

from publishing import (
    edit_bundle_directory,
    edit_bundle_keys,
    is_edit_bundle_key,
    sibling_key,
)

LOCAL_UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", "uploads"))
LOCAL_RESULTS_DIR = Path(os.getenv("RESULTS_DIR", "results"))
LOCAL_TEMP_DIR = Path(os.getenv("TEMP_DIR", ".tmp"))


class LocalStorage:
    backend = "local"

    def __init__(self):
        LOCAL_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        LOCAL_RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        LOCAL_TEMP_DIR.mkdir(parents=True, exist_ok=True)

    def save_upload_file(self, local_file_path, key, content_type=None):
        target = (LOCAL_UPLOAD_DIR / key).resolve()
        target.parent.mkdir(parents=True, exist_ok=True)

        shutil.move(
            str(local_file_path),
            str(target),
        )

        return str(target)

    def save_text(self, key, text, content_type=None):
        target = (LOCAL_RESULTS_DIR / key).resolve()
        target.parent.mkdir(parents=True, exist_ok=True)

        target.write_text(
            text,
            encoding="utf-8",
        )

        return str(target)

    def save_bytes(self, key, data, content_type=None):
        target = (LOCAL_RESULTS_DIR / key).resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return str(target)

    def save_local_file(self, local_file_path, key, content_type=None):
        return self.save_bytes(
            key,
            Path(local_file_path).read_bytes(),
            content_type=content_type,
        )

    def get_local_audio_path(self, storage_key):
        return Path(storage_key)

    def read_upload_bytes(self, storage_key):
        return Path(storage_key).read_bytes()

    def get_result_signed_url(self, result_storage_key, expires_in=3600):
        return None

    def read_result_text(self, result_storage_key):
        return Path(result_storage_key).read_text(encoding="utf-8")

    def read_result_bytes(self, result_storage_key):
        return Path(result_storage_key).read_bytes()

    def result_sidecar_key(self, result_storage_key, filename):
        name = Path(filename).name
        if result_storage_key:
            parent = Path(result_storage_key).parent
            if str(parent) not in {".", ""}:
                return str(parent / name)
        return str(LOCAL_RESULTS_DIR / name)

    def result_exists(self, key):
        if not key:
            return False
        path = Path(key)
        return path.is_file()

    def delete_upload(self, storage_key):
        if not storage_key:
            return
        path = Path(storage_key)
        if path.exists():
            path.unlink()
        work_dir = path.parent / f"bp_{path.stem}"
        if work_dir.is_dir():
            shutil.rmtree(work_dir, ignore_errors=True)

    def delete_edited(self, job_id, result_storage_key=None):
        names = (
            f"{job_id}.edits.json",
            f"{job_id}.edited.musicxml",
            f"{job_id}.edited.mid",
        )
        parent = LOCAL_RESULTS_DIR
        if result_storage_key:
            parent = Path(result_storage_key).parent
        for name in names:
            (parent / name).unlink(missing_ok=True)

    def gc_edit_bundle(self, edited_key, job_id, keep_key=None):
        if not edited_key or edited_key == keep_key:
            return
        if is_edit_bundle_key(edited_key, job_id):
            directory = edit_bundle_directory(edited_key, job_id)
            if directory:
                shutil.rmtree(directory, ignore_errors=True)
            return
        name = Path(edited_key).name
        if name.endswith(".edited.musicxml") or name.endswith(".edits.json"):
            self.delete_edited(job_id, edited_key)

    def delete_result(self, result_storage_key, job_id=None):
        if result_storage_key:
            path = Path(result_storage_key)
            if path.exists():
                path.unlink()
            if path.parent.exists() and job_id:
                for sidecar in path.parent.glob(f"{job_id}.*"):
                    sidecar.unlink(missing_ok=True)
        if job_id:
            shutil.rmtree(LOCAL_RESULTS_DIR / f"{job_id}.attempts", ignore_errors=True)
            shutil.rmtree(LOCAL_RESULTS_DIR / f"{job_id}.edits", ignore_errors=True)
            if result_storage_key:
                root = Path(result_storage_key).parent
                if root.name and (
                    root.parent.name == f"{job_id}.attempts"
                    or root.parent.name == f"{job_id}.edits"
                ):
                    root = root.parent.parent
                shutil.rmtree(root / f"{job_id}.attempts", ignore_errors=True)
                shutil.rmtree(root / f"{job_id}.edits", ignore_errors=True)


class SupabaseStorage:
    backend = "supabase"

    def __init__(self):
        try:
            from supabase import create_client
        except ImportError as exc:
            raise RuntimeError(
                "The supabase package is not installed. "
                "Run: pip install supabase"
            ) from exc

        self.url = os.getenv("SUPABASE_URL")
        self.service_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

        if not self.url or not self.service_key:
            raise RuntimeError(
                "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set "
                "to use SupabaseStorage."
            )

        self.client = create_client(
            self.url,
            self.service_key,
        )

        self.audio_bucket = os.getenv(
            "SUPABASE_BUCKET_AUDIO",
            "audio-uploads",
        )

        self.results_bucket = os.getenv(
            "SUPABASE_BUCKET_RESULTS",
            "musicxml-exports",
        )

        LOCAL_TEMP_DIR.mkdir(parents=True, exist_ok=True)

    def _temp_file_for_key(self, key):
        safe = str(key).replace("/", "__").replace("\\", "__")
        return LOCAL_TEMP_DIR / f"{uuid.uuid4().hex}-{safe}"

    def _bucket(self, bucket_name):
        return self.client.storage.from_(bucket_name)

    def save_upload_file(self, local_file_path, key, content_type=None):
        options = {
            "upsert": "true",
        }

        if content_type:
            options["content-type"] = content_type

        self._bucket(self.audio_bucket).upload(
            key,
            str(local_file_path),
            options,
        )

        Path(local_file_path).unlink(missing_ok=True)

        return key

    def save_text(self, key, text, content_type=None):
        temp_file = self._temp_file_for_key(key)

        temp_file.write_text(
            text,
            encoding="utf-8",
        )

        options = {
            "upsert": "true",
        }

        if content_type:
            options["content-type"] = content_type

        try:
            self._bucket(self.results_bucket).upload(
                key,
                str(temp_file),
                options,
            )
        finally:
            temp_file.unlink(missing_ok=True)

        return key

    def save_bytes(self, key, data, content_type=None):
        temp_file = self._temp_file_for_key(key)
        temp_file.write_bytes(data)
        options = {"upsert": "true"}
        if content_type:
            options["content-type"] = content_type
        try:
            self._bucket(self.results_bucket).upload(
                key,
                str(temp_file),
                options,
            )
        finally:
            temp_file.unlink(missing_ok=True)
        return key

    def save_local_file(self, local_file_path, key, content_type=None):
        return self.save_bytes(
            key,
            Path(local_file_path).read_bytes(),
            content_type=content_type,
        )

    def get_local_audio_path(self, storage_key):
        local_path = LOCAL_TEMP_DIR / f"audio-{Path(storage_key).name}"

        data = self._bucket(self.audio_bucket).download(storage_key)

        local_path.write_bytes(data)

        return local_path

    def read_upload_bytes(self, storage_key):
        data = self._bucket(self.audio_bucket).download(storage_key)
        if isinstance(data, bytes):
            return data
        return bytes(data)

    def get_result_signed_url(self, result_storage_key, expires_in=3600):
        data = self._bucket(self.results_bucket).create_signed_url(
            result_storage_key,
            expires_in,
        )

        if isinstance(data, str):
            return data

        return (
            data.get("signedURL")
            or data.get("signed_url")
            or data.get("signedUrl")
        )

    def read_result_text(self, result_storage_key):
        data = self._bucket(self.results_bucket).download(result_storage_key)

        if isinstance(data, bytes):
            return data.decode("utf-8")

        return str(data)

    def read_result_bytes(self, result_storage_key):
        data = self._bucket(self.results_bucket).download(result_storage_key)
        if isinstance(data, bytes):
            return data
        return bytes(data)

    def result_sidecar_key(self, result_storage_key, filename):
        name = Path(filename).name
        sibling = sibling_key(result_storage_key, name)
        return sibling or name

    def result_exists(self, key):
        if not key:
            return False
        try:
            self.read_result_bytes(key)
            return True
        except Exception:
            return False

    def delete_upload(self, storage_key):
        if not storage_key:
            return
        try:
            self._bucket(self.audio_bucket).remove([storage_key])
        except Exception:
            return

    def delete_result(self, result_storage_key, job_id=None):
        keys = []
        if result_storage_key:
            keys.append(result_storage_key)
            parent = str(Path(result_storage_key).parent).replace("\\", "/")
            if job_id and parent not in {".", ""}:
                for name in (
                    f"{job_id}.musicxml",
                    f"{job_id}.raw.mid",
                    f"{job_id}.validated.mid",
                    f"{job_id}.score.mid",
                    f"{job_id}.manifest.json",
                ):
                    keys.append(f"{parent}/{name}")
        if job_id:
            keys.extend(
                [
                    f"{job_id}.musicxml",
                    f"{job_id}.raw.mid",
                    f"{job_id}.validated.mid",
                    f"{job_id}.score.mid",
                    f"{job_id}.edits.json",
                    f"{job_id}.edited.musicxml",
                    f"{job_id}.edited.mid",
                ]
            )
        if not keys:
            return
        try:
            self._bucket(self.results_bucket).remove(keys)
        except Exception:
            return

    def delete_edited(self, job_id, result_storage_key=None):
        keys = [
            f"{job_id}.edits.json",
            f"{job_id}.edited.musicxml",
            f"{job_id}.edited.mid",
        ]
        if result_storage_key:
            parent = str(Path(result_storage_key).parent).replace("\\", "/")
            if parent not in {".", ""}:
                keys.extend(f"{parent}/{name}" for name in list(keys))
        try:
            self._bucket(self.results_bucket).remove(keys)
        except Exception:
            return

    def gc_edit_bundle(self, edited_key, job_id, keep_key=None):
        if not edited_key or edited_key == keep_key:
            return
        if is_edit_bundle_key(edited_key, job_id):
            directory = edit_bundle_directory(edited_key, job_id)
            bundle_id = Path(directory).name if directory else ""
            if bundle_id:
                keys = list(edit_bundle_keys(job_id, bundle_id).values())
                try:
                    self._bucket(self.results_bucket).remove(keys)
                except Exception:
                    return
            return
        name = Path(edited_key).name
        if name.endswith(".edited.musicxml") or name.endswith(".edits.json"):
            self.delete_edited(job_id, edited_key)


@lru_cache
def get_storage():
    if os.getenv("SUPABASE_URL") and os.getenv("SUPABASE_SERVICE_ROLE_KEY"):
        return SupabaseStorage()

    return LocalStorage()
