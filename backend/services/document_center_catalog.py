"""Catálogo, Seguridad RBAC, Índice Reconstruible, Relaciones y Actividad del Centro de Documentos CALEBSYS.

Conecta las fuentes reales habilitadas del ERP sin alterar registros operativos de caja, ventas, saldos ni inventario.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import re
import uuid
from decimal import Decimal
from typing import Any, Dict, List, Optional, Set, Tuple
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

import models
from roles import normalize_role

DEFAULT_BRANCH_TZ = "America/Mazatlan"

# ══════════════════════════════════════════════════════════════════════════════
# 1. ÁRBOL DE CATEGORÍAS Y SUBTIPOS DOCUMENTALES
# ══════════════════════════════════════════════════════════════════════════════

DOCUMENT_CATEGORIES_TREE: List[Dict[str, Any]] = [
    {
        "id": "ventas",
        "label": "Ventas",
        "icon": "fa-file-invoice-dollar",
        "subtypes": [
            {"id": "venta_contado", "label": "Ventas de contado", "short": "Nota de venta", "icon": "fa-receipt", "print_doc_type": "ticket_venta_contado", "formats": ["CARTA", "TICKET"]},
            {"id": "venta_credito", "label": "Ventas a crédito", "short": "Venta a crédito", "icon": "fa-handshake", "print_doc_type": "ticket_venta_credito", "formats": ["CARTA", "TICKET"]},
            {"id": "cotizacion", "label": "Cotizaciones", "short": "Cotización", "icon": "fa-file-lines", "print_doc_type": "cotizacion", "formats": ["CARTA", "TICKET"]},
            {"id": "devolucion_venta", "label": "Devoluciones", "short": "Devolución", "icon": "fa-rotate-left", "print_doc_type": "devolucion", "formats": ["CARTA", "TICKET"]},
            {"id": "nota_credito_interna", "label": "Notas de crédito internas", "short": "Nota de crédito interna", "icon": "fa-file-circle-minus", "print_doc_type": "devolucion", "formats": ["CARTA", "TICKET"]},
            {"id": "apartado", "label": "Apartados", "short": "Apartado", "icon": "fa-bookmark", "print_doc_type": "ticket_venta_credito", "formats": ["CARTA", "TICKET"]},
            {"id": "abono_apartado", "label": "Abonos a apartados", "short": "Abono de apartado", "icon": "fa-coins", "print_doc_type": "comprobante_pago", "formats": ["CARTA", "TICKET"]},
            {"id": "liquidacion_comision", "label": "Liquidaciones a comisionistas", "short": "Liquidación comisión", "icon": "fa-user-tie", "print_doc_type": "comprobante_pago", "formats": ["CARTA", "TICKET"]},
        ],
    },
    {
        "id": "caja",
        "label": "Caja",
        "icon": "fa-cash-register",
        "subtypes": [
            {"id": "apertura_caja", "label": "Comprobantes de apertura", "short": "Apertura de caja", "icon": "fa-door-open", "print_doc_type": "apertura_caja", "formats": ["TICKET", "CARTA"]},
            {"id": "entrada_caja", "label": "Entradas de efectivo", "short": "Entrada de caja", "icon": "fa-arrow-down-to-line", "print_doc_type": "apertura_caja", "formats": ["TICKET", "CARTA"]},
            {"id": "salida_caja", "label": "Salidas y retiros", "short": "Salida de caja", "icon": "fa-arrow-up-from-line", "print_doc_type": "apertura_caja", "formats": ["TICKET", "CARTA"]},
            {"id": "arqueo_caja", "label": "Arqueos (Corte ciego)", "short": "Arqueo ciego", "icon": "fa-vault", "print_doc_type": "corte_ciego", "formats": ["TICKET", "CARTA"]},
            {"id": "corte_x", "label": "Cortes X (Parciales)", "short": "Corte X", "icon": "fa-clipboard-check", "print_doc_type": "corte_x", "formats": ["TICKET", "CARTA"]},
            {"id": "corte_z", "label": "Cortes Z (Cierre por caja)", "short": "Corte Z", "icon": "fa-scale-balanced", "print_doc_type": "corte_z", "formats": ["TICKET", "CARTA"]},
        ],
    },
    {
        "id": "compras",
        "label": "Compras",
        "icon": "fa-cart-shopping",
        "subtypes": [
            {"id": "orden_compra", "label": "Órdenes de compra", "short": "Orden de compra", "icon": "fa-cart-flatbed", "print_doc_type": "orden_compra", "formats": ["CARTA", "TICKET"]},
            {"id": "recepcion_compra", "label": "Recepciones de mercancía", "short": "Recepción", "icon": "fa-truck-ramp-box", "print_doc_type": "remision", "formats": ["CARTA", "TICKET"]},
            {"id": "cuenta_por_pagar", "label": "Documentos CxP", "short": "Cuenta por pagar", "icon": "fa-file-invoice", "print_doc_type": "estado_cuenta_cliente", "formats": ["CARTA", "TICKET"]},
            {"id": "pago_proveedor", "label": "Pagos a proveedores", "short": "Pago a proveedor", "icon": "fa-money-check-dollar", "print_doc_type": "comprobante_pago", "formats": ["CARTA", "TICKET"]},
            {"id": "gasto_operativo", "label": "Gastos de operación", "short": "Gasto operativo", "icon": "fa-wallet", "print_doc_type": "comprobante_pago", "formats": ["CARTA", "TICKET"]},
        ],
    },
    {
        "id": "almacen",
        "label": "Almacén",
        "icon": "fa-boxes-stacked",
        "subtypes": [
            {"id": "orden_entrega", "label": "Órdenes y notas de entrega", "short": "Nota de entrega", "icon": "fa-box-open", "print_doc_type": "orden_entrega", "formats": ["CARTA", "TICKET"], "non_monetary_safe": True},
            {"id": "traslado", "label": "Traslados", "short": "Traslado", "icon": "fa-truck-fast", "print_doc_type": "remision", "formats": ["CARTA", "TICKET"], "non_monetary_safe": True},
            {"id": "ajuste_inventario", "label": "Ajustes de inventario", "short": "Ajuste inventario", "icon": "fa-sliders", "print_doc_type": "remision", "formats": ["CARTA", "TICKET"], "non_monetary_safe": True},
            {"id": "toma_inventario", "label": "Tomas de inventario", "short": "Toma física", "icon": "fa-clipboard-list", "print_doc_type": "remision", "formats": ["CARTA", "TICKET"], "non_monetary_safe": True},
            {"id": "comodato", "label": "Comodatos", "short": "Comodato", "icon": "fa-hand-holding-hand", "print_doc_type": "documento_formal", "formats": ["CARTA", "TICKET"], "non_monetary_safe": True},
            {"id": "movimiento_envase", "label": "Movimientos de envases", "short": "Envases", "icon": "fa-recycle", "print_doc_type": "remision", "formats": ["CARTA", "TICKET"], "non_monetary_safe": True},
        ],
    },
    {
        "id": "cartera",
        "label": "Cartera",
        "icon": "fa-credit-card",
        "subtypes": [
            {"id": "estado_cuenta", "label": "Estados de cuenta / Cargos CxC", "short": "Cargo / Estado CxC", "icon": "fa-file-contract", "print_doc_type": "estado_cuenta_cliente", "formats": ["CARTA", "TICKET"]},
            {"id": "comprobante_abono", "label": "Comprobantes de abono", "short": "Comprobante de abono", "icon": "fa-money-bill-transfer", "print_doc_type": "comprobante_pago", "formats": ["CARTA", "TICKET"]},
            {"id": "anticipo_cliente", "label": "Anticipos recibidos", "short": "Anticipo recibido", "icon": "fa-piggy-bank", "print_doc_type": "comprobante_pago", "formats": ["CARTA", "TICKET"]},
            {"id": "aplicacion_saldo", "label": "Aplicación de saldo a favor", "short": "Aplicación de saldo", "icon": "fa-right-left", "print_doc_type": "comprobante_pago", "formats": ["CARTA", "TICKET"]},
            {"id": "contrato_adhesion", "label": "Contratos emitidos", "short": "Contrato de adhesión", "icon": "fa-signature", "print_doc_type": "documento_formal", "formats": ["CARTA", "TICKET"]},
        ],
    },
    {
        "id": "facturacion",
        "label": "Facturación",
        "icon": "fa-stamp",
        "subtypes": [
            {"id": "cfdi_ingreso", "label": "CFDI Facturas (Ingreso)", "short": "Factura", "icon": "fa-file-shield", "print_doc_type": "cfdi_factura_ticket", "formats": ["CARTA", "TICKET", "XML"]},
            {"id": "factura_global", "label": "Facturas globales", "short": "Factura global", "icon": "fa-globe", "print_doc_type": "cfdi_factura_ticket", "formats": ["CARTA", "XML"]},
            {"id": "cfdi_egreso", "label": "Notas de crédito fiscales (CFDI E)", "short": "CFDI de egreso", "icon": "fa-file-circle-xmark", "print_doc_type": "cfdi_factura_ticket", "formats": ["CARTA", "TICKET", "XML"]},
            {"id": "cfdi_pago", "label": "Complementos de pago (CFDI P)", "short": "Complemento pago", "icon": "fa-file-circle-check", "print_doc_type": "cfdi_factura_ticket", "formats": ["CARTA", "TICKET", "XML"]},
            {"id": "cfdi_traslado", "label": "Carta Porte / Traslado (CFDI T)", "short": "Carta Porte CFDI", "icon": "fa-route", "print_doc_type": "cfdi_factura_ticket", "formats": ["CARTA", "XML"], "non_monetary_safe": True},
        ],
    },
    {
        "id": "rrhh",
        "label": "Recursos humanos",
        "icon": "fa-users",
        "subtypes": [
            {"id": "comprobante_rh", "label": "Autorizaciones e incidencias", "short": "Comprobante RH", "icon": "fa-id-badge", "print_doc_type": "documento_formal", "formats": ["CARTA", "TICKET"], "non_monetary_safe": True},
            {"id": "constancia_rh", "label": "Constancias y documentos emitidos", "short": "Constancia RH", "icon": "fa-file-signature", "print_doc_type": "documento_formal", "formats": ["CARTA"], "non_monetary_safe": True},
        ],
    },
]

SUBTYPE_META_MAP: Dict[str, Dict[str, Any]] = {}
CATEGORY_LABELS: Dict[str, str] = {}
for _cat in DOCUMENT_CATEGORIES_TREE:
    CATEGORY_LABELS[_cat["id"]] = _cat["label"]
    for _st in _cat["subtypes"]:
        _entry = dict(_st)
        _entry["category"] = _cat["id"]
        _entry["category_label"] = _cat["label"]
        SUBTYPE_META_MAP[_st["id"]] = _entry


# ══════════════════════════════════════════════════════════════════════════════
# 2. PERMISOS POR ROL, CATEGORÍA, IMPORTES, RRHH Y SUCURSALES
# ══════════════════════════════════════════════════════════════════════════════

DEFAULT_ROLE_PERMISSIONS: Dict[str, Dict[str, Any]] = {
    "admin": {
        "categories": ["ventas", "caja", "compras", "almacen", "cartera", "facturacion", "rrhh"],
        "view": True, "view_amounts": True, "print": True, "download": True,
        "export": True, "send": True, "manage_attachments": True,
        "view_rh": True, "view_corte_consolidado": True, "all_branches": True,
    },
    "superadmin": {
        "categories": ["ventas", "caja", "compras", "almacen", "cartera", "facturacion", "rrhh"],
        "view": True, "view_amounts": True, "print": True, "download": True,
        "export": True, "send": True, "manage_attachments": True,
        "view_rh": True, "view_corte_consolidado": True, "all_branches": True,
    },
    "admin_sucursal": {
        "categories": ["ventas", "caja", "compras", "almacen", "cartera", "facturacion"],
        "view": True, "view_amounts": True, "print": True, "download": True,
        "export": True, "send": True, "manage_attachments": True,
        "view_rh": False, "view_corte_consolidado": False, "all_branches": False,
    },
    "gerente": {
        "categories": ["ventas", "caja", "compras", "almacen", "cartera", "facturacion", "rrhh"],
        "view": True, "view_amounts": True, "print": True, "download": True,
        "export": True, "send": True, "manage_attachments": True,
        "view_rh": True, "view_corte_consolidado": False, "all_branches": False,
    },
    "comprador": {
        "categories": ["compras", "almacen", "facturacion"],
        "view": True, "view_amounts": True, "print": True, "download": True,
        "export": True, "send": True, "manage_attachments": True,
        "view_rh": False, "view_corte_consolidado": False, "all_branches": False,
    },
    "contador": {
        "categories": ["ventas", "caja", "compras", "cartera", "facturacion"],
        "view": True, "view_amounts": True, "print": True, "download": True,
        "export": True, "send": True, "manage_attachments": False,
        "view_rh": False, "view_corte_consolidado": False, "all_branches": True,
    },
    "vendedor_cajero": {
        "categories": ["ventas", "caja", "almacen", "cartera", "facturacion"],
        "view": True, "view_amounts": True, "print": True, "download": True,
        "export": False, "send": True, "manage_attachments": False,
        "view_rh": False, "view_corte_consolidado": False, "all_branches": False,
    },
    "cajero": {
        "categories": ["ventas", "caja", "cartera", "facturacion"],
        "view": True, "view_amounts": True, "print": True, "download": True,
        "export": False, "send": True, "manage_attachments": False,
        "view_rh": False, "view_corte_consolidado": False, "all_branches": False,
    },
    "operador_caja": {
        "categories": ["ventas", "caja", "cartera", "facturacion"],
        "view": True, "view_amounts": True, "print": True, "download": True,
        "export": False, "send": True, "manage_attachments": False,
        "view_rh": False, "view_corte_consolidado": False, "all_branches": False,
    },
    "vendedor": {
        "categories": ["ventas", "almacen", "cartera", "facturacion"],
        "view": True, "view_amounts": True, "print": True, "download": True,
        "export": False, "send": True, "manage_attachments": False,
        "view_rh": False, "view_corte_consolidado": False, "all_branches": False,
    },
    "vendedor_calle": {
        "categories": ["ventas", "cartera"],
        "view": True, "view_amounts": True, "print": True, "download": True,
        "export": False, "send": True, "manage_attachments": False,
        "view_rh": False, "view_corte_consolidado": False, "all_branches": False,
    },
    "almacenista": {
        "categories": ["almacen", "compras", "ventas"],
        "view": True, "view_amounts": False, "print": True, "download": True,
        "export": False, "send": False, "manage_attachments": True,
        "view_rh": False, "view_corte_consolidado": False, "all_branches": False,
    },
    "transportista": {
        "categories": ["almacen"],
        "view": True, "view_amounts": False, "print": True, "download": False,
        "export": False, "send": False, "manage_attachments": True,
        "view_rh": False, "view_corte_consolidado": False, "all_branches": False,
    },
    "auxiliar": {
        "categories": [],
        "view": False, "view_amounts": False, "print": False, "download": False,
        "export": False, "send": False, "manage_attachments": False,
        "view_rh": False, "view_corte_consolidado": False, "all_branches": False,
    },
}


def get_user_doc_permissions(db: Session, tenant_payload: dict) -> Dict[str, Any]:
    empresa_id = str(tenant_payload.get("empresa") or "").strip()
    raw_role = str(tenant_payload.get("role") or "").strip()
    norm_role = normalize_role(raw_role)
    user_id = str(tenant_payload.get("user_id") or tenant_payload.get("sub") or "").strip()

    base = dict(DEFAULT_ROLE_PERMISSIONS.get(norm_role) or DEFAULT_ROLE_PERMISSIONS.get(raw_role.lower()) or {
        "categories": ["ventas", "almacen"],
        "view": True, "view_amounts": False, "print": True, "download": False,
        "export": False, "send": False, "manage_attachments": False,
        "view_rh": False, "view_corte_consolidado": False, "all_branches": False,
    })
    base["categories"] = list(base.get("categories") or [])

    # Permitir sobrescritura configurable por tenant en AdminConfig ('documents.role_permissions')
    cfg_row = (
        db.query(models.AdminConfig)
        .filter(
            models.AdminConfig.empresa_id == empresa_id,
            models.AdminConfig.config_key == "documents.role_permissions",
        )
        .first()
    )
    if cfg_row and isinstance(cfg_row.config_val, dict):
        override = cfg_row.config_val.get(norm_role) or cfg_row.config_val.get(raw_role.lower())
        if isinstance(override, dict):
            for k, v in override.items():
                base[k] = v

    # Verificar bloqueo de módulos para admin_sucursal (RRHH / COMPRAS) y permisos temporales
    if norm_role == "admin_sucursal":
        from deps import _blocked_modules_for_tenant, _has_temp_grant
        blocked = set(_blocked_modules_for_tenant(db, empresa_id))
        if "COMPRAS" in blocked and not _has_temp_grant(db, empresa_id, user_id, "COMPRAS"):
            base["categories"] = [c for c in base["categories"] if c != "compras"]
        if "RRHH" not in blocked or _has_temp_grant(db, empresa_id, user_id, "RRHH"):
            if "rrhh" not in base["categories"]:
                base["categories"].append("rrhh")
            base["view_rh"] = True
        else:
            base["categories"] = [c for c in base["categories"] if c != "rrhh"]
            base["view_rh"] = False

    # Regla estricta CALEBSYS: consolidado de Corte Z en pantalla SOLO para admin dueño/general
    if norm_role not in ("admin", "superadmin"):
        base["view_corte_consolidado"] = False

    if not base.get("view_rh"):
        base["categories"] = [c for c in base["categories"] if c != "rrhh"]

    base["normalized_role"] = norm_role
    base["raw_role"] = raw_role
    return base


def resolve_allowed_branches(db: Session, tenant_payload: dict, perms: Dict[str, Any]) -> Tuple[bool, List[str], List[Dict[str, str]]]:
    """Devuelve (can_all_branches, allowed_branch_ids_or_names, branch_options)."""
    empresa_id = str(tenant_payload.get("empresa") or "").strip()
    session_suc = str(tenant_payload.get("sucursal") or "MATRIZ").strip()
    user_id = str(tenant_payload.get("user_id") or "").strip()
    sub = str(tenant_payload.get("sub") or "").strip()

    db_branches = (
        db.query(models.Branch)
        .filter(models.Branch.empresa_id == empresa_id, models.Branch.status == "ACTIVE")
        .order_by(models.Branch.is_main.desc(), models.Branch.name.asc())
        .all()
    )

    branch_map: Dict[str, str] = {}
    branch_options: List[Dict[str, str]] = []
    known_codes: Set[str] = set()
    for b in db_branches:
        b_name = (b.name or b.id or "MATRIZ").strip()
        branch_map[b.id] = b_name
        branch_map[b_name] = b_name
        if b_name.upper() not in known_codes:
            known_codes.add(b_name.upper())
            branch_options.append({"id": b_name, "branch_uuid": b.id, "name": b_name, "is_main": bool(b.is_main)})

    if not branch_options:
        branch_options.append({"id": session_suc, "branch_uuid": session_suc, "name": session_suc, "is_main": True})

    if perms.get("all_branches"):
        all_vals: List[str] = []
        for b in db_branches:
            all_vals.extend([b.id, b.name])
        all_vals.append(session_suc)
        return True, list(dict.fromkeys(v for v in all_vals if v)), branch_options

    allowed: List[str] = [session_suc]
    if session_suc in branch_map:
        allowed.append(branch_map[session_suc])
    for b in db_branches:
        if b.name.upper() == session_suc.upper() or b.id == session_suc:
            allowed.extend([b.id, b.name])

    # Revisar allowed_branches en User si aplica
    usr = None
    if user_id:
        usr = db.query(models.User).filter(models.User.empresa_id == empresa_id, models.User.id == user_id).first()
    if not usr and sub:
        usr = db.query(models.User).filter(models.User.empresa_id == empresa_id, models.User.username == sub).first()
    if usr and isinstance(usr.allowed_branches, list) and usr.allowed_branches:
        for ab in usr.allowed_branches:
            ab_s = str(ab).strip()
            if ab_s:
                allowed.append(ab_s)
                if ab_s in branch_map:
                    allowed.append(branch_map[ab_s])

    allowed_set_upper = {a.upper() for a in allowed if a}
    filtered_opts = [
        o for o in branch_options
        if o["id"].upper() in allowed_set_upper or o["branch_uuid"].upper() in allowed_set_upper
    ]
    if not filtered_opts:
        filtered_opts = [{"id": session_suc, "branch_uuid": session_suc, "name": session_suc, "is_main": False}]

    can_multi = len(filtered_opts) > 1
    return can_multi, list(dict.fromkeys(a for a in allowed if a)), filtered_opts


def expand_branch_filter_values(db: Session, empresa_id: str, requested_sucursal: Optional[str]) -> List[str]:
    """Expande un nombre o UUID de sucursal a todas sus claves equivalentes (ej. UUID + 'MATRIZ')."""
    if not requested_sucursal or requested_sucursal.upper() == "ALL":
        return []
    req = requested_sucursal.strip()
    vals = [req]
    rows = db.query(models.Branch).filter(models.Branch.empresa_id == empresa_id).all()
    for b in rows:
        if b.id == req or (b.name or "").strip().upper() == req.upper():
            vals.extend([b.id, (b.name or "").strip()])
    return list(dict.fromkeys(v for v in vals if v))


def audit_doc_event(
    db: Session,
    empresa_id: str,
    sucursal_id: str,
    user_id: str,
    action: str,
    details: Any = None,
    severity: str = "INFO",
    commit: bool = True,
) -> None:
    try:
        db.add(models.AuditLog(
            empresa_id=empresa_id or "DESCONOCIDA",
            sucursal_id=sucursal_id or "MATRIZ",
            user_id=user_id or "sistema",
            action=action,
            severity=severity,
            details=details if isinstance(details, (dict, list)) else {"message": str(details or "")},
        ))
        if commit:
            db.commit()
    except Exception:
        if commit:
            db.rollback()


# ══════════════════════════════════════════════════════════════════════════════
# 3. ZONA HORARIA DE SUCURSAL Y UTILIDADES DE SEGURIDAD (CSV, ARCHIVOS, NOMBRES)
# ══════════════════════════════════════════════════════════════════════════════

def get_branch_timezones_map(db: Session, empresa_id: str) -> Dict[str, str]:
    row = (
        db.query(models.AdminConfig)
        .filter(
            models.AdminConfig.empresa_id == empresa_id,
            models.AdminConfig.config_key.in_(["branch.timezones", "params.timezone"]),
        )
        .all()
    )
    default_tz = DEFAULT_BRANCH_TZ
    tz_map: Dict[str, str] = {}
    for r in row:
        if r.config_key == "params.timezone":
            if isinstance(r.config_val, str) and r.config_val.strip():
                default_tz = r.config_val.strip()
            elif isinstance(r.config_val, dict) and r.config_val.get("timezone"):
                default_tz = str(r.config_val["timezone"]).strip()
        elif r.config_key == "branch.timezones" and isinstance(r.config_val, dict):
            for k, v in r.config_val.items():
                if v:
                    tz_map[str(k).strip().upper()] = str(v).strip()
    tz_map["__DEFAULT__"] = default_tz
    return tz_map


def resolve_tz_for_branch(tz_map: Dict[str, str], sucursal_id: Optional[str]) -> str:
    cand = tz_map.get(str(sucursal_id or "").strip().upper()) or tz_map.get("__DEFAULT__") or DEFAULT_BRANCH_TZ
    try:
        ZoneInfo(cand)
        return cand
    except Exception:
        return DEFAULT_BRANCH_TZ


def to_branch_local_dt(dt_val: Any, tz_name: str = DEFAULT_BRANCH_TZ) -> Tuple[_dt.datetime, str]:
    try:
        z = ZoneInfo(tz_name)
    except Exception:
        z = _dt.timezone(_dt.timedelta(hours=-7))

    if dt_val is None:
        now_utc = _dt.datetime.now(_dt.timezone.utc)
        loc = now_utc.astimezone(z)
        return now_utc, loc.strftime("%Y-%m-%d")

    if isinstance(dt_val, str):
        s = dt_val.strip()
        try:
            parsed = _dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
        except Exception:
            try:
                parsed = _dt.datetime.strptime(s[:19], "%Y-%m-%d %H:%M:%S")
            except Exception:
                try:
                    parsed = _dt.datetime.strptime(s[:10], "%Y-%m-%d")
                except Exception:
                    parsed = _dt.datetime.now(_dt.timezone.utc)
        dt_val = parsed

    if isinstance(dt_val, _dt.date) and not isinstance(dt_val, _dt.datetime):
        dt_val = _dt.datetime(dt_val.year, dt_val.month, dt_val.day, 12, 0, 0, tzinfo=_dt.timezone.utc)

    if dt_val.tzinfo is None:
        dt_utc = dt_val.replace(tzinfo=_dt.timezone.utc)
    else:
        dt_utc = dt_val.astimezone(_dt.timezone.utc)

    loc = dt_utc.astimezone(z)
    return dt_utc, loc.strftime("%Y-%m-%d")


def sanitize_csv_cell(val: Any) -> str:
    """Protege celdas CSV contra inyección de fórmulas (=, +, -, @, Tab, CR)."""
    if val is None:
        return ""
    s = str(val)
    if s and s[0] in ("=", "+", "-", "@", "\t", "\r"):
        # Si es un número negativo legítimo como -130.02 lo dejamos numérico, salvo que contenga caracteres no numéricos
        if s[0] == "-" and re.match(r"^-\d+(\.\d+)?$", s):
            return s
        return "'" + s
    return s


def build_safe_download_filename(folio: str, sucursal: str, fmt_label: str, ext: str) -> str:
    f_clean = re.sub(r"[^A-Za-z0-9_-]", "-", str(folio or "DOC").strip().upper()).strip("-") or "DOC"
    s_clean = re.sub(r"[^A-Za-z0-9_-]", "-", str(sucursal or "MATRIZ").strip().upper()).strip("-") or "MATRIZ"
    m_clean = re.sub(r"[^A-Za-z0-9_-]", "-", str(fmt_label or "ORIGINAL").strip().upper()).strip("-") or "ORIGINAL"
    ext_clean = ext.lstrip(".").lower()
    return f"{f_clean}_{s_clean}_{m_clean}.{ext_clean}"


MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024  # 10 MB

ALLOWED_ATTACHMENT_SIGNATURES = {
    "application/pdf": [b"%PDF-"],
    "image/png": [b"\x89PNG\r\n\x1a\n"],
    "image/jpeg": [b"\xff\xd8\xff"],
    "application/xml": [b"<?xml", b"<cfdi:", b"<Comprobante", b"<Acuse"],
    "text/xml": [b"<?xml", b"<cfdi:", b"<Comprobante", b"<Acuse"],
}


def validate_attachment_upload(filename: str, content_type: str, raw_bytes: bytes) -> Tuple[str, str]:
    """Valida extensión, tipo MIME, firma real de contenido (magic bytes) y tamaño."""
    if not raw_bytes:
        raise HTTPException(status_code=400, detail="El archivo adjunto está vacío.")
    if len(raw_bytes) > MAX_ATTACHMENT_BYTES:
        raise HTTPException(status_code=413, detail="El adjunto excede el límite máximo permitido de 10 MB.")

    fname = os.path.basename(filename or "adjunto.bin").strip()
    ext = os.path.splitext(fname)[1].lower()
    head = raw_bytes[:64].lstrip()

    detected_mime = None
    if head.startswith(b"%PDF-"):
        detected_mime = "application/pdf"
    elif raw_bytes[:8] == b"\x89PNG\r\n\x1a\n":
        detected_mime = "image/png"
    elif raw_bytes[:3] == b"\xff\xd8\xff":
        detected_mime = "image/jpeg"
    elif head.startswith((b"<?xml", b"<cfdi:", b"<Comprobante", b"<Acuse", b"<Cancelacion")):
        detected_mime = "application/xml"

    if not detected_mime:
        raise HTTPException(
            status_code=400,
            detail="Tipo o contenido de archivo no autorizado. Solo se permiten PDF, PNG, JPG o XML válidos.",
        )

    valid_exts = {
        "application/pdf": {".pdf"},
        "image/png": {".png"},
        "image/jpeg": {".jpg", ".jpeg"},
        "application/xml": {".xml"},
    }
    if ext not in valid_exts[detected_mime]:
        raise HTTPException(
            status_code=400,
            detail=f"La extensión '{ext}' no coincide con el contenido real del archivo ({detected_mime}).",
        )

    safe_name = re.sub(r"[^A-Za-z0-9._-]", "_", fname)[:180]
    return safe_name, detected_mime


# ══════════════════════════════════════════════════════════════════════════════
# 4. MOTOR DE SINCRONIZACIÓN Y RECONSTRUCCIÓN IDEMPOTENTE DEL ÍNDICE DOCUMENTAL
# ══════════════════════════════════════════════════════════════════════════════

def make_doc_key(empresa_id: str, source_table: str, source_id: str) -> str:
    return f"{empresa_id}::{source_table}::{source_id}"


def _dec(val: Any) -> Optional[Decimal]:
    if val is None:
        return None
    try:
        return Decimal(str(val)).quantize(Decimal("0.0001"))
    except Exception:
        return Decimal("0.0000")


def _norm_branch_display(branch_lookup: Dict[str, str], raw_suc: Optional[str]) -> str:
    s = str(raw_suc or "MATRIZ").strip() or "MATRIZ"
    return branch_lookup.get(s, s)


def sync_document_registry_for_tenant(db: Session, empresa_id: str, rebuild_clean: bool = False) -> Dict[str, int]:
    """Inventaría todas las fuentes habilitadas del tenant y actualiza/inserta en
    `document_registry_entries` sin duplicados.
    - Conserva la sucursal y caja de emisión original si el documento ya estaba indexado.
    - Si `rebuild_clean=True`, reconstruye desde las fuentes preservando el estado de envío confirmado."""
    tz_map = get_branch_timezones_map(db, empresa_id)

    branches = db.query(models.Branch).filter(models.Branch.empresa_id == empresa_id).all()
    branch_lookup: Dict[str, str] = {}
    for b in branches:
        branch_lookup[b.id] = (b.name or b.id).strip()
        branch_lookup[(b.name or b.id).strip()] = (b.name or b.id).strip()

    clients_map: Dict[str, Any] = {
        c.id: c for c in db.query(models.Client).filter(models.Client.empresa_id == empresa_id).all()
    }
    suppliers_map: Dict[str, Any] = {
        s.id: s for s in db.query(models.Supplier).filter(models.Supplier.empresa_id == empresa_id).all()
    }
    users_map: Dict[str, str] = {}
    for u in db.query(models.User).filter(models.User.empresa_id == empresa_id).all():
        users_map[u.id] = (u.username or u.id).upper()
        users_map[u.username] = (u.username or u.id).upper()
    employees_map: Dict[str, Any] = {}
    for emp in db.query(models.Employee).filter(models.Employee.empresa_id == empresa_id).all():
        employees_map[emp.id] = emp
        if emp.user_id:
            employees_map[emp.user_id] = emp
        if emp.usuario_id:
            employees_map[emp.usuario_id] = emp

    # Mapa de emisiones conservadas (original file)
    emissions_by_op: Set[str] = set()
    all_emissions = db.query(models.PrintEmissionRecord).filter(models.PrintEmissionRecord.empresa_id == empresa_id).all()
    for em in all_emissions:
        emissions_by_op.add(str(em.operation_id))
        if em.operation_folio:
            emissions_by_op.add(str(em.operation_folio))

    # Mapa de adjuntos por doc_key
    att_counts: Dict[str, int] = dict(
        db.query(models.DocumentAttachment.doc_key, func.count(models.DocumentAttachment.id))
        .filter(models.DocumentAttachment.empresa_id == empresa_id)
        .group_by(models.DocumentAttachment.doc_key)
        .all()
    )
    # Archivos de recepción 360
    rec_file_counts: Dict[str, int] = dict(
        db.query(models.ReceptionFile.expediente_id, func.count(models.ReceptionFile.id))
        .filter(models.ReceptionFile.empresa_id == empresa_id)
        .group_by(models.ReceptionFile.expediente_id)
        .all()
    )

    # Estado de envío real por doc_key
    disp_items = (
        db.query(models.DocumentDispatchItem)
        .filter(models.DocumentDispatchItem.empresa_id == empresa_id)
        .order_by(models.DocumentDispatchItem.updated_at.asc())
        .all()
    )
    dispatch_status_map: Dict[str, str] = {}
    for di in disp_items:
        st = (di.status or "").upper()
        if di.provider_read_confirmed:
            dispatch_status_map[di.doc_key] = "LEIDO"
        elif di.provider_delivery_confirmed:
            dispatch_status_map[di.doc_key] = "ENTREGADO"
        elif st in ("SENT", "SENT_UNCONFIRMED"):
            if dispatch_status_map.get(di.doc_key) not in ("ENTREGADO", "LEIDO"):
                dispatch_status_map[di.doc_key] = "ENVIADO"
        elif st == "OPENED_CLIENT":
            if dispatch_status_map.get(di.doc_key) not in ("ENVIADO", "ENTREGADO", "LEIDO"):
                dispatch_status_map[di.doc_key] = "WHATSAPP_ABIERTO"
        elif st in ("FAILED_SAFE_RETRY", "FAILED_PERMANENT"):
            dispatch_status_map[di.doc_key] = "CON_ERROR"
        elif st == "UNCERTAIN":
            dispatch_status_map[di.doc_key] = "INCIERTO"

    # CFDI por sale_id para estado fiscal de ventas
    cfdi_by_sale: Dict[str, Any] = {}
    all_cfdis = db.query(models.CfdiDocument).filter(models.CfdiDocument.empresa_id == empresa_id).all()
    for cd in all_cfdis:
        if cd.sale_id:
            cfdi_by_sale[cd.sale_id] = cd

    # CxC por sale_id para distinguir crédito y estado de pago
    ar_by_sale: Dict[str, Any] = {}
    all_ars = db.query(models.AccountsReceivable).filter(models.AccountsReceivable.empresa_id == empresa_id).all()
    for ar in all_ars:
        if ar.sale_id:
            ar_by_sale[ar.sale_id] = ar

    candidates: List[Dict[str, Any]] = []

    def _emp_label(uid: Optional[str]) -> str:
        if not uid:
            return "SISTEMA"
        emp = employees_map.get(uid)
        if emp and (emp.display_name or emp.full_name):
            return str(emp.display_name or emp.full_name).upper()
        return str(users_map.get(uid, uid)).upper()

    def _push(row_dict: Dict[str, Any]) -> None:
        candidates.append(row_dict)

    # ── 1. VENTAS (Contado y Crédito) ─────────────────────────────────────────
    sales_rows = db.query(models.Sale).filter(models.Sale.empresa_id == empresa_id).all()
    sales_map: Dict[str, Any] = {s.id: s for s in sales_rows}
    for s in sales_rows:
        cli = clients_map.get(s.client_id) if s.client_id else None
        ar = ar_by_sale.get(s.id)
        cfdi = cfdi_by_sale.get(s.id)
        pm = str(s.payment_method or "001").strip().upper()
        is_credit = pm in ("006", "CREDITO", "CRÉDITO", "99", "CREDIT") or (ar is not None)
        subtype = "venta_credito" if is_credit else "venta_contado"
        tot = float(s.total or 0)
        sub = round(tot / 1.16, 4)
        iva = round(tot - sub, 4)
        st_raw = str(s.status or "completed").strip().upper()
        doc_st = "CANCELADA" if st_raw in ("CANCELLED", "CANCELADA", "CANCELED") else "EMITIDA"
        if doc_st == "CANCELADA":
            pay_st = "CANCELADO"
        elif is_credit and ar:
            bal = float(ar.current_balance if ar.current_balance is not None else (ar.amount_due or 0))
            if ar.is_paid or bal <= 0.009:
                pay_st = "PAGADO"
            elif bal < float(ar.original_amount or tot):
                pay_st = "PARCIAL"
            else:
                pay_st = "PENDIENTE"
        else:
            pay_st = "PAGADO"

        if cfdi:
            cst = str(cfdi.status or "").upper()
            fisc_st = "TIMBRADA" if cst == "TIMBRADO" else ("CANCELADA_SAT" if cst == "CANCELADO" else cst or "PENDIENTE")
        else:
            fisc_st = "TIMBRADA" if s.is_cfdi and s.cfdi_document_id else "SIN_FACTURAR"

        folio_vis = str(s.folio or f"VTA-{s.id[:6]}").upper()
        caja_emision = None
        if s.payment_details:
            try:
                pd_js = json.loads(s.payment_details) if isinstance(s.payment_details, str) and s.payment_details.startswith("{") else {}
                caja_emision = pd_js.get("terminal_id") or pd_js.get("caja_id")
            except Exception:
                caja_emision = None

        _push({
            "source_table": "sales",
            "source_id": str(s.id),
            "sucursal_id": _norm_branch_display(branch_lookup, s.sucursal_id),
            "caja_id": str(caja_emision or "CAJA-01").upper(),
            "category": "ventas",
            "doc_subtype": subtype,
            "print_doc_type": "ticket_venta_credito" if is_credit else "ticket_venta_contado",
            "doc_nature": "EMITIDO",
            "serie": "VTA",
            "folio_visible": folio_vis,
            "emisor_user_id": str(s.seller_id or ""),
            "emisor_nombre": _emp_label(s.seller_id),
            "tercero_id": str(s.client_id or ""),
            "tercero_tipo": "CLIENTE",
            "tercero_nombre": str((cli.name if cli else "PÚBLICO EN GENERAL") or "PÚBLICO EN GENERAL").upper(),
            "tercero_rfc": str((cli.rfc if cli else "XAXX010101000") or "XAXX010101000").upper(),
            "uuid_fiscal": str(cfdi.uuid_fiscal or "") if cfdi else None,
            "reference_text": str(s.canal_venta or pm or "").upper(),
            "currency": "MXN",
            "amount_applicable": True,
            "subtotal": _dec(sub),
            "discount_amount": _dec(s.discount or 0),
            "tax_amount": _dec(iva),
            "total_amount": _dec(tot),
            "doc_status": doc_st,
            "payment_status": pay_st,
            "fiscal_status": fisc_st,
            "cancel_reason": "VENTA CANCELADA EN ORIGEN" if doc_st == "CANCELADA" else None,
            "emitted_at": s.created_at,
            "has_original_file": (str(s.id) in emissions_by_op or folio_vis in emissions_by_op),
            "has_xml": bool(cfdi and cfdi.xml),
            "has_acuse": bool(cfdi and cfdi.cancelado_at),
            "extra_meta_json": {"payment_method": pm, "is_safekept": bool(s.is_safekept)},
        })

    # ── 2. COTIZACIONES ───────────────────────────────────────────────────────
    for q in db.query(models.Quote).filter(models.Quote.empresa_id == empresa_id).all():
        cli = clients_map.get(q.client_id) if q.client_id else None
        tot = float(q.total or 0)
        sub = round(tot / 1.16, 4)
        st = str(q.status or "VIGENTE").strip().upper()
        folio_vis = str(q.folio or f"COT-{q.id[:6]}").upper()
        _push({
            "source_table": "quotes",
            "source_id": str(q.id),
            "sucursal_id": _norm_branch_display(branch_lookup, q.sucursal_id),
            "caja_id": None,
            "category": "ventas",
            "doc_subtype": "cotizacion",
            "print_doc_type": "cotizacion",
            "doc_nature": "EMITIDO",
            "serie": "COT",
            "folio_visible": folio_vis,
            "emisor_user_id": None,
            "emisor_nombre": "VENTAS MOSTRADOR",
            "tercero_id": str(q.client_id or ""),
            "tercero_tipo": "CLIENTE",
            "tercero_nombre": str(q.client_name or (cli.name if cli else "PÚBLICO EN GENERAL")).upper(),
            "tercero_rfc": str((cli.rfc if cli else "XAXX010101000") or "XAXX010101000").upper(),
            "uuid_fiscal": None,
            "reference_text": "COTIZACIÓN COMERCIAL",
            "currency": "MXN",
            "amount_applicable": True,
            "subtotal": _dec(sub),
            "discount_amount": _dec(0),
            "tax_amount": _dec(round(tot - sub, 4)),
            "total_amount": _dec(tot),
            "doc_status": "VIGENTE" if st in ("OPEN", "ACTIVE", "VIGENTE", "PENDING") else st,
            "payment_status": "NO_APLICA",
            "fiscal_status": "NO_FISCAL",
            "cancel_reason": None,
            "emitted_at": q.created_at,
            "has_original_file": (str(q.id) in emissions_by_op or folio_vis in emissions_by_op),
            "has_xml": False,
            "has_acuse": False,
            "extra_meta_json": {},
        })

    # ── 3. DEVOLUCIONES DE VENTA ──────────────────────────────────────────────
    for sr in db.query(models.SaleReturn).filter(models.SaleReturn.empresa_id == empresa_id).all():
        parent_sale = sales_map.get(sr.sale_id) if sr.sale_id else None
        cli = clients_map.get(parent_sale.client_id) if (parent_sale and parent_sale.client_id) else None
        tot = float(parent_sale.total or 0) if parent_sale else 0.0
        folio_vis = f"DEV-{str(sr.id)[:8].upper()}"
        _push({
            "source_table": "sale_returns",
            "source_id": str(sr.id),
            "sucursal_id": _norm_branch_display(branch_lookup, sr.sucursal_origen or (parent_sale.sucursal_id if parent_sale else "MATRIZ")),
            "caja_id": None,
            "category": "ventas",
            "doc_subtype": "devolucion_venta",
            "print_doc_type": "devolucion",
            "doc_nature": "EMITIDO",
            "serie": "DEV",
            "folio_visible": folio_vis,
            "emisor_user_id": str(sr.created_by or ""),
            "emisor_nombre": _emp_label(sr.created_by),
            "tercero_id": str(cli.id if cli else ""),
            "tercero_tipo": "CLIENTE",
            "tercero_nombre": str((cli.name if cli else "PÚBLICO EN GENERAL")).upper(),
            "tercero_rfc": str((cli.rfc if cli else "XAXX010101000") or "XAXX010101000").upper(),
            "uuid_fiscal": None,
            "reference_text": str(sr.notes or (f"VENTA {parent_sale.folio}" if parent_sale else "")).upper(),
            "currency": "MXN",
            "amount_applicable": True,
            "subtotal": _dec(round(tot / 1.16, 4)),
            "discount_amount": _dec(0),
            "tax_amount": _dec(round(tot - round(tot / 1.16, 4), 4)),
            "total_amount": _dec(tot),
            "doc_status": str(sr.estado or "AUTORIZADA").upper(),
            "payment_status": "APLICADO",
            "fiscal_status": "NO_FISCAL",
            "cancel_reason": None,
            "emitted_at": sr.created_at,
            "has_original_file": (str(sr.id) in emissions_by_op or folio_vis in emissions_by_op),
            "has_xml": False,
            "has_acuse": False,
            "extra_meta_json": {"sale_id": sr.sale_id, "authorized_by": sr.authorized_by},
        })

    # ── 4. LEDGER DE SALDO A FAVOR: NOTA DE CRÉDITO INTERNA vs ANTICIPO vs APLICACIÓN ─
    for cl in db.query(models.CustomerCreditLedger).filter(models.CustomerCreditLedger.empresa_id == empresa_id).all():
        cli = clients_map.get(cl.client_id) if cl.client_id else None
        ttype = str(cl.transaction_type or "CREDIT").strip().upper()
        amt = abs(float(cl.amount or 0))
        desc_u = str(cl.description or "").strip().upper()
        # Extraer folio explícito si viene en description (ej. "NC-PMM-00-0003 | ...")
        m_fol = re.match(r"^([A-Z]{2,5}-[A-Z0-9-]{3,30})\b", desc_u)
        if ttype in ("ANTICIPO", "ADVANCE", "DEPOSITO_ANTICIPO"):
            cat_id = "cartera"
            sub_id = "anticipo_cliente"
            prt_dt = "comprobante_pago"
            fol = m_fol.group(1) if m_fol else f"ANT-{str(cl.id)[:6].upper()}"
            st_doc = "REGISTRADO"
        elif ttype in ("APPLY", "APLICACION", "APLICACION_SALDO", "USO_SALDO", "DEBIT"):
            cat_id = "cartera"
            sub_id = "aplicacion_saldo"
            prt_dt = "comprobante_pago"
            fol = m_fol.group(1) if m_fol else f"APL-{str(cl.id)[:6].upper()}"
            st_doc = "APLICADA"
        else:
            # Nota de crédito interna (distinta de CFDI de egreso)
            cat_id = "ventas"
            sub_id = "nota_credito_interna"
            prt_dt = "devolucion"
            fol = m_fol.group(1) if m_fol else f"NC-{str(cl.id)[:6].upper()}"
            st_doc = "APLICADA" if "APLICADA" in desc_u or ttype == "APPLIED" else ("VIGENTE" if ttype == "VIGENTE" else "APLICADA")

        sub_v = round(amt / 1.16, 4)
        _push({
            "source_table": "customer_credit_ledger",
            "source_id": str(cl.id),
            "sucursal_id": _norm_branch_display(branch_lookup, cl.sucursal_id),
            "caja_id": "CAJA-01",
            "category": cat_id,
            "doc_subtype": sub_id,
            "print_doc_type": prt_dt,
            "doc_nature": "EMITIDO",
            "serie": fol.split("-")[0] if "-" in fol else "NC",
            "folio_visible": fol,
            "emisor_user_id": None,
            "emisor_nombre": "ADMINISTRACIÓN / CAJA",
            "tercero_id": str(cl.client_id or ""),
            "tercero_tipo": "CLIENTE",
            "tercero_nombre": str((cli.name if cli else "CLIENTE GENERAL")).upper(),
            "tercero_rfc": str((cli.rfc if cli else "XAXX010101000") or "XAXX010101000").upper(),
            "uuid_fiscal": None,
            "reference_text": desc_u or ttype,
            "currency": "MXN",
            "amount_applicable": True,
            "subtotal": _dec(sub_v),
            "discount_amount": _dec(0),
            "tax_amount": _dec(round(amt - sub_v, 4)),
            "total_amount": _dec(amt),
            "doc_status": st_doc,
            "payment_status": "APLICADO" if st_doc == "APLICADA" else "SALDO_DISPONIBLE",
            "fiscal_status": "INTERNO_NO_FISCAL",
            "cancel_reason": None,
            "emitted_at": cl.created_at,
            "has_original_file": (str(cl.id) in emissions_by_op or fol in emissions_by_op),
            "has_xml": False,
            "has_acuse": False,
            "extra_meta_json": {"sale_id": cl.sale_id, "transaction_type": ttype},
        })

    # ── 5. APARTADOS Y ABONOS A APARTADOS ─────────────────────────────────────
    layaways_rows = db.query(models.Layaway).filter(models.Layaway.empresa_id == empresa_id).all()
    layaways_map = {lw.id: lw for lw in layaways_rows}
    for lw in layaways_rows:
        cli = clients_map.get(lw.client_id) if lw.client_id else None
        tot = float(lw.total_amount or 0)
        fol = str(lw.folio or f"APT-{lw.id[:6]}").upper()
        _push({
            "source_table": "layaways",
            "source_id": str(lw.id),
            "sucursal_id": _norm_branch_display(branch_lookup, lw.sucursal_id),
            "caja_id": "CAJA-01",
            "category": "ventas",
            "doc_subtype": "apartado",
            "print_doc_type": "ticket_venta_credito",
            "doc_nature": "EMITIDO",
            "serie": "APT",
            "folio_visible": fol,
            "emisor_user_id": str(lw.created_by or lw.seller_id or ""),
            "emisor_nombre": _emp_label(lw.created_by or lw.seller_id),
            "tercero_id": str(lw.client_id or ""),
            "tercero_tipo": "CLIENTE",
            "tercero_nombre": str(lw.client_name or (cli.name if cli else "PÚBLICO EN GENERAL")).upper(),
            "tercero_rfc": str((cli.rfc if cli else "XAXX010101000") or "XAXX010101000").upper(),
            "uuid_fiscal": None,
            "reference_text": str(lw.nota or "APARTADO DE MERCANCÍA").upper(),
            "currency": "MXN",
            "amount_applicable": True,
            "subtotal": _dec(round(tot / 1.16, 4)),
            "discount_amount": _dec(0),
            "tax_amount": _dec(round(tot - round(tot / 1.16, 4), 4)),
            "total_amount": _dec(tot),
            "doc_status": str(lw.status or "ACTIVO").upper(),
            "payment_status": "LIQUIDADO" if float(lw.amount_pending or 0) <= 0.01 else "PARCIAL",
            "fiscal_status": "NO_FISCAL",
            "cancel_reason": None,
            "emitted_at": lw.created_at,
            "has_original_file": (str(lw.id) in emissions_by_op or fol in emissions_by_op),
            "has_xml": False,
            "has_acuse": False,
            "extra_meta_json": {"amount_paid": float(lw.amount_paid or 0), "amount_pending": float(lw.amount_pending or 0)},
        })

    for lp in db.query(models.LayawayPayment).filter(models.LayawayPayment.empresa_id == empresa_id).all():
        lw = layaways_map.get(lp.layaway_id)
        amt = float(lp.amount or 0)
        fol = f"ABP-{str(lp.id)[:6].upper()}"
        _push({
            "source_table": "layaway_payments",
            "source_id": str(lp.id),
            "sucursal_id": _norm_branch_display(branch_lookup, lw.sucursal_id if lw else "MATRIZ"),
            "caja_id": "CAJA-01",
            "category": "ventas",
            "doc_subtype": "abono_apartado",
            "print_doc_type": "comprobante_pago",
            "doc_nature": "EMITIDO",
            "serie": "ABP",
            "folio_visible": fol,
            "emisor_user_id": str(lp.created_by or ""),
            "emisor_nombre": _emp_label(lp.created_by),
            "tercero_id": str(lw.client_id if lw else ""),
            "tercero_tipo": "CLIENTE",
            "tercero_nombre": str((lw.client_name if lw else "PÚBLICO EN GENERAL") or "PÚBLICO EN GENERAL").upper(),
            "tercero_rfc": "XAXX010101000",
            "uuid_fiscal": None,
            "reference_text": f"ABONO APARTADO {lw.folio if lw else lp.layaway_id}".upper(),
            "currency": "MXN",
            "amount_applicable": True,
            "subtotal": _dec(amt),
            "discount_amount": _dec(0),
            "tax_amount": _dec(0),
            "total_amount": _dec(amt),
            "doc_status": "REGISTRADO",
            "payment_status": "PAGADO",
            "fiscal_status": "NO_FISCAL",
            "cancel_reason": None,
            "emitted_at": lp.created_at,
            "has_original_file": (str(lp.id) in emissions_by_op),
            "has_xml": False,
            "has_acuse": False,
            "extra_meta_json": {"layaway_id": lp.layaway_id, "payment_method": lp.payment_method},
        })

    # ── 6. LIQUIDACIONES A COMISIONISTAS ──────────────────────────────────────
    for sc in db.query(models.SellerCommissionLedger).filter(models.SellerCommissionLedger.empresa_id == empresa_id).all():
        emp = employees_map.get(sc.employee_id) if sc.employee_id else None
        amt = abs(float(sc.amount or 0))
        fol = f"COM-{str(sc.id)[:6].upper()}"
        _push({
            "source_table": "seller_commission_ledger",
            "source_id": str(sc.id),
            "sucursal_id": _norm_branch_display(branch_lookup, emp.sucursal_id if emp else "MATRIZ"),
            "caja_id": None,
            "category": "ventas",
            "doc_subtype": "liquidacion_comision",
            "print_doc_type": "comprobante_pago",
            "doc_nature": "EMITIDO",
            "serie": "COM",
            "folio_visible": fol,
            "emisor_user_id": str(sc.registrado_por or ""),
            "emisor_nombre": _emp_label(sc.registrado_por),
            "tercero_id": str(sc.employee_id or ""),
            "tercero_tipo": "EMPLEADO",
            "tercero_nombre": str((emp.full_name if emp else sc.employee_id) or "COMISIONISTA").upper(),
            "tercero_rfc": None,
            "uuid_fiscal": None,
            "reference_text": str(sc.descripcion or sc.entry_type or "LIQUIDACIÓN COMISIÓN").upper(),
            "currency": "MXN",
            "amount_applicable": True,
            "subtotal": _dec(amt),
            "discount_amount": _dec(0),
            "tax_amount": _dec(0),
            "total_amount": _dec(amt),
            "doc_status": str(sc.entry_type or "LIQUIDADA").upper(),
            "payment_status": "PAGADO",
            "fiscal_status": "NO_FISCAL",
            "cancel_reason": None,
            "emitted_at": sc.created_at,
            "has_original_file": (str(sc.id) in emissions_by_op),
            "has_xml": False,
            "has_acuse": False,
            "extra_meta_json": {"sale_id": sc.sale_id, "ar_payment_id": sc.ar_payment_id},
        })

    # ── 7. CAJA: TURNOS ABIERTOS (APERTURA) Y CERRADOS (CORTE Z POR CAJA) ─────
    for cs in db.query(models.CashShift).filter(models.CashShift.empresa_id == empresa_id).all():
        st = str(cs.status or "OPEN").upper()
        suc_lbl = _norm_branch_display(branch_lookup, cs.sucursal_id)
        caja_code = f"CAJA 01 · {suc_lbl}".upper()
        if st == "OPEN":
            sub_id = "apertura_caja"
            prt_dt = "apertura_caja"
            fol = f"APE-{str(cs.id)[:6].upper()}"
            amt = float(cs.opening_amount or 0)
            st_lbl = "ABIERTO"
        else:
            sub_id = "corte_z"
            prt_dt = "corte_z"
            fol = f"COR-{str(cs.id)[:6].upper()}"
            amt = float(cs.reported_amount if cs.reported_amount is not None else (cs.expected_amount or 0))
            st_lbl = "CON_DIFERENCIA" if st == "DISCREPANCY" else "CERRADO"

        _push({
            "source_table": "cash_shifts",
            "source_id": str(cs.id),
            "sucursal_id": suc_lbl,
            "caja_id": caja_code,
            "category": "caja",
            "doc_subtype": sub_id,
            "print_doc_type": prt_dt,
            "doc_nature": "EMITIDO",
            "serie": "COR" if sub_id == "corte_z" else "APE",
            "folio_visible": fol,
            "emisor_user_id": str(cs.closed_by_id or cs.opened_by_id or ""),
            "emisor_nombre": _emp_label(cs.closed_by_id or cs.opened_by_id),
            "tercero_id": str(cs.id),
            "tercero_tipo": "CAJA",
            "tercero_nombre": caja_code,
            "tercero_rfc": None,
            "uuid_fiscal": None,
            "reference_text": f"TURNO {str(cs.id)[:8].upper()} · FONDO ${float(cs.opening_amount or 0):,.2f}",
            "currency": "MXN",
            "amount_applicable": True,
            "subtotal": _dec(amt),
            "discount_amount": _dec(0),
            "tax_amount": _dec(0),
            "total_amount": _dec(amt),
            "doc_status": st_lbl,
            "payment_status": "CONCILIADO" if st == "CLOSED" else ("PENDIENTE_AUTORIZACION" if st == "DISCREPANCY" else "EN_TURNO"),
            "fiscal_status": "NO_FISCAL",
            "cancel_reason": None,
            "emitted_at": cs.created_at,
            "has_original_file": (str(cs.id) in emissions_by_op or fol in emissions_by_op),
            "has_xml": False,
            "has_acuse": False,
            "extra_meta_json": {
                "opening_amount": float(cs.opening_amount or 0),
                "expected_amount": float(cs.expected_amount or 0),
                "reported_amount": float(cs.reported_amount) if cs.reported_amount is not None else None,
                "difference": float(cs.difference) if cs.difference is not None else None,
                "individual_caja_only": True,
            },
        })

    # Emisiones explícitas de Caja (Corte X, Arqueo Ciego, Entradas/Salidas) y Constancias RH
    for em in all_emissions:
        dt_code = str(em.doc_type or "").lower()
        if dt_code in ("corte_x", "corte_ciego", "entrada_caja", "salida_caja", "constancia_rh", "documento_formal_rh"):
            snap = em.data_snapshot_json if isinstance(em.data_snapshot_json, dict) else {}
            imp = snap.get("importes") if isinstance(snap.get("importes"), dict) else {}
            tot_em = float(imp.get("total") or 0)
            if dt_code in ("constancia_rh", "documento_formal_rh"):
                cat_em, sub_em, prt_em, app_amt = "rrhh", "constancia_rh", "documento_formal", False
                terc_t = "EMPLEADO"
                terc_n = str((snap.get("cliente") or {}).get("nombre") or "COLABORADOR").upper()
            else:
                cat_em = "caja"
                sub_em = "arqueo_caja" if dt_code == "corte_ciego" else dt_code
                prt_em = "corte_ciego" if dt_code == "corte_ciego" else ("corte_x" if dt_code == "corte_x" else "apertura_caja")
                app_amt = True
                terc_t = "CAJA"
                terc_n = f"CAJA 01 · {_norm_branch_display(branch_lookup, em.sucursal_id)}".upper()
            _push({
                "source_table": "print_emission_records",
                "source_id": str(em.id),
                "sucursal_id": _norm_branch_display(branch_lookup, em.sucursal_id),
                "caja_id": terc_n if terc_t == "CAJA" else None,
                "category": cat_em,
                "doc_subtype": sub_em,
                "print_doc_type": prt_em,
                "doc_nature": "REPORTE_AL_MOMENTO" if dt_code == "corte_x" else "EMITIDO",
                "serie": sub_em[:3].upper(),
                "folio_visible": str(em.operation_folio or f"EMI-{em.id[:6]}").upper(),
                "emisor_user_id": str(em.emitted_by or ""),
                "emisor_nombre": _emp_label(em.emitted_by),
                "tercero_id": str(em.operation_id or ""),
                "tercero_tipo": terc_t,
                "tercero_nombre": terc_n,
                "tercero_rfc": None,
                "uuid_fiscal": None,
                "reference_text": f"EMISIÓN v{em.version_num} ({em.mode})",
                "currency": "MXN",
                "amount_applicable": app_amt,
                "subtotal": _dec(tot_em) if app_amt else None,
                "discount_amount": _dec(0) if app_amt else None,
                "tax_amount": _dec(0) if app_amt else None,
                "total_amount": _dec(tot_em) if app_amt else None,
                "doc_status": "EMITIDO",
                "payment_status": "NO_APLICA",
                "fiscal_status": "NO_FISCAL",
                "cancel_reason": None,
                "emitted_at": em.emitted_at,
                "has_original_file": True,
                "has_xml": False,
                "has_acuse": False,
                "extra_meta_json": {"template_id": em.template_id, "version_id": em.version_id},
            })

    # ── 8. COMPRAS: ÓRDENES, RECEPCIONES, CXP, PAGOS Y GASTOS ─────────────────
    for po in db.query(models.PurchaseOrder).filter(models.PurchaseOrder.empresa_id == empresa_id).all():
        sup = suppliers_map.get(po.supplier_id) if po.supplier_id else None
        tot = float(po.total or 0)
        fol = str(po.folio or f"OC-{po.id[:6]}").upper()
        st = str(po.status or "EMITIDA").upper()
        _push({
            "source_table": "purchase_orders",
            "source_id": str(po.id),
            "sucursal_id": _norm_branch_display(branch_lookup, po.sucursal_id),
            "caja_id": None,
            "category": "compras",
            "doc_subtype": "orden_compra",
            "print_doc_type": "orden_compra",
            "doc_nature": "EMITIDO",
            "serie": "OC",
            "folio_visible": fol,
            "emisor_user_id": str(po.authorized_by or ""),
            "emisor_nombre": _emp_label(po.authorized_by),
            "tercero_id": str(po.supplier_id or ""),
            "tercero_tipo": "PROVEEDOR",
            "tercero_nombre": str((sup.name if sup else "PROVEEDOR GENERAL")).upper(),
            "tercero_rfc": str((sup.rfc if sup else "") or "").upper() or None,
            "uuid_fiscal": None,
            "reference_text": str(po.notes or "ORDEN DE COMPRA").upper(),
            "currency": "MXN",
            "amount_applicable": True,
            "subtotal": _dec(po.subtotal if po.subtotal is not None else round(tot / 1.16, 4)),
            "discount_amount": _dec(0),
            "tax_amount": _dec(po.tax_amount if po.tax_amount is not None else round(tot - round(tot / 1.16, 4), 4)),
            "total_amount": _dec(tot),
            "doc_status": "CANCELADA" if st in ("CANCELLED", "CANCELADA") else st,
            "payment_status": "NO_APLICA",
            "fiscal_status": "NO_FISCAL",
            "cancel_reason": str(po.notes or "").upper() if st in ("CANCELLED", "CANCELADA") else None,
            "emitted_at": po.issue_date or po.created_at,
            "has_original_file": (str(po.id) in emissions_by_op or fol in emissions_by_op),
            "has_xml": False,
            "has_acuse": False,
            "extra_meta_json": {},
        })

    covered_receipt_ids: Set[str] = set()
    for rx in db.query(models.ReceptionExpediente).filter(models.ReceptionExpediente.empresa_id == empresa_id).all():
        if rx.purchase_receipt_id:
            covered_receipt_ids.add(str(rx.purchase_receipt_id))
        tot = float(rx.total or 0)
        fol = str(rx.folio or rx.purchase_receipt_folio or f"REC-{rx.id[:6]}").upper()
        n_files = int(rec_file_counts.get(rx.id, 0))
        _push({
            "source_table": "reception_expedientes",
            "source_id": str(rx.id),
            "sucursal_id": _norm_branch_display(branch_lookup, rx.sucursal_id),
            "caja_id": None,
            "category": "compras",
            "doc_subtype": "recepcion_compra",
            "print_doc_type": "remision",
            "doc_nature": "EMITIDO",
            "serie": "REC",
            "folio_visible": fol,
            "emisor_user_id": str(rx.created_by or ""),
            "emisor_nombre": _emp_label(rx.created_by),
            "tercero_id": str(rx.supplier_id or ""),
            "tercero_tipo": "PROVEEDOR",
            "tercero_nombre": str(rx.supplier_name or "PROVEEDOR").upper(),
            "tercero_rfc": str(rx.supplier_rfc or "").upper() or None,
            "uuid_fiscal": str(rx.invoice_uuid or "") or None,
            "reference_text": f"OC: {rx.po_folio or 'DIRECTA'} · FACT: {rx.invoice_folio or '—'}".upper(),
            "currency": "MXN",
            "amount_applicable": True,
            "subtotal": _dec(rx.subtotal or round(tot / 1.16, 4)),
            "discount_amount": _dec(0),
            "tax_amount": _dec(rx.tax_amount or round(tot - round(tot / 1.16, 4), 4)),
            "total_amount": _dec(tot),
            "doc_status": str(rx.status or "RECIBIDA").upper(),
            "payment_status": str(rx.payment_condition or "PENDIENTE").upper(),
            "fiscal_status": "CON_CFDI_PROVEEDOR" if rx.invoice_uuid else "SIN_CFDI",
            "cancel_reason": None,
            "emitted_at": rx.created_at,
            "has_original_file": n_files > 0 or (str(rx.id) in emissions_by_op),
            "has_xml": bool(rx.invoice_uuid),
            "has_acuse": False,
            "attachments_extra": n_files,
            "extra_meta_json": {
                "purchase_order_id": rx.purchase_order_id,
                "accounts_payable_id": rx.accounts_payable_id,
                "freight_expense_id": rx.freight_expense_id,
            },
        })

    for pr in db.query(models.PurchaseReceipt).filter(models.PurchaseReceipt.empresa_id == empresa_id).all():
        if str(pr.id) in covered_receipt_ids:
            continue
        sup = suppliers_map.get(pr.supplier_id) if pr.supplier_id else None
        tot = float(pr.total or 0)
        fol = str(pr.folio or f"REC-{pr.id[:6]}").upper()
        _push({
            "source_table": "purchase_receipts",
            "source_id": str(pr.id),
            "sucursal_id": _norm_branch_display(branch_lookup, pr.sucursal_id),
            "caja_id": None,
            "category": "compras",
            "doc_subtype": "recepcion_compra",
            "print_doc_type": "remision",
            "doc_nature": "EMITIDO",
            "serie": "REC",
            "folio_visible": fol,
            "emisor_user_id": str(pr.received_by or ""),
            "emisor_nombre": _emp_label(pr.received_by),
            "tercero_id": str(pr.supplier_id or ""),
            "tercero_tipo": "PROVEEDOR",
            "tercero_nombre": str((sup.name if sup else "PROVEEDOR")).upper(),
            "tercero_rfc": str((sup.rfc if sup else "") or "").upper() or None,
            "uuid_fiscal": None,
            "reference_text": str(pr.notes or "RECEPCIÓN DE MERCANCÍA").upper(),
            "currency": "MXN",
            "amount_applicable": True,
            "subtotal": _dec(pr.subtotal or round(tot / 1.16, 4)),
            "discount_amount": _dec(0),
            "tax_amount": _dec(pr.tax_amount or round(tot - round(tot / 1.16, 4), 4)),
            "total_amount": _dec(tot),
            "doc_status": "RECIBIDA",
            "payment_status": str(pr.payment_type or "CRÉDITO").upper(),
            "fiscal_status": "NO_FISCAL",
            "cancel_reason": None,
            "emitted_at": pr.receipt_date or pr.created_at,
            "has_original_file": (str(pr.id) in emissions_by_op),
            "has_xml": False,
            "has_acuse": False,
            "extra_meta_json": {"purchase_order_id": pr.purchase_order_id},
        })

    ap_rows = db.query(models.AccountsPayable).filter(models.AccountsPayable.empresa_id == empresa_id).all()
    ap_map = {ap.id: ap for ap in ap_rows}
    for ap in ap_rows:
        sup = suppliers_map.get(ap.supplier_id) if ap.supplier_id else None
        tot = float(ap.amount or 0)
        bal = float(ap.balance if ap.balance is not None else tot)
        fol = str(ap.folio or ap.invoice_ref or f"CXP-{ap.id[:6]}").upper()
        _push({
            "source_table": "accounts_payable",
            "source_id": str(ap.id),
            "sucursal_id": _norm_branch_display(branch_lookup, ap.sucursal_id),
            "caja_id": None,
            "category": "compras",
            "doc_subtype": "cuenta_por_pagar",
            "print_doc_type": "estado_cuenta_cliente",
            "doc_nature": "EMITIDO",
            "serie": "CXP",
            "folio_visible": fol,
            "emisor_user_id": None,
            "emisor_nombre": "CUENTAS POR PAGAR",
            "tercero_id": str(ap.supplier_id or ""),
            "tercero_tipo": "PROVEEDOR",
            "tercero_nombre": str((sup.name if sup else "PROVEEDOR")).upper(),
            "tercero_rfc": str((sup.rfc if sup else "") or "").upper() or None,
            "uuid_fiscal": str(ap.invoice_uuid or "") or None,
            "reference_text": str(ap.concept or ap.invoice_ref or "PASIVO PROVEEDOR").upper(),
            "currency": "MXN",
            "amount_applicable": True,
            "subtotal": _dec(round(tot / 1.16, 4)),
            "discount_amount": _dec(0),
            "tax_amount": _dec(round(tot - round(tot / 1.16, 4), 4)),
            "total_amount": _dec(tot),
            "doc_status": str(ap.status or "ACTIVA").upper(),
            "payment_status": "PAGADO" if bal <= 0.01 else ("PARCIAL" if float(ap.amount_paid or 0) > 0 else "PENDIENTE"),
            "fiscal_status": "VINCULADO_UUID" if ap.invoice_uuid else "SIN_UUID",
            "cancel_reason": None,
            "emitted_at": ap.issue_date or ap.created_at,
            "has_original_file": bool(ap.expediente_id and rec_file_counts.get(ap.expediente_id)),
            "has_xml": bool(ap.invoice_uuid),
            "has_acuse": False,
            "extra_meta_json": {
                "purchase_order_id": ap.purchase_order_id,
                "purchase_receipt_id": ap.purchase_receipt_id,
                "expediente_id": ap.expediente_id,
                "balance": bal,
            },
        })

    for sp in db.query(models.SupplierPayment).filter(models.SupplierPayment.empresa_id == empresa_id).all():
        ap = ap_map.get(sp.accounts_payable_id) if sp.accounts_payable_id else None
        sup = suppliers_map.get(ap.supplier_id) if (ap and ap.supplier_id) else None
        amt = float(sp.amount or 0)
        fol = f"PAG-{str(sp.id)[:6].upper()}"
        _push({
            "source_table": "supplier_payments",
            "source_id": str(sp.id),
            "sucursal_id": _norm_branch_display(branch_lookup, ap.sucursal_id if ap else "MATRIZ"),
            "caja_id": None,
            "category": "compras",
            "doc_subtype": "pago_proveedor",
            "print_doc_type": "comprobante_pago",
            "doc_nature": "EMITIDO",
            "serie": "PAG",
            "folio_visible": fol,
            "emisor_user_id": str(sp.registered_by or ""),
            "emisor_nombre": _emp_label(sp.registered_by),
            "tercero_id": str(sup.id if sup else ""),
            "tercero_tipo": "PROVEEDOR",
            "tercero_nombre": str((sup.name if sup else "PROVEEDOR")).upper(),
            "tercero_rfc": str((sup.rfc if sup else "") or "").upper() or None,
            "uuid_fiscal": None,
            "reference_text": str(sp.reference or sp.notes or "PAGO A PROVEEDOR").upper(),
            "currency": "MXN",
            "amount_applicable": True,
            "subtotal": _dec(amt),
            "discount_amount": _dec(0),
            "tax_amount": _dec(0),
            "total_amount": _dec(amt),
            "doc_status": "APLICADO",
            "payment_status": "PAGADO",
            "fiscal_status": "NO_FISCAL",
            "cancel_reason": None,
            "emitted_at": sp.payment_date or sp.created_at,
            "has_original_file": (str(sp.id) in emissions_by_op),
            "has_xml": False,
            "has_acuse": False,
            "extra_meta_json": {"accounts_payable_id": sp.accounts_payable_id, "payment_method": sp.payment_method},
        })

    for oe in db.query(models.OperatingExpense).filter(models.OperatingExpense.empresa_id == empresa_id).all():
        amt = float(oe.amount or 0)
        fol = str(oe.folio or oe.doc_folio or f"GAS-{oe.id[:6]}").upper()
        _push({
            "source_table": "operating_expenses",
            "source_id": str(oe.id),
            "sucursal_id": _norm_branch_display(branch_lookup, oe.sucursal_id),
            "caja_id": None,
            "category": "compras",
            "doc_subtype": "gasto_operativo",
            "print_doc_type": "comprobante_pago",
            "doc_nature": "EMITIDO",
            "serie": "GAS",
            "folio_visible": fol,
            "emisor_user_id": str(oe.created_by or ""),
            "emisor_nombre": _emp_label(oe.created_by),
            "tercero_id": None,
            "tercero_tipo": "PROVEEDOR",
            "tercero_nombre": str(oe.supplier_name or oe.category or "GASTO OPERATIVO").upper(),
            "tercero_rfc": str(oe.supplier_rfc or "").upper() or None,
            "uuid_fiscal": str(oe.doc_uuid or "") or None,
            "reference_text": str(oe.concept or oe.category or "").upper(),
            "currency": "MXN",
            "amount_applicable": True,
            "subtotal": _dec(round(amt / 1.16, 4)),
            "discount_amount": _dec(0),
            "tax_amount": _dec(round(amt - round(amt / 1.16, 4), 4)),
            "total_amount": _dec(amt),
            "doc_status": str(oe.status or "REGISTRADO").upper(),
            "payment_status": str(oe.payment_condition or "PAGADO").upper(),
            "fiscal_status": "CON_CFDI" if oe.doc_uuid else "NO_FISCAL",
            "cancel_reason": None,
            "emitted_at": oe.created_at,
            "has_original_file": (str(oe.id) in emissions_by_op),
            "has_xml": bool(oe.doc_uuid),
            "has_acuse": False,
            "extra_meta_json": {"expediente_id": oe.expediente_id, "accounts_payable_id": oe.accounts_payable_id},
        })

    # ── 9. ALMACÉN: ENTREGAS, TRASLADOS, AJUSTES, TOMAS, COMODATOS, ENVASES ───
    sk_rows = db.query(models.SafekeptItem).filter(models.SafekeptItem.empresa_id == empresa_id).all()
    sk_map = {sk.id: sk for sk in sk_rows}
    delivered_sk_ids: Set[str] = set()
    for kd in db.query(models.KardexDelivery).filter(models.KardexDelivery.empresa_id == empresa_id).all():
        sk = sk_map.get(kd.safekept_item_id) if kd.safekept_item_id else None
        if sk:
            delivered_sk_ids.add(str(sk.id))
        sale = sales_map.get(sk.sale_id) if (sk and sk.sale_id) else None
        cli = clients_map.get(sale.client_id) if (sale and sale.client_id) else None
        tot = float(sale.total or 0) if sale else 0.0
        fol = f"ENT-{str(kd.id)[:6].upper()}"
        _push({
            "source_table": "kardex_deliveries",
            "source_id": str(kd.id),
            "sucursal_id": _norm_branch_display(branch_lookup, kd.sucursal_id or (sale.sucursal_id if sale else "MATRIZ")),
            "caja_id": None,
            "category": "almacen",
            "doc_subtype": "orden_entrega",
            "print_doc_type": "orden_entrega",
            "doc_nature": "EMITIDO",
            "serie": "ENT",
            "folio_visible": fol,
            "emisor_user_id": None,
            "emisor_nombre": "DESPACHO ALMACÉN",
            "tercero_id": str(cli.id if cli else ""),
            "tercero_tipo": "CLIENTE",
            "tercero_nombre": str((cli.name if cli else "PÚBLICO EN GENERAL")).upper(),
            "tercero_rfc": str((cli.rfc if cli else "XAXX010101000") or "XAXX010101000").upper(),
            "uuid_fiscal": None,
            "reference_text": str(kd.notes or (f"ENTREGA VENTA {sale.folio}" if sale else "ENTREGA DE PATIO")).upper(),
            "currency": "MXN",
            "amount_applicable": bool(sale is not None),
            "subtotal": _dec(round(tot / 1.16, 4)) if sale else None,
            "discount_amount": _dec(0) if sale else None,
            "tax_amount": _dec(round(tot - round(tot / 1.16, 4), 4)) if sale else None,
            "total_amount": _dec(tot) if sale else None,
            "doc_status": "ENTREGADA",
            "payment_status": "PAGADO" if sale else "NO_APLICA",
            "fiscal_status": "NO_FISCAL",
            "cancel_reason": None,
            "emitted_at": kd.delivery_date,
            "has_original_file": (str(kd.id) in emissions_by_op or fol in emissions_by_op),
            "has_xml": False,
            "has_acuse": False,
            "extra_meta_json": {"sale_id": sale.id if sale else None, "safekept_item_id": kd.safekept_item_id, "quantity_delivered": float(kd.quantity_delivered or 0)},
        })

    for sk in sk_rows:
        if str(sk.id) in delivered_sk_ids:
            continue
        sale = sales_map.get(sk.sale_id) if sk.sale_id else None
        cli = clients_map.get(sale.client_id) if (sale and sale.client_id) else None
        tot = float(sale.total or 0) if sale else 0.0
        fol = f"ORD-ENT-{str(sk.id)[:6].upper()}"
        _push({
            "source_table": "safekept_items",
            "source_id": str(sk.id),
            "sucursal_id": _norm_branch_display(branch_lookup, sk.sucursal_id),
            "caja_id": None,
            "category": "almacen",
            "doc_subtype": "orden_entrega",
            "print_doc_type": "orden_entrega",
            "doc_nature": "EMITIDO",
            "serie": "ENT",
            "folio_visible": fol,
            "emisor_user_id": None,
            "emisor_nombre": "ALMACÉN / RESGUARDO",
            "tercero_id": str(cli.id if cli else ""),
            "tercero_tipo": "CLIENTE",
            "tercero_nombre": str((cli.name if cli else "PÚBLICO EN GENERAL")).upper(),
            "tercero_rfc": str((cli.rfc if cli else "XAXX010101000") or "XAXX010101000").upper(),
            "uuid_fiscal": None,
            "reference_text": f"ORDEN DE ENTREGA SKU {sk.product_sku} ({float(sk.quantity_delivered or 0)}/{float(sk.quantity_ordered or 0)})".upper(),
            "currency": "MXN",
            "amount_applicable": bool(sale is not None),
            "subtotal": _dec(round(tot / 1.16, 4)) if sale else None,
            "discount_amount": _dec(0) if sale else None,
            "tax_amount": _dec(round(tot - round(tot / 1.16, 4), 4)) if sale else None,
            "total_amount": _dec(tot) if sale else None,
            "doc_status": str(sk.status or "PENDIENTE_ENTREGA").upper(),
            "payment_status": "NO_APLICA",
            "fiscal_status": "NO_FISCAL",
            "cancel_reason": None,
            "emitted_at": sk.created_at,
            "has_original_file": (str(sk.id) in emissions_by_op),
            "has_xml": False,
            "has_acuse": False,
            "extra_meta_json": {"sale_id": sk.sale_id, "product_sku": sk.product_sku},
        })

    for tr in db.query(models.Transfer).filter(models.Transfer.empresa_id == empresa_id).all():
        orig = _norm_branch_display(branch_lookup, tr.sucursal_origen_id or "MATRIZ")
        dest = _norm_branch_display(branch_lookup, tr.sucursal_destino_id or "SUCURSAL")
        fol = str(tr.folio or f"TRA-{tr.id[:6]}").upper()
        _push({
            "source_table": "transfers",
            "source_id": str(tr.id),
            "sucursal_id": orig,
            "caja_id": None,
            "category": "almacen",
            "doc_subtype": "traslado",
            "print_doc_type": "remision",
            "doc_nature": "EMITIDO",
            "serie": "TRA",
            "folio_visible": fol,
            "emisor_user_id": str(tr.requested_by or ""),
            "emisor_nombre": _emp_label(tr.requested_by),
            "tercero_id": str(tr.sucursal_destino_id or ""),
            "tercero_tipo": "INTERNO",
            "tercero_nombre": f"{orig} → {dest}".upper(),
            "tercero_rfc": None,
            "uuid_fiscal": None,
            "reference_text": str(tr.notes or f"TRASLADO INTERBODEGA ({tr.tipo or 'GENERAL'})").upper(),
            "currency": "MXN",
            "amount_applicable": False,  # Importe NO aplicable (distinto de $0.00)
            "subtotal": None,
            "discount_amount": None,
            "tax_amount": None,
            "total_amount": None,
            "doc_status": str(tr.status or "EN_TRANSITO").upper(),
            "payment_status": "NO_APLICA",
            "fiscal_status": "NO_FISCAL",
            "cancel_reason": str(tr.rejection_reason or "").upper() or None,
            "emitted_at": tr.created_at,
            "has_original_file": (str(tr.id) in emissions_by_op or fol in emissions_by_op),
            "has_xml": False,
            "has_acuse": False,
            "extra_meta_json": {"origin": orig, "dest": dest},
        })

    for im in db.query(models.InventoryMovement).filter(models.InventoryMovement.empresa_id == empresa_id).all():
        mtype = str(im.movement_type or "").strip().upper()
        if mtype in ("SALE", "VENTA", "PURCHASE", "COMPRA", "RECEPCION"):
            continue
        is_toma = mtype in ("TOMA_INVENTARIO", "CONTEO_FISICO", "INVENTARIO_FISICO")
        sub_id = "toma_inventario" if is_toma else "ajuste_inventario"
        fol_pref = "TOM" if is_toma else "AJU"
        fol = f"{fol_pref}-{str(im.id)[:6].upper()}"
        val_amt = abs(float(im.quantity or 0) * float(im.unit_cost or 0))
        app_amt = not is_toma
        _push({
            "source_table": "inventory_movements",
            "source_id": str(im.id),
            "sucursal_id": _norm_branch_display(branch_lookup, im.sucursal_id),
            "caja_id": None,
            "category": "almacen",
            "doc_subtype": sub_id,
            "print_doc_type": "remision",
            "doc_nature": "EMITIDO",
            "serie": fol_pref,
            "folio_visible": fol,
            "emisor_user_id": str(im.authorized_by_id or ""),
            "emisor_nombre": _emp_label(im.authorized_by_id),
            "tercero_id": str(im.warehouse_id or ""),
            "tercero_tipo": "INTERNO",
            "tercero_nombre": f"ALMACÉN {im.warehouse_id or 'GENERAL'}".upper(),
            "tercero_rfc": None,
            "uuid_fiscal": None,
            "reference_text": str(im.reason or mtype or "AJUSTE INVENTARIO").upper(),
            "currency": "MXN",
            "amount_applicable": app_amt,
            "subtotal": _dec(val_amt) if app_amt else None,
            "discount_amount": _dec(0) if app_amt else None,
            "tax_amount": _dec(0) if app_amt else None,
            "total_amount": _dec(val_amt) if app_amt else None,
            "doc_status": "APLICADO",
            "payment_status": "NO_APLICA",
            "fiscal_status": "NO_FISCAL",
            "cancel_reason": None,
            "emitted_at": im.created_at,
            "has_original_file": (str(im.id) in emissions_by_op),
            "has_xml": False,
            "has_acuse": False,
            "extra_meta_json": {"movement_type": mtype, "quantity": float(im.quantity or 0), "product_id": im.product_id},
        })

    for cm in db.query(models.ComodatoItem).filter(models.ComodatoItem.empresa_id == empresa_id).all():
        cli = clients_map.get(cm.client_id) if cm.client_id else None
        ctipo = str(cm.tipo or "COMODATO").strip().upper()
        is_env = ctipo in ("ENVASE", "RETORNABLE", "GARRAFON", "TARIMA")
        sub_id = "movimiento_envase" if is_env else "comodato"
        fol = str(cm.folio or f"{'ENV' if is_env else 'CMD'}-{cm.id[:6]}").upper()
        gar = float(cm.valor_garantia or 0)
        _push({
            "source_table": "comodato_items",
            "source_id": str(cm.id),
            "sucursal_id": _norm_branch_display(branch_lookup, cm.sucursal_id),
            "caja_id": None,
            "category": "almacen",
            "doc_subtype": sub_id,
            "print_doc_type": "remision" if is_env else "documento_formal",
            "doc_nature": "EMITIDO",
            "serie": "ENV" if is_env else "CMD",
            "folio_visible": fol,
            "emisor_user_id": str(cm.created_by or ""),
            "emisor_nombre": _emp_label(cm.created_by),
            "tercero_id": str(cm.client_id or ""),
            "tercero_tipo": "CLIENTE",
            "tercero_nombre": str((cli.name if cli else "CLIENTE GENERAL")).upper(),
            "tercero_rfc": str((cli.rfc if cli else "") or "").upper() or None,
            "uuid_fiscal": None,
            "reference_text": str(cm.descripcion or cm.notas or ctipo).upper(),
            "currency": "MXN",
            "amount_applicable": True,
            "subtotal": _dec(gar),
            "discount_amount": _dec(0),
            "tax_amount": _dec(0),
            "total_amount": _dec(gar),
            "doc_status": str(cm.status or "ACTIVO").upper(),
            "payment_status": "GARANTÍA",
            "fiscal_status": "NO_FISCAL",
            "cancel_reason": None,
            "emitted_at": cm.fecha_entrega or cm.created_at,
            "has_original_file": (str(cm.id) in emissions_by_op),
            "has_xml": False,
            "has_acuse": False,
            "extra_meta_json": {"sale_id": cm.sale_id, "adhesion_contract_id": cm.adhesion_contract_id},
        })

    # ── 10. CARTERA: ESTADOS DE CUENTA, ABONOS, APLICACIÓN SALDO, CONTRATOS ───
    for ar in all_ars:
        cli = clients_map.get(ar.client_id) if ar.client_id else None
        orig_amt = float(ar.original_amount or 0)
        bal = float(ar.current_balance if ar.current_balance is not None else orig_amt)
        fol = f"CXC-{str(ar.sale_folio or ar.id[:6]).upper()}"
        _push({
            "source_table": "accounts_receivable",
            "source_id": str(ar.id),
            "sucursal_id": _norm_branch_display(branch_lookup, ar.sucursal_id),
            "caja_id": None,
            "category": "cartera",
            "doc_subtype": "estado_cuenta",
            "print_doc_type": "estado_cuenta_cliente",
            "doc_nature": "EMITIDO",
            "serie": "CXC",
            "folio_visible": fol,
            "emisor_user_id": str(ar.seller_id or ""),
            "emisor_nombre": _emp_label(ar.seller_id),
            "tercero_id": str(ar.client_id or ""),
            "tercero_tipo": "CLIENTE",
            "tercero_nombre": str((cli.name if cli else "CLIENTE CRÉDITO")).upper(),
            "tercero_rfc": str((cli.rfc if cli else "XAXX010101000") or "XAXX010101000").upper(),
            "uuid_fiscal": None,
            "reference_text": f"SALDO ACTUAL ${bal:,.2f} · VENTA {ar.sale_folio or ''}".upper(),
            "currency": "MXN",
            "amount_applicable": True,
            "subtotal": _dec(orig_amt),
            "discount_amount": _dec(0),
            "tax_amount": _dec(0),
            "total_amount": _dec(orig_amt),
            "doc_status": "PAGADO" if (ar.is_paid or bal <= 0.01) else str(ar.status or "VIGENTE").upper(),
            "payment_status": "PAGADO" if (ar.is_paid or bal <= 0.01) else ("PARCIAL" if bal < orig_amt else "PENDIENTE"),
            "fiscal_status": "NO_FISCAL",
            "cancel_reason": None,
            "emitted_at": ar.created_at,
            "has_original_file": (str(ar.id) in emissions_by_op),
            "has_xml": False,
            "has_acuse": False,
            "extra_meta_json": {"sale_id": ar.sale_id, "current_balance": bal},
        })

    for arp in db.query(models.AccountReceivablePayment).filter(models.AccountReceivablePayment.empresa_id == empresa_id).all():
        cli = clients_map.get(arp.client_id) if arp.client_id else None
        app_from = str(arp.applied_from or "CAJA").strip().upper()
        is_aplicacion = app_from in ("SALDO_FAVOR", "ANTICIPO")
        sub_id = "aplicacion_saldo" if is_aplicacion else "comprobante_abono"
        fol_pref = "APL" if is_aplicacion else "ABO"
        fol = f"{fol_pref}-{str(arp.id)[:6].upper()}"
        amt = float(arp.amount or 0)
        _push({
            "source_table": "account_receivable_payments",
            "source_id": str(arp.id),
            "sucursal_id": _norm_branch_display(branch_lookup, arp.sucursal_id),
            "caja_id": "CAJA-01",
            "category": "cartera",
            "doc_subtype": sub_id,
            "print_doc_type": "comprobante_pago",
            "doc_nature": "EMITIDO",
            "serie": fol_pref,
            "folio_visible": fol,
            "emisor_user_id": str(arp.created_by or ""),
            "emisor_nombre": _emp_label(arp.created_by),
            "tercero_id": str(arp.client_id or ""),
            "tercero_tipo": "CLIENTE",
            "tercero_nombre": str((cli.name if cli else "CLIENTE CRÉDITO")).upper(),
            "tercero_rfc": str((cli.rfc if cli else "XAXX010101000") or "XAXX010101000").upper(),
            "uuid_fiscal": None,
            "reference_text": str(arp.reference or arp.notes or arp.method or "ABONO A CUENTA").upper(),
            "currency": "MXN",
            "amount_applicable": True,
            "subtotal": _dec(amt),
            "discount_amount": _dec(0),
            "tax_amount": _dec(0),
            "total_amount": _dec(amt),
            "doc_status": "APLICADA" if is_aplicacion else "REGISTRADO",
            "payment_status": "PAGADO",
            "fiscal_status": "NO_FISCAL",
            "cancel_reason": None,
            "emitted_at": arp.created_at,
            "has_original_file": (str(arp.id) in emissions_by_op or fol in emissions_by_op),
            "has_xml": False,
            "has_acuse": False,
            "extra_meta_json": {"ar_id": arp.ar_id, "applied_from": app_from, "balance_after": float(arp.balance_after or 0)},
        })

    for ac in db.query(models.AdhesionContract).filter(models.AdhesionContract.empresa_id == empresa_id).all():
        cli = clients_map.get(ac.client_id) if ac.client_id else None
        fol = f"CTR-{str(ac.id)[:6].upper()}"
        _push({
            "source_table": "adhesion_contracts",
            "source_id": str(ac.id),
            "sucursal_id": _norm_branch_display(branch_lookup, ac.sucursal_id),
            "caja_id": None,
            "category": "cartera",
            "doc_subtype": "contrato_adhesion",
            "print_doc_type": "documento_formal",
            "doc_nature": "EMITIDO",
            "serie": "CTR",
            "folio_visible": fol,
            "emisor_user_id": str(ac.created_by or ""),
            "emisor_nombre": _emp_label(ac.created_by),
            "tercero_id": str(ac.client_id or ""),
            "tercero_tipo": "CLIENTE",
            "tercero_nombre": str((cli.name if cli else "CLIENTE")).upper(),
            "tercero_rfc": str((cli.rfc if cli else "") or "").upper() or None,
            "uuid_fiscal": None,
            "reference_text": f"CONTRATO {ac.tipo or 'ADHESIÓN'} v{ac.version or '1.0'}".upper(),
            "currency": "MXN",
            "amount_applicable": False,
            "subtotal": None,
            "discount_amount": None,
            "tax_amount": None,
            "total_amount": None,
            "doc_status": "FIRMADO" if ac.firmado_cliente else str(ac.status or "EMITIDO").upper(),
            "payment_status": "NO_APLICA",
            "fiscal_status": "PROFECO_LEGAL",
            "cancel_reason": None,
            "emitted_at": ac.firma_fecha or ac.created_at,
            "has_original_file": True,
            "has_xml": False,
            "has_acuse": False,
            "extra_meta_json": {"sale_id": ac.sale_id, "firmado_cliente": bool(ac.firmado_cliente)},
        })

    # ── 11. FACTURACIÓN: CFDI I / E / P / T Y FACTURAS GLOBALES ───────────────
    for cd in all_cfdis:
        ctipo = str(cd.tipo or "I").strip().upper()
        sub_map = {"I": "cfdi_ingreso", "E": "cfdi_egreso", "P": "cfdi_pago", "T": "cfdi_traslado"}
        sub_id = sub_map.get(ctipo, "cfdi_ingreso")
        pref = {"I": "FAC", "E": "NCE", "P": "REP", "T": "CPT"}.get(ctipo, "FAC")
        sf = "-".join(x for x in (cd.serie, cd.folio) if x)
        fol = f"{pref}-{sf}".upper() if sf else f"{pref}-{str(cd.id)[:6].upper()}"
        tot = float(cd.total or 0)
        sub_v = 0.0 if ctipo in ("P", "T") else round(tot / 1.16, 4)
        iva_v = 0.0 if ctipo in ("P", "T") else round(tot - sub_v, 4)
        cst = str(cd.status or "TIMBRADO").strip().upper()
        _push({
            "source_table": "cfdi_documents",
            "source_id": str(cd.id),
            "sucursal_id": _norm_branch_display(branch_lookup, cd.sucursal_id),
            "caja_id": None,
            "category": "facturacion",
            "doc_subtype": sub_id,
            "print_doc_type": "cfdi_factura_ticket",
            "doc_nature": "EMITIDO",
            "serie": str(cd.serie or pref).upper(),
            "folio_visible": fol,
            "emisor_user_id": str(cd.created_by or ""),
            "emisor_nombre": _emp_label(cd.created_by),
            "tercero_id": None,
            "tercero_tipo": "CLIENTE",
            "tercero_nombre": str(cd.receptor_nombre or "PÚBLICO EN GENERAL").upper(),
            "tercero_rfc": str(cd.receptor_rfc or "XAXX010101000").upper(),
            "uuid_fiscal": str(cd.uuid_fiscal or "") or None,
            "reference_text": f"USO {cd.uso_cfdi or 'G03'} · {cd.metodo_pago or 'PUE'}/{cd.forma_pago or '01'}".upper(),
            "currency": "MXN",
            "amount_applicable": ctipo != "T",
            "subtotal": _dec(sub_v) if ctipo != "T" else None,
            "discount_amount": _dec(0) if ctipo != "T" else None,
            "tax_amount": _dec(iva_v) if ctipo != "T" else None,
            "total_amount": _dec(tot) if ctipo != "T" else None,
            "doc_status": "TIMBRADA" if cst == "TIMBRADO" else ("CANCELADA" if cst == "CANCELADO" else cst),
            "payment_status": "PAGADO" if (cd.metodo_pago or "PUE").upper() == "PUE" else "PPD_POR_COBRAR",
            "fiscal_status": "TIMBRADO" if cst == "TIMBRADO" else ("CANCELADO_SAT" if cst == "CANCELADO" else cst),
            "cancel_reason": str(cd.motivo_cancelacion or "").upper() or None,
            "emitted_at": cd.timbrado_at or cd.created_at,
            "has_original_file": bool(cd.pdf_base64 or cd.xml),
            "has_xml": bool(cd.xml),
            "has_acuse": bool(cd.cancelado_at or cd.motivo_cancelacion),
            "extra_meta_json": {"sale_id": cd.sale_id, "tipo_cfdi": ctipo, "uso_cfdi": cd.uso_cfdi},
        })

    for cb in db.query(models.CfdiBatch).filter(models.CfdiBatch.empresa_id == empresa_id).all():
        tot = float(cb.monto_declarado if cb.monto_declarado is not None else (cb.total_sistema or 0))
        fol = f"FGL-{str(cb.periodo or cb.id[:6]).upper()}"
        _push({
            "source_table": "cfdi_batches",
            "source_id": str(cb.id),
            "sucursal_id": _norm_branch_display(branch_lookup, cb.sucursal_id),
            "caja_id": None,
            "category": "facturacion",
            "doc_subtype": "factura_global",
            "print_doc_type": "cfdi_factura_ticket",
            "doc_nature": "EMITIDO",
            "serie": "FGL",
            "folio_visible": fol,
            "emisor_user_id": str(cb.created_by or ""),
            "emisor_nombre": _emp_label(cb.created_by),
            "tercero_id": None,
            "tercero_tipo": "CLIENTE",
            "tercero_nombre": "PÚBLICO EN GENERAL (FACTURA GLOBAL)",
            "tercero_rfc": "XAXX010101000",
            "uuid_fiscal": str(cb.cfdi_uuid or "") or None,
            "reference_text": f"PERIODO {cb.periodo or ''} · {cb.notas_contador or ''}".strip().upper(),
            "currency": "MXN",
            "amount_applicable": True,
            "subtotal": _dec(round(tot / 1.16, 4)),
            "discount_amount": _dec(0),
            "tax_amount": _dec(round(tot - round(tot / 1.16, 4), 4)),
            "total_amount": _dec(tot),
            "doc_status": str(cb.estado or "EMITIDA").upper(),
            "payment_status": "PAGADO",
            "fiscal_status": "TIMBRADO" if cb.cfdi_uuid else "BORRADOR",
            "cancel_reason": None,
            "emitted_at": cb.fecha_emision or cb.created_at,
            "has_original_file": bool(cb.cfdi_pdf_path or cb.cfdi_xml_path),
            "has_xml": bool(cb.cfdi_xml_path),
            "has_acuse": False,
            "extra_meta_json": {"periodo": cb.periodo},
        })

    # ── 12. RECURSOS HUMANOS (Autorizaciones/comprobantes emitidos — NO fichas de catálogo) ─
    for aa in db.query(models.AttendanceAuthorization).filter(models.AttendanceAuthorization.empresa_id == empresa_id).all():
        emp = employees_map.get(aa.user_id) if aa.user_id else None
        fol = f"RH-AUT-{int(aa.id):05d}"
        _push({
            "source_table": "attendance_authorizations",
            "source_id": str(aa.id),
            "sucursal_id": _norm_branch_display(branch_lookup, aa.sucursal_id),
            "caja_id": None,
            "category": "rrhh",
            "doc_subtype": "comprobante_rh",
            "print_doc_type": "documento_formal",
            "doc_nature": "EMITIDO",
            "serie": "RH",
            "folio_visible": fol,
            "emisor_user_id": str(aa.resolved_by or aa.user_id or ""),
            "emisor_nombre": _emp_label(aa.resolved_by or aa.user_id),
            "tercero_id": str(aa.user_id or ""),
            "tercero_tipo": "EMPLEADO",
            "tercero_nombre": str((emp.full_name if emp else aa.user_id) or "COLABORADOR").upper(),
            "tercero_rfc": None,
            "uuid_fiscal": None,
            "reference_text": f"AUTORIZACIÓN SALIDA {aa.event_date} ({float(aa.horas_transcurridas or 0):.1f} H)".upper(),
            "currency": "MXN",
            "amount_applicable": False,
            "subtotal": None,
            "discount_amount": None,
            "tax_amount": None,
            "total_amount": None,
            "doc_status": str(aa.status or "PENDIENTE").upper(),
            "payment_status": "NO_APLICA",
            "fiscal_status": "NO_FISCAL",
            "cancel_reason": None,
            "emitted_at": aa.created_at,
            "has_original_file": (str(aa.id) in emissions_by_op),
            "has_xml": False,
            "has_acuse": False,
            "extra_meta_json": {"event_date": aa.event_date, "horas_transcurridas": aa.horas_transcurridas},
        })

    # ── UPSERT SIN DUPLICADOS EN document_registry_entries ────────────────────
    if rebuild_clean:
        db.query(models.DocumentRegistryEntry).filter(models.DocumentRegistryEntry.empresa_id == empresa_id).delete()
        db.flush()

    existing_rows = {
        (r.source_table, r.source_id): r
        for r in db.query(models.DocumentRegistryEntry).filter(models.DocumentRegistryEntry.empresa_id == empresa_id).all()
    }

    inserted = 0
    updated = 0
    seen_pairs: Set[Tuple[str, str]] = set()

    for cand in candidates:
        pair = (cand["source_table"], cand["source_id"])
        if pair in seen_pairs:
            continue
        seen_pairs.add(pair)

        dkey = make_doc_key(empresa_id, cand["source_table"], cand["source_id"])
        existing_row = existing_rows.get(pair)

        # Conservar siempre la sucursal y caja originales de emisión
        suc_final = existing_row.sucursal_id if (existing_row and existing_row.sucursal_id) else cand["sucursal_id"]
        caja_final = existing_row.caja_id if (existing_row and existing_row.caja_id) else cand.get("caja_id")

        tz_name = resolve_tz_for_branch(tz_map, suc_final)
        emitted_utc, local_date_str = to_branch_local_dt(cand.get("emitted_at"), tz_name)

        n_att = int(att_counts.get(dkey, 0)) + int(cand.get("attachments_extra", 0))
        disp_st = dispatch_status_map.get(dkey, existing_row.dispatch_status if existing_row else "SIN_ENVIO")

        search_parts = [
            cand.get("folio_visible") or "",
            cand.get("serie") or "",
            cand.get("tercero_nombre") or "",
            cand.get("tercero_rfc") or "",
            cand.get("uuid_fiscal") or "",
            cand.get("reference_text") or "",
            cand.get("emisor_nombre") or "",
            suc_final or "",
            SUBTYPE_META_MAP.get(cand["doc_subtype"], {}).get("label", ""),
        ]
        s_blob = " | ".join(str(p).upper() for p in search_parts if p)

        if existing_row:
            existing_row.category = cand["category"]
            existing_row.doc_subtype = cand["doc_subtype"]
            existing_row.print_doc_type = cand.get("print_doc_type")
            existing_row.doc_nature = cand.get("doc_nature") or "EMITIDO"
            existing_row.serie = cand.get("serie")
            existing_row.folio_visible = cand["folio_visible"]
            existing_row.emisor_user_id = cand.get("emisor_user_id")
            existing_row.emisor_nombre = cand.get("emisor_nombre")
            existing_row.tercero_id = cand.get("tercero_id")
            existing_row.tercero_tipo = cand.get("tercero_tipo")
            existing_row.tercero_nombre = cand.get("tercero_nombre")
            existing_row.tercero_rfc = cand.get("tercero_rfc")
            existing_row.uuid_fiscal = cand.get("uuid_fiscal")
            existing_row.reference_text = cand.get("reference_text")
            existing_row.currency = cand.get("currency") or "MXN"
            existing_row.amount_applicable = bool(cand.get("amount_applicable", True))
            existing_row.subtotal = cand.get("subtotal")
            existing_row.discount_amount = cand.get("discount_amount")
            existing_row.tax_amount = cand.get("tax_amount")
            existing_row.total_amount = cand.get("total_amount")
            existing_row.doc_status = cand["doc_status"]
            existing_row.payment_status = cand["payment_status"]
            existing_row.fiscal_status = cand["fiscal_status"]
            existing_row.dispatch_status = disp_st
            existing_row.cancel_reason = cand.get("cancel_reason")
            existing_row.emitted_at = emitted_utc
            existing_row.branch_tz = tz_name
            existing_row.emitted_local_date = local_date_str
            existing_row.has_original_file = bool(existing_row.has_original_file or cand.get("has_original_file"))
            existing_row.has_xml = bool(cand.get("has_xml"))
            existing_row.has_acuse = bool(cand.get("has_acuse"))
            existing_row.attachments_count = n_att
            existing_row.extra_meta_json = cand.get("extra_meta_json") or {}
            existing_row.search_blob = s_blob
            updated += 1
        else:
            new_entry = models.DocumentRegistryEntry(
                id=str(uuid.uuid4()),
                doc_key=dkey,
                empresa_id=empresa_id,
                sucursal_id=suc_final,
                caja_id=caja_final,
                source_table=cand["source_table"],
                source_id=cand["source_id"],
                category=cand["category"],
                doc_subtype=cand["doc_subtype"],
                print_doc_type=cand.get("print_doc_type"),
                doc_nature=cand.get("doc_nature") or "EMITIDO",
                serie=cand.get("serie"),
                folio_visible=cand["folio_visible"],
                emisor_user_id=cand.get("emisor_user_id"),
                emisor_nombre=cand.get("emisor_nombre"),
                tercero_id=cand.get("tercero_id"),
                tercero_tipo=cand.get("tercero_tipo"),
                tercero_nombre=cand.get("tercero_nombre"),
                tercero_rfc=cand.get("tercero_rfc"),
                uuid_fiscal=cand.get("uuid_fiscal"),
                reference_text=cand.get("reference_text"),
                currency=cand.get("currency") or "MXN",
                amount_applicable=bool(cand.get("amount_applicable", True)),
                subtotal=cand.get("subtotal"),
                discount_amount=cand.get("discount_amount"),
                tax_amount=cand.get("tax_amount"),
                total_amount=cand.get("total_amount"),
                doc_status=cand["doc_status"],
                payment_status=cand["payment_status"],
                fiscal_status=cand["fiscal_status"],
                dispatch_status=disp_st,
                cancel_reason=cand.get("cancel_reason"),
                emitted_at=emitted_utc,
                branch_tz=tz_name,
                emitted_local_date=local_date_str,
                has_original_file=bool(cand.get("has_original_file")),
                has_xml=bool(cand.get("has_xml")),
                has_acuse=bool(cand.get("has_acuse")),
                attachments_count=n_att,
                extra_meta_json=cand.get("extra_meta_json") or {},
                search_blob=s_blob,
            )
            db.add(new_entry)
            inserted += 1

    db.commit()
    return {"inserted": inserted, "updated": updated, "total_indexed": inserted + updated}


# ══════════════════════════════════════════════════════════════════════════════
# 5. VÍNCULOS COMPROBABLES (RELACIONADOS), RUTA DE MOVIMIENTO ORIGINAL Y ACTIVIDAD
# ══════════════════════════════════════════════════════════════════════════════

def resolve_movement_route(entry: models.DocumentRegistryEntry) -> Dict[str, str]:
    """Devuelve la página/ruta del módulo emisor donde se edita o cancela el movimiento."""
    route_map = {
        "ventas": ("reportes", "/admin#reportes", "Ventas y Operaciones"),
        "caja": ("caja", "/admin#caja", "Caja y Cortes"),
        "compras": ("compras-ordenes", "/admin#compras-ordenes", "Compras"),
        "almacen": ("kardex", "/admin#kardex", "Almacén y Kardex"),
        "cartera": ("cuentas_cobrar", "/admin#cuentas_cobrar", "Cartera / CxC"),
        "facturacion": ("cfdi", "/admin#cfdi", "Operaciones · CFDI"),
        "rrhh": ("recursos-humanos", "/admin#recursos-humanos", "Recursos Humanos"),
    }
    subtype_overrides = {
        "recepcion_compra": ("compras-recepciones", "/admin#compras-recepciones", "Recepción de Mercancía 360"),
        "cuenta_por_pagar": ("compras-cxp", "/admin#compras-cxp", "Cuentas por Pagar"),
        "pago_proveedor": ("compras-cxp", "/admin#compras-cxp", "Cuentas por Pagar"),
        "traslado": ("traspasos", "/admin#traspasos", "Traslados entre Bodegas"),
        "devolucion_venta": ("almacen-devoluciones", "/admin#almacen-devoluciones", "Devoluciones de Venta"),
        "ajuste_inventario": ("almacen-ajuste", "/admin#almacen-ajuste", "Ajuste de Inventario"),
        "toma_inventario": ("inventario", "/admin#inventario", "Inventario Multibodega"),
    }
    page_id, url, label = subtype_overrides.get(entry.doc_subtype) or route_map.get(entry.category, ("dashboard", "/admin#dashboard", "Módulo Origen"))
    return {
        "page_id": page_id,
        "url": f"{url}?origin_doc={entry.doc_key}&source_id={entry.source_id}",
        "module_label": label,
    }


def build_related_documents(
    db: Session,
    empresa_id: str,
    entry: models.DocumentRegistryEntry,
    perms: Dict[str, Any],
    can_all_branches: bool,
    allowed_branches: List[str],
) -> List[Dict[str, Any]]:
    """Descubre todos los documentos relacionados comprobables en BD para el expediente actual
    y evalúa permisos individuales en cada vínculo."""
    related_pairs: Set[Tuple[str, str, str]] = set()  # (source_table, source_id, relation_label)
    meta = entry.extra_meta_json if isinstance(entry.extra_meta_json, dict) else {}

    # Determinar el anchor sale_id o purchase_order_id si existe
    anchor_sale_id: Optional[str] = None
    anchor_po_id: Optional[str] = None
    anchor_exp_id: Optional[str] = None
    anchor_ap_id: Optional[str] = None

    if entry.source_table == "sales":
        anchor_sale_id = entry.source_id
    elif meta.get("sale_id"):
        anchor_sale_id = str(meta["sale_id"])
    elif entry.source_table == "account_receivable_payments" and meta.get("ar_id"):
        ar_obj = db.query(models.AccountsReceivable).filter(
            models.AccountsReceivable.empresa_id == empresa_id,
            models.AccountsReceivable.id == str(meta["ar_id"]),
        ).first()
        if ar_obj:
            related_pairs.add(("accounts_receivable", str(ar_obj.id), "Cuenta por cobrar"))
            if ar_obj.sale_id:
                anchor_sale_id = str(ar_obj.sale_id)

    if entry.source_table == "purchase_orders":
        anchor_po_id = entry.source_id
    elif meta.get("purchase_order_id"):
        anchor_po_id = str(meta["purchase_order_id"])

    if entry.source_table == "reception_expedientes":
        anchor_exp_id = entry.source_id
    elif meta.get("expediente_id"):
        anchor_exp_id = str(meta["expediente_id"])

    if entry.source_table == "accounts_payable":
        anchor_ap_id = entry.source_id
    elif meta.get("accounts_payable_id"):
        anchor_ap_id = str(meta["accounts_payable_id"])

    # Grafo comercial: Venta <-> Entrega <-> CFDI <-> CxC <-> Abonos <-> Devolución <-> Nota Crédito <-> Contrato
    if anchor_sale_id:
        if entry.source_table != "sales":
            related_pairs.add(("sales", anchor_sale_id, "Venta origen"))

        for cd in db.query(models.CfdiDocument).filter(models.CfdiDocument.empresa_id == empresa_id, models.CfdiDocument.sale_id == anchor_sale_id).all():
            lbl = "Nota de crédito fiscal (CFDI E)" if (cd.tipo or "").upper() == "E" else ("Complemento de pago (CFDI P)" if (cd.tipo or "").upper() == "P" else "Factura CFDI")
            related_pairs.add(("cfdi_documents", str(cd.id), lbl))

        for sk in db.query(models.SafekeptItem).filter(models.SafekeptItem.empresa_id == empresa_id, models.SafekeptItem.sale_id == anchor_sale_id).all():
            kds = db.query(models.KardexDelivery).filter(models.KardexDelivery.empresa_id == empresa_id, models.KardexDelivery.safekept_item_id == sk.id).all()
            if kds:
                for kd in kds:
                    related_pairs.add(("kardex_deliveries", str(kd.id), "Nota de entrega vinculada"))
            else:
                related_pairs.add(("safekept_items", str(sk.id), "Orden de entrega pendiente"))

        for sr in db.query(models.SaleReturn).filter(models.SaleReturn.empresa_id == empresa_id, models.SaleReturn.sale_id == anchor_sale_id).all():
            related_pairs.add(("sale_returns", str(sr.id), "Devolución de mercancía"))

        for cl in db.query(models.CustomerCreditLedger).filter(models.CustomerCreditLedger.empresa_id == empresa_id, models.CustomerCreditLedger.sale_id == anchor_sale_id).all():
            related_pairs.add(("customer_credit_ledger", str(cl.id), "Movimiento de saldo / Nota interna"))

        for ar in db.query(models.AccountsReceivable).filter(models.AccountsReceivable.empresa_id == empresa_id, models.AccountsReceivable.sale_id == anchor_sale_id).all():
            related_pairs.add(("accounts_receivable", str(ar.id), "Cargo en Cartera CxC"))
            for arp in db.query(models.AccountReceivablePayment).filter(models.AccountReceivablePayment.empresa_id == empresa_id, models.AccountReceivablePayment.ar_id == ar.id).all():
                related_pairs.add(("account_receivable_payments", str(arp.id), "Abono / Aplicación de pago"))

        for ac in db.query(models.AdhesionContract).filter(models.AdhesionContract.empresa_id == empresa_id, models.AdhesionContract.sale_id == anchor_sale_id).all():
            related_pairs.add(("adhesion_contracts", str(ac.id), "Contrato emitido"))

        for cm in db.query(models.ComodatoItem).filter(models.ComodatoItem.empresa_id == empresa_id, models.ComodatoItem.sale_id == anchor_sale_id).all():
            related_pairs.add(("comodato_items", str(cm.id), "Comodato / Envase vinculado"))

    # Apartados <-> Abonos de apartado
    if entry.source_table == "layaways":
        for lp in db.query(models.LayawayPayment).filter(models.LayawayPayment.empresa_id == empresa_id, models.LayawayPayment.layaway_id == entry.source_id).all():
            related_pairs.add(("layaway_payments", str(lp.id), "Abono a apartado"))
    elif entry.source_table == "layaway_payments" and meta.get("layaway_id"):
        related_pairs.add(("layaways", str(meta["layaway_id"]), "Apartado origen"))

    # Grafo de compras: OC <-> Recepción/Expediente <-> CxP <-> Pagos <-> Gasto flete
    if anchor_po_id:
        if entry.source_table != "purchase_orders":
            related_pairs.add(("purchase_orders", anchor_po_id, "Orden de compra origen"))
        for rx in db.query(models.ReceptionExpediente).filter(models.ReceptionExpediente.empresa_id == empresa_id, models.ReceptionExpediente.purchase_order_id == anchor_po_id).all():
            related_pairs.add(("reception_expedientes", str(rx.id), "Recepción 360 vinculada"))
            if rx.accounts_payable_id:
                anchor_ap_id = anchor_ap_id or str(rx.accounts_payable_id)
        for pr in db.query(models.PurchaseReceipt).filter(models.PurchaseReceipt.empresa_id == empresa_id, models.PurchaseReceipt.purchase_order_id == anchor_po_id).all():
            related_pairs.add(("purchase_receipts", str(pr.id), "Recepción almacén"))
        for ap in db.query(models.AccountsPayable).filter(models.AccountsPayable.empresa_id == empresa_id, models.AccountsPayable.purchase_order_id == anchor_po_id).all():
            related_pairs.add(("accounts_payable", str(ap.id), "Cuenta por pagar"))
            anchor_ap_id = anchor_ap_id or str(ap.id)

    if anchor_exp_id:
        if entry.source_table != "reception_expedientes":
            related_pairs.add(("reception_expedientes", anchor_exp_id, "Expediente recepción"))
        for oe in db.query(models.OperatingExpense).filter(models.OperatingExpense.empresa_id == empresa_id, models.OperatingExpense.expediente_id == anchor_exp_id).all():
            related_pairs.add(("operating_expenses", str(oe.id), "Gasto operativo / Flete"))

    if anchor_ap_id:
        if entry.source_table != "accounts_payable":
            related_pairs.add(("accounts_payable", anchor_ap_id, "Cuenta por pagar"))
        for sp in db.query(models.SupplierPayment).filter(models.SupplierPayment.empresa_id == empresa_id, models.SupplierPayment.accounts_payable_id == anchor_ap_id).all():
            related_pairs.add(("supplier_payments", str(sp.id), "Pago a proveedor"))

    # Resolver contra el índice y evaluar permisos por cada documento relacionado
    allowed_cats = set(perms.get("categories") or [])
    allowed_suc_upper = {b.upper() for b in allowed_branches}
    view_amounts = bool(perms.get("view_amounts"))

    out: List[Dict[str, Any]] = []
    seen_keys: Set[str] = {entry.doc_key}

    for stbl, sid, rel_lbl in related_pairs:
        dkey = make_doc_key(empresa_id, stbl, sid)
        if dkey in seen_keys:
            continue
        seen_keys.add(dkey)

        rel_entry = (
            db.query(models.DocumentRegistryEntry)
            .filter(models.DocumentRegistryEntry.empresa_id == empresa_id, models.DocumentRegistryEntry.doc_key == dkey)
            .first()
        )
        if not rel_entry:
            continue

        cat_ok = rel_entry.category in allowed_cats
        suc_ok = can_all_branches or (rel_entry.sucursal_id or "").upper() in allowed_suc_upper
        authorized = bool(cat_ok and suc_ok)

        st_meta = SUBTYPE_META_MAP.get(rel_entry.doc_subtype, {})
        item_dict: Dict[str, Any] = {
            "doc_key": rel_entry.doc_key if authorized else None,
            "relation_label": rel_lbl,
            "folio_visible": rel_entry.folio_visible,
            "category": rel_entry.category,
            "doc_subtype": rel_entry.doc_subtype,
            "subtype_label": st_meta.get("short") or rel_entry.doc_subtype,
            "sucursal_id": rel_entry.sucursal_id,
            "doc_status": rel_entry.doc_status,
            "emitted_at": rel_entry.emitted_at.isoformat() if rel_entry.emitted_at else None,
            "authorized": authorized,
            "restriction_reason": None if authorized else "Sin permiso de rol o sucursal para abrir este documento vinculado.",
        }
        if authorized and view_amounts:
            item_dict["amount_applicable"] = bool(rel_entry.amount_applicable)
            item_dict["total_amount"] = float(rel_entry.total_amount) if rel_entry.total_amount is not None else None
        else:
            item_dict["amount_applicable"] = bool(rel_entry.amount_applicable)
            item_dict["total_amount"] = None
            item_dict["amount_redacted"] = not view_amounts

        out.append(item_dict)

    out.sort(key=lambda x: x.get("emitted_at") or "", reverse=True)
    return out


def build_document_activity(db: Session, empresa_id: str, entry: models.DocumentRegistryEntry) -> List[Dict[str, Any]]:
    """Construye la bitácora cronológica confirmada (emisión, impresiones, descargas, envíos y consultas)."""
    events: List[Dict[str, Any]] = []

    # 1. Evento de emisión original en fuente
    events.append({
        "timestamp": entry.emitted_at.isoformat() if entry.emitted_at else None,
        "actor": entry.emisor_nombre or entry.emisor_user_id or "SISTEMA",
        "action": "Emisión en módulo origen",
        "channel": CATEGORY_LABELS.get(entry.category, entry.category).upper(),
        "result": f"Registrado ({entry.doc_status})",
        "confirmed": True,
    })

    # 2. Emisiones / Reimpresiones en PrintEmissionRecord
    emissions = (
        db.query(models.PrintEmissionRecord)
        .filter(
            models.PrintEmissionRecord.empresa_id == empresa_id,
            or_(
                models.PrintEmissionRecord.operation_id == entry.source_id,
                models.PrintEmissionRecord.operation_folio == entry.folio_visible,
            ),
        )
        .order_by(models.PrintEmissionRecord.emitted_at.desc())
        .limit(25)
        .all()
    )
    for em in emissions:
        events.append({
            "timestamp": em.emitted_at.isoformat() if em.emitted_at else None,
            "actor": (em.emitted_by or "SISTEMA").upper(),
            "action": f"Representación conservada ({em.mode} v{em.version_num})",
            "channel": "DISEÑADOR DE FORMATOS",
            "result": f"Original conservado · Reimpresiones: {int(em.reprint_count or 0)}",
            "confirmed": True,
        })

    # 3. Envíos individuales o en lote
    dispatches = (
        db.query(models.DocumentDispatchItem)
        .filter(
            models.DocumentDispatchItem.empresa_id == empresa_id,
            models.DocumentDispatchItem.doc_key == entry.doc_key,
        )
        .order_by(models.DocumentDispatchItem.updated_at.desc())
        .limit(30)
        .all()
    )
    for di in dispatches:
        if di.provider_read_confirmed:
            res_lbl = f"Leído confirmado ({di.recipient})"
            conf = True
        elif di.provider_delivery_confirmed:
            res_lbl = f"Entregado confirmado ({di.recipient})"
            conf = True
        elif di.status in ("SENT", "SENT_UNCONFIRMED"):
            res_lbl = f"Enviado al canal ({di.recipient}) — sin acuse de lectura"
            conf = True
        elif di.status == "OPENED_CLIENT":
            res_lbl = f"Apertura de WhatsApp solicitada ({di.recipient})"
            conf = False
        elif di.status == "UNCERTAIN":
            res_lbl = f"Resultado incierto ({di.recipient}) — pendiente verificación proveedor"
            conf = False
        else:
            res_lbl = f"Error de envío ({di.recipient}): {di.error_detail or di.status}"
            conf = False

        events.append({
            "timestamp": (di.confirmed_at or di.sent_at or di.updated_at).isoformat() if (di.confirmed_at or di.sent_at or di.updated_at) else None,
            "actor": (di.provider_name or di.channel or "DESPACHO").upper(),
            "action": f"Envío documental (intento #{di.attempt_count})",
            "channel": di.channel,
            "result": res_lbl,
            "confirmed": conf,
        })

    # 4. Eventos de AuditLog asociados al documento (consultas, solicitudes de impresión, descargas)
    logs = (
        db.query(models.AuditLog)
        .filter(
            models.AuditLog.empresa_id == empresa_id,
            models.AuditLog.action.like("DOC_CENTER_%"),
        )
        .order_by(models.AuditLog.created_at.desc())
        .limit(120)
        .all()
    )
    for lg in logs:
        det = lg.details if isinstance(lg.details, dict) else {}
        det_str = str(lg.details or "")
        if det.get("doc_key") == entry.doc_key or entry.doc_key in det_str or entry.folio_visible in det_str:
            act_map = {
                "DOC_CENTER_VIEW": "Consulta de expediente",
                "DOC_CENTER_RH_ACCESS": "Acceso auditado RRHH",
                "DOC_CENTER_PRINT_REQUEST": "Solicitud de impresión (navegador)",
                "DOC_CENTER_PRINT_CONFIRMED": "Impreso confirmado (agente local)",
                "DOC_CENTER_DOWNLOAD": "Descarga de archivo",
                "DOC_CENTER_SHARE_CREATE": "Creación de enlace temporal",
                "DOC_CENTER_SHARE_REVOKE": "Revocación de enlace temporal",
                "DOC_CENTER_SHARE_DOWNLOAD": "Descarga mediante enlace compartido",
                "DOC_CENTER_ATTACHMENT_UPLOAD": "Carga de archivo adjunto",
            }
            events.append({
                "timestamp": lg.created_at.isoformat() if lg.created_at else None,
                "actor": (lg.user_id or "USUARIO").upper(),
                "action": act_map.get(lg.action, lg.action),
                "channel": str(det.get("channel") or "CENTRO DE DOCUMENTOS").upper(),
                "result": str(det.get("result") or "Registrado"),
                "confirmed": bool(det.get("confirmed", lg.action != "DOC_CENTER_PRINT_REQUEST")),
            })

    events.sort(key=lambda e: e.get("timestamp") or "", reverse=True)
    return events
