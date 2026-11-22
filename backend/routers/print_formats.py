"""Router FastAPI para el Submódulo «Diseñador de formatos» (Configuración -> Impresoras F9).

Implementa:
- Seguridad multiempresa estricta basada en JWT (`get_tenant_context`).
- Separación de permisos por rol: consultar, disenar, publicar, asignar, imprimir.
- Bitácora de auditoría (`AuditLog`) en creación, edición, publicación, restauración y asignación.
- Gestión de activos (PDF multipágina e imágenes PNG/JPG), plantillas, versiones inmutables,
  asignaciones con precedencia (Terminal -> Sucursal -> Empresa), generación real de PDF
  y reimpresiones históricas con snapshot inmutable.
"""
import copy
import datetime as _dt
import os
import uuid
from decimal import Decimal
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, Query, Response, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

import models
from database import get_db
from deps import get_tenant_context
from roles import normalize_role
from services import print_formats_service as _pfs

router = APIRouter(prefix="/api/print-formats", tags=["print-formats"])

_PERM_ROLES = {
    "consultar": {"admin", "administrador", "superadmin", "admin_sucursal", "gerente", "cajero", "operador caja", "vendedor_cajero", "vendedor", "vendedor_mostrador", "almacenista", "contador"},
    "disenar":   {"admin", "administrador", "superadmin", "admin_sucursal", "gerente"},
    "publicar":  {"admin", "administrador", "superadmin", "gerente"},
    "asignar":   {"admin", "administrador", "superadmin", "admin_sucursal", "gerente"},
    "imprimir":  {"admin", "administrador", "superadmin", "admin_sucursal", "gerente", "cajero", "operador caja", "vendedor_cajero", "vendedor", "vendedor_mostrador", "almacenista", "contador"},
}


def _check_perm(payload: dict, action: str) -> None:
    raw_role = str(payload.get("role") or "").strip().lower()
    norm_r = normalize_role(raw_role)
    allowed = _PERM_ROLES.get(action, {"admin", "administrador", "superadmin"})
    if raw_role not in allowed and norm_r not in allowed:
        raise HTTPException(
            status_code=403,
            detail=f"Tu rol ('{payload.get('role')}') no tiene permiso para la acción '{action}' en el Diseñador de Formatos.",
        )


def _get_user_permissions(payload: dict) -> Dict[str, bool]:
    raw_role = str(payload.get("role") or "").strip().lower()
    norm_r = normalize_role(raw_role)
    return {
        act: (raw_role in roles_set or norm_r in roles_set)
        for act, roles_set in _PERM_ROLES.items()
    }


def _audit(
    db: Session,
    empresa_id: str,
    sucursal_id: str,
    user_id: str,
    action: str,
    details: Any = None,
    severity: str = "INFO",
) -> None:
    try:
        db.add(models.AuditLog(
            empresa_id=empresa_id or "DESCONOCIDA",
            sucursal_id=sucursal_id or "MATRIZ",
            user_id=user_id or "sistema",
            action=action,
            severity=severity,
            details=details if isinstance(details, str) else str(details),
        ))
        db.commit()
    except Exception:
        db.rollback()


def _serialize_template(tpl: models.PrintFormatTemplate, ver: Optional[models.PrintFormatVersion] = None) -> Dict[str, Any]:
    out = {
        "id": tpl.id,
        "empresa_id": tpl.empresa_id,
        "sucursal_id": tpl.sucursal_id,
        "code": tpl.code,
        "name": tpl.name,
        "doc_type": tpl.doc_type,
        "doc_type_name": (_pfs.DOC_TYPES_MAP.get(tpl.doc_type) or {}).get("name", tpl.doc_type),
        "mode": tpl.mode,
        "paper_size": tpl.paper_size,
        "orientation": tpl.orientation,
        "status": tpl.status,
        "active_published_version_id": tpl.active_published_version_id,
        "latest_draft_version_id": tpl.latest_draft_version_id,
        "current_version_num": tpl.current_version_num,
        "is_system_seed": bool(tpl.is_system_seed),
        "integration_status": tpl.integration_status,
        "created_by": tpl.created_by,
        "updated_by": tpl.updated_by,
        "created_at": tpl.created_at.isoformat() if tpl.created_at else None,
        "updated_at": tpl.updated_at.isoformat() if tpl.updated_at else None,
        "published_at": tpl.published_at.isoformat() if tpl.published_at else None,
    }
    if ver is not None:
        out["working_version"] = _serialize_version(ver)
    return out


def _serialize_version(ver: models.PrintFormatVersion) -> Dict[str, Any]:
    return {
        "id": ver.id,
        "empresa_id": ver.empresa_id,
        "template_id": ver.template_id,
        "version_num": ver.version_num,
        "status": ver.status,
        "name_snapshot": ver.name_snapshot,
        "mode": ver.mode,
        "paper_size": ver.paper_size,
        "orientation": ver.orientation,
        "paper_width_mm": float(ver.paper_width_mm or 215.9),
        "paper_height_mm": float(ver.paper_height_mm or 279.4),
        "printable_width_mm": float(ver.printable_width_mm or 215.9),
        "margins_mm_json": ver.margins_mm_json or {},
        "background_asset_id": ver.background_asset_id,
        "background_settings_json": ver.background_settings_json or {},
        "definition_json": ver.definition_json or {},
        "validation_warnings_json": ver.validation_warnings_json or [],
        "changelog": ver.changelog,
        "created_by": ver.created_by,
        "published_by": ver.published_by,
        "created_at": ver.created_at.isoformat() if ver.created_at else None,
        "published_at": ver.published_at.isoformat() if ver.published_at else None,
    }


def _serialize_asset(a: models.PrintTemplateAsset) -> Dict[str, Any]:
    return {
        "id": a.id,
        "empresa_id": a.empresa_id,
        "sucursal_id": a.sucursal_id,
        "kind": a.kind,
        "original_filename": a.original_filename,
        "mime_type": a.mime_type,
        "size_bytes": a.size_bytes,
        "sha256_hash": a.sha256_hash,
        "page_count": a.page_count,
        "pages_meta": a.pages_meta or [],
        "created_by": a.created_by,
        "created_at": a.created_at.isoformat() if a.created_at else None,
    }


# ══════════════════════════════════════════════════════════════════════════════
# 1. CATÁLOGO DE TIPOS DE DOCUMENTOS, CAMPOS Y PERMISOS
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/catalog")
def get_print_formats_catalog(
    doc_type: Optional[str] = Query(None),
    tenant: dict = Depends(get_tenant_context),
):
    _check_perm(tenant, "consultar")
    selected_dt = doc_type or "ticket_venta_contado"
    return {
        "empresa_id": tenant.get("empresa"),
        "sucursal_id": tenant.get("sucursal"),
        "permissions": _get_user_permissions(tenant),
        "doc_types": _pfs.DOC_TYPES_CATALOG,
        "field_groups_for_doc": _pfs.get_fields_for_doc_type(selected_dt),
        "all_field_groups": _pfs.FIELD_GROUPS_CATALOG,
        "demo_context": _pfs.build_demo_context(selected_dt),
    }


# ══════════════════════════════════════════════════════════════════════════════
# 2. BIBLIOTECA DE PLANTILLAS Y VERSIONES INMUTABLES
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/templates")
def list_templates(
    doc_type: Optional[str] = Query(None),
    mode: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    tenant: dict = Depends(get_tenant_context),
):
    _check_perm(tenant, "consultar")
    empresa_id = tenant.get("empresa")
    user_id = tenant.get("sub") or "sistema"

    _pfs.ensure_seed_templates(db, empresa_id, user_id=user_id)

    q = db.query(models.PrintFormatTemplate).filter(models.PrintFormatTemplate.empresa_id == empresa_id)
    if doc_type:
        q = q.filter(models.PrintFormatTemplate.doc_type == doc_type)
    if mode:
        q = q.filter(models.PrintFormatTemplate.mode == mode.upper())
    if status:
        q = q.filter(models.PrintFormatTemplate.status == status.upper())

    rows = q.order_by(models.PrintFormatTemplate.updated_at.desc()).all()
    return {
        "templates": [_serialize_template(r) for r in rows],
        "count": len(rows),
    }


@router.post("/templates", status_code=201)
def create_template(
    body: Dict[str, Any] = Body(...),
    db: Session = Depends(get_db),
    tenant: dict = Depends(get_tenant_context),
):
    _check_perm(tenant, "disenar")
    empresa_id = tenant.get("empresa")
    sucursal_id = tenant.get("sucursal") or "MATRIZ"
    user_id = tenant.get("sub") or "admin"

    raw_name = str(body.get("name") or "NUEVA PLANTILLA DE IMPRESIÓN").strip().upper()
    doc_type = str(body.get("doc_type") or "ticket_venta_contado").strip()
    if doc_type not in _pfs.DOC_TYPES_MAP:
        raise HTTPException(status_code=400, detail=f"Tipo de documento '{doc_type}' no reconocido en el catálogo.")

    doc_meta = _pfs.DOC_TYPES_MAP[doc_type]
    mode = str(body.get("mode") or doc_meta.get("default_mode") or "CARTA").strip().upper()
    if mode not in doc_meta.get("allowed_modes", ["TICKET", "CARTA"]):
        raise HTTPException(
            status_code=400,
            detail=f"El documento '{doc_meta['name']}' solo admite las modalidades: {', '.join(doc_meta['allowed_modes'])}.",
        )

    orientation = str(body.get("orientation") or "portrait").strip().lower()
    paper_size = str(body.get("paper_size") or ("letter" if mode == "CARTA" else "80mm")).strip()

    if mode == "CARTA":
        w_mm = _pfs.CARTA_HEIGHT_MM if orientation == "landscape" else _pfs.CARTA_WIDTH_MM
        h_mm = _pfs.CARTA_WIDTH_MM if orientation == "landscape" else _pfs.CARTA_HEIGHT_MM
        if paper_size == "A4":
            w_mm = _pfs.A4_HEIGHT_MM if orientation == "landscape" else _pfs.A4_WIDTH_MM
            h_mm = _pfs.A4_WIDTH_MM if orientation == "landscape" else _pfs.A4_HEIGHT_MM
        printable_w = w_mm
    else:
        w_mm = float(body.get("paper_width_mm") or (58.0 if paper_size == "58mm" else 80.0))
        h_mm = 0.0
        printable_w = float(body.get("printable_width_mm") or (48.0 if w_mm <= 60 else 72.0))

    tpl_id = str(uuid.uuid4())
    ver_id = str(uuid.uuid4())
    now = _dt.datetime.now(_dt.timezone.utc)

    default_els = _pfs._default_carta_elements(raw_name, doc_type) if mode == "CARTA" else []
    defn = body.get("definition_json") or {
        "doc_title": raw_name,
        "elements": default_els,
        "flow_blocks": [
            {"id": "blk-header", "type": "header", "label": "ENCABEZADO Y LOGOTIPO", "enabled": True, "fields": ["empresa.nombre_comercial", "empresa.rfc", "empresa.domicilio"]},
            {"id": "blk-op", "type": "operation", "label": "DATOS DE LA OPERACIÓN", "enabled": True, "fields": ["operacion.folio", "operacion.fecha", "operacion.cajero"]},
            {"id": "blk-client", "type": "client", "label": "DATOS DEL CLIENTE", "enabled": True, "fields": ["cliente.nombre", "cliente.rfc"]},
            {"id": "blk-items", "type": "items_table", "label": "TABLA DE PRODUCTOS", "enabled": True, "fields": ["productos.codigo", "productos.descripcion", "productos.cantidad", "productos.precio", "productos.importe"]},
            {"id": "blk-totals", "type": "totals", "label": "BLOQUE DE TOTALES", "enabled": True, "fields": ["importes.subtotal", "importes.impuestos", "importes.total", "importes.total_letra"]},
        ],
        "section_flags": {"showLogo": True, "showCompanyRfc": True, "showFolio": True, "showDateTime": True, "showClientSection": True, "showPrices": True, "showTotalInWords": True},
    }

    bg_settings = body.get("background_settings_json") or {
        "fit_mode": "fit",
        "page_rule": "all",
        "specific_pages": [1],
        "continuation_page": 2,
        "print_mode": "background_and_fields",
        "manual_x_mm": 0.0,
        "manual_y_mm": 0.0,
        "manual_w_mm": w_mm,
        "manual_h_mm": h_mm,
    }

    tpl = models.PrintFormatTemplate(
        id=tpl_id,
        empresa_id=empresa_id,
        sucursal_id=body.get("sucursal_id"),
        code=str(body.get("code") or f"TPL_{uuid.uuid4().hex[:8]}").upper(),
        name=raw_name,
        doc_type=doc_type,
        mode=mode,
        paper_size=paper_size,
        orientation=orientation,
        status="DRAFT",
        active_published_version_id=None,
        latest_draft_version_id=ver_id,
        current_version_num=1,
        is_system_seed=False,
        integration_status=doc_meta.get("integration_status", "OPERATIVO"),
        created_by=user_id,
        updated_by=user_id,
        created_at=now,
        updated_at=now,
    )
    ver = models.PrintFormatVersion(
        id=ver_id,
        empresa_id=empresa_id,
        template_id=tpl_id,
        version_num=1,
        status="DRAFT",
        name_snapshot=raw_name,
        mode=mode,
        paper_size=paper_size,
        orientation=orientation,
        paper_width_mm=Decimal(str(w_mm)),
        paper_height_mm=Decimal(str(h_mm)),
        printable_width_mm=Decimal(str(printable_w)),
        margins_mm_json=body.get("margins_mm_json") or {"top": 10, "right": 10, "bottom": 10, "left": 10},
        background_asset_id=body.get("background_asset_id"),
        background_settings_json=bg_settings,
        definition_json=defn,
        validation_warnings_json=[],
        changelog=str(body.get("changelog") or "Creación de plantilla en borrador."),
        created_by=user_id,
        created_at=now,
    )
    db.add(tpl)
    db.add(ver)
    db.commit()
    db.refresh(tpl)
    db.refresh(ver)

    _audit(db, empresa_id, sucursal_id, user_id, "PRINT_FORMAT_CREATE", f"Plantilla creada: {raw_name} ({doc_type} / {mode})")
    return _serialize_template(tpl, ver)


@router.get("/templates/{template_id}")
def get_template_detail(
    template_id: str,
    version_id: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    tenant: dict = Depends(get_tenant_context),
):
    _check_perm(tenant, "consultar")
    empresa_id = tenant.get("empresa")

    tpl = (
        db.query(models.PrintFormatTemplate)
        .filter(models.PrintFormatTemplate.empresa_id == empresa_id, models.PrintFormatTemplate.id == template_id)
        .first()
    )
    if not tpl:
        raise HTTPException(status_code=404, detail="Plantilla no encontrada o pertenece a otra empresa.")

    versions = (
        db.query(models.PrintFormatVersion)
        .filter(models.PrintFormatVersion.empresa_id == empresa_id, models.PrintFormatVersion.template_id == tpl.id)
        .order_by(models.PrintFormatVersion.version_num.desc())
        .all()
    )

    working_ver = None
    if version_id:
        working_ver = next((v for v in versions if v.id == version_id), None)
    if not working_ver and tpl.latest_draft_version_id:
        working_ver = next((v for v in versions if v.id == tpl.latest_draft_version_id), None)
    if not working_ver and tpl.active_published_version_id:
        working_ver = next((v for v in versions if v.id == tpl.active_published_version_id), None)
    if not working_ver and versions:
        working_ver = versions[0]

    bg_asset_data = None
    if working_ver and working_ver.background_asset_id:
        asset_row = (
            db.query(models.PrintTemplateAsset)
            .filter(
                models.PrintTemplateAsset.empresa_id == empresa_id,
                models.PrintTemplateAsset.id == working_ver.background_asset_id,
            )
            .first()
        )
        if asset_row:
            bg_asset_data = _serialize_asset(asset_row)

    out = _serialize_template(tpl, working_ver)
    out["versions"] = [_serialize_version(v) for v in versions]
    out["background_asset"] = bg_asset_data
    out["field_groups"] = _pfs.get_fields_for_doc_type(tpl.doc_type)
    return out


@router.put("/templates/{template_id}/draft")
def save_template_draft(
    template_id: str,
    body: Dict[str, Any] = Body(...),
    db: Session = Depends(get_db),
    tenant: dict = Depends(get_tenant_context),
):
    """Guarda cambios sobre un borrador.
    REGLA DE INMUTABILIDAD: Si la versión actual es PUBLISHED y no existe un borrador abierto,
    crea automáticamente una nueva versión DRAFT (version_num + 1), preservando intacta la versión publicada."""
    _check_perm(tenant, "disenar")
    empresa_id = tenant.get("empresa")
    sucursal_id = tenant.get("sucursal") or "MATRIZ"
    user_id = tenant.get("sub") or "admin"

    tpl = (
        db.query(models.PrintFormatTemplate)
        .filter(models.PrintFormatTemplate.empresa_id == empresa_id, models.PrintFormatTemplate.id == template_id)
        .first()
    )
    if not tpl:
        raise HTTPException(status_code=404, detail="Plantilla no encontrada o sin acceso para esta empresa.")

    draft_ver = None
    if tpl.latest_draft_version_id:
        draft_ver = (
            db.query(models.PrintFormatVersion)
            .filter(
                models.PrintFormatVersion.empresa_id == empresa_id,
                models.PrintFormatVersion.id == tpl.latest_draft_version_id,
                models.PrintFormatVersion.status == "DRAFT",
            )
            .first()
        )

    now = _dt.datetime.now(_dt.timezone.utc)
    if not draft_ver:
        # Clonar desde la versión publicada activa (o la última existente) hacia un nuevo DRAFT
        base_ver = None
        if tpl.active_published_version_id:
            base_ver = (
                db.query(models.PrintFormatVersion)
                .filter(
                    models.PrintFormatVersion.empresa_id == empresa_id,
                    models.PrintFormatVersion.id == tpl.active_published_version_id,
                )
                .first()
            )
        if not base_ver:
            base_ver = (
                db.query(models.PrintFormatVersion)
                .filter(
                    models.PrintFormatVersion.empresa_id == empresa_id,
                    models.PrintFormatVersion.template_id == tpl.id,
                )
                .order_by(models.PrintFormatVersion.version_num.desc())
                .first()
            )

        next_vnum = int(tpl.current_version_num or 1) + 1
        new_ver_id = str(uuid.uuid4())
        draft_ver = models.PrintFormatVersion(
            id=new_ver_id,
            empresa_id=empresa_id,
            template_id=tpl.id,
            version_num=next_vnum,
            status="DRAFT",
            name_snapshot=tpl.name,
            mode=base_ver.mode if base_ver else tpl.mode,
            paper_size=base_ver.paper_size if base_ver else tpl.paper_size,
            orientation=base_ver.orientation if base_ver else tpl.orientation,
            paper_width_mm=base_ver.paper_width_mm if base_ver else Decimal("215.90"),
            paper_height_mm=base_ver.paper_height_mm if base_ver else Decimal("279.40"),
            printable_width_mm=base_ver.printable_width_mm if base_ver else Decimal("215.90"),
            margins_mm_json=copy.deepcopy(base_ver.margins_mm_json if base_ver else {}),
            background_asset_id=base_ver.background_asset_id if base_ver else None,
            background_settings_json=copy.deepcopy(base_ver.background_settings_json if base_ver else {}),
            definition_json=copy.deepcopy(base_ver.definition_json if base_ver else {}),
            validation_warnings_json=[],
            changelog="Nuevo borrador creado a partir de versión publicada.",
            created_by=user_id,
            created_at=now,
        )
        db.add(draft_ver)
        tpl.latest_draft_version_id = new_ver_id
        tpl.current_version_num = next_vnum

    # Aplicar actualizaciones al borrador
    if "name" in body and body["name"]:
        up_name = str(body["name"]).strip().upper()
        tpl.name = up_name
        draft_ver.name_snapshot = up_name
    if "paper_size" in body and body["paper_size"]:
        draft_ver.paper_size = str(body["paper_size"])
        tpl.paper_size = str(body["paper_size"])
    if "orientation" in body and body["orientation"]:
        draft_ver.orientation = str(body["orientation"]).lower()
        tpl.orientation = str(body["orientation"]).lower()
        if draft_ver.mode == "CARTA":
            if draft_ver.orientation == "landscape":
                draft_ver.paper_width_mm = Decimal(str(_pfs.CARTA_HEIGHT_MM))
                draft_ver.paper_height_mm = Decimal(str(_pfs.CARTA_WIDTH_MM))
            else:
                draft_ver.paper_width_mm = Decimal(str(_pfs.CARTA_WIDTH_MM))
                draft_ver.paper_height_mm = Decimal(str(_pfs.CARTA_HEIGHT_MM))
    if "paper_width_mm" in body and body["paper_width_mm"] is not None:
        draft_ver.paper_width_mm = Decimal(str(body["paper_width_mm"]))
    if "paper_height_mm" in body and body["paper_height_mm"] is not None:
        draft_ver.paper_height_mm = Decimal(str(body["paper_height_mm"]))
    if "printable_width_mm" in body and body["printable_width_mm"] is not None:
        draft_ver.printable_width_mm = Decimal(str(body["printable_width_mm"]))
    if "margins_mm_json" in body and isinstance(body["margins_mm_json"], dict):
        draft_ver.margins_mm_json = body["margins_mm_json"]
    if "background_asset_id" in body:
        asset_id_val = body["background_asset_id"]
        if asset_id_val:
            # Verificar que el asset pertenezca a la misma empresa
            chk_asset = (
                db.query(models.PrintTemplateAsset)
                .filter(models.PrintTemplateAsset.empresa_id == empresa_id, models.PrintTemplateAsset.id == asset_id_val)
                .first()
            )
            if not chk_asset:
                raise HTTPException(status_code=403, detail="El archivo de fondo seleccionado no pertenece a esta empresa.")
        draft_ver.background_asset_id = asset_id_val
    if "background_settings_json" in body and isinstance(body["background_settings_json"], dict):
        draft_ver.background_settings_json = body["background_settings_json"]
    if "definition_json" in body and isinstance(body["definition_json"], dict):
        draft_ver.definition_json = body["definition_json"]
    if "changelog" in body and body["changelog"] is not None:
        draft_ver.changelog = str(body["changelog"])[:500]

    _, _, warnings = _pfs.validate_template_for_publish(tpl.doc_type, draft_ver.mode, draft_ver.definition_json)
    draft_ver.validation_warnings_json = warnings
    tpl.updated_by = user_id
    tpl.updated_at = now

    db.commit()
    db.refresh(tpl)
    db.refresh(draft_ver)

    _audit(db, empresa_id, sucursal_id, user_id, "PRINT_FORMAT_SAVE_DRAFT", f"Borrador v{draft_ver.version_num} guardado para '{tpl.name}'.")
    return _serialize_template(tpl, draft_ver)


@router.post("/templates/{template_id}/publish")
def publish_template(
    template_id: str,
    body: Dict[str, Any] = Body(default={}),
    db: Session = Depends(get_db),
    tenant: dict = Depends(get_tenant_context),
):
    """Publica el borrador actual haciéndolo inmutable y disponible para asignaciones operativas."""
    _check_perm(tenant, "publicar")
    empresa_id = tenant.get("empresa")
    sucursal_id = tenant.get("sucursal") or "MATRIZ"
    user_id = tenant.get("sub") or "admin"

    tpl = (
        db.query(models.PrintFormatTemplate)
        .filter(models.PrintFormatTemplate.empresa_id == empresa_id, models.PrintFormatTemplate.id == template_id)
        .first()
    )
    if not tpl:
        raise HTTPException(status_code=404, detail="Plantilla no encontrada.")

    target_ver_id = body.get("version_id") or tpl.latest_draft_version_id or tpl.active_published_version_id
    ver = (
        db.query(models.PrintFormatVersion)
        .filter(
            models.PrintFormatVersion.empresa_id == empresa_id,
            models.PrintFormatVersion.template_id == tpl.id,
            models.PrintFormatVersion.id == target_ver_id,
        )
        .first()
    )
    if not ver:
        raise HTTPException(status_code=404, detail="Versión a publicar no encontrada.")

    ok, blocking_errors, warnings = _pfs.validate_template_for_publish(tpl.doc_type, ver.mode, ver.definition_json)
    if not ok:
        raise HTTPException(
            status_code=400,
            detail={
                "message": "No se puede publicar el formato porque omite campos obligatorios.",
                "blocking_errors": blocking_errors,
                "warnings": warnings,
            },
        )

    now = _dt.datetime.now(_dt.timezone.utc)
    ver.status = "PUBLISHED"
    ver.published_by = user_id
    ver.published_at = now
    ver.validation_warnings_json = warnings
    if body.get("changelog"):
        ver.changelog = str(body["changelog"])[:500]

    tpl.status = "PUBLISHED"
    tpl.active_published_version_id = ver.id
    if tpl.latest_draft_version_id == ver.id:
        tpl.latest_draft_version_id = None
    tpl.published_at = now
    tpl.updated_by = user_id
    tpl.updated_at = now

    db.commit()
    db.refresh(tpl)
    db.refresh(ver)

    _audit(db, empresa_id, sucursal_id, user_id, "PRINT_FORMAT_PUBLISH", f"Publicada versión v{ver.version_num} de '{tpl.name}'.")
    return _serialize_template(tpl, ver)


@router.post("/templates/{template_id}/duplicate", status_code=201)
def duplicate_template(
    template_id: str,
    body: Dict[str, Any] = Body(default={}),
    db: Session = Depends(get_db),
    tenant: dict = Depends(get_tenant_context),
):
    _check_perm(tenant, "disenar")
    empresa_id = tenant.get("empresa")
    sucursal_id = tenant.get("sucursal") or "MATRIZ"
    user_id = tenant.get("sub") or "admin"

    src_tpl = (
        db.query(models.PrintFormatTemplate)
        .filter(models.PrintFormatTemplate.empresa_id == empresa_id, models.PrintFormatTemplate.id == template_id)
        .first()
    )
    if not src_tpl:
        raise HTTPException(status_code=404, detail="Plantilla origen no encontrada.")

    src_ver_id = src_tpl.latest_draft_version_id or src_tpl.active_published_version_id
    src_ver = (
        db.query(models.PrintFormatVersion)
        .filter(models.PrintFormatVersion.empresa_id == empresa_id, models.PrintFormatVersion.id == src_ver_id)
        .first()
    )

    new_name = str(body.get("name") or f"{src_tpl.name} (COPIA)").strip().upper()
    now = _dt.datetime.now(_dt.timezone.utc)
    new_tpl_id = str(uuid.uuid4())
    new_ver_id = str(uuid.uuid4())

    new_tpl = models.PrintFormatTemplate(
        id=new_tpl_id,
        empresa_id=empresa_id,
        sucursal_id=src_tpl.sucursal_id,
        code=f"COPY_{uuid.uuid4().hex[:8].upper()}",
        name=new_name,
        doc_type=src_tpl.doc_type,
        mode=src_tpl.mode,
        paper_size=src_tpl.paper_size,
        orientation=src_tpl.orientation,
        status="DRAFT",
        active_published_version_id=None,
        latest_draft_version_id=new_ver_id,
        current_version_num=1,
        is_system_seed=False,
        integration_status=src_tpl.integration_status,
        created_by=user_id,
        updated_by=user_id,
        created_at=now,
        updated_at=now,
    )
    new_ver = models.PrintFormatVersion(
        id=new_ver_id,
        empresa_id=empresa_id,
        template_id=new_tpl_id,
        version_num=1,
        status="DRAFT",
        name_snapshot=new_name,
        mode=src_ver.mode if src_ver else src_tpl.mode,
        paper_size=src_ver.paper_size if src_ver else src_tpl.paper_size,
        orientation=src_ver.orientation if src_ver else src_tpl.orientation,
        paper_width_mm=src_ver.paper_width_mm if src_ver else Decimal("215.90"),
        paper_height_mm=src_ver.paper_height_mm if src_ver else Decimal("279.40"),
        printable_width_mm=src_ver.printable_width_mm if src_ver else Decimal("215.90"),
        margins_mm_json=copy.deepcopy(src_ver.margins_mm_json if src_ver else {}),
        background_asset_id=src_ver.background_asset_id if src_ver else None,
        background_settings_json=copy.deepcopy(src_ver.background_settings_json if src_ver else {}),
        definition_json=copy.deepcopy(src_ver.definition_json if src_ver else {}),
        validation_warnings_json=[],
        changelog=f"Duplicada a partir de '{src_tpl.name}'.",
        created_by=user_id,
        created_at=now,
    )
    db.add(new_tpl)
    db.add(new_ver)
    db.commit()
    db.refresh(new_tpl)
    db.refresh(new_ver)

    _audit(db, empresa_id, sucursal_id, user_id, "PRINT_FORMAT_DUPLICATE", f"Duplicada '{src_tpl.name}' -> '{new_name}'.")
    return _serialize_template(new_tpl, new_ver)


@router.post("/templates/{template_id}/versions/{version_id}/restore")
def restore_version_to_new_draft(
    template_id: str,
    version_id: str,
    db: Session = Depends(get_db),
    tenant: dict = Depends(get_tenant_context),
):
    """Restaura una versión histórica creando un nuevo borrador (DRAFT), sin alterar ni borrar versiones previas."""
    _check_perm(tenant, "disenar")
    empresa_id = tenant.get("empresa")
    sucursal_id = tenant.get("sucursal") or "MATRIZ"
    user_id = tenant.get("sub") or "admin"

    tpl = (
        db.query(models.PrintFormatTemplate)
        .filter(models.PrintFormatTemplate.empresa_id == empresa_id, models.PrintFormatTemplate.id == template_id)
        .first()
    )
    if not tpl:
        raise HTTPException(status_code=404, detail="Plantilla no encontrada.")

    hist_ver = (
        db.query(models.PrintFormatVersion)
        .filter(
            models.PrintFormatVersion.empresa_id == empresa_id,
            models.PrintFormatVersion.template_id == tpl.id,
            models.PrintFormatVersion.id == version_id,
        )
        .first()
    )
    if not hist_ver:
        raise HTTPException(status_code=404, detail="Versión histórica no encontrada.")

    now = _dt.datetime.now(_dt.timezone.utc)
    next_vnum = int(tpl.current_version_num or 1) + 1
    new_ver_id = str(uuid.uuid4())

    new_draft = models.PrintFormatVersion(
        id=new_ver_id,
        empresa_id=empresa_id,
        template_id=tpl.id,
        version_num=next_vnum,
        status="DRAFT",
        name_snapshot=hist_ver.name_snapshot,
        mode=hist_ver.mode,
        paper_size=hist_ver.paper_size,
        orientation=hist_ver.orientation,
        paper_width_mm=hist_ver.paper_width_mm,
        paper_height_mm=hist_ver.paper_height_mm,
        printable_width_mm=hist_ver.printable_width_mm,
        margins_mm_json=copy.deepcopy(hist_ver.margins_mm_json or {}),
        background_asset_id=hist_ver.background_asset_id,
        background_settings_json=copy.deepcopy(hist_ver.background_settings_json or {}),
        definition_json=copy.deepcopy(hist_ver.definition_json or {}),
        validation_warnings_json=[],
        changelog=f"Restaurado en nuevo borrador a partir de versión v{hist_ver.version_num}.",
        created_by=user_id,
        created_at=now,
    )
    db.add(new_draft)
    tpl.latest_draft_version_id = new_ver_id
    tpl.current_version_num = next_vnum
    tpl.updated_by = user_id
    tpl.updated_at = now
    db.commit()
    db.refresh(tpl)
    db.refresh(new_draft)

    _audit(db, empresa_id, sucursal_id, user_id, "PRINT_FORMAT_RESTORE_VERSION", f"Restaurada v{hist_ver.version_num} hacia nuevo borrador v{next_vnum} en '{tpl.name}'.")
    return _serialize_template(tpl, new_draft)


@router.post("/templates/{template_id}/archive")
def archive_template(
    template_id: str,
    db: Session = Depends(get_db),
    tenant: dict = Depends(get_tenant_context),
):
    _check_perm(tenant, "publicar")
    empresa_id = tenant.get("empresa")
    sucursal_id = tenant.get("sucursal") or "MATRIZ"
    user_id = tenant.get("sub") or "admin"

    tpl = (
        db.query(models.PrintFormatTemplate)
        .filter(models.PrintFormatTemplate.empresa_id == empresa_id, models.PrintFormatTemplate.id == template_id)
        .first()
    )
    if not tpl:
        raise HTTPException(status_code=404, detail="Plantilla no encontrada.")

    tpl.status = "ARCHIVED"
    tpl.updated_by = user_id
    tpl.updated_at = _dt.datetime.now(_dt.timezone.utc)
    db.commit()
    _audit(db, empresa_id, sucursal_id, user_id, "PRINT_FORMAT_ARCHIVE", f"Archivada plantilla '{tpl.name}'.")
    return _serialize_template(tpl)


# ══════════════════════════════════════════════════════════════════════════════
# 3. SUBIDA Y CONSULTA PROTEGIDA DE ARCHIVOS DE FONDO (PDF / PNG / JPG)
# ══════════════════════════════════════════════════════════════════════════════

@router.post("/assets/upload", status_code=201)
async def upload_background_or_image_asset(
    file: UploadFile = File(...),
    kind: str = Form("BACKGROUND"),
    db: Session = Depends(get_db),
    tenant: dict = Depends(get_tenant_context),
):
    _check_perm(tenant, "disenar")
    empresa_id = tenant.get("empresa")
    sucursal_id = tenant.get("sucursal") or "MATRIZ"
    user_id = tenant.get("sub") or "admin"

    content = await file.read()
    try:
        asset = _pfs.store_and_inspect_asset(
            db=db,
            empresa_id=empresa_id,
            sucursal_id=sucursal_id,
            user_id=user_id,
            original_filename=file.filename or "fondo.pdf",
            content=content,
            kind=kind,
        )
    except _pfs.PrintFormatError as exc:
        raise HTTPException(status_code=exc.status_code, detail={"message": exc.message, "code": exc.code}) from exc

    _audit(
        db,
        empresa_id,
        sucursal_id,
        user_id,
        "PRINT_FORMAT_ASSET_UPLOAD",
        f"Subido activo '{asset.original_filename}' ({asset.kind}, {asset.page_count} pág., {asset.size_bytes} bytes).",
    )
    return _serialize_asset(asset)


@router.get("/assets")
def list_assets(
    db: Session = Depends(get_db),
    tenant: dict = Depends(get_tenant_context),
):
    _check_perm(tenant, "consultar")
    empresa_id = tenant.get("empresa")
    rows = (
        db.query(models.PrintTemplateAsset)
        .filter(models.PrintTemplateAsset.empresa_id == empresa_id)
        .order_by(models.PrintTemplateAsset.created_at.desc())
        .all()
    )
    return {"assets": [_serialize_asset(a) for a in rows]}


@router.get("/assets/{asset_id}/page/{page_num}")
def get_asset_page_preview(
    asset_id: str,
    page_num: int,
    db: Session = Depends(get_db),
    tenant: dict = Depends(get_tenant_context),
):
    _check_perm(tenant, "consultar")
    empresa_id = tenant.get("empresa")
    asset = (
        db.query(models.PrintTemplateAsset)
        .filter(models.PrintTemplateAsset.empresa_id == empresa_id, models.PrintTemplateAsset.id == asset_id)
        .first()
    )
    if not asset:
        raise HTTPException(status_code=404, detail="Archivo de fondo no encontrado o pertenece a otra empresa.")

    pages_meta = asset.pages_meta or []
    pmeta = next((m for m in pages_meta if int(m.get("page") or 1) == page_num), None)
    if not pmeta:
        raise HTTPException(status_code=404, detail=f"La página {page_num} no existe en este archivo.")

    abs_path = os.path.abspath(os.path.join(_pfs.MEDIA_PRINT_ROOT, pmeta["preview_rel_path"]))
    if not abs_path.startswith(os.path.abspath(_pfs.MEDIA_PRINT_ROOT)) or not os.path.isfile(abs_path):
        raise HTTPException(status_code=404, detail="Archivo de previsualización no disponible.")

    return FileResponse(abs_path, media_type="image/png")


@router.get("/assets/{asset_id}/original")
def get_asset_original_file(
    asset_id: str,
    db: Session = Depends(get_db),
    tenant: dict = Depends(get_tenant_context),
):
    _check_perm(tenant, "consultar")
    empresa_id = tenant.get("empresa")
    asset = (
        db.query(models.PrintTemplateAsset)
        .filter(models.PrintTemplateAsset.empresa_id == empresa_id, models.PrintTemplateAsset.id == asset_id)
        .first()
    )
    if not asset:
        raise HTTPException(status_code=404, detail="Archivo original no encontrado o pertenece a otra empresa.")

    abs_path = os.path.abspath(os.path.join(_pfs.MEDIA_PRINT_ROOT, asset.storage_rel_path))
    if not abs_path.startswith(os.path.abspath(_pfs.MEDIA_PRINT_ROOT)) or not os.path.isfile(abs_path):
        raise HTTPException(status_code=404, detail="Archivo original no encontrado en almacenamiento.")

    return FileResponse(abs_path, media_type=asset.mime_type, filename=asset.original_filename)


# ══════════════════════════════════════════════════════════════════════════════
# 4. ASIGNACIÓN DETERMINISTA (TERMINAL -> SUCURSAL -> EMPRESA) Y REGLAS
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/assignments")
def list_assignments(
    doc_type: Optional[str] = Query(None),
    sucursal_id: Optional[str] = Query(None),
    terminal_id: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    tenant: dict = Depends(get_tenant_context),
):
    _check_perm(tenant, "consultar")
    empresa_id = tenant.get("empresa")
    q = db.query(models.PrintFormatAssignment).filter(models.PrintFormatAssignment.empresa_id == empresa_id)
    if doc_type:
        q = q.filter(models.PrintFormatAssignment.doc_type == doc_type)
    rows = q.order_by(models.PrintFormatAssignment.updated_at.desc()).all()

    out = []
    for r in rows:
        tpl = db.query(models.PrintFormatTemplate).filter(models.PrintFormatTemplate.id == r.template_id).first()
        ver = db.query(models.PrintFormatVersion).filter(models.PrintFormatVersion.id == r.published_version_id).first()
        out.append({
            "id": r.id,
            "empresa_id": r.empresa_id,
            "sucursal_id": r.sucursal_id,
            "terminal_id": r.terminal_id,
            "doc_type": r.doc_type,
            "doc_type_name": (_pfs.DOC_TYPES_MAP.get(r.doc_type) or {}).get("name", r.doc_type),
            "mode": r.mode,
            "role_target": r.role_target,
            "template_id": r.template_id,
            "template_name": tpl.name if tpl else "",
            "published_version_id": r.published_version_id,
            "version_num": ver.version_num if ver else 1,
            "printer_num": r.printer_num,
            "printer_name": r.printer_name,
            "copies": r.copies,
            "print_background": bool(r.print_background),
            "active": bool(r.active),
            "updated_by": r.updated_by,
            "updated_at": r.updated_at.isoformat() if r.updated_at else None,
        })

    resolved = None
    if doc_type:
        eff = _pfs.resolve_effective_assignment(
            db, empresa_id, doc_type, sucursal_id=sucursal_id or tenant.get("sucursal"), terminal_id=terminal_id
        )
        if eff:
            resolved = eff.id

    return {
        "assignments": out,
        "resolved_assignment_id": resolved,
        "precedence_rule": "TERMINAL -> SUCURSAL -> EMPRESA -> PREDETERMINADO COMPATIBLE",
    }


@router.post("/assignments")
def upsert_assignment(
    body: Dict[str, Any] = Body(...),
    db: Session = Depends(get_db),
    tenant: dict = Depends(get_tenant_context),
):
    _check_perm(tenant, "asignar")
    empresa_id = tenant.get("empresa")
    user_id = tenant.get("sub") or "admin"

    template_id = str(body.get("template_id") or "").strip()
    doc_type = str(body.get("doc_type") or "").strip()
    if not template_id or not doc_type:
        raise HTTPException(status_code=400, detail="Debes indicar el tipo de documento y la plantilla publicada.")

    tpl = (
        db.query(models.PrintFormatTemplate)
        .filter(models.PrintFormatTemplate.empresa_id == empresa_id, models.PrintFormatTemplate.id == template_id)
        .first()
    )
    if not tpl:
        raise HTTPException(status_code=404, detail="Plantilla no encontrada para esta empresa.")

    pub_ver_id = body.get("published_version_id") or tpl.active_published_version_id
    if not pub_ver_id:
        raise HTTPException(
            status_code=400,
            detail="Solo se pueden asignar plantillas que tengan una versión PUBLICADA. Publica primero el borrador.",
        )

    pub_ver = (
        db.query(models.PrintFormatVersion)
        .filter(
            models.PrintFormatVersion.empresa_id == empresa_id,
            models.PrintFormatVersion.id == pub_ver_id,
            models.PrintFormatVersion.status == "PUBLISHED",
        )
        .first()
    )
    if not pub_ver:
        raise HTTPException(status_code=400, detail="La versión seleccionada no está publicada.")

    # Validar compatibilidad entre formato de plantilla e impresora si se envía printer_paper_width
    printer_paper = str(body.get("printer_paper") or "").strip().lower()
    if printer_paper:
        if pub_ver.mode == "CARTA" and ("58mm" in printer_paper or "80mm" in printer_paper):
            raise HTTPException(
                status_code=400,
                detail=f"Incompatibilidad de papel: No puedes asignar un formato CARTA a una impresora térmica de rollo ({printer_paper}).",
            )
        if pub_ver.mode == "TICKET" and "carta" in printer_paper:
            raise HTTPException(
                status_code=400,
                detail="Incompatibilidad de papel: No puedes asignar un formato TICKET térmico a una impresora configurada exclusivamente para hojas Carta.",
            )

    suc_scope = (str(body.get("sucursal_id")).strip() if body.get("sucursal_id") else None) or None
    term_scope = (str(body.get("terminal_id")).strip() if body.get("terminal_id") else None) or None
    role_target = str(body.get("role_target") or "CLIENTE").strip().upper()

    existing = (
        db.query(models.PrintFormatAssignment)
        .filter(
            models.PrintFormatAssignment.empresa_id == empresa_id,
            models.PrintFormatAssignment.doc_type == doc_type,
            models.PrintFormatAssignment.sucursal_id == suc_scope,
            models.PrintFormatAssignment.terminal_id == term_scope,
            models.PrintFormatAssignment.role_target == role_target,
        )
        .first()
    )

    now = _dt.datetime.now(_dt.timezone.utc)
    if existing:
        existing.template_id = tpl.id
        existing.published_version_id = pub_ver.id
        existing.mode = pub_ver.mode
        existing.printer_num = str(body.get("printer_num") or "")
        existing.printer_name = str(body.get("printer_name") or "")
        existing.copies = max(1, min(10, int(body.get("copies") or 1)))
        existing.print_background = bool(body.get("print_background", True))
        existing.active = True
        existing.updated_by = user_id
        existing.updated_at = now
        row = existing
    else:
        row = models.PrintFormatAssignment(
            id=str(uuid.uuid4()),
            empresa_id=empresa_id,
            sucursal_id=suc_scope,
            terminal_id=term_scope,
            doc_type=doc_type,
            mode=pub_ver.mode,
            role_target=role_target,
            template_id=tpl.id,
            published_version_id=pub_ver.id,
            printer_num=str(body.get("printer_num") or ""),
            printer_name=str(body.get("printer_name") or ""),
            copies=max(1, min(10, int(body.get("copies") or 1))),
            print_background=bool(body.get("print_background", True)),
            active=True,
            updated_by=user_id,
            updated_at=now,
        )
        db.add(row)

    db.commit()
    db.refresh(row)

    _audit(
        db,
        empresa_id,
        suc_scope or (tenant.get("sucursal") or "MATRIZ"),
        user_id,
        "PRINT_FORMAT_ASSIGN",
        f"Asignada plantilla '{tpl.name}' (v{pub_ver.version_num}) a doc='{doc_type}', suc='{suc_scope or 'TODAS'}', term='{term_scope or 'TODAS'}', destino='{role_target}'.",
    )
    return {"ok": True, "assignment_id": row.id}


@router.delete("/assignments/{assignment_id}")
def delete_assignment(
    assignment_id: str,
    db: Session = Depends(get_db),
    tenant: dict = Depends(get_tenant_context),
):
    _check_perm(tenant, "asignar")
    empresa_id = tenant.get("empresa")
    row = (
        db.query(models.PrintFormatAssignment)
        .filter(models.PrintFormatAssignment.empresa_id == empresa_id, models.PrintFormatAssignment.id == assignment_id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Asignación no encontrada.")
    db.delete(row)
    db.commit()
    return {"ok": True}


# ══════════════════════════════════════════════════════════════════════════════
# 5. VISTA PREVIA COMPARTIDA, GENERACIÓN DE PDF REAL E IMPRESIÓN / REIMPRESIÓN
# ══════════════════════════════════════════════════════════════════════════════

@router.post("/preview")
def preview_template_execution(
    body: Dict[str, Any] = Body(...),
    db: Session = Depends(get_db),
    tenant: dict = Depends(get_tenant_context),
):
    _check_perm(tenant, "consultar")
    empresa_id = tenant.get("empresa")

    template_id = body.get("template_id")
    version_id = body.get("version_id")
    operation_id = body.get("operation_id")
    multi_page_demo = bool(body.get("multi_page_demo", False))

    ver = None
    tpl = None
    if template_id:
        tpl = (
            db.query(models.PrintFormatTemplate)
            .filter(models.PrintFormatTemplate.empresa_id == empresa_id, models.PrintFormatTemplate.id == template_id)
            .first()
        )
        if not tpl:
            raise HTTPException(status_code=404, detail="Plantilla no encontrada para esta empresa.")
        vid = version_id or tpl.latest_draft_version_id or tpl.active_published_version_id
        ver = (
            db.query(models.PrintFormatVersion)
            .filter(models.PrintFormatVersion.empresa_id == empresa_id, models.PrintFormatVersion.id == vid)
            .first()
        )
    if not ver:
        raise HTTPException(status_code=404, detail="Versión de plantilla no encontrada.")

    doc_type = tpl.doc_type if tpl else str(body.get("doc_type") or "ticket_venta_contado")
    try:
        if operation_id:
            context = _pfs.build_real_operation_context(db, empresa_id, doc_type, str(operation_id))
        else:
            context = _pfs.build_demo_context(doc_type, multi_page_demo=multi_page_demo)
    except _pfs.PrintFormatError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

    pagination = _pfs.paginate_template_definition(ver, context)

    # Resolver valores de cada elemento por página usando el mismo motor que usa el PDF
    resolved_pages = []
    for p in pagination["pages"]:
        resolved_els = []
        for el in p["elements"]:
            if not _pfs.evaluate_visual_condition(el.get("condition"), context):
                continue
            el_copy = copy.deepcopy(el)
            if el.get("field_key") and not el.get("text"):
                el_copy["resolved_text"] = _pfs.resolve_field_value(context, str(el["field_key"]), el.get("format_options"))
            else:
                el_copy["resolved_text"] = _pfs.evaluate_safe_template_text(
                    str(el.get("text") or el.get("label") or ""), context, el.get("format_options")
                )
            resolved_els.append(el_copy)
        resolved_pages.append({
            "page_number": p["page_number"],
            "background_source_page": p.get("background_source_page"),
            "is_last_page": p["is_last_page"],
            "elements": resolved_els,
            "table_slice": p.get("table_slice") or p.get("table_rows") or [],
        })

    return {
        "template_id": tpl.id if tpl else None,
        "version_id": ver.id,
        "version_num": ver.version_num,
        "mode": ver.mode,
        "is_demo_data": bool(context.get("_is_demo", True)),
        "total_pages": pagination["total_pages"],
        "paper_width_mm": pagination["paper_width_mm"],
        "paper_height_mm": pagination.get("paper_height_mm", 279.4),
        "pages": resolved_pages,
        "context_summary": {
            "folio": context["operacion"]["folio"],
            "cliente": context["cliente"]["nombre"],
            "total": context["importes"]["total"],
            "items_count": len(context.get("productos") or []),
        },
    }


@router.post("/pdf")
def generate_template_pdf_endpoint(
    body: Dict[str, Any] = Body(...),
    db: Session = Depends(get_db),
    tenant: dict = Depends(get_tenant_context),
):
    _check_perm(tenant, "imprimir")
    empresa_id = tenant.get("empresa")

    template_id = body.get("template_id")
    version_id = body.get("version_id")
    operation_id = body.get("operation_id")
    include_background = body.get("include_background")
    multi_page_demo = bool(body.get("multi_page_demo", False))

    tpl = (
        db.query(models.PrintFormatTemplate)
        .filter(models.PrintFormatTemplate.empresa_id == empresa_id, models.PrintFormatTemplate.id == template_id)
        .first()
    )
    if not tpl:
        raise HTTPException(status_code=404, detail="Plantilla no encontrada o pertenece a otra empresa.")

    vid = version_id or tpl.latest_draft_version_id or tpl.active_published_version_id
    ver = (
        db.query(models.PrintFormatVersion)
        .filter(models.PrintFormatVersion.empresa_id == empresa_id, models.PrintFormatVersion.id == vid)
        .first()
    )
    if not ver:
        raise HTTPException(status_code=404, detail="Versión no encontrada.")

    if operation_id:
        context = _pfs.build_real_operation_context(db, empresa_id, tpl.doc_type, str(operation_id))
    else:
        context = _pfs.build_demo_context(tpl.doc_type, multi_page_demo=multi_page_demo)

    pdf_bytes = _pfs.generate_pdf_bytes(
        db=db,
        empresa_id=empresa_id,
        version_obj=ver,
        context=context,
        include_background=include_background,
    )
    mode_suffix = "SOLO_CAMPOS" if include_background is False else "COMPLETO"
    fname = f"{tpl.code}_v{ver.version_num}_{mode_suffix}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{fname}"'},
    )


@router.post("/emissions", status_code=201)
def record_document_emission(
    body: Dict[str, Any] = Body(...),
    db: Session = Depends(get_db),
    tenant: dict = Depends(get_tenant_context),
):
    """Registra la emisión histórica de un documento conservando la versión exacta de la plantilla
    y el snapshot de datos originales del momento de emisión."""
    _check_perm(tenant, "imprimir")
    empresa_id = tenant.get("empresa")
    sucursal_id = tenant.get("sucursal") or "MATRIZ"
    user_id = tenant.get("sub") or "cajero"

    doc_type = str(body.get("doc_type") or "ticket_venta_contado")
    operation_id = str(body.get("operation_id") or f"OP-{uuid.uuid4().hex[:8].upper()}")
    template_id = body.get("template_id")

    if not template_id:
        asig = _pfs.resolve_effective_assignment(db, empresa_id, doc_type, sucursal_id=sucursal_id)
        if asig:
            template_id = asig.template_id
            version_id = asig.published_version_id
        else:
            seeds = _pfs.ensure_seed_templates(db, empresa_id, user_id)
            match_t = next((t for t in seeds if t.doc_type == doc_type), seeds[0])
            template_id = match_t.id
            version_id = match_t.active_published_version_id
    else:
        tpl = (
            db.query(models.PrintFormatTemplate)
            .filter(models.PrintFormatTemplate.empresa_id == empresa_id, models.PrintFormatTemplate.id == template_id)
            .first()
        )
        if not tpl:
            raise HTTPException(status_code=404, detail="Plantilla no encontrada.")
        version_id = body.get("version_id") or tpl.active_published_version_id or tpl.latest_draft_version_id

    ver = (
        db.query(models.PrintFormatVersion)
        .filter(models.PrintFormatVersion.empresa_id == empresa_id, models.PrintFormatVersion.id == version_id)
        .first()
    )
    if not ver:
        raise HTTPException(status_code=404, detail="Versión de plantilla no encontrada.")

    snapshot = body.get("data_snapshot_json")
    if not snapshot:
        try:
            snapshot = _pfs.build_real_operation_context(db, empresa_id, doc_type, operation_id)
        except Exception:
            snapshot = _pfs.build_demo_context(doc_type)

    rec = models.PrintEmissionRecord(
        id=str(uuid.uuid4()),
        empresa_id=empresa_id,
        sucursal_id=sucursal_id,
        doc_type=doc_type,
        operation_id=operation_id,
        operation_folio=str((snapshot.get("operacion") or {}).get("folio") or operation_id),
        template_id=ver.template_id,
        version_id=ver.id,
        version_num=ver.version_num,
        mode=ver.mode,
        data_snapshot_json=snapshot,
        emitted_by=user_id,
    )
    db.add(rec)
    db.commit()
    db.refresh(rec)
    return {
        "emission_id": rec.id,
        "operation_id": rec.operation_id,
        "operation_folio": rec.operation_folio,
        "template_id": rec.template_id,
        "version_id": rec.version_id,
        "version_num": rec.version_num,
        "emitted_at": rec.emitted_at.isoformat() if rec.emitted_at else None,
    }


@router.get("/emissions")
def list_emissions(
    operation_id: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    tenant: dict = Depends(get_tenant_context),
):
    _check_perm(tenant, "consultar")
    empresa_id = tenant.get("empresa")
    q = db.query(models.PrintEmissionRecord).filter(models.PrintEmissionRecord.empresa_id == empresa_id)
    if operation_id:
        q = q.filter(
            (models.PrintEmissionRecord.operation_id == operation_id)
            | (models.PrintEmissionRecord.operation_folio == operation_id)
        )
    rows = q.order_by(models.PrintEmissionRecord.emitted_at.desc()).limit(50).all()
    return {
        "emissions": [
            {
                "id": r.id,
                "doc_type": r.doc_type,
                "operation_id": r.operation_id,
                "operation_folio": r.operation_folio,
                "template_id": r.template_id,
                "version_id": r.version_id,
                "version_num": r.version_num,
                "mode": r.mode,
                "emitted_by": r.emitted_by,
                "emitted_at": r.emitted_at.isoformat() if r.emitted_at else None,
                "reprint_count": r.reprint_count,
                "last_reprinted_at": r.last_reprinted_at.isoformat() if r.last_reprinted_at else None,
            }
            for r in rows
        ]
    }


@router.post("/emissions/{emission_id}/reprint")
def reprint_emission(
    emission_id: str,
    body: Dict[str, Any] = Body(default={}),
    db: Session = Depends(get_db),
    tenant: dict = Depends(get_tenant_context),
):
    """Distingue claramente entre:
    - `reprint_mode = 'historical'` (por defecto): Reimprime el documento emitido usando EXACTAMENTE
      la versión histórica de la plantilla (`rec.version_id`) y el snapshot de datos originales (`rec.data_snapshot_json`).
    - `reprint_mode = 'updated'`: Genera un documento actualizado con la plantilla publicada actual y datos vigentes."""
    _check_perm(tenant, "imprimir")
    empresa_id = tenant.get("empresa")
    user_id = tenant.get("sub") or "cajero"

    rec = (
        db.query(models.PrintEmissionRecord)
        .filter(models.PrintEmissionRecord.empresa_id == empresa_id, models.PrintEmissionRecord.id == emission_id)
        .first()
    )
    if not rec:
        raise HTTPException(status_code=404, detail="Registro histórico de emisión no encontrado.")

    reprint_mode = str(body.get("reprint_mode") or "historical").lower()
    if reprint_mode == "historical":
        ver = (
            db.query(models.PrintFormatVersion)
            .filter(models.PrintFormatVersion.empresa_id == empresa_id, models.PrintFormatVersion.id == rec.version_id)
            .first()
        )
        if not ver:
            raise HTTPException(status_code=404, detail="La versión histórica original no fue encontrada.")
        context = copy.deepcopy(rec.data_snapshot_json or {})
        rec.reprint_count = int(rec.reprint_count or 0) + 1
        rec.last_reprinted_at = _dt.datetime.now(_dt.timezone.utc)
        db.commit()
    else:
        tpl = (
            db.query(models.PrintFormatTemplate)
            .filter(models.PrintFormatTemplate.empresa_id == empresa_id, models.PrintFormatTemplate.id == rec.template_id)
            .first()
        )
        vid = (tpl.active_published_version_id if tpl else None) or rec.version_id
        ver = (
            db.query(models.PrintFormatVersion)
            .filter(models.PrintFormatVersion.empresa_id == empresa_id, models.PrintFormatVersion.id == vid)
            .first()
        )
        try:
            context = _pfs.build_real_operation_context(db, empresa_id, rec.doc_type, rec.operation_id)
        except Exception:
            context = copy.deepcopy(rec.data_snapshot_json or {})

    pagination = _pfs.paginate_template_definition(ver, context)
    _audit(
        db,
        empresa_id,
        rec.sucursal_id or "MATRIZ",
        user_id,
        "PRINT_FORMAT_REPRINT",
        f"Reimpresión ({reprint_mode}) de folio '{rec.operation_folio}' usando versión v{ver.version_num}.",
    )
    return {
        "emission_id": rec.id,
        "reprint_mode": reprint_mode,
        "used_version_id": ver.id,
        "used_version_num": ver.version_num,
        "reprint_count": rec.reprint_count,
        "data_snapshot_preserved": (reprint_mode == "historical"),
        "context": context,
        "pagination": pagination,
        "version": _serialize_version(ver),
    }
