"""Submódulo Centro de Documentos (Documentos · Consulta e impresión):
Índice documental reconstruible, preferencias por usuario/empresa, adjuntos validados,
operaciones de envío idempotentes con reintento parcial seguro y enlaces temporales revocables.

Justificación arquitectónica:
- 100% aditiva y reversible: no altera ni bloquea ninguna tabla operativa (ventas, caja, saldos, inventario, CFDI, RRHH).
- Permite paginación y ordenamiento reales en servidor sobre las 25+ fuentes documentales del ERP con una identidad única
  (empresa_id, source_table, source_id) sin duplicados y con reconstrucción completa desde origen.

Revision ID: doc_center_erp_01
Revises: prt_formats_designer_01
Create Date: 2026-11-20
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "doc_center_erp_01"
down_revision = "prt_formats_designer_01"
branch_labels = None
depends_on = None


def _json_type():
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        return postgresql.JSONB(astext_type=sa.Text())
    return sa.JSON()


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    existing = set(insp.get_table_names())
    jtype = _json_type()

    if "document_registry_entries" not in existing:
        op.create_table(
            "document_registry_entries",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("doc_key", sa.String(220), nullable=False, unique=True, index=True),
            sa.Column("empresa_id", sa.String(64), nullable=False, index=True),
            sa.Column("sucursal_id", sa.String(64), nullable=False, server_default="MATRIZ", index=True),
            sa.Column("caja_id", sa.String(64), nullable=True),
            sa.Column("source_table", sa.String(64), nullable=False, index=True),
            sa.Column("source_id", sa.String(96), nullable=False, index=True),
            sa.Column("category", sa.String(32), nullable=False, index=True),
            sa.Column("doc_subtype", sa.String(48), nullable=False, index=True),
            sa.Column("print_doc_type", sa.String(64), nullable=True),
            sa.Column("doc_nature", sa.String(24), nullable=False, server_default="EMITIDO"),
            sa.Column("serie", sa.String(32), nullable=True),
            sa.Column("folio_visible", sa.String(96), nullable=False, index=True),
            sa.Column("emisor_user_id", sa.String(64), nullable=True, index=True),
            sa.Column("emisor_nombre", sa.String(160), nullable=True),
            sa.Column("tercero_id", sa.String(96), nullable=True, index=True),
            sa.Column("tercero_tipo", sa.String(24), nullable=True),
            sa.Column("tercero_nombre", sa.String(220), nullable=True, index=True),
            sa.Column("tercero_rfc", sa.String(32), nullable=True, index=True),
            sa.Column("uuid_fiscal", sa.String(64), nullable=True, index=True),
            sa.Column("reference_text", sa.String(320), nullable=True),
            sa.Column("currency", sa.String(12), nullable=False, server_default="MXN"),
            sa.Column("amount_applicable", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("subtotal", sa.Numeric(15, 4), nullable=True),
            sa.Column("discount_amount", sa.Numeric(15, 4), nullable=True),
            sa.Column("tax_amount", sa.Numeric(15, 4), nullable=True),
            sa.Column("total_amount", sa.Numeric(15, 4), nullable=True, index=True),
            sa.Column("doc_status", sa.String(32), nullable=False, server_default="EMITIDO", index=True),
            sa.Column("payment_status", sa.String(32), nullable=False, server_default="NO_APLICA", index=True),
            sa.Column("fiscal_status", sa.String(32), nullable=False, server_default="NO_FISCAL", index=True),
            sa.Column("dispatch_status", sa.String(32), nullable=False, server_default="SIN_ENVIO", index=True),
            sa.Column("cancel_reason", sa.String(300), nullable=True),
            sa.Column("emitted_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False, index=True),
            sa.Column("branch_tz", sa.String(64), nullable=False, server_default="America/Mazatlan"),
            sa.Column("emitted_local_date", sa.String(10), nullable=False, server_default="", index=True),
            sa.Column("has_original_file", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("has_xml", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("has_acuse", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("attachments_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("extra_meta_json", jtype, nullable=False),
            sa.Column("search_blob", sa.Text(), nullable=False, server_default=""),
            sa.Column("synced_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.UniqueConstraint("empresa_id", "source_table", "source_id", name="uq_doc_reg_emp_src"),
        )
        op.create_index("idx_doc_reg_emp_cat_date", "document_registry_entries", ["empresa_id", "category", "doc_subtype", "emitted_at"])
        op.create_index("idx_doc_reg_emp_suc_date", "document_registry_entries", ["empresa_id", "sucursal_id", "emitted_local_date"])

    if "document_user_preferences" not in existing:
        op.create_table(
            "document_user_preferences",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("empresa_id", sa.String(64), nullable=False, index=True),
            sa.Column("user_id", sa.String(64), nullable=False, index=True),
            sa.Column("favorites_json", jtype, nullable=False),
            sa.Column("recents_json", jtype, nullable=False),
            sa.Column("saved_views_json", jtype, nullable=False),
            sa.Column("ui_prefs_json", jtype, nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.UniqueConstraint("empresa_id", "user_id", name="uq_doc_user_pref_emp_usr"),
        )

    if "document_attachments" not in existing:
        op.create_table(
            "document_attachments",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("empresa_id", sa.String(64), nullable=False, index=True),
            sa.Column("sucursal_id", sa.String(64), nullable=True, index=True),
            sa.Column("doc_key", sa.String(220), nullable=False, index=True),
            sa.Column("source_table", sa.String(64), nullable=False),
            sa.Column("source_id", sa.String(96), nullable=False),
            sa.Column("kind", sa.String(32), nullable=False, server_default="EVIDENCIA"),
            sa.Column("original_filename", sa.String(255), nullable=False),
            sa.Column("mime_type", sa.String(80), nullable=False),
            sa.Column("size_bytes", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("sha256_hash", sa.String(64), nullable=False),
            sa.Column("contains_amounts", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("storage_rel_path", sa.String(512), nullable=False),
            sa.Column("notes", sa.String(300), nullable=True),
            sa.Column("uploaded_by", sa.String(64), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
        op.create_index("idx_doc_att_emp_key", "document_attachments", ["empresa_id", "doc_key", "created_at"])

    if "document_dispatch_operations" not in existing:
        op.create_table(
            "document_dispatch_operations",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("empresa_id", sa.String(64), nullable=False, index=True),
            sa.Column("sucursal_id", sa.String(64), nullable=True, index=True),
            sa.Column("operation_key", sa.String(120), nullable=False),
            sa.Column("channel", sa.String(32), nullable=False, index=True),
            sa.Column("status", sa.String(32), nullable=False, server_default="PROCESSING", index=True),
            sa.Column("subject", sa.String(240), nullable=True),
            sa.Column("message_body", sa.Text(), nullable=True),
            sa.Column("total_items", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("succeeded_items", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("failed_items", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("uncertain_items", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("is_test_mode", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("created_by", sa.String(64), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.UniqueConstraint("empresa_id", "operation_key", name="uq_doc_disp_emp_opkey"),
        )
        op.create_index("idx_doc_disp_emp_status", "document_dispatch_operations", ["empresa_id", "status", "created_at"])

    if "document_dispatch_items" not in existing:
        op.create_table(
            "document_dispatch_items",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("empresa_id", sa.String(64), nullable=False, index=True),
            sa.Column("operation_id", sa.String(36), nullable=False, index=True),
            sa.Column("doc_key", sa.String(220), nullable=False, index=True),
            sa.Column("folio_visible", sa.String(96), nullable=True),
            sa.Column("recipient", sa.String(220), nullable=False),
            sa.Column("recipient_name", sa.String(220), nullable=True),
            sa.Column("channel", sa.String(32), nullable=False),
            sa.Column("formats_json", jtype, nullable=False),
            sa.Column("filenames_json", jtype, nullable=False),
            sa.Column("status", sa.String(32), nullable=False, server_default="PENDING", index=True),
            sa.Column("safe_to_retry", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("provider_name", sa.String(48), nullable=True),
            sa.Column("provider_message_id", sa.String(140), nullable=True),
            sa.Column("provider_raw_status", sa.String(64), nullable=True),
            sa.Column("provider_delivery_confirmed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("provider_read_confirmed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("error_detail", sa.String(400), nullable=True),
            sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
        op.create_index("idx_doc_disp_item_doc", "document_dispatch_items", ["empresa_id", "doc_key", "status"])

    if "document_share_links" not in existing:
        op.create_table(
            "document_share_links",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("token", sa.String(96), nullable=False, unique=True, index=True),
            sa.Column("empresa_id", sa.String(64), nullable=False, index=True),
            sa.Column("sucursal_id", sa.String(64), nullable=True),
            sa.Column("doc_key", sa.String(220), nullable=False, index=True),
            sa.Column("format_code", sa.String(32), nullable=False, server_default="CARTA"),
            sa.Column("recipient_label", sa.String(220), nullable=True),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False, index=True),
            sa.Column("max_downloads", sa.Integer(), nullable=False, server_default="10"),
            sa.Column("download_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("revoked", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("revoked_by", sa.String(64), nullable=True),
            sa.Column("created_by", sa.String(64), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
        op.create_index("idx_doc_share_emp_doc", "document_share_links", ["empresa_id", "doc_key", "revoked"])


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    existing = set(insp.get_table_names())
    for tbl in (
        "document_share_links",
        "document_dispatch_items",
        "document_dispatch_operations",
        "document_attachments",
        "document_user_preferences",
        "document_registry_entries",
    ):
        if tbl in existing:
            op.drop_table(tbl)
