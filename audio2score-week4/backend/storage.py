from dotenv import load_dotenv

load_dotenv()

import os
import shutil
from pathlib import Path
from functools import lru_cache

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

    def delete_upload(self, storage_key):
        if not storage_key:
            return
        path = Path(storage_key)
        if path.exists():
            path.unlink()
        work_dir = path.parent / f"bp_{path.stem}"
        if work_dir.is_dir():
            shutil.rmtree(work_dir, ignore_errors=True)

    def delete_result(self, result_storage_key, job_id=None):
        if result_storage_key:
            path = Path(result_storage_key)
            if path.exists():
                path.unlink()
            if path.parent.exists() and job_id:
                for sidecar in path.parent.glob(f"{job_id}.*"):
                    sidecar.unlink(missing_ok=True)


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
        temp_file = LOCAL_TEMP_DIR / Path(key).name

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
        temp_file = LOCAL_TEMP_DIR / Path(key).name
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
        if job_id:
            keys.extend(
                [
                    f"{job_id}.musicxml",
                    f"{job_id}.raw.mid",
                    f"{job_id}.validated.mid",
                    f"{job_id}.score.mid",
                ]
            )
        if not keys:
            return
        try:
            self._bucket(self.results_bucket).remove(keys)
        except Exception:
            return


@lru_cache
def get_storage():
    if os.getenv("SUPABASE_URL") and os.getenv("SUPABASE_SERVICE_ROLE_KEY"):
        return SupabaseStorage()

    return LocalStorage()
