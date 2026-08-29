"""File metadata. The bytes live in object storage; this row is what the product knows about them.

PLAN §30: "Files live in object storage; database stores metadata, classification, hashes and
references." PLAN Step 1.6 asks for tenant-prefixed keys, metadata, hash, classification, signed
URL expiry and malware-scan state.

**The key is tenant-prefixed, and that is a second boundary rather than a convenience.** Row-level
security protects this table, so one organisation cannot read another's metadata — but object
storage has no idea what a tenant is. A key of `t/<tenant>/<uuid>` means a bucket policy, a
lifecycle rule or an export can be scoped per tenant later without moving a single object. A flat
key space cannot be retrofitted with that.

**`scan_state` starts at `pending` and a download is refused until it is `clean`.** A file that
has been uploaded and not yet scanned is not a file anyone should be handed. The scanner itself
arrives with the integration that needs it; until then nothing moves off `pending`, and that is
visible rather than a silent allow.

**`sha256` is recorded, not trusted from the client.** It is computed while the bytes stream
through, so it says what was actually stored — which is the only version worth having when the
question is whether a file changed.

Revision: 0009
Parent:   0008
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: What the file is, for retention and for who may see it. PLAN §19 requires privacy controls to
#: act on classification, so it is a column rather than a guess made later from the file name.
CLASSIFICATIONS: tuple[str, ...] = (
    "internal",
    "confidential",
    "personal_data",
    "public",
)

#: Where a file is in the scan. `pending` blocks download; only `clean` releases it.
SCAN_STATES: tuple[str, ...] = ("pending", "clean", "infected", "failed")


def upgrade() -> None:
    classifications = ", ".join(f"'{value}'" for value in CLASSIFICATIONS)
    scan_states = ", ".join(f"'{value}'" for value in SCAN_STATES)

    op.create_table(
        "files",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        #  The object's key in the bucket, tenant-prefixed. Stored rather than derived, so a
        #  future change to the naming scheme cannot orphan everything uploaded before it.
        sa.Column("storage_key", sa.String(length=512), nullable=False),
        #  As the person named it. Never used to build the storage key — a filename arrives from
        #  a browser and can contain anything, including `../`.
        sa.Column("original_name", sa.String(length=400), nullable=False),
        sa.Column("content_type", sa.String(length=200), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        #  Computed from the bytes as they were stored, not taken from the client.
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column(
            "classification", sa.String(length=40), nullable=False, server_default="internal"
        ),
        sa.Column("scan_state", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("scan_detail", sa.Text(), nullable=True),
        sa.Column("scanned_at", sa.DateTime(timezone=True), nullable=True),
        #  Who uploaded it. A membership, not a user — a file belongs to a person inside one
        #  organisation.
        sa.Column("uploaded_by_membership_id", postgresql.UUID(as_uuid=True), nullable=True),
        #  What it is attached to. Null while a file is uploaded before the thing it belongs to
        #  exists — a draft being written, for instance.
        sa.Column("owner_type", sa.String(length=40), nullable=True),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_files"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="fk_files_tenant_id_tenants", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "uploaded_by_membership_id"],
            ["memberships.tenant_id", "memberships.id"],
            name="fk_files_tenant_uploader",
            ondelete="SET NULL",
        ),
        #  One row per object. Without this a bug could point two rows at one object, and
        #  deleting either would take the other's bytes with it.
        sa.UniqueConstraint("storage_key", name="uq_files_storage_key"),
        sa.CheckConstraint(
            f"classification IN ({classifications})", name="ck_files_classification_known"
        ),
        sa.CheckConstraint(f"scan_state IN ({scan_states})", name="ck_files_scan_state_known"),
        sa.CheckConstraint("size_bytes >= 0", name="ck_files_size_not_negative"),
        #  The key must start with this tenant's own prefix. Belt and braces with row-level
        #  security: a row that passed the policy but pointed at another tenant's object would
        #  hand over its bytes, and the policy cannot see inside a string.
        sa.CheckConstraint(
            "storage_key LIKE 't/' || tenant_id::text || '/%'",
            name="ck_files_key_is_tenant_prefixed",
        ),
    )
    op.create_index("ix_files_tenant_id", "files", ["tenant_id"])
    op.create_index("ix_files_tenant_id_owner", "files", ["tenant_id", "owner_type", "owner_id"])
    #  The scanner's queue: what still needs looking at.
    op.execute(
        """
        CREATE INDEX ix_files_awaiting_scan
            ON files (created_at)
            WHERE scan_state = 'pending';
        """
    )

    op.execute("ALTER TABLE files ENABLE ROW LEVEL SECURITY;")
    op.execute(
        """
        CREATE POLICY files_tenant_isolation ON files
            FOR ALL
            USING (tenant_id = app_current_tenant())
            WITH CHECK (tenant_id = app_current_tenant());
        """
    )
    op.execute(
        """
        CREATE TRIGGER files_set_updated_at
            BEFORE UPDATE ON files
            FOR EACH ROW EXECUTE FUNCTION set_updated_at();
        """
    )


def downgrade() -> None:
    """Reversible in the database. **It does not delete the objects.**

    Dropping this table loses every reference to what is in the bucket, and the bytes stay there
    with nothing pointing at them. That is the safer failure — deleting a customer's files
    because a migration was reversed is not recoverable — but somebody has to know it happened.
    """
    op.execute("DROP TABLE IF EXISTS files CASCADE")
