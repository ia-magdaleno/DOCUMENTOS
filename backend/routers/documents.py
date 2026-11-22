"""Router FastAPI del Módulo «Centro de Documentos» (Documentos · Consulta e impresión).

Valida en servidor empresa, sucursales autorizadas, rol y permisos por acción en cada endpoint:
listado, contadores, expediente, vista previa, miniatura, descarga, adjuntos, lote ZIP, exportación,
reporte imprimible, envíos idempotentes y enlaces temporales revocables.
"""
from __future__ import annotations

import base64
import datetime as _dt
import hashlib
import os
import secrets
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, Query, Response, UploadFile
from sqlalchemy import asc, desc, func, or_
from sqlalchemy.orm import Session

import models
from database import get_db
from deps import get_tenant_context
from services import print_formats_service as _pfs
from services.document_center_catalog import (
    CATEGORY_LABELS,
    DOCUMENT_CATEGORIES_TREE,
    SUBTYPE_META_MAP,
    audit_doc_event,
    build_document_activity,
    build_related_documents,
    build_safe_download_filename,
    expand_branch_filter_values,
    get_branch_timezones_map,
    get_user_doc_permissions,
    resolve_allowed_branches,
    resolve_movement_route,
    resolve_tz_for_branch,
    sync_document_registry_for_tenant,
    to_branch_local_dt,
    validate_attachment_upload,
)
from services.document_center_render import (
    MEDIA_DOC_CENTER_ROOT,
    build_batch_zip,
    build_dispatch_preview,
    execute_dispatch_operation,
    export_documents_dataset,
    get_channels_availability,
    get_session_company_profile,
    refresh_uncertain_dispatch_status,
    render_lazy_thumbnail_png,
    render_pdf_page_png,
    resolve_document_pdf_and_meta,
    resolve_xml_or_acuse_bytes,
    retry_failed_dispatch_items,
)

router = APIRouter(prefix="/api/documents", tags=["documents"])


# ══════════════════════════════════════════════════════════════════════════════
# HELPERS INTERNOS DE SESIÓN, PREFERENCIAS Y FILTRADO EN SERVIDOR
# ══════════════════════════════════════════════════════════════════════════════

def _user_key(tenant: dict) -> str:
    return str(tenant.get("sub") or tenant.get("user_id") or "usuario").strip()


def _get_or_create_prefs(db: Session, empresa_id: str, user_key: str) -> models.DocumentUserPreference:
    pref = (
        db.query(models.DocumentUserPreference)
        .filter(
            models.DocumentUserPreference.empresa_id == empresa_id,
            models.DocumentUserPreference.user_id == user_key,
        )
        .first()
    )
    if not pref:
        pref = models.DocumentUserPreference(
            id=str(uuid.uuid4()),
            empresa_id=empresa_id,
            user_id=user_key,
            favorites_json=[],
            recents_json=[],
            saved_views_json=[],
            ui_prefs_json={
                "density": "comfortable",
                "view_mode": "list",
                "drawer_width": 440,
                "library_collapsed": False,
                "columns": ["folio", "tercero", "sucursal", "emision", "total", "estado"],
            },
        )
        db.add(pref)
        db.commit()
        db.refresh(pref)
    return pref


def _get_authorized_entry(
    db: Session,
    tenant: dict,
    perms: Dict[str, Any],
    doc_ref: str,
) -> models.DocumentRegistryEntry:
    if not perms.get("view"):
        raise HTTPException(status_code=403, detail="Tu rol no tiene permiso de consulta en el Centro de Documentos.")

    empresa_id = str(tenant.get("empresa") or "").strip()
    ref_clean = str(doc_ref or "").strip()

    entry = (
        db.query(models.DocumentRegistryEntry)
        .filter(
            models.DocumentRegistryEntry.empresa_id == empresa_id,
            or_(
                models.DocumentRegistryEntry.id == ref_clean,
                models.DocumentRegistryEntry.doc_key == ref_clean,
            ),
        )
        .first()
    )
    if not entry:
        raise HTTPException(status_code=404, detail="Documento no encontrado en la empresa activa.")

    allowed_cats = set(perms.get("categories") or [])
    if entry.category not in allowed_cats:
        raise HTTPException(
            status_code=403,
            detail=f"Tu rol no cuenta con autorización para consultar documentos de '{CATEGORY_LABELS.get(entry.category, entry.category)}'.",
        )

    can_all, allowed_branches, _ = resolve_allowed_branches(db, tenant, perms)
    if not can_all:
        allowed_upper = {b.upper() for b in allowed_branches}
        if (entry.sucursal_id or "").upper() not in allowed_upper:
            raise HTTPException(
                status_code=403,
                detail="No tienes autorización para consultar documentos emitidos en otra sucursal.",
            )

    if entry.category == "rrhh":
        audit_doc_event(
            db,
            empresa_id,
            entry.sucursal_id,
            _user_key(tenant),
            "DOC_CENTER_RH_ACCESS",
            {"doc_key": entry.doc_key, "folio": entry.folio_visible, "channel": "EXPEDIENTE", "result": "Acceso autorizado RRHH"},
        )

    return entry


def _serialize_list_item(
    entry: models.DocumentRegistryEntry,
    perms: Dict[str, Any],
    favorites_set: set,
) -> Dict[str, Any]:
    st_meta = SUBTYPE_META_MAP.get(entry.doc_subtype, {})
    view_amounts = bool(perms.get("view_amounts"))

    if not entry.amount_applicable:
        amt_state = "NOT_APPLICABLE"
        total_out = None
        sub_out = None
        tax_out = None
    elif not view_amounts:
        amt_state = "REDACTED"
        total_out = None
        sub_out = None
        tax_out = None
    else:
        amt_state = "ZERO" if abs(float(entry.total_amount or 0.0)) < 0.0001 else "VALUE"
        total_out = round(float(entry.total_amount or 0.0), 2)
        sub_out = round(float(entry.subtotal or 0.0), 2) if entry.subtotal is not None else None
        tax_out = round(float(entry.tax_amount or 0.0), 2) if entry.tax_amount is not None else None

    fmts = list(st_meta.get("formats") or ["CARTA", "TICKET"])
    if entry.has_xml and "XML" not in fmts and view_amounts:
        fmts.append("XML")
    if entry.has_acuse and "ACUSE" not in fmts and view_amounts:
        fmts.append("ACUSE")
    if not view_amounts:
        fmts = [f for f in fmts if f not in ("XML", "ACUSE")]
        if entry.amount_applicable and not st_meta.get("non_monetary_safe"):
            fmts = []

    emitted_local_str = ""
    if entry.emitted_at:
        try:
            from zoneinfo import ZoneInfo
            loc = entry.emitted_at.astimezone(ZoneInfo(entry.branch_tz or "America/Mazatlan"))
            emitted_local_str = loc.strftime("%Y-%m-%d %H:%M")
        except Exception:
            emitted_local_str = entry.emitted_at.strftime("%Y-%m-%d %H:%M")

    return {
        "id": entry.id,
        "doc_key": entry.doc_key,
        "category": entry.category,
        "category_label": CATEGORY_LABELS.get(entry.category, entry.category),
        "doc_subtype": entry.doc_subtype,
        "subtype_label": st_meta.get("short") or entry.doc_subtype,
        "subtype_full_label": st_meta.get("label") or entry.doc_subtype,
        "icon": st_meta.get("icon") or "fa-file-lines",
        "doc_nature": entry.doc_nature,
        "serie": entry.serie,
        "folio_visible": entry.folio_visible,
        "sucursal_id": entry.sucursal_id,
        "caja_id": entry.caja_id,
        "emisor_user_id": entry.emisor_user_id,
        "emisor_nombre": entry.emisor_nombre,
        "tercero_tipo": entry.tercero_tipo,
        "tercero_nombre": entry.tercero_nombre,
        "tercero_rfc": entry.tercero_rfc,
        "uuid_fiscal": entry.uuid_fiscal,
        "reference_text": entry.reference_text,
        "currency": entry.currency,
        "amount_applicable": bool(entry.amount_applicable),
        "amount_state": amt_state,  # VALUE | ZERO | NOT_APPLICABLE | REDACTED
        "subtotal": sub_out,
        "tax_amount": tax_out,
        "total_amount": total_out,
        "doc_status": entry.doc_status,
        "payment_status": entry.payment_status,
        "fiscal_status": entry.fiscal_status,
        "dispatch_status": entry.dispatch_status,
        "cancel_reason": entry.cancel_reason,
        "emitted_at": entry.emitted_at.isoformat() if entry.emitted_at else None,
        "emitted_local": emitted_local_str,
        "emitted_local_date": entry.emitted_local_date,
        "branch_tz": entry.branch_tz,
        "has_original_file": bool(entry.has_original_file),
        "has_xml": bool(entry.has_xml and view_amounts),
        "has_acuse": bool(entry.has_acuse and view_amounts),
        "attachments_count": int(entry.attachments_count or 0),
        "available_formats": fmts,
        "is_favorite": entry.doc_key in favorites_set,
    }


def _build_filtered_query(
    db: Session,
    tenant: dict,
    perms: Dict[str, Any],
    pref: models.DocumentUserPreference,
    q: Optional[str] = None,
    view_preset: Optional[str] = None,
    category: Optional[str] = None,
    doc_subtype: Optional[str] = None,
    sucursal_id: Optional[str] = None,
    emisor: Optional[str] = None,
    doc_nature: Optional[str] = None,
    currency: Optional[str] = None,
    importe_min: Optional[float] = None,
    importe_max: Optional[float] = None,
    doc_status: Optional[str] = None,
    payment_status: Optional[str] = None,
    fiscal_status: Optional[str] = None,
    dispatch_status: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
):
    empresa_id = str(tenant.get("empresa") or "").strip()
    allowed_cats = list(perms.get("categories") or [])
    if not allowed_cats:
        return db.query(models.DocumentRegistryEntry).filter(models.DocumentRegistryEntry.id == "__NONE__"), None

    can_all, allowed_branches, _ = resolve_allowed_branches(db, tenant, perms)

    query = db.query(models.DocumentRegistryEntry).filter(
        models.DocumentRegistryEntry.empresa_id == empresa_id,
        models.DocumentRegistryEntry.category.in_(allowed_cats),
    )

    effective_suc = None
    if not can_all:
        # Forzar alcance estricto a las sucursales autorizadas de la sesión
        if sucursal_id and sucursal_id.upper() != "ALL":
            req_vals = expand_branch_filter_values(db, empresa_id, sucursal_id)
            allowed_upper = {b.upper() for b in allowed_branches}
            valid_vals = [v for v in req_vals if v.upper() in allowed_upper]
            if not valid_vals:
                raise HTTPException(status_code=403, detail="No tienes autorización para filtrar otra sucursal.")
            query = query.filter(models.DocumentRegistryEntry.sucursal_id.in_(valid_vals))
            effective_suc = sucursal_id
        else:
            query = query.filter(models.DocumentRegistryEntry.sucursal_id.in_(allowed_branches))
            effective_suc = allowed_branches[0] if allowed_branches else tenant.get("sucursal")
    else:
        if sucursal_id and sucursal_id.upper() != "ALL":
            req_vals = expand_branch_filter_values(db, empresa_id, sucursal_id)
            query = query.filter(models.DocumentRegistryEntry.sucursal_id.in_(req_vals))
            effective_suc = sucursal_id

    if view_preset == "favorites":
        favs = list(pref.favorites_json or [])
        query = query.filter(models.DocumentRegistryEntry.doc_key.in_(favs or ["__NONE__"]))
    elif view_preset == "recents":
        recs = [r.get("doc_key") for r in (pref.recents_json or []) if isinstance(r, dict) and r.get("doc_key")]
        query = query.filter(models.DocumentRegistryEntry.doc_key.in_(recs or ["__NONE__"]))

    if category and category.lower() not in ("all", "todos"):
        cat_l = category.strip().lower()
        if cat_l not in allowed_cats:
            raise HTTPException(status_code=403, detail=f"Sin acceso a la categoría '{category}'.")
        query = query.filter(models.DocumentRegistryEntry.category == cat_l)
        if cat_l == "rrhh":
            audit_doc_event(
                db, empresa_id, effective_suc or "MATRIZ", _user_key(tenant),
                "DOC_CENTER_RH_ACCESS",
                {"channel": "LISTADO_RRHH", "result": "Consulta de listado RRHH autorizada"},
            )

    if doc_subtype and doc_subtype.lower() not in ("all", "todos"):
        st_l = doc_subtype.strip().lower()
        st_meta = SUBTYPE_META_MAP.get(st_l)
        if st_meta and st_meta["category"] not in allowed_cats:
            raise HTTPException(status_code=403, detail="Sin acceso a este tipo documental.")
        query = query.filter(models.DocumentRegistryEntry.doc_subtype == st_l)

    if q and q.strip():
        tokens = [t.strip().upper() for t in q.strip().split() if t.strip()]
        for tok in tokens[:6]:
            like_pat = f"%{tok}%"
            query = query.filter(
                or_(
                    models.DocumentRegistryEntry.search_blob.ilike(like_pat),
                    models.DocumentRegistryEntry.folio_visible.ilike(like_pat),
                    models.DocumentRegistryEntry.uuid_fiscal.ilike(like_pat),
                    models.DocumentRegistryEntry.tercero_rfc.ilike(like_pat),
                    models.DocumentRegistryEntry.tercero_nombre.ilike(like_pat),
                )
            )

    if emisor and emisor.strip():
        em_pat = f"%{emisor.strip().upper()}%"
        query = query.filter(
            or_(
                models.DocumentRegistryEntry.emisor_nombre.ilike(em_pat),
                models.DocumentRegistryEntry.emisor_user_id.ilike(em_pat),
            )
        )

    if doc_nature and doc_nature.upper() not in ("ALL", "TODOS"):
        query = query.filter(models.DocumentRegistryEntry.doc_nature == doc_nature.strip().upper())

    if currency and currency.upper() not in ("ALL", "TODAS"):
        query = query.filter(models.DocumentRegistryEntry.currency == currency.strip().upper())

    if importe_min is not None or importe_max is not None:
        if not perms.get("view_amounts"):
            raise HTTPException(status_code=403, detail="Tu rol no tiene permiso para filtrar por rangos de importe.")
        query = query.filter(models.DocumentRegistryEntry.amount_applicable == True)
        if importe_min is not None:
            query = query.filter(models.DocumentRegistryEntry.total_amount >= float(importe_min))
        if importe_max is not None:
            query = query.filter(models.DocumentRegistryEntry.total_amount <= float(importe_max))

    if doc_status and doc_status.upper() not in ("ALL", "TODOS"):
        query = query.filter(models.DocumentRegistryEntry.doc_status == doc_status.strip().upper())

    if payment_status and payment_status.upper() not in ("ALL", "TODOS"):
        query = query.filter(models.DocumentRegistryEntry.payment_status == payment_status.strip().upper())

    if fiscal_status and fiscal_status.upper() not in ("ALL", "TODOS"):
        query = query.filter(models.DocumentRegistryEntry.fiscal_status == fiscal_status.strip().upper())

    if dispatch_status and dispatch_status.upper() not in ("ALL", "TODOS"):
        query = query.filter(models.DocumentRegistryEntry.dispatch_status == dispatch_status.strip().upper())

    # Fechas interpretadas sobre `emitted_local_date` (calculada en la zona horaria configurada de la sucursal)
    if date_from and len(date_from.strip()) >= 10:
        query = query.filter(models.DocumentRegistryEntry.emitted_local_date >= date_from.strip()[:10])
    if date_to and len(date_to.strip()) >= 10:
        query = query.filter(models.DocumentRegistryEntry.emitted_local_date <= date_to.strip()[:10])

    return query, effective_suc


# ══════════════════════════════════════════════════════════════════════════════
# 1. BOOTSTRAP Y SINCRONIZACIÓN DEL CENTRO DE DOCUMENTOS
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/bootstrap")
def documents_bootstrap(
    db: Session = Depends(get_db),
    tenant: dict = Depends(get_tenant_context),
):
    perms = get_user_doc_permissions(db, tenant)
    if not perms.get("view"):
        raise HTTPException(status_code=403, detail="Tu rol no tiene acceso al Centro de Documentos.")

    empresa_id = str(tenant.get("empresa") or "").strip()
    session_suc = str(tenant.get("sucursal") or "MATRIZ").strip()
    user_k = _user_key(tenant)

    # Sincronizar fuentes reales de forma idempotente
    sync_stats = sync_document_registry_for_tenant(db, empresa_id, rebuild_clean=False)
    pref = _get_or_create_prefs(db, empresa_id, user_k)
    can_all, allowed_branches, branch_options = resolve_allowed_branches(db, tenant, perms)
    prof = get_session_company_profile(db, empresa_id, session_suc)
    tz_map = get_branch_timezones_map(db, empresa_id)
    active_tz = resolve_tz_for_branch(tz_map, session_suc)

    # Contadores por categoría y subtipo respetando sucursales y categorías del rol
    allowed_cats = set(perms.get("categories") or [])
    base_q = db.query(
        models.DocumentRegistryEntry.category,
        models.DocumentRegistryEntry.doc_subtype,
        func.count(models.DocumentRegistryEntry.id),
    ).filter(
        models.DocumentRegistryEntry.empresa_id == empresa_id,
        models.DocumentRegistryEntry.category.in_(list(allowed_cats) or ["__NONE__"]),
    )
    if not can_all:
        base_q = base_q.filter(models.DocumentRegistryEntry.sucursal_id.in_(allowed_branches))

    counts_raw = base_q.group_by(
        models.DocumentRegistryEntry.category,
        models.DocumentRegistryEntry.doc_subtype,
    ).all()

    cat_totals: Dict[str, int] = {}
    sub_totals: Dict[str, int] = {}
    grand_total = 0
    for cat_id, sub_id, cnt in counts_raw:
        c_i = int(cnt or 0)
        cat_totals[cat_id] = cat_totals.get(cat_id, 0) + c_i
        sub_totals[sub_id] = sub_totals.get(sub_id, 0) + c_i
        grand_total += c_i

    tree_out = []
    for cat in DOCUMENT_CATEGORIES_TREE:
        if cat["id"] not in allowed_cats:
            continue
        subs_out = []
        for st in cat["subtypes"]:
            subs_out.append({
                **st,
                "count": sub_totals.get(st["id"], 0),
            })
        tree_out.append({
            "id": cat["id"],
            "label": cat["label"],
            "icon": cat["icon"],
            "count": cat_totals.get(cat["id"], 0),
            "subtypes": subs_out,
        })

    # Impresoras configuradas del tenant
    prt_row = (
        db.query(models.AdminConfig)
        .filter(models.AdminConfig.empresa_id == empresa_id, models.AdminConfig.config_key == "printers.catalog")
        .first()
    )
    printers = prt_row.config_val if (prt_row and isinstance(prt_row.config_val, list)) else []

    return {
        "session": {
            "empresa_id": empresa_id,
            "user_id": user_k,
            "role": perms["raw_role"],
            "normalized_role": perms["normalized_role"],
            "session_sucursal": session_suc,
            "branch_timezone": active_tz,
            "company_profile": prof,
        },
        "permissions": perms,
        "branches": {
            "can_select_all": can_all,
            "default_branch": "ALL" if can_all else (branch_options[0]["id"] if branch_options else session_suc),
            "options": branch_options,
        },
        "library": {
            "total_authorized": grand_total,
            "favorites_count": len(pref.favorites_json or []),
            "recents_count": len(pref.recents_json or []),
            "categories": tree_out,
        },
        "preferences": {
            "favorites": pref.favorites_json or [],
            "recents": pref.recents_json or [],
            "saved_views": pref.saved_views_json or [],
            "ui_prefs": pref.ui_prefs_json or {},
        },
        "printers": printers,
        "channels": get_channels_availability(db, empresa_id),
        "sync": sync_stats,
    }


@router.post("/sync")
def rebuild_or_sync_documents(
    body: Dict[str, Any] = Body(default={}),
    db: Session = Depends(get_db),
    tenant: dict = Depends(get_tenant_context),
):
    perms = get_user_doc_permissions(db, tenant)
    if not perms.get("view"):
        raise HTTPException(status_code=403, detail="Sin permiso para sincronizar el índice documental.")
    rebuild_clean = bool(body.get("rebuild_clean", False))
    if rebuild_clean and perms["normalized_role"] not in ("admin", "superadmin"):
        raise HTTPException(status_code=403, detail="Solo el administrador puede ejecutar una reconstrucción completa del índice.")
    res = sync_document_registry_for_tenant(db, str(tenant.get("empresa")), rebuild_clean=rebuild_clean)
    return {"ok": True, **res}


# ══════════════════════════════════════════════════════════════════════════════
# 2. BÚSQUEDA, FILTRADO, ORDENAMIENTO Y PAGINACIÓN EN SERVIDOR + MÉTRICAS
# ══════════════════════════════════════════════════════════════════════════════

@router.get("")
def list_documents(
    q: Optional[str] = Query(None),
    view_preset: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    doc_subtype: Optional[str] = Query(None),
    sucursal_id: Optional[str] = Query(None),
    emisor: Optional[str] = Query(None),
    doc_nature: Optional[str] = Query(None),
    currency: Optional[str] = Query(None),
    importe_min: Optional[float] = Query(None),
    importe_max: Optional[float] = Query(None),
    doc_status: Optional[str] = Query(None),
    payment_status: Optional[str] = Query(None),
    fiscal_status: Optional[str] = Query(None),
    dispatch_status: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    sort_by: str = Query("emitted_at"),
    sort_dir: str = Query("desc"),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=5, le=100),
    sync: bool = Query(True),
    db: Session = Depends(get_db),
    tenant: dict = Depends(get_tenant_context),
):
    perms = get_user_doc_permissions(db, tenant)
    if not perms.get("view"):
        raise HTTPException(status_code=403, detail="Tu rol no tiene acceso al Centro de Documentos.")

    empresa_id = str(tenant.get("empresa") or "").strip()
    if sync:
        sync_document_registry_for_tenant(db, empresa_id, rebuild_clean=False)

    pref = _get_or_create_prefs(db, empresa_id, _user_key(tenant))
    if sort_by == "total_amount" and not perms.get("view_amounts"):
        raise HTTPException(status_code=403, detail="Tu rol no tiene permiso para ordenar por importe.")

    query, effective_suc = _build_filtered_query(
        db, tenant, perms, pref,
        q=q, view_preset=view_preset, category=category, doc_subtype=doc_subtype,
        sucursal_id=sucursal_id, emisor=emisor, doc_nature=doc_nature, currency=currency,
        importe_min=importe_min, importe_max=importe_max, doc_status=doc_status,
        payment_status=payment_status, fiscal_status=fiscal_status, dispatch_status=dispatch_status,
        date_from=date_from, date_to=date_to,
    )

    total_items = query.count()

    # Cifra 2: Emitidos hoy (en la zona horaria configurada de la sucursal activa)
    tz_map = get_branch_timezones_map(db, empresa_id)
    tz_active = resolve_tz_for_branch(tz_map, effective_suc or tenant.get("sucursal"))
    _, today_local_str = to_branch_local_dt(_dt.datetime.now(_dt.timezone.utc), tz_active)

    can_all, allowed_branches, _ = resolve_allowed_branches(db, tenant, perms)
    scope_q = db.query(models.DocumentRegistryEntry).filter(
        models.DocumentRegistryEntry.empresa_id == empresa_id,
        models.DocumentRegistryEntry.category.in_(list(perms.get("categories") or []) or ["__NONE__"]),
    )
    if not can_all:
        scope_q = scope_q.filter(models.DocumentRegistryEntry.sucursal_id.in_(allowed_branches))
    elif sucursal_id and sucursal_id.upper() != "ALL":
        scope_q = scope_q.filter(models.DocumentRegistryEntry.sucursal_id.in_(expand_branch_filter_values(db, empresa_id, sucursal_id)))

    emitted_today_count = scope_q.filter(models.DocumentRegistryEntry.emitted_local_date == today_local_str).count()
    dispatch_errors_count = scope_q.filter(models.DocumentRegistryEntry.dispatch_status == "CON_ERROR").count()

    sort_cols = {
        "emitted_at": models.DocumentRegistryEntry.emitted_at,
        "folio_visible": models.DocumentRegistryEntry.folio_visible,
        "tercero_nombre": models.DocumentRegistryEntry.tercero_nombre,
        "total_amount": models.DocumentRegistryEntry.total_amount,
        "doc_status": models.DocumentRegistryEntry.doc_status,
        "sucursal_id": models.DocumentRegistryEntry.sucursal_id,
    }
    col_obj = sort_cols.get(sort_by, models.DocumentRegistryEntry.emitted_at)
    order_expr = asc(col_obj) if sort_dir.lower() == "asc" else desc(col_obj)

    offset = (page - 1) * page_size
    rows = query.order_by(order_expr, desc(models.DocumentRegistryEntry.id)).offset(offset).limit(page_size).all()
    fav_set = set(pref.favorites_json or [])

    # Consolidado de Corte Z EXCLUSIVAMENTE EN PANTALLA para el administrador general
    corte_z_consolidado_screen = None
    if perms.get("view_corte_consolidado") and (category == "caja" or doc_subtype == "corte_z"):
        cz_rows = (
            db.query(
                models.DocumentRegistryEntry.sucursal_id,
                func.count(models.DocumentRegistryEntry.id),
                func.coalesce(func.sum(models.DocumentRegistryEntry.total_amount), 0),
            )
            .filter(
                models.DocumentRegistryEntry.empresa_id == empresa_id,
                models.DocumentRegistryEntry.doc_subtype == "corte_z",
            )
            .group_by(models.DocumentRegistryEntry.sucursal_id)
            .all()
        )
        if cz_rows:
            corte_z_consolidado_screen = {
                "screen_only": True,
                "policy_notice": "Consolidado de Matriz y Sucursales exclusivo de consulta en pantalla para el Administrador General. No imprimible, no exportable ni enviable.",
                "by_branch": [
                    {"sucursal_id": r[0], "cortes_count": int(r[1] or 0), "total_declarado": round(float(r[2] or 0), 2)}
                    for r in cz_rows
                ],
                "grand_total": round(sum(float(r[2] or 0) for r in cz_rows), 2),
                "total_cortes": sum(int(r[1] or 0) for r in cz_rows),
            }

    total_pages = max(1, (total_items + page_size - 1) // page_size)
    return {
        "items": [_serialize_list_item(r, perms, fav_set) for r in rows],
        "pagination": {
            "page": page,
            "page_size": page_size,
            "total_items": total_items,
            "total_pages": total_pages,
            "from_index": (offset + 1) if total_items > 0 else 0,
            "to_index": min(offset + len(rows), total_items),
        },
        "metrics": {
            "filtered_count": total_items,
            "emitted_today_count": emitted_today_count,
            "dispatch_errors_count": dispatch_errors_count,
            "branch_timezone": tz_active,
            "today_local_date": today_local_str,
            "explanations": {
                "filtered_count": "Total de documentos emitidos autorizados que coinciden con la búsqueda y filtros activos.",
                "emitted_today_count": f"Documentos emitidos el día de hoy ({today_local_str}) según el huso horario de la sucursal ({tz_active}).",
                "dispatch_errors_count": "Documentos de la sede seleccionada cuyo último intento de envío por correo o WhatsApp registró error y requiere atención.",
            },
        },
        "corte_z_consolidado_screen": corte_z_consolidado_screen,
    }


# ══════════════════════════════════════════════════════════════════════════════
# 3. PREFERENCIAS, FAVORITOS, RECIENTES Y VISTAS GUARDADAS POR USUARIO Y EMPRESA
# ══════════════════════════════════════════════════════════════════════════════

@router.post("/favorites/{doc_ref:path}")
def toggle_favorite_document(
    doc_ref: str,
    db: Session = Depends(get_db),
    tenant: dict = Depends(get_tenant_context),
):
    perms = get_user_doc_permissions(db, tenant)
    entry = _get_authorized_entry(db, tenant, perms, doc_ref)
    empresa_id = str(tenant.get("empresa") or "").strip()
    pref = _get_or_create_prefs(db, empresa_id, _user_key(tenant))

    favs = list(pref.favorites_json or [])
    if entry.doc_key in favs:
        favs = [k for k in favs if k != entry.doc_key]
        is_fav = False
    else:
        favs.insert(0, entry.doc_key)
        is_fav = True
    pref.favorites_json = favs[:200]
    db.commit()
    return {"ok": True, "doc_key": entry.doc_key, "is_favorite": is_fav, "favorites_count": len(pref.favorites_json)}


@router.post("/views", status_code=201)
def save_user_view(
    body: Dict[str, Any] = Body(...),
    db: Session = Depends(get_db),
    tenant: dict = Depends(get_tenant_context),
):
    perms = get_user_doc_permissions(db, tenant)
    if not perms.get("view"):
        raise HTTPException(status_code=403, detail="Sin permiso.")
    empresa_id = str(tenant.get("empresa") or "").strip()
    pref = _get_or_create_prefs(db, empresa_id, _user_key(tenant))

    # Regla global AGENTS.md: Normalizar nombres de negocio capturados a MAYÚSCULAS
    name_upper = str(body.get("name") or "").strip().upper()
    if not name_upper:
        raise HTTPException(status_code=400, detail="Indica un nombre para guardar la vista.")

    filters_obj = body.get("filters") if isinstance(body.get("filters"), dict) else {}
    views = list(pref.saved_views_json or [])
    new_view = {
        "id": str(uuid.uuid4())[:8],
        "name": name_upper[:80],
        "filters": filters_obj,
        "created_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
    }
    views.insert(0, new_view)
    pref.saved_views_json = views[:30]
    db.commit()
    return {"ok": True, "view": new_view, "saved_views": pref.saved_views_json}


@router.delete("/views/{view_id}")
def delete_user_view(
    view_id: str,
    db: Session = Depends(get_db),
    tenant: dict = Depends(get_tenant_context),
):
    empresa_id = str(tenant.get("empresa") or "").strip()
    pref = _get_or_create_prefs(db, empresa_id, _user_key(tenant))
    pref.saved_views_json = [v for v in (pref.saved_views_json or []) if str(v.get("id")) != view_id]
    db.commit()
    return {"ok": True, "saved_views": pref.saved_views_json}


@router.put("/preferences")
def update_ui_preferences(
    body: Dict[str, Any] = Body(...),
    db: Session = Depends(get_db),
    tenant: dict = Depends(get_tenant_context),
):
    empresa_id = str(tenant.get("empresa") or "").strip()
    pref = _get_or_create_prefs(db, empresa_id, _user_key(tenant))
    curr = dict(pref.ui_prefs_json or {})
    for k in ("density", "view_mode", "drawer_width", "library_collapsed", "columns", "surface_mode"):
        if k in body:
            curr[k] = body[k]
    pref.ui_prefs_json = curr
    db.commit()
    return {"ok": True, "ui_prefs": pref.ui_prefs_json}


# ══════════════════════════════════════════════════════════════════════════════
# 4. EXPORTAR LISTADO (CSV PROTEGIDO / XLSX), REPORTE IMPRIMIBLE Y LOTE ZIP
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/export")
def export_documents_endpoint(
    format: str = Query("csv"),  # csv | xlsx
    scope: str = Query("all_results"),  # current_page | all_results
    columns: Optional[str] = Query(None),
    consolidado: bool = Query(False),
    q: Optional[str] = Query(None),
    view_preset: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    doc_subtype: Optional[str] = Query(None),
    sucursal_id: Optional[str] = Query(None),
    emisor: Optional[str] = Query(None),
    doc_nature: Optional[str] = Query(None),
    currency: Optional[str] = Query(None),
    importe_min: Optional[float] = Query(None),
    importe_max: Optional[float] = Query(None),
    doc_status: Optional[str] = Query(None),
    payment_status: Optional[str] = Query(None),
    fiscal_status: Optional[str] = Query(None),
    dispatch_status: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    sort_by: str = Query("emitted_at"),
    sort_dir: str = Query("desc"),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=5, le=100),
    db: Session = Depends(get_db),
    tenant: dict = Depends(get_tenant_context),
):
    perms = get_user_doc_permissions(db, tenant)
    if not perms.get("export"):
        raise HTTPException(status_code=403, detail="Tu rol no cuenta con permiso para exportar listados documentales.")

    if consolidado:
        raise HTTPException(
            status_code=403,
            detail="Regla CALEBSYS: El consolidado de Corte Z de matriz y sucursales es exclusivamente de consulta en pantalla para el administrador autorizado.",
        )

    empresa_id = str(tenant.get("empresa") or "").strip()
    pref = _get_or_create_prefs(db, empresa_id, _user_key(tenant))

    query, effective_suc = _build_filtered_query(
        db, tenant, perms, pref,
        q=q, view_preset=view_preset, category=category, doc_subtype=doc_subtype,
        sucursal_id=sucursal_id, emisor=emisor, doc_nature=doc_nature, currency=currency,
        importe_min=importe_min, importe_max=importe_max, doc_status=doc_status,
        payment_status=payment_status, fiscal_status=fiscal_status, dispatch_status=dispatch_status,
        date_from=date_from, date_to=date_to,
    )

    col_obj = models.DocumentRegistryEntry.emitted_at
    order_expr = asc(col_obj) if sort_dir.lower() == "asc" else desc(col_obj)
    if scope == "current_page":
        rows = query.order_by(order_expr).offset((page - 1) * page_size).limit(page_size).all()
    else:
        rows = query.order_by(order_expr).limit(5000).all()

    # Regla CALEBSYS Corte Z: impedir que la exportación produzca un consolidado multi-caja / multi-sucursal de Cortes Z
    cz_rows = [r for r in rows if r.doc_subtype == "corte_z"]
    if doc_subtype == "corte_z" and len({(r.sucursal_id, r.caja_id or r.source_id) for r in cz_rows}) > 1:
        raise HTTPException(
            status_code=403,
            detail="Regla CALEBSYS: El consolidado de Cortes Z entre múltiples cajas o sucursales no puede exportarse. Seleccione una caja individual o descargue su comprobante individual.",
        )

    prof = get_session_company_profile(db, empresa_id, effective_suc)
    req_cols = [c.strip() for c in columns.split(",") if c.strip()] if columns else None
    raw_bytes, mime_type, fname = export_documents_dataset(
        rows=rows,
        perms=perms,
        fmt=format,
        requested_columns=req_cols,
        scope_label=scope,
        company_name=prof["nombre_comercial"],
    )

    audit_doc_event(
        db, empresa_id, effective_suc or "MATRIZ", _user_key(tenant),
        "DOC_CENTER_EXPORT",
        {"format": format, "scope": scope, "rows": len(rows)},
    )
    return Response(
        content=raw_bytes,
        media_type=mime_type,
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@router.get("/report-print")
def print_filtered_report_endpoint(
    scope: str = Query("current_page"),  # current_page | all_results
    consolidado: bool = Query(False),
    q: Optional[str] = Query(None),
    view_preset: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    doc_subtype: Optional[str] = Query(None),
    sucursal_id: Optional[str] = Query(None),
    emisor: Optional[str] = Query(None),
    doc_status: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=5, le=100),
    db: Session = Depends(get_db),
    tenant: dict = Depends(get_tenant_context),
):
    perms = get_user_doc_permissions(db, tenant)
    if not perms.get("print"):
        raise HTTPException(status_code=403, detail="Tu rol no cuenta con permiso para imprimir reportes.")
    if consolidado:
        raise HTTPException(
            status_code=403,
            detail="Regla CALEBSYS: El consolidado de Corte Z de matriz y sucursales no puede imprimirse como reporte.",
        )

    empresa_id = str(tenant.get("empresa") or "").strip()
    pref = _get_or_create_prefs(db, empresa_id, _user_key(tenant))
    query, effective_suc = _build_filtered_query(
        db, tenant, perms, pref,
        q=q, view_preset=view_preset, category=category, doc_subtype=doc_subtype,
        sucursal_id=sucursal_id, emisor=emisor, doc_status=doc_status,
        date_from=date_from, date_to=date_to,
    )
    total_filtered = query.count()
    if scope == "current_page":
        rows = query.order_by(desc(models.DocumentRegistryEntry.emitted_at)).offset((page - 1) * page_size).limit(page_size).all()
    else:
        rows = query.order_by(desc(models.DocumentRegistryEntry.emitted_at)).limit(1000).all()

    cz_rows = [r for r in rows if r.doc_subtype == "corte_z"]
    if doc_subtype == "corte_z" and len({(r.sucursal_id, r.caja_id or r.source_id) for r in cz_rows}) > 1:
        raise HTTPException(
            status_code=403,
            detail="Regla CALEBSYS: Impide imprimir consolidado de Cortes Z de múltiples cajas/sucursales. Imprima cada Corte Z individual.",
        )

    prof = get_session_company_profile(db, empresa_id, effective_suc)
    fav_set = set(pref.favorites_json or [])
    items_out = [_serialize_list_item(r, perms, fav_set) for r in rows]

    audit_doc_event(
        db, empresa_id, effective_suc or "MATRIZ", _user_key(tenant),
        "DOC_CENTER_REPORT_PRINT",
        {"scope": scope, "printed_rows": len(items_out), "total_filtered": total_filtered},
    )
    return {
        "company_profile": prof,
        "scope": scope,
        "scope_label": f"PÁGINA ACTUAL ({len(items_out)} de {total_filtered} resultados)" if scope == "current_page" else f"TODOS LOS RESULTADOS FILTRADOS ({len(items_out)} documentos)",
        "generated_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "generated_by": _user_key(tenant).upper(),
        "view_amounts": bool(perms.get("view_amounts")),
        "items": items_out,
    }


@router.post("/download-batch")
def download_batch_zip_endpoint(
    body: Dict[str, Any] = Body(...),
    db: Session = Depends(get_db),
    tenant: dict = Depends(get_tenant_context),
):
    perms = get_user_doc_permissions(db, tenant)
    if not perms.get("download"):
        raise HTTPException(status_code=403, detail="Tu rol no cuenta con permiso para descargar archivos por lote.")

    doc_keys = [str(k).strip() for k in (body.get("doc_keys") or []) if str(k).strip()]
    if not doc_keys:
        raise HTTPException(status_code=400, detail="Selecciona al menos un documento para descargar en lote.")
    if len(doc_keys) > 100:
        raise HTTPException(status_code=400, detail="Máximo 100 documentos por lote ZIP.")

    empresa_id = str(tenant.get("empresa") or "").strip()
    can_all, allowed_branches, _ = resolve_allowed_branches(db, tenant, perms)
    allowed_upper = {b.upper() for b in allowed_branches}

    db_entries = (
        db.query(models.DocumentRegistryEntry)
        .filter(
            models.DocumentRegistryEntry.empresa_id == empresa_id,
            models.DocumentRegistryEntry.doc_key.in_(doc_keys),
        )
        .all()
    )
    entries_by_key: Dict[str, models.DocumentRegistryEntry] = {}
    for e in db_entries:
        if can_all or (e.sucursal_id or "").upper() in allowed_upper:
            entries_by_key[e.doc_key] = e

    pref_mode = str(body.get("preferred_mode") or "AUTO").upper()
    zip_bytes, manifest = build_batch_zip(
        db=db,
        empresa_id=empresa_id,
        entries_by_key=entries_by_key,
        requested_keys=doc_keys,
        perms=perms,
        preferred_mode=pref_mode,
        include_xml=bool(body.get("include_xml", True)),
    )
    ts_tag = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    zip_filename = f"CALEBSYS_LOTE_{manifest['included_count']}_ARCHIVOS_{ts_tag}.zip"

    audit_doc_event(
        db, empresa_id, str(tenant.get("sucursal") or "MATRIZ"), _user_key(tenant),
        "DOC_CENTER_BATCH_ZIP",
        {"requested": len(doc_keys), "included": manifest["included_count"], "failed": manifest["failed_count"]},
    )
    return {
        "ok": True,
        "filename": zip_filename,
        "zip_base64": base64.b64encode(zip_bytes).decode("ascii"),
        "included_count": manifest["included_count"],
        "failed_count": manifest["failed_count"],
        "included": manifest["included"],
        "failed": manifest["failed"],
    }


# ══════════════════════════════════════════════════════════════════════════════
# 5. ENVÍOS (PREVISUALIZACIÓN, EJECUCIÓN IDEMPOTENTE, REINTENTO SEGURO, PROVEEDOR Y ENLACES)
# ══════════════════════════════════════════════════════════════════════════════

def _resolve_entries_map_for_dispatch(
    db: Session,
    tenant: dict,
    perms: Dict[str, Any],
    items_spec: List[Dict[str, Any]],
) -> Dict[str, models.DocumentRegistryEntry]:
    empresa_id = str(tenant.get("empresa") or "").strip()
    dkeys = [str(x.get("doc_key") or "").strip() for x in items_spec if x.get("doc_key")]
    if not dkeys:
        raise HTTPException(status_code=400, detail="Selecciona al menos un documento para enviar.")
    entries_map: Dict[str, models.DocumentRegistryEntry] = {}
    for dk in dkeys:
        ent = _get_authorized_entry(db, tenant, perms, dk)
        entries_map[ent.doc_key] = ent
    return entries_map


@router.post("/dispatch/preview")
def preview_dispatch_endpoint(
    body: Dict[str, Any] = Body(...),
    db: Session = Depends(get_db),
    tenant: dict = Depends(get_tenant_context),
):
    perms = get_user_doc_permissions(db, tenant)
    items_spec = body.get("items") or []
    entries_map = _resolve_entries_map_for_dispatch(db, tenant, perms, items_spec)
    return build_dispatch_preview(
        db=db,
        empresa_id=str(tenant.get("empresa")),
        entries_by_key=entries_map,
        items_spec=items_spec,
        channel=str(body.get("channel") or "EMAIL"),
        message=str(body.get("message") or ""),
        perms=perms,
    )


@router.post("/dispatch")
def execute_dispatch_endpoint(
    body: Dict[str, Any] = Body(...),
    db: Session = Depends(get_db),
    tenant: dict = Depends(get_tenant_context),
):
    perms = get_user_doc_permissions(db, tenant)
    items_spec = body.get("items") or []
    entries_map = _resolve_entries_map_for_dispatch(db, tenant, perms, items_spec)
    return execute_dispatch_operation(
        db=db,
        empresa_id=str(tenant.get("empresa")),
        sucursal_id=str(tenant.get("sucursal") or "MATRIZ"),
        user_id=_user_key(tenant),
        operation_key=str(body.get("operation_key") or ""),
        entries_by_key=entries_map,
        items_spec=items_spec,
        channel=str(body.get("channel") or "EMAIL"),
        subject=str(body.get("subject") or ""),
        message=str(body.get("message") or ""),
        is_test_mode=bool(body.get("is_test_mode", False)),
        perms=perms,
    )


@router.post("/dispatch/{operation_id}/retry")
def retry_dispatch_endpoint(
    operation_id: str,
    body: Dict[str, Any] = Body(default={}),
    db: Session = Depends(get_db),
    tenant: dict = Depends(get_tenant_context),
):
    perms = get_user_doc_permissions(db, tenant)
    if not perms.get("send"):
        raise HTTPException(status_code=403, detail="Sin permiso para reintentar envíos.")
    return retry_failed_dispatch_items(
        db=db,
        empresa_id=str(tenant.get("empresa")),
        sucursal_id=str(tenant.get("sucursal") or "MATRIZ"),
        user_id=_user_key(tenant),
        operation_id=operation_id,
        perms=perms,
        override_recipients=body.get("override_recipients") if isinstance(body.get("override_recipients"), dict) else None,
    )


@router.post("/dispatch/{operation_id}/refresh-status")
def refresh_dispatch_status_endpoint(
    operation_id: str,
    db: Session = Depends(get_db),
    tenant: dict = Depends(get_tenant_context),
):
    perms = get_user_doc_permissions(db, tenant)
    if not perms.get("view"):
        raise HTTPException(status_code=403, detail="Sin permiso.")
    return refresh_uncertain_dispatch_status(
        db=db,
        empresa_id=str(tenant.get("empresa")),
        operation_id=operation_id,
    )


@router.post("/share-links", status_code=201)
def create_share_link_endpoint(
    body: Dict[str, Any] = Body(...),
    db: Session = Depends(get_db),
    tenant: dict = Depends(get_tenant_context),
):
    perms = get_user_doc_permissions(db, tenant)
    if not perms.get("send") or not perms.get("download"):
        raise HTTPException(status_code=403, detail="Tu rol requiere permisos de descarga y envío para generar enlaces externos.")

    entry = _get_authorized_entry(db, tenant, perms, str(body.get("doc_key") or ""))
    fmt_code = str(body.get("format_code") or "CARTA").strip().upper()
    if fmt_code not in ("CARTA", "TICKET", "XML"):
        raise HTTPException(status_code=400, detail="Formato de enlace no válido.")

    if not perms.get("view_amounts") and entry.amount_applicable and not SUBTYPE_META_MAP.get(entry.doc_subtype, {}).get("non_monetary_safe"):
        raise HTTPException(status_code=403, detail="No puedes generar enlaces de documentos con importes restringidos para tu rol.")

    hours = max(1, min(168, int(body.get("expires_in_hours") or 24)))
    max_dl = max(1, min(50, int(body.get("max_downloads") or 5)))
    rec_lbl = str(body.get("recipient_label") or entry.tercero_nombre or "EXTERNO").strip().upper()[:200]

    tok = secrets.token_urlsafe(32)
    exp_at = _dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(hours=hours)
    lnk = models.DocumentShareLink(
        id=str(uuid.uuid4()),
        token=tok,
        empresa_id=entry.empresa_id,
        sucursal_id=entry.sucursal_id,
        doc_key=entry.doc_key,
        format_code=fmt_code,
        recipient_label=rec_lbl,
        expires_at=exp_at,
        max_downloads=max_dl,
        download_count=0,
        revoked=False,
        created_by=_user_key(tenant),
    )
    db.add(lnk)
    db.commit()
    db.refresh(lnk)

    audit_doc_event(
        db, entry.empresa_id, entry.sucursal_id, _user_key(tenant),
        "DOC_CENTER_SHARE_CREATE",
        {"doc_key": entry.doc_key, "link_id": lnk.id, "format": fmt_code, "expires_at": exp_at.isoformat(), "result": f"Enlace creado ({hours}h)"},
    )
    return {
        "id": lnk.id,
        "token": lnk.token,
        "share_path": f"/api/documents/shared/{lnk.token}",
        "doc_key": lnk.doc_key,
        "folio_visible": entry.folio_visible,
        "format_code": lnk.format_code,
        "recipient_label": lnk.recipient_label,
        "expires_at": lnk.expires_at.isoformat(),
        "max_downloads": lnk.max_downloads,
        "download_count": lnk.download_count,
        "revoked": lnk.revoked,
    }


@router.post("/share-links/{link_id}/revoke")
def revoke_share_link_endpoint(
    link_id: str,
    db: Session = Depends(get_db),
    tenant: dict = Depends(get_tenant_context),
):
    perms = get_user_doc_permissions(db, tenant)
    if not perms.get("send"):
        raise HTTPException(status_code=403, detail="Sin permiso para revocar enlaces.")
    empresa_id = str(tenant.get("empresa") or "").strip()
    lnk = (
        db.query(models.DocumentShareLink)
        .filter(models.DocumentShareLink.empresa_id == empresa_id, models.DocumentShareLink.id == link_id)
        .first()
    )
    if not lnk:
        raise HTTPException(status_code=404, detail="Enlace compartido no encontrado.")
    lnk.revoked = True
    lnk.revoked_at = _dt.datetime.now(_dt.timezone.utc)
    lnk.revoked_by = _user_key(tenant)
    db.commit()

    audit_doc_event(
        db, empresa_id, lnk.sucursal_id or "MATRIZ", _user_key(tenant),
        "DOC_CENTER_SHARE_REVOKE",
        {"doc_key": lnk.doc_key, "link_id": lnk.id, "result": "Enlace revocado inmediatamente"},
    )
    return {"ok": True, "id": lnk.id, "revoked": True, "revoked_at": lnk.revoked_at.isoformat()}


@router.get("/shared/{token}")
def consume_scoped_share_link(
    token: str,
    db: Session = Depends(get_db),
):
    """Descarga controlada por token criptográfico: alcance estrictamente limitado al único archivo autorizado,
    validando no-revocación, fecha de expiración y límite de descargas."""
    lnk = db.query(models.DocumentShareLink).filter(models.DocumentShareLink.token == str(token).strip()).first()
    if not lnk:
        raise HTTPException(status_code=404, detail="Enlace no válido o inexistente.")
    if lnk.revoked:
        raise HTTPException(status_code=410, detail="Este enlace fue revocado por el emisor y ya no está disponible.")

    now = _dt.datetime.now(_dt.timezone.utc)
    exp = lnk.expires_at if lnk.expires_at.tzinfo else lnk.expires_at.replace(tzinfo=_dt.timezone.utc)
    if now > exp:
        raise HTTPException(status_code=410, detail="Este enlace ha expirado.")
    if int(lnk.download_count or 0) >= int(lnk.max_downloads or 10):
        raise HTTPException(status_code=410, detail="Este enlace alcanzó su número máximo autorizado de descargas.")

    entry = (
        db.query(models.DocumentRegistryEntry)
        .filter(
            models.DocumentRegistryEntry.empresa_id == lnk.empresa_id,
            models.DocumentRegistryEntry.doc_key == lnk.doc_key,
        )
        .first()
    )
    if not entry:
        raise HTTPException(status_code=404, detail="Archivo origen no disponible.")

    # Usar permisos equivalentes a quién creó el enlace (enlace ya fue autorizado al crearse)
    creator_perms = {"view": True, "view_amounts": True, "download": True}
    if lnk.format_code == "XML":
        raw_b, mime, fname = resolve_xml_or_acuse_bytes(db, lnk.empresa_id, entry, creator_perms, kind="XML")
    else:
        raw_b, _ = resolve_document_pdf_and_meta(db, lnk.empresa_id, entry, creator_perms, mode=lnk.format_code, representation="original")
        mime = "application/pdf"
        fname = build_safe_download_filename(entry.folio_visible, entry.sucursal_id, lnk.format_code, "pdf")

    lnk.download_count = int(lnk.download_count or 0) + 1
    db.commit()

    audit_doc_event(
        db, lnk.empresa_id, entry.sucursal_id, lnk.recipient_label or "ENLACE_PUBLICO",
        "DOC_CENTER_SHARE_DOWNLOAD",
        {"doc_key": entry.doc_key, "link_id": lnk.id, "download_count": lnk.download_count, "result": f"Descarga #{lnk.download_count}"},
    )
    return Response(
        content=raw_b,
        media_type=mime,
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


# ══════════════════════════════════════════════════════════════════════════════
# 6. EXPEDIENTE INDIVIDUAL (4 PESTAÑAS, VISTA PREVIA REAL, MINIATURA, DESCARGA, IMPRESIÓN Y ADJUNTOS)
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/item/{doc_ref:path}/thumbnail")
def get_document_thumbnail(
    doc_ref: str,
    db: Session = Depends(get_db),
    tenant: dict = Depends(get_tenant_context),
):
    perms = get_user_doc_permissions(db, tenant)
    entry = _get_authorized_entry(db, tenant, perms, doc_ref)
    png_bytes = render_lazy_thumbnail_png(db, entry.empresa_id, entry, perms)
    return Response(content=png_bytes, media_type="image/png", headers={"Cache-Control": "private, max-age=60"})


@router.get("/item/{doc_ref:path}/preview-page")
def get_document_preview_page(
    doc_ref: str,
    mode: str = Query("CARTA"),
    representation: str = Query("original"),  # original | updated
    page: int = Query(1, ge=1),
    include_background: Optional[bool] = Query(None),
    db: Session = Depends(get_db),
    tenant: dict = Depends(get_tenant_context),
):
    perms = get_user_doc_permissions(db, tenant)
    entry = _get_authorized_entry(db, tenant, perms, doc_ref)
    pdf_bytes, rep_meta = resolve_document_pdf_and_meta(
        db=db,
        empresa_id=entry.empresa_id,
        entry=entry,
        perms=perms,
        mode=mode,
        representation=representation,
        include_background=include_background,
    )
    png_bytes, total_pages = render_pdf_page_png(pdf_bytes, page_num=page, scale=1.65)
    return {
        "doc_key": entry.doc_key,
        "folio_visible": entry.folio_visible,
        "page": min(page, total_pages),
        "total_pages": total_pages,
        "representation_meta": rep_meta,
        "image_data_uri": "data:image/png;base64," + base64.b64encode(png_bytes).decode("ascii"),
    }


@router.get("/item/{doc_ref:path}/file")
def download_document_file(
    doc_ref: str,
    format: str = Query("CARTA"),  # CARTA | TICKET | XML | ACUSE | ATTACHMENT
    representation: str = Query("original"),
    attachment_id: Optional[str] = Query(None),
    disposition: str = Query("attachment"),  # attachment | inline
    db: Session = Depends(get_db),
    tenant: dict = Depends(get_tenant_context),
):
    perms = get_user_doc_permissions(db, tenant)
    disp_clean = "inline" if disposition == "inline" else "attachment"
    if disp_clean == "attachment" and not perms.get("download"):
        raise HTTPException(status_code=403, detail="Tu rol no cuenta con permiso para descargar archivos.")
    if disp_clean == "inline" and not perms.get("print") and not perms.get("view"):
        raise HTTPException(status_code=403, detail="Sin permiso de visualización/impresión.")

    entry = _get_authorized_entry(db, tenant, perms, doc_ref)
    fmt_u = format.strip().upper()

    if fmt_u == "ATTACHMENT":
        if not attachment_id:
            raise HTTPException(status_code=400, detail="Falta attachment_id.")
        # Buscar en DocumentAttachment o en ReceptionFile si proviene de recepción 360
        att = (
            db.query(models.DocumentAttachment)
            .filter(
                models.DocumentAttachment.empresa_id == entry.empresa_id,
                models.DocumentAttachment.doc_key == entry.doc_key,
                models.DocumentAttachment.id == attachment_id,
            )
            .first()
        )
        if att:
            if att.contains_amounts and not perms.get("view_amounts"):
                raise HTTPException(status_code=403, detail="Este adjunto contiene importes restringidos para tu rol.")
            abs_p = os.path.join(MEDIA_DOC_CENTER_ROOT, att.storage_rel_path)
            if not os.path.isfile(abs_p):
                raise HTTPException(status_code=404, detail="Archivo adjunto faltante en almacenamiento.")
            with open(abs_p, "rb") as fh:
                raw_b = fh.read()
            fname = build_safe_download_filename(entry.folio_visible, entry.sucursal_id, f"ADJ_{att.kind}", os.path.splitext(att.original_filename)[1] or ".pdf")
            mime = att.mime_type
        else:
            rf = (
                db.query(models.ReceptionFile)
                .filter(
                    models.ReceptionFile.empresa_id == entry.empresa_id,
                    models.ReceptionFile.id == attachment_id,
                )
                .first()
            )
            if not rf or not rf.content_b64:
                raise HTTPException(status_code=404, detail="Adjunto no encontrado.")
            if not perms.get("view_amounts"):
                raise HTTPException(status_code=403, detail="Este adjunto de recepción contiene costos/importes restringidos para tu rol.")
            raw_b = base64.b64decode(rf.content_b64)
            mime = rf.mime or "application/octet-stream"
            fname = build_safe_download_filename(entry.folio_visible, entry.sucursal_id, f"REC_{rf.kind or 'ADJ'}", os.path.splitext(rf.filename or ".pdf")[1] or ".pdf")
    elif fmt_u in ("XML", "ACUSE"):
        raw_b, mime, fname = resolve_xml_or_acuse_bytes(db, entry.empresa_id, entry, perms, kind=fmt_u)
    else:
        raw_b, _ = resolve_document_pdf_and_meta(
            db=db,
            empresa_id=entry.empresa_id,
            entry=entry,
            perms=perms,
            mode=fmt_u,
            representation=representation,
        )
        mime = "application/pdf"
        suffix = fmt_u if representation == "original" else f"{fmt_u}_ACTUALIZADO"
        fname = build_safe_download_filename(entry.folio_visible, entry.sucursal_id, suffix, "pdf")

    if disp_clean == "attachment":
        audit_doc_event(
            db, entry.empresa_id, entry.sucursal_id, _user_key(tenant),
            "DOC_CENTER_DOWNLOAD",
            {"doc_key": entry.doc_key, "folio": entry.folio_visible, "format": fmt_u, "filename": fname, "result": "Descarga autorizada"},
        )

    return Response(
        content=raw_b,
        media_type=mime,
        headers={"Content-Disposition": f'{disp_clean}; filename="{fname}"'},
    )


@router.post("/item/{doc_ref:path}/print-log")
def log_document_print_action(
    doc_ref: str,
    body: Dict[str, Any] = Body(...),
    db: Session = Depends(get_db),
    tenant: dict = Depends(get_tenant_context),
):
    """Registra honestamente:
    - `BROWSER_DIALOG`: 'Solicitud de impresión' (el diálogo del navegador no confirma impresión física).
    - `LOCAL_AGENT` con `spooler_confirmed=True`: 'Impreso' confirmado."""
    perms = get_user_doc_permissions(db, tenant)
    if not perms.get("print"):
        raise HTTPException(status_code=403, detail="Tu rol no cuenta con permiso para imprimir.")

    entry = _get_authorized_entry(db, tenant, perms, doc_ref)
    channel = str(body.get("channel") or "BROWSER_DIALOG").strip().upper()
    fmt = str(body.get("format") or "CARTA").strip().upper()
    copies = max(1, min(20, int(body.get("copies") or 1)))
    printer_name = str(body.get("printer_name") or "DIÁLOGO DEL NAVEGADOR").strip().upper()
    confirmed = bool(channel == "LOCAL_AGENT" and body.get("spooler_confirmed") is True)

    if confirmed:
        act_code = "DOC_CENTER_PRINT_CONFIRMED"
        status_label = "Impreso"
        res_txt = f"Impreso confirmado en '{printer_name}' ({copies} copia(s), {fmt})"
    else:
        act_code = "DOC_CENTER_PRINT_REQUEST"
        status_label = "Solicitud de impresión"
        res_txt = f"Solicitud de impresión abierta en navegador ({fmt}, {copies} copia(s))"

    audit_doc_event(
        db, entry.empresa_id, entry.sucursal_id, _user_key(tenant),
        act_code,
        {
            "doc_key": entry.doc_key,
            "folio": entry.folio_visible,
            "channel": channel,
            "printer_name": printer_name,
            "copies": copies,
            "format": fmt,
            "confirmed": confirmed,
            "result": res_txt,
        },
    )
    return {
        "ok": True,
        "registered_status": status_label,
        "confirmed_physical_print": confirmed,
        "detail": res_txt,
    }


@router.post("/item/{doc_ref:path}/attachments", status_code=201)
async def upload_document_attachment(
    doc_ref: str,
    file: UploadFile = File(...),
    kind: str = Form("EVIDENCIA"),
    contains_amounts: bool = Form(True),
    notes: str = Form(""),
    db: Session = Depends(get_db),
    tenant: dict = Depends(get_tenant_context),
):
    perms = get_user_doc_permissions(db, tenant)
    if not perms.get("manage_attachments"):
        raise HTTPException(status_code=403, detail="Tu rol no tiene permiso para adjuntar archivos a expedientes.")

    entry = _get_authorized_entry(db, tenant, perms, doc_ref)
    raw_bytes = await file.read()
    safe_name, detected_mime = validate_attachment_upload(file.filename or "adjunto", file.content_type or "", raw_bytes)

    sha = hashlib.sha256(raw_bytes).hexdigest()
    safe_emp = _pfs._safe_tenant_segment(entry.empresa_id)
    rel_dir = os.path.join(safe_emp, "attachments")
    abs_dir = os.path.join(MEDIA_DOC_CENTER_ROOT, rel_dir)
    os.makedirs(abs_dir, exist_ok=True)

    att_id = str(uuid.uuid4())
    ext = os.path.splitext(safe_name)[1].lower()
    stored_fname = f"{att_id}{ext}"
    rel_path = os.path.join(rel_dir, stored_fname).replace("\\", "/")
    abs_path = os.path.join(MEDIA_DOC_CENTER_ROOT, rel_path)
    with open(abs_path, "wb") as fh:
        fh.write(raw_bytes)

    notes_upper = str(notes or "").strip().upper()[:280] or None
    kind_upper = str(kind or "EVIDENCIA").strip().upper()[:32]

    att = models.DocumentAttachment(
        id=att_id,
        empresa_id=entry.empresa_id,
        sucursal_id=entry.sucursal_id,
        doc_key=entry.doc_key,
        source_table=entry.source_table,
        source_id=entry.source_id,
        kind=kind_upper,
        original_filename=safe_name,
        mime_type=detected_mime,
        size_bytes=len(raw_bytes),
        sha256_hash=sha,
        contains_amounts=bool(contains_amounts),
        storage_rel_path=rel_path,
        notes=notes_upper,
        uploaded_by=_user_key(tenant),
    )
    db.add(att)
    entry.attachments_count = int(entry.attachments_count or 0) + 1
    db.commit()

    audit_doc_event(
        db, entry.empresa_id, entry.sucursal_id, _user_key(tenant),
        "DOC_CENTER_ATTACHMENT_UPLOAD",
        {"doc_key": entry.doc_key, "attachment_id": att.id, "filename": safe_name, "mime": detected_mime, "size_bytes": len(raw_bytes), "result": f"Adjunto '{safe_name}' validado"},
    )
    return {
        "id": att.id,
        "kind": att.kind,
        "original_filename": att.original_filename,
        "mime_type": att.mime_type,
        "size_bytes": att.size_bytes,
        "contains_amounts": att.contains_amounts,
        "notes": att.notes,
        "created_at": att.created_at.isoformat() if att.created_at else None,
    }


@router.get("/item/{doc_ref:path}")
def get_document_expediente(
    doc_ref: str,
    db: Session = Depends(get_db),
    tenant: dict = Depends(get_tenant_context),
):
    """Devuelve el expediente completo de 4 pestañas (Documento, Datos, Relacionados, Actividad),
    actualiza Recientes del usuario y registra auditoría de consulta."""
    perms = get_user_doc_permissions(db, tenant)
    entry = _get_authorized_entry(db, tenant, perms, doc_ref)
    empresa_id = entry.empresa_id
    user_k = _user_key(tenant)

    pref = _get_or_create_prefs(db, empresa_id, user_k)
    fav_set = set(pref.favorites_json or [])

    # Actualizar lista de recientes por usuario y empresa
    recs = [r for r in (pref.recents_json or []) if isinstance(r, dict) and r.get("doc_key") != entry.doc_key]
    recs.insert(0, {
        "doc_key": entry.doc_key,
        "folio_visible": entry.folio_visible,
        "opened_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
    })
    pref.recents_json = recs[:40]
    db.commit()

    can_all, allowed_branches, _ = resolve_allowed_branches(db, tenant, perms)
    view_amounts = bool(perms.get("view_amounts"))

    # Adjuntos del expediente (propios + ReceptionFile si es recepción 360)
    attachments_list = []
    own_atts = (
        db.query(models.DocumentAttachment)
        .filter(
            models.DocumentAttachment.empresa_id == empresa_id,
            models.DocumentAttachment.doc_key == entry.doc_key,
        )
        .order_by(models.DocumentAttachment.created_at.desc())
        .all()
    )
    for a in own_atts:
        restricted_att = bool(a.contains_amounts and not view_amounts)
        attachments_list.append({
            "id": a.id,
            "kind": a.kind,
            "filename": a.original_filename,
            "mime_type": a.mime_type,
            "size_bytes": a.size_bytes,
            "notes": a.notes,
            "restricted": restricted_att,
            "restriction_reason": "Contiene importes reservados para tu rol" if restricted_att else None,
            "created_at": a.created_at.isoformat() if a.created_at else None,
        })

    if entry.source_table == "reception_expedientes":
        rfs = (
            db.query(models.ReceptionFile)
            .filter(
                models.ReceptionFile.empresa_id == empresa_id,
                models.ReceptionFile.expediente_id == entry.source_id,
            )
            .all()
        )
        for rf in rfs:
            attachments_list.append({
                "id": rf.id,
                "kind": (rf.kind or "RECEPCIÓN").upper(),
                "filename": rf.filename or "adjunto_recepcion.pdf",
                "mime_type": rf.mime or "application/pdf",
                "size_bytes": rf.size_bytes or 0,
                "notes": "ADJUNTO DE RECEPCIÓN 360",
                "restricted": not view_amounts,
                "restriction_reason": "Contiene costos reservados para tu rol" if not view_amounts else None,
                "created_at": rf.created_at.isoformat() if rf.created_at else None,
            })

    # Enlaces compartidos activos del documento
    share_links_rows = (
        db.query(models.DocumentShareLink)
        .filter(
            models.DocumentShareLink.empresa_id == empresa_id,
            models.DocumentShareLink.doc_key == entry.doc_key,
        )
        .order_by(models.DocumentShareLink.created_at.desc())
        .limit(10)
        .all()
    )
    share_links_out = [
        {
            "id": s.id,
            "share_path": f"/api/documents/shared/{s.token}",
            "format_code": s.format_code,
            "recipient_label": s.recipient_label,
            "expires_at": s.expires_at.isoformat() if s.expires_at else None,
            "download_count": s.download_count,
            "max_downloads": s.max_downloads,
            "revoked": bool(s.revoked),
        }
        for s in share_links_rows
    ]

    # Datos de contacto del cliente/proveedor para prellenar envío
    contact_email = ""
    contact_phone = ""
    if entry.tercero_id:
        if entry.tercero_tipo == "CLIENTE":
            cli = db.query(models.Client).filter(models.Client.empresa_id == empresa_id, models.Client.id == entry.tercero_id).first()
            if cli:
                contact_email = cli.email or ""
                contact_phone = cli.whatsapp or cli.phone or ""
        elif entry.tercero_tipo == "PROVEEDOR":
            sup = db.query(models.Supplier).filter(models.Supplier.empresa_id == empresa_id, models.Supplier.id == entry.tercero_id).first()
            if sup:
                contact_email = sup.email or ""
                contact_phone = sup.whatsapp or sup.phone or ""

    # Auditar consulta conforme a política del proyecto
    audit_doc_event(
        db, empresa_id, entry.sucursal_id, user_k,
        "DOC_CENTER_VIEW",
        {"doc_key": entry.doc_key, "folio": entry.folio_visible, "channel": "EXPEDIENTE", "result": "Expediente consultado"},
    )

    base_info = _serialize_list_item(entry, perms, fav_set)
    related_list = build_related_documents(db, empresa_id, entry, perms, can_all, allowed_branches)
    activity_list = build_document_activity(db, empresa_id, entry)
    mov_route = resolve_movement_route(entry)

    default_fmt = "TICKET" if (entry.category == "caja" and "TICKET" in base_info["available_formats"]) else (
        base_info["available_formats"][0] if base_info["available_formats"] else None
    )

    return {
        "document": base_info,
        "default_format": default_fmt,
        "contact": {
            "email": contact_email,
            "phone": contact_phone,
        },
        "movement_origin": mov_route,
        "attachments": attachments_list,
        "share_links": share_links_out,
        "related": related_list,
        "activity": activity_list,
        "action_availability": {
            "can_print": bool(perms.get("print") and len(base_info["available_formats"]) > 0),
            "can_download": bool(perms.get("download") and len(base_info["available_formats"]) > 0),
            "can_send": bool(perms.get("send") and len(base_info["available_formats"]) > 0),
            "can_attach": bool(perms.get("manage_attachments")),
            "disabled_reason": (
                "Representaciones gráficas protegidas porque tu rol no tiene permiso para visualizar importes."
                if (not view_amounts and len(base_info["available_formats"]) == 0)
                else None
            ),
        },
    }
