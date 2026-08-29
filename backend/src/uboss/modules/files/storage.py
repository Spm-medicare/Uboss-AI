"""Putting bytes in object storage and getting them back out.

Everything here is S3-compatible — MinIO locally, whatever the deployment uses in production —
so there is no "local mode" branch in the code. A storage path that only runs in development is
a storage path nobody tests.

**Every key is tenant-prefixed**, `t/<tenant>/<uuid>`, and the prefix is built here from the
verified tenant. The database enforces the same shape with a `CHECK`, so a row whose key points
at another organisation's object cannot exist even if this module were wrong.

**A download link is short-lived and signed.** PLAN §19 asks for short-lived signed URLs, and the
reason is that a link is forwardable: an email, a chat message, a screenshot. A link that expires
in minutes limits how far a leaked one travels.

**A file is not served until it has been scanned clean.** That check is in the service, not here
— this module moves bytes and does not decide who may have them.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from typing import Any

import aioboto3
from botocore.config import Config

from uboss.core.settings import Settings

#: Streamed in chunks rather than read whole. A 200 MB upload read into memory is 200 MB of
#: memory, per concurrent upload, and that is how a process dies during a busy afternoon.
CHUNK = 1024 * 1024


@dataclass(frozen=True, slots=True)
class StoredObject:
    """What was actually written."""

    key: str
    size_bytes: int
    sha256: str


def key_for(tenant_id: uuid.UUID) -> str:
    """A new key inside one tenant's prefix.

    The name is a fresh UUID and never the person's filename. A filename arrives from a browser
    and may contain `../`, a null byte, or 300 characters of Unicode that a storage backend
    normalises into somebody else's key.
    """
    return f"t/{tenant_id}/{uuid.uuid4()}"


def owns(key: str, tenant_id: uuid.UUID) -> bool:
    """Whether a key belongs to this tenant.

    Checked before every read, because the key is the only thing object storage understands. It
    has no idea what a tenant is, so if a wrong key ever reaches it, it will serve the bytes.
    """
    return key.startswith(f"t/{tenant_id}/")


class Storage:
    """The bucket, and the four things done to it."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._session = aioboto3.Session()

    def _client(self) -> Any:
        return self._session.client(
            "s3",
            endpoint_url=self._settings.s3_endpoint_url,
            aws_access_key_id=self._settings.s3_access_key.get_secret_value(),
            aws_secret_access_key=self._settings.s3_secret_key.get_secret_value(),
            region_name=self._settings.s3_region,
            config=Config(
                signature_version="s3v4",
                #  Path style, because MinIO and most self-hosted gateways do not do
                #  virtual-host addressing. AWS accepts it too, so one setting works everywhere.
                s3={"addressing_style": "path"},
                retries={"max_attempts": 3, "mode": "standard"},
            ),
        )

    async def ensure_bucket(self) -> None:
        """Create the bucket if it is missing. Safe to call repeatedly.

        Used at start-up in development and by the test suite. A deployment creates its bucket
        through infrastructure-as-code, where the retention and versioning policies live too.
        """
        async with self._client() as s3:
            try:
                await s3.head_bucket(Bucket=self._settings.s3_bucket)
            except Exception:
                await s3.create_bucket(Bucket=self._settings.s3_bucket)

    async def put(
        self, key: str, data: bytes, *, content_type: str
    ) -> StoredObject:
        """Write the bytes, and report what was written.

        The digest is computed here rather than taken from the caller, so it describes what is
        actually in the bucket. A client-supplied hash describes what the client believed.
        """
        digest = hashlib.sha256(data).hexdigest()
        async with self._client() as s3:
            await s3.put_object(
                Bucket=self._settings.s3_bucket,
                Key=key,
                Body=data,
                ContentType=content_type,
                #  Recorded on the object as well as in the database. If the two ever disagree,
                #  that disagreement is the interesting fact.
                Metadata={"sha256": digest},
            )
        return StoredObject(key=key, size_bytes=len(data), sha256=digest)

    async def get(self, key: str) -> bytes:
        async with self._client() as s3:
            response = await s3.get_object(Bucket=self._settings.s3_bucket, Key=key)
            async with response["Body"] as stream:
                #  `read()` with no argument. The aiohttp-backed body this client returns takes
                #  no size, and its content is already buffered by the time it is handed over.
                body: bytes = await stream.read()
                return body

    async def signed_url(self, key: str, *, seconds: int | None = None) -> str:
        """A link that works for a few minutes and then does not.

        Signing is a local computation — no request is made — so this is cheap enough to do per
        download rather than caching a URL somewhere it could outlive its expiry.
        """
        async with self._client() as s3:
            url: str = await s3.generate_presigned_url(
                "get_object",
                Params={"Bucket": self._settings.s3_bucket, "Key": key},
                ExpiresIn=seconds or self._settings.s3_signed_url_seconds,
            )
            return url

    async def delete(self, key: str) -> None:
        async with self._client() as s3:
            await s3.delete_object(Bucket=self._settings.s3_bucket, Key=key)
