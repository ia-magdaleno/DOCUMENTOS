"""Submódulo Diseñador de Formatos: tablas de activos, plantillas, versiones, asignaciones y reimpresiones históricas.

Revision ID: prt_formats_designer_01
Revises: dash_erp_layouts_01
Create Date: 2026-11-17
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "prt_formats_designer_01"
down_revision = "dash_erp_layouts_01"
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

    if "print_template_assets" not in existing:
        op.create_table(
            "print_template_assets",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("empresa_id", sa.String(64), nullable=False, index=True),
            sa.Column("sucursal_id", sa.String(64), nullable=True, index=True),
            sa.Column("kind", sa.String(32), nullable=False, server_default="BACKGROUND_PDF"),
            sa.Column("original_filename", sa.String(255), nullable=False, server_default="fondo.pdf"),
            sa.Column("mime_type", sa.String(80), nullable=False, server_default="application/pdf"),
            sa.Column("size_bytes", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("sha256_hash", sa.String(64), nullable=False, server_default=""),
            sa.Column("page_count", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("pages_meta", jtype, nullable=False),
            sa.Column("storage_rel_path", sa.String(512), nullable=False, server_default=""),
            sa.Column("created_by", sa.String(64), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
        op.create_index("idx_prt_assets_emp_kind", "print_template_assets", ["empresa_id", "kind", "created_at"])

    if "print_format_templates" not in existing:
        op.create_table(
            "print_format_templates",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("empresa_id", sa.String(64), nullable=False, index=True),
            sa.Column("sucursal_id", sa.String(64), nullable=True, index=True),
            sa.Column("code", sa.String(80), nullable=False, index=True),
            sa.Column("name", sa.String(180), nullable=False),
            sa.Column("doc_type", sa.String(64), nullable=False, index=True),
            sa.Column("mode", sa.String(16), nullable=False, server_default="CARTA"),
            sa.Column("paper_size", sa.String(24), nullable=False, server_default="letter"),
            sa.Column("orientation", sa.String(16), nullable=False, server_default="portrait"),
            sa.Column("status", sa.String(20), nullable=False, server_default="DRAFT", index=True),
            sa.Column("active_published_version_id", sa.String(36), nullable=True),
            sa.Column("latest_draft_version_id", sa.String(36), nullable=True),
            sa.Column("current_version_num", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("is_system_seed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("integration_status", sa.String(24), nullable=False, server_default="OPERATIVO"),
            sa.Column("created_by", sa.String(64), nullable=True),
            sa.Column("updated_by", sa.String(64), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index("idx_prt_tpl_emp_doctype", "print_format_templates", ["empresa_id", "doc_type", "mode", "status"])

    if "print_format_versions" not in existing:
        op.create_table(
            "print_format_versions",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("empresa_id", sa.String(64), nullable=False, index=True),
            sa.Column("template_id", sa.String(36), nullable=False, index=True),
            sa.Column("version_num", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("status", sa.String(20), nullable=False, server_default="DRAFT", index=True),
            sa.Column("name_snapshot", sa.String(180), nullable=False),
            sa.Column("mode", sa.String(16), nullable=False, server_default="CARTA"),
            sa.Column("paper_size", sa.String(24), nullable=False, server_default="letter"),
            sa.Column("orientation", sa.String(16), nullable=False, server_default="portrait"),
            sa.Column("paper_width_mm", sa.Numeric(10, 2), nullable=False, server_default="215.90"),
            sa.Column("paper_height_mm", sa.Numeric(10, 2), nullable=False, server_default="279.40"),
            sa.Column("printable_width_mm", sa.Numeric(10, 2), nullable=False, server_default="215.90"),
            sa.Column("margins_mm_json", jtype, nullable=False),
            sa.Column("background_asset_id", sa.String(36), nullable=True),
            sa.Column("background_settings_json", jtype, nullable=False),
            sa.Column("definition_json", jtype, nullable=False),
            sa.Column("validation_warnings_json", jtype, nullable=False),
            sa.Column("changelog", sa.String(500), nullable=True),
            sa.Column("created_by", sa.String(64), nullable=True),
            sa.Column("published_by", sa.String(64), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("published_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        )
        op.create_index("idx_prt_ver_emp_tpl", "print_format_versions", ["empresa_id", "template_id", "version_num"])

    if "print_format_assignments" not in existing:
        op.create_table(
            "print_format_assignments",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("empresa_id", sa.String(64), nullable=False, index=True),
            sa.Column("sucursal_id", sa.String(64), nullable=True, index=True),
            sa.Column("terminal_id", sa.String(64), nullable=True, index=True),
            sa.Column("doc_type", sa.String(64), nullable=False, index=True),
            sa.Column("mode", sa.String(16), nullable=False, server_default="TICKET"),
            sa.Column("role_target", sa.String(32), nullable=False, server_default="CLIENTE"),
            sa.Column("template_id", sa.String(36), nullable=False),
            sa.Column("published_version_id", sa.String(36), nullable=False),
            sa.Column("printer_num", sa.String(32), nullable=True),
            sa.Column("printer_name", sa.String(140), nullable=True),
            sa.Column("copies", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("print_background", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("updated_by", sa.String(64), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
        op.create_index("idx_prt_asig_lookup", "print_format_assignments", ["empresa_id", "doc_type", "sucursal_id", "terminal_id", "active"])

    if "print_emission_records" not in existing:
        op.create_table(
            "print_emission_records",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("empresa_id", sa.String(64), nullable=False, index=True),
            sa.Column("sucursal_id", sa.String(64), nullable=True, index=True),
            sa.Column("doc_type", sa.String(64), nullable=False, index=True),
            sa.Column("operation_id", sa.String(80), nullable=False, index=True),
            sa.Column("operation_folio", sa.String(80), nullable=True, index=True),
            sa.Column("template_id", sa.String(36), nullable=False),
            sa.Column("version_id", sa.String(36), nullable=False),
            sa.Column("version_num", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("mode", sa.String(16), nullable=False, server_default="TICKET"),
            sa.Column("data_snapshot_json", jtype, nullable=False),
            sa.Column("emitted_by", sa.String(64), nullable=True),
            sa.Column("emitted_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("reprint_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("last_reprinted_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index("idx_prt_emission_op", "print_emission_records", ["empresa_id", "doc_type", "operation_id", "emitted_at"])


def downgrade() -> None:
    for tbl in (
        "print_emission_records",
        "print_format_assignments",
        "print_format_versions",
        "print_format_templates",
        "print_template_assets",
    ):
        op.drop_table(tbl)
