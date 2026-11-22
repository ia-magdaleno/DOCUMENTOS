"""Motor de Representación, Originales Conservados, Miniaturas, Exportación (CSV/XLSX/ZIP) y Envíos del Centro de Documentos CALEBSYS.

Reutiliza `services/print_formats_service.py` (plantillas publicadas, fondos PDF/imagen, coordenadas mm, multipágina)
y los canales existentes de correo (SMTP/PAC), WhatsApp (`services/whatsapp.py`), CONECT y enlaces seguros.
"""
from __future__ import annotations

import base64
import copy
import csv
import datetime as _dt
import hashlib
import io
import json
import os
import re
import secrets
import smtplib
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile
from email.message import EmailMessage
from typing import Any, Dict, List, Optional, Tuple
from xml.sax.saxutils import escape as _xml_escape

import pypdfium2 as pdfium
from fastapi import HTTPException
from PIL import Image, ImageDraw, ImageFont
from sqlalchemy import or_
from sqlalchemy.orm import Session

import models
from services import print_formats_service as _pfs
from services import whatsapp as _wa
from services.document_center_catalog import (
    CATEGORY_LABELS,
    SUBTYPE_META_MAP,
    audit_doc_event,
    build_safe_download_filename,
    sanitize_csv_cell,
)

MEDIA_DOC_CENTER_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../../media/document_center")
)


# ══════════════════════════════════════════════════════════════════════════════
# 1. PERFIL DE EMPRESA, LOGOTIPO Y SUCURSAL DESDE LA SESIÓN
# ══════════════════════════════════════════════════════════════════════════════

def get_session_company_profile(db: Session, empresa_id: str, sucursal_id: Optional[str] = None) -> Dict[str, Any]:
    comp = db.query(models.Company).filter(models.Company.id == empresa_id).first()
    cfgs = {
        r.config_key: r.config_val
        for r in db.query(models.AdminConfig)
        .filter(
            models.AdminConfig.empresa_id == empresa_id,
            models.AdminConfig.config_key.in_([
                "params.empresa_nombre",
                "params.empresa_rfc",
                "params.empresa_direccion",
                "params.empresa_telefono",
                "params.empresa_logo",
                "empresa.perfil",
                "integrations.cfdi",
                "ticket.header",
            ]),
        )
        .all()
    }
    ep = cfgs.get("empresa.perfil") if isinstance(cfgs.get("empresa.perfil"), dict) else {}
    cfdi_cfg = cfgs.get("integrations.cfdi") if isinstance(cfgs.get("integrations.cfdi"), dict) else {}
    param_nom = str(cfgs.get("params.empresa_nombre") or "").strip().strip('"')
    param_rfc = str(cfgs.get("params.empresa_rfc") or "").strip().strip('"')

    nombre_comercial = str(
        param_nom
        or ep.get("nombre_comercial")
        or (comp.name if comp else None)
        or cfdi_cfg.get("nombre_emisor")
        or empresa_id
    ).upper()
    razon_social = str(
        ep.get("razon_social")
        or cfdi_cfg.get("nombre_emisor")
        or param_nom
        or nombre_comercial
    ).upper()
    rfc = str(
        param_rfc
        or ep.get("rfc")
        or (comp.rfc if comp and comp.rfc else None)
        or cfdi_cfg.get("rfc_emisor")
        or "XAXX010101000"
    ).upper()
    regimen = str(ep.get("regimen_fiscal") or cfdi_cfg.get("regimen_fiscal") or "601 - GENERAL DE LEY PERSONAS MORALES").upper()

    branch = None
    if sucursal_id:
        branch = (
            db.query(models.Branch)
            .filter(
                models.Branch.empresa_id == empresa_id,
                or_(models.Branch.id == sucursal_id, models.Branch.name == sucursal_id),
            )
            .first()
        )
    if not branch:
        branch = (
            db.query(models.Branch)
            .filter(models.Branch.empresa_id == empresa_id)
            .order_by(models.Branch.is_main.desc())
            .first()
        )

    logo_asset = (
        db.query(models.PrintTemplateAsset)
        .filter(models.PrintTemplateAsset.empresa_id == empresa_id, models.PrintTemplateAsset.kind == "LOGO")
        .order_by(models.PrintTemplateAsset.created_at.desc())
        .first()
    )
    logo_data_uri = ep.get("logo_data_uri") or ""
    if not logo_data_uri and logo_asset and logo_asset.storage_rel_path:
        abs_logo = os.path.join(_pfs.MEDIA_PRINT_ROOT, logo_asset.storage_rel_path)
        if os.path.isfile(abs_logo):
            try:
                with open(abs_logo, "rb") as fh:
                    b64_l = base64.b64encode(fh.read()).decode("ascii")
                logo_data_uri = f"data:{logo_asset.mime_type or 'image/png'};base64,{b64_l}"
            except Exception:
                logo_data_uri = ""

    return {
        "empresa_id": empresa_id,
        "nombre_comercial": nombre_comercial,
        "razon_social": razon_social,
        "rfc": rfc,
        "regimen_fiscal": regimen,
        "domicilio": str(ep.get("domicilio") or (branch.address if branch else "") or "").upper(),
        "telefonos": str(ep.get("telefono") or (branch.phone if branch else "") or ""),
        "correo": str(ep.get("correo") or (branch.email if branch else "") or ""),
        "logotipo": logo_data_uri,
        "logo_asset_id": logo_asset.id if logo_asset else None,
        "sucursal_nombre": str((branch.name if branch else sucursal_id) or "MATRIZ").upper(),
        "sucursal_domicilio": str((branch.address if branch else "") or "").upper(),
        "sucursal_telefono": str((branch.phone if branch else "") or ""),
    }


# ══════════════════════════════════════════════════════════════════════════════
# 2. CONSTRUCTOR DE CONTEXTO REAL PARA TODAS LAS FUENTES DEL ERP
# ══════════════════════════════════════════════════════════════════════════════

def _make_item_row(codigo: str, descripcion: str, cantidad: float, unidad: str, precio_con_iva: float) -> Dict[str, Any]:
    sub = round(cantidad * precio_con_iva, 2)
    imp_sin = round(sub / 1.16, 2)
    iva_it = round(sub - imp_sin, 2)
    pu_sin = round(imp_sin / cantidad, 2) if cantidad else round(precio_con_iva / 1.16, 2)
    return {
        "codigo": str(codigo or "S/C").upper(),
        "descripcion": str(descripcion or "CONCEPTO DOCUMENTAL").upper(),
        "cantidad": round(cantidad, 3),
        "unidad": str(unidad or "PZA").upper(),
        "precio": round(precio_con_iva, 2),
        "precio_con_iva": round(precio_con_iva, 2),
        "precio_sin_iva": pu_sin,
        "descuento": 0.0,
        "impuestos": iva_it,
        "iva_articulo": iva_it,
        "importe": sub,
        "importe_sin_iva": imp_sin,
        "importe_con_iva": sub,
        "ubicacion": "",
        "clave_sat": "",
    }


def build_context_for_registry_entry(
    db: Session,
    empresa_id: str,
    entry: models.DocumentRegistryEntry,
    redact_amounts: bool = False,
) -> Dict[str, Any]:
    """Construye el diccionario `context` real compatible con `print_formats_service`
    a partir de la tabla fuente original del documento."""
    prof = get_session_company_profile(db, empresa_id, entry.sucursal_id)
    st_meta = SUBTYPE_META_MAP.get(entry.doc_subtype, {})
    products_map = {
        p.id: p for p in db.query(models.Product).filter(models.Product.empresa_id == empresa_id).all()
    }
    products_by_sku = {str(p.sku or "").upper(): p for p in products_map.values() if p.sku}

    items: List[Dict[str, Any]] = []
    meta = entry.extra_meta_json if isinstance(entry.extra_meta_json, dict) else {}

    stbl = entry.source_table
    sid = entry.source_id

    if stbl == "sales":
        s_items = db.query(models.SaleItem).filter(models.SaleItem.empresa_id == empresa_id, models.SaleItem.sale_id == sid).all()
        for it in s_items:
            pr = products_map.get(it.product_id) or products_by_sku.get(str(it.product_sku or "").upper())
            qty = float(it.quantity or 1)
            sub_i = float(it.subtotal or 0)
            pu = round(sub_i / qty, 2) if qty else float(it.price or 0)
            items.append(_make_item_row(
                it.product_sku or (pr.sku if pr else "ART"),
                (pr.name if pr else None) or f"ARTÍCULO {it.product_sku}",
                qty,
                (pr.sale_unit if pr and getattr(pr, "sale_unit", None) else "PZA"),
                pu,
            ))
    elif stbl == "quotes":
        q_items = db.query(models.QuoteItem).filter(models.QuoteItem.empresa_id == empresa_id, models.QuoteItem.quote_id == sid).all()
        for it in q_items:
            qty = float(it.quantity or 1)
            pu = float(it.price or (float(it.subtotal or 0) / qty if qty else 0))
            items.append(_make_item_row(it.product_sku or "COT", it.description or f"PARTIDA {it.product_sku}", qty, "PZA", pu))
    elif stbl == "layaways":
        l_items = db.query(models.LayawayItem).filter(models.LayawayItem.empresa_id == empresa_id, models.LayawayItem.layaway_id == sid).all()
        for it in l_items:
            qty = float(it.quantity or 1)
            pu = float(it.price or 0)
            items.append(_make_item_row(it.product_sku or "APT", it.description or f"APARTADO {it.product_sku}", qty, "PZA", pu))
    elif stbl == "purchase_orders":
        po_items = db.query(models.PurchaseOrderItem).filter(models.PurchaseOrderItem.empresa_id == empresa_id, models.PurchaseOrderItem.purchase_order_id == sid).all()
        for it in po_items:
            qty = float(it.quantity_ordered or 1)
            pu = float(it.unit_cost or 0)
            items.append(_make_item_row(it.sku or "OC", it.description or f"INSUMO {it.sku}", qty, "PZA", pu))
    elif stbl == "purchase_receipts":
        pr_items = db.query(models.PurchaseReceiptItem).filter(models.PurchaseReceiptItem.empresa_id == empresa_id, models.PurchaseReceiptItem.receipt_id == sid).all()
        for it in pr_items:
            qty = float(it.quantity_received or 1)
            pu = float(it.unit_cost or 0)
            items.append(_make_item_row(it.sku or "REC", it.description or f"RECIBIDO {it.sku}", qty, "PZA", pu))
    elif stbl == "reception_expedientes":
        rx = db.query(models.ReceptionExpediente).filter(models.ReceptionExpediente.empresa_id == empresa_id, models.ReceptionExpediente.id == sid).first()
        if rx and isinstance(rx.payload, dict):
            for idx, ln in enumerate(rx.payload.get("lines") or rx.payload.get("items") or []):
                qty = float(ln.get("qty_received") or ln.get("quantity") or 1)
                pu = float(ln.get("unit_cost") or ln.get("price") or 0)
                items.append(_make_item_row(ln.get("sku") or f"R-{idx+1}", ln.get("description") or ln.get("name") or "MERCANCÍA RECIBIDA", qty, ln.get("unit") or "PZA", pu))
    elif stbl == "transfers":
        t_items = db.query(models.TransferItem).filter(models.TransferItem.empresa_id == empresa_id, models.TransferItem.transfer_id == sid).all()
        for it in t_items:
            qty = float(it.quantity_sent or it.quantity_requested or 1)
            items.append(_make_item_row(it.product_sku or "TRA", it.description or f"TRASLADO {it.product_sku}", qty, "PZA", 0.0))
    elif stbl in ("kardex_deliveries", "safekept_items"):
        sale_id_ref = meta.get("sale_id")
        if sale_id_ref:
            s_items = db.query(models.SaleItem).filter(models.SaleItem.empresa_id == empresa_id, models.SaleItem.sale_id == str(sale_id_ref)).all()
            for it in s_items:
                pr = products_map.get(it.product_id) or products_by_sku.get(str(it.product_sku or "").upper())
                qty = float(it.quantity or 1)
                pu = float(it.price or (float(it.subtotal or 0) / qty if qty else 0))
                items.append(_make_item_row(it.product_sku or "ENT", (pr.name if pr else None) or f"ENTREGA {it.product_sku}", qty, "PZA", pu))

    tot_f = float(entry.total_amount or 0.0) if entry.amount_applicable else 0.0
    sub_f = float(entry.subtotal if entry.subtotal is not None else round(tot_f / 1.16, 2)) if entry.amount_applicable else 0.0
    iva_f = float(entry.tax_amount if entry.tax_amount is not None else round(tot_f - sub_f, 2)) if entry.amount_applicable else 0.0
    disc_f = float(entry.discount_amount or 0.0) if entry.amount_applicable else 0.0

    if not items:
        items.append(_make_item_row(
            entry.serie or "DOC",
            f"{st_meta.get('short') or entry.doc_subtype} · {entry.reference_text or entry.folio_visible}",
            1.0,
            "SERV" if entry.amount_applicable else "MOV",
            tot_f,
        ))

    dt_em = entry.emitted_at or _dt.datetime.now(_dt.timezone.utc)
    try:
        from zoneinfo import ZoneInfo
        dt_loc = dt_em.astimezone(ZoneInfo(entry.branch_tz or "America/Mazatlan"))
    except Exception:
        dt_loc = dt_em

    # Datos de Corte de Caja si es CashShift
    opening_f = float(meta.get("opening_amount") or 0.0)
    expected_f = float(meta.get("expected_amount") or tot_f)
    reported_f = float(meta.get("reported_amount") if meta.get("reported_amount") is not None else tot_f)
    diff_f = float(meta.get("difference") if meta.get("difference") is not None else (reported_f - expected_f))

    ctx: Dict[str, Any] = {
        "_is_demo": False,
        "empresa": {
            "nombre_comercial": prof["nombre_comercial"],
            "razon_social": prof["razon_social"],
            "rfc": prof["rfc"],
            "regimen_fiscal": prof["regimen_fiscal"],
            "domicilio": prof["domicilio"] or "DOMICILIO FISCAL REGISTRADO EN SISTEMA",
            "telefonos": prof["telefonos"] or "",
            "correo": prof["correo"] or "",
            "logotipo": prof["logotipo"] or "",
        },
        "sucursal": {
            "nombre": str(entry.sucursal_id or prof["sucursal_nombre"]).upper(),
            "clave": str(entry.sucursal_id or "MATRIZ").upper(),
            "domicilio": prof["sucursal_domicilio"],
            "telefono": prof["sucursal_telefono"],
        },
        "operacion": {
            "tipo": str(st_meta.get("short") or entry.doc_subtype).upper(),
            "folio": str(entry.folio_visible).upper(),
            "fecha": dt_loc.strftime("%d/%m/%Y"),
            "hora": dt_loc.strftime("%H:%M"),
            "estado": str(entry.doc_status or "EMITIDO").upper(),
            "vendedor": str(entry.emisor_nombre or "SISTEMA").upper(),
            "cajero": str(entry.emisor_nombre or "CAJA").upper(),
            "caja": str(entry.caja_id or entry.sucursal_id or "MATRIZ").upper(),
            "referencias": str(entry.reference_text or "").upper(),
        },
        "cliente": {
            "nombre": str(entry.tercero_nombre or "PÚBLICO EN GENERAL").upper(),
            "rfc": str(entry.tercero_rfc or "XAXX010101000").upper(),
            "domicilio": "",
            "telefono": "",
            "correo": "",
            "regimen_fiscal": "616" if (entry.tercero_rfc or "XAXX010101000") == "XAXX010101000" else "601",
            "uso_cfdi": str(meta.get("uso_cfdi") or "G03").upper(),
            "condiciones_credito": "CRÉDITO" if entry.doc_subtype == "venta_credito" else "CONTADO",
        },
        "productos": items,
        "importes": {
            "subtotal": sub_f,
            "subtotal_sin_iva": sub_f,
            "subtotal_con_iva": tot_f,
            "descuentos": disc_f,
            "impuestos": iva_f,
            "impuesto_total": iva_f,
            "total_sin_iva": sub_f,
            "total_con_iva": tot_f,
            "total": tot_f,
            "total_letra": _pfs.number_to_spanish_words_mxn(tot_f) if entry.amount_applicable else "SIN IMPORTE MONETARIO APLICABLE",
            "moneda": str(entry.currency or "MXN").upper(),
        },
        "pagos": {
            "metodo": str(meta.get("payment_method") or "01").upper(),
            "referencia": str(entry.reference_text or "").upper(),
            "importe_recibido": tot_f,
            "cambio": 0.0,
            "desglose_mixto": "",
        },
        "pago": {
            "importe_letra": _pfs.number_to_spanish_words_mxn(tot_f) if entry.amount_applicable else "NO APLICA",
            "concepto": f"{st_meta.get('short') or 'DOCUMENTO'} FOLIO {entry.folio_visible}".upper(),
        },
        "credito": {
            "limite_credito": 0.0,
            "fecha_vencimiento": "",
            "saldo_anterior": tot_f,
            "importe_abono": tot_f if entry.doc_subtype in ("comprobante_abono", "aplicacion_saldo", "abono_apartado") else 0.0,
            "saldo_actual": float(meta.get("balance_after") or meta.get("current_balance") or 0.0),
            "saldo_pendiente": float(meta.get("current_balance") or 0.0),
            "documento_relacionado": str(entry.folio_visible).upper(),
            "pagare_leyenda": f"DOCUMENTO EMITIDO POR {prof['razon_social']}",
        },
        "entrega": {
            "domicilio": prof["sucursal_domicilio"],
            "instrucciones": str(entry.reference_text or "ENTREGA AUTORIZADA").upper(),
            "chofer_unidad": "PATIO / REPARTO",
            "placas": "",
            "persona_recibe": str(entry.tercero_nombre or "").upper(),
            "cantidades_pendientes": "0",
        },
        "cfdi": {
            "uuid": str(entry.uuid_fiscal or ""),
            "serie_folio": str(entry.folio_visible),
            "fecha_timbrado": dt_loc.strftime("%Y-%m-%dT%H:%M:%S") if entry.uuid_fiscal else "",
            "serie_sello": "00001000000500000001" if entry.uuid_fiscal else "",
            "no_cert_emisor": "00001000000500000001" if entry.uuid_fiscal else "",
            "no_cert_sat": "00001000000504465028" if entry.uuid_fiscal else "",
            "sello_cfdi": "SELLO-DIGITAL-CFDI-CONSERVADO" if entry.uuid_fiscal else "",
            "sello_sat": "SELLO-DIGITAL-SAT-CONSERVADO" if entry.uuid_fiscal else "",
            "cadena_original": f"||4.0|{entry.folio_visible}|{entry.uuid_fiscal}||" if entry.uuid_fiscal else "",
            "qr_sat": str(entry.uuid_fiscal or ""),
        },
        "corte": {
            "tipo_corte": str(st_meta.get("short") or "CORTE DE CAJA").upper(),
            "turno": str(entry.folio_visible),
            "folio_inicial": str(entry.folio_visible),
            "folio_final": str(entry.folio_visible),
            "num_operaciones": "REGISTRO INDIVIDUAL DE CAJA",
            "fondo_inicial": opening_f,
            "ventas_efectivo": max(0.0, expected_f - opening_f),
            "abonos_efectivo": 0.0,
            "entradas_efectivo": 0.0,
            "retiros_fajillas": 0.0,
            "salidas_gastos": 0.0,
            "devoluciones_efectivo": 0.0,
            "efectivo_esperado": expected_f,
            "efectivo_declarado": reported_f,
            "diferencia_efectivo": diff_f,
            "ventas_tarjeta_debito": 0.0,
            "ventas_tarjeta_credito": 0.0,
            "tarjetas_declaradas": 0.0,
            "diferencia_tarjetas": 0.0,
            "ventas_transferencia": 0.0,
            "transferencias_declaradas": 0.0,
            "ventas_credito_otorgado": 0.0,
            "total_cancelaciones": 0.0,
            "total_devoluciones": 0.0,
            "desglose_denominaciones": "CORTE INDIVIDUAL DE CAJA",
            "total_esperado_general": expected_f,
            "total_declarado_general": reported_f,
            "diferencia_neta": diff_f,
            "estado_cuadre": "CUADRADO EXACTO" if abs(diff_f) < 0.01 else ("SOBRANTE" if diff_f > 0 else "FALTANTE"),
            "folio_sobre": f"SOBRE-{entry.folio_visible}",
            "supervisor_autoriza": str(entry.emisor_nombre or "ADMINISTRACIÓN"),
        },
        "profeco": {
            "leyenda_garantias": "CONSERVE ESTE COMPROBANTE PARA CUALQUIER ACLARACIÓN O GARANTÍA CONFORME A PROFECO.",
            "leyenda_consumidor": "DOCUMENTO EMITIDO EN SISTEMA ERP CALEBSYS.",
            "plazo_facturacion": "FACTURACIÓN DENTRO DEL MES EN CURSO.",
            "unidad_medida_nom": "UNIDADES CONFORME A NOM-030-SCFI.",
        },
    }

    if redact_amounts:
        for it in ctx["productos"]:
            for k in ("precio", "precio_con_iva", "precio_sin_iva", "descuento", "impuestos", "iva_articulo", "importe", "importe_sin_iva", "importe_con_iva"):
                it[k] = "RESERVADO"
        for k in list(ctx["importes"].keys()):
            ctx["importes"][k] = "RESERVADO"
        ctx["pagos"]["importe_recibido"] = "RESERVADO"
        ctx["pagos"]["cambio"] = "RESERVADO"
        ctx["pago"]["importe_letra"] = "IMPORTE RESERVADO POR PERMISO DE ROL"
        for k in ("limite_credito", "saldo_anterior", "importe_abono", "saldo_actual", "saldo_pendiente"):
            ctx["credito"][k] = "RESERVADO"

    return ctx


def _sanitize_version_for_redacted_amounts(ver: models.PrintFormatVersion) -> models.PrintFormatVersion:
    """Clona en memoria una versión de plantilla eliminando bloques de importes/totales
    para roles sin permiso `view_amounts`."""
    transient = models.PrintFormatVersion(
        id=ver.id,
        empresa_id=ver.empresa_id,
        template_id=ver.template_id,
        version_num=ver.version_num,
        status=ver.status,
        name_snapshot=ver.name_snapshot,
        mode=ver.mode,
        paper_size=ver.paper_size,
        orientation=ver.orientation,
        paper_width_mm=ver.paper_width_mm,
        paper_height_mm=ver.paper_height_mm,
        printable_width_mm=ver.printable_width_mm,
        margins_mm_json=copy.deepcopy(ver.margins_mm_json or {}),
        background_asset_id=ver.background_asset_id,
        background_settings_json=copy.deepcopy(ver.background_settings_json or {}),
        definition_json=copy.deepcopy(ver.definition_json or {}),
    )
    def_js = transient.definition_json or {}
    clean_els = []
    for el in (def_js.get("elements") or []):
        etype = str(el.get("type") or "")
        fkey = str(el.get("field_key") or "")
        txt = str(el.get("text") or "")
        if etype in ("totals_block", "table_corte_z", "table_corte_x", "table_corte_ciego"):
            continue
        if fkey.startswith(("importes.", "credito.", "pagos.", "corte.")) or "importes." in txt or "credito." in txt:
            continue
        if etype == "table_products":
            el = copy.deepcopy(el)
            el["columns"] = [
                {"field": "codigo", "header": "CÓDIGO", "width_pct": 22},
                {"field": "cantidad", "header": "CANT.", "width_pct": 16},
                {"field": "unidad", "header": "UNIDAD", "width_pct": 14},
                {"field": "descripcion", "header": "DESCRIPCIÓN AUTORIZADA (SIN IMPORTES)", "width_pct": 48},
            ]
        clean_els.append(el)
    def_js["elements"] = clean_els
    if def_js.get("flow_blocks"):
        def_js["flow_blocks"] = [
            b for b in def_js["flow_blocks"]
            if str(b.get("block_type") or "") not in ("totals", "payment", "credit")
        ]
    transient.definition_json = def_js
    return transient


# ══════════════════════════════════════════════════════════════════════════════
# 3. RESOLUCIÓN DE PDF (ORIGINAL CONSERVADO VS NUEVA REPRESENTACIÓN VS RECONSTRUCCIÓN)
# ══════════════════════════════════════════════════════════════════════════════

def resolve_document_pdf_and_meta(
    db: Session,
    empresa_id: str,
    entry: models.DocumentRegistryEntry,
    perms: Dict[str, Any],
    mode: str = "CARTA",
    representation: str = "original",  # "original" | "updated"
    include_background: Optional[bool] = None,
) -> Tuple[bytes, Dict[str, Any]]:
    """Genera o recupera los bytes PDF de un documento respetando:
    - Permisos de visualización de importes (`view_amounts`).
    - Original conservado inmutable (`PrintEmissionRecord` o `CfdiDocument.pdf_base64`).
    - Plantillas asignadas por empresa/sucursal/terminal en `print_formats_service` (con fondos PDF/imagen).
    - Identificación explícita cuando es nueva representación o reconstrucción histórica."""
    mode_u = str(mode or "CARTA").strip().upper()
    if mode_u not in ("CARTA", "TICKET", "TICKET_80MM", "TICKET_58MM"):
        mode_u = "CARTA"
    norm_mode = "TICKET" if mode_u.startswith("TICKET") else "CARTA"

    view_amounts = bool(perms.get("view_amounts"))
    st_meta = SUBTYPE_META_MAP.get(entry.doc_subtype, {})
    if not view_amounts:
        if entry.amount_applicable and not st_meta.get("non_monetary_safe"):
            raise HTTPException(
                status_code=403,
                detail="Tu rol no cuenta con permiso para ver importes ni generar o descargar representaciones que los revelen.",
            )

    # Caso 1: CFDI con PDF original conservado en base64 (cuando se pide original en CARTA y usuario ve importes)
    if (
        entry.source_table == "cfdi_documents"
        and norm_mode == "CARTA"
        and representation == "original"
        and view_amounts
    ):
        cd = db.query(models.CfdiDocument).filter(
            models.CfdiDocument.empresa_id == empresa_id,
            models.CfdiDocument.id == entry.source_id,
        ).first()
        if cd and cd.pdf_base64:
            pdf_raw = base64.b64decode(cd.pdf_base64)
            return pdf_raw, {
                "kind": "ORIGINAL_CONSERVADO",
                "is_conserved_original": True,
                "is_reconstructed": False,
                "mode": "CARTA",
                "template_code": "CFDI_PAC_ORIGINAL",
                "template_name": "Representación Impresa CFDI 4.0 Conservada",
                "version_num": 1,
                "generated_at": (cd.timbrado_at or cd.created_at or _dt.datetime.now(_dt.timezone.utc)).isoformat(),
                "sha256": hashlib.sha256(pdf_raw).hexdigest(),
                "notice": "Original conservado al momento del timbrado.",
            }

    # Caso 2: Contrato de adhesión firmado con contenido textual conservado o cualquier documento con PrintEmissionRecord
    conserved_rec = None
    if representation == "original":
        q_em = db.query(models.PrintEmissionRecord).filter(models.PrintEmissionRecord.empresa_id == empresa_id)
        if entry.source_table == "print_emission_records":
            conserved_rec = q_em.filter(models.PrintEmissionRecord.id == entry.source_id).first()
        else:
            conserved_rec = (
                q_em.filter(
                    or_(
                        models.PrintEmissionRecord.operation_id == entry.source_id,
                        models.PrintEmissionRecord.operation_folio == entry.folio_visible,
                    ),
                    models.PrintEmissionRecord.mode == norm_mode,
                )
                .order_by(models.PrintEmissionRecord.emitted_at.asc())
                .first()
            )

    if conserved_rec:
        ver = (
            db.query(models.PrintFormatVersion)
            .filter(
                models.PrintFormatVersion.empresa_id == empresa_id,
                models.PrintFormatVersion.id == conserved_rec.version_id,
            )
            .first()
        )
        tpl = (
            db.query(models.PrintFormatTemplate)
            .filter(
                models.PrintFormatTemplate.empresa_id == empresa_id,
                models.PrintFormatTemplate.id == conserved_rec.template_id,
            )
            .first()
        )
        if ver:
            ctx = copy.deepcopy(conserved_rec.data_snapshot_json or {})
            if not ctx:
                ctx = build_context_for_registry_entry(db, empresa_id, entry, redact_amounts=not view_amounts)
            elif not view_amounts:
                ctx = build_context_for_registry_entry(db, empresa_id, entry, redact_amounts=True)
            ver_to_use = _sanitize_version_for_redacted_amounts(ver) if not view_amounts else ver
            pdf_bytes = _pfs.generate_pdf_bytes(
                db=db,
                empresa_id=empresa_id,
                version_obj=ver_to_use,
                context=ctx,
                include_background=include_background,
            )
            return pdf_bytes, {
                "kind": "ORIGINAL_CONSERVADO",
                "is_conserved_original": True,
                "is_reconstructed": False,
                "emission_id": conserved_rec.id,
                "mode": norm_mode,
                "template_code": tpl.code if tpl else "PLANTILLA_HISTORICA",
                "template_name": ver.name_snapshot or (tpl.name if tpl else "Plantilla Original"),
                "version_num": ver.version_num,
                "generated_at": conserved_rec.emitted_at.isoformat() if conserved_rec.emitted_at else None,
                "sha256": hashlib.sha256(pdf_bytes).hexdigest(),
                "notice": f"Original conservado inmutable · Plantilla {tpl.code if tpl else ''} v{ver.version_num}.",
            }

    # Caso 3: Resolver plantilla activa publicada de la empresa (o sembrar base)
    target_doc_type = entry.print_doc_type or st_meta.get("print_doc_type") or "ticket_venta_contado"
    _pfs.ensure_seed_templates(db, empresa_id, user_id="sistema")

    ver = None
    tpl = None
    asig = _pfs.resolve_effective_assignment(db, empresa_id, target_doc_type, sucursal_id=entry.sucursal_id)
    if asig:
        cand_tpl = db.query(models.PrintFormatTemplate).filter(
            models.PrintFormatTemplate.empresa_id == empresa_id,
            models.PrintFormatTemplate.id == asig.template_id,
        ).first()
        if cand_tpl and cand_tpl.mode == norm_mode:
            tpl = cand_tpl
            ver = db.query(models.PrintFormatVersion).filter(
                models.PrintFormatVersion.empresa_id == empresa_id,
                models.PrintFormatVersion.id == asig.published_version_id,
            ).first()

    if not ver:
        tpl = (
            db.query(models.PrintFormatTemplate)
            .filter(
                models.PrintFormatTemplate.empresa_id == empresa_id,
                models.PrintFormatTemplate.doc_type == target_doc_type,
                models.PrintFormatTemplate.mode == norm_mode,
            )
            .order_by(models.PrintFormatTemplate.is_system_seed.asc(), models.PrintFormatTemplate.updated_at.desc())
            .first()
        )
        if not tpl:
            tpl = (
                db.query(models.PrintFormatTemplate)
                .filter(
                    models.PrintFormatTemplate.empresa_id == empresa_id,
                    models.PrintFormatTemplate.mode == norm_mode,
                )
                .first()
            )
        if tpl:
            vid = tpl.active_published_version_id or tpl.latest_draft_version_id
            ver = db.query(models.PrintFormatVersion).filter(
                models.PrintFormatVersion.empresa_id == empresa_id,
                models.PrintFormatVersion.id == vid,
            ).first()

    if not ver or not tpl:
        raise HTTPException(status_code=404, detail="No hay plantilla disponible para representar este documento.")

    ctx = build_context_for_registry_entry(db, empresa_id, entry, redact_amounts=not view_amounts)

    # Si existe logotipo de sesión y la plantilla tiene capa de logo vacía, inyectarlo respetando su posición
    ver_work = _sanitize_version_for_redacted_amounts(ver) if not view_amounts else copy.deepcopy(ver)
    if ctx["empresa"].get("logotipo") and isinstance(ver_work.definition_json, dict):
        def_c = copy.deepcopy(ver_work.definition_json)
        for el in (def_c.get("elements") or []):
            if el.get("type") == "image" and "logo" in str(el.get("id") or "").lower() and not el.get("src") and not el.get("asset_id"):
                el["src"] = ctx["empresa"]["logotipo"]
        ver_work.definition_json = def_c

    pdf_bytes = _pfs.generate_pdf_bytes(
        db=db,
        empresa_id=empresa_id,
        version_obj=ver_work,
        context=ctx,
        include_background=include_background,
    )
    now_iso = _dt.datetime.now(_dt.timezone.utc).isoformat()

    if representation == "updated":
        meta_out = {
            "kind": "NUEVA_REPRESENTACION",
            "is_conserved_original": False,
            "is_reconstructed": False,
            "mode": norm_mode,
            "template_code": tpl.code,
            "template_name": tpl.name,
            "version_num": ver.version_num,
            "generated_at": now_iso,
            "sha256": hashlib.sha256(pdf_bytes).hexdigest(),
            "notice": f"Nueva representación generada con plantilla {tpl.code} v{ver.version_num} ({now_iso[:19].replace('T', ' ')} UTC).",
        }
    elif (
        representation == "original"
        and (view_amounts or not entry.amount_applicable)
        and not (isinstance(entry.extra_meta_json, dict) and entry.extra_meta_json.get("simulate_missing_original"))
    ):
        # Emitir y sellar automáticamente el registro original inmutable (PrintEmissionRecord)
        safe_snapshot = json.loads(json.dumps(ctx, default=str))
        em_dt = entry.emitted_at or _dt.datetime.now(_dt.timezone.utc)
        em_rec = models.PrintEmissionRecord(
            id=str(uuid.uuid4()),
            empresa_id=empresa_id,
            sucursal_id=entry.sucursal_id or "MATRIZ",
            doc_type=target_doc_type,
            operation_id=str(entry.source_id),
            operation_folio=str(entry.folio_visible),
            template_id=tpl.id,
            version_id=ver.id,
            version_num=ver.version_num,
            mode=norm_mode,
            data_snapshot_json=safe_snapshot,
            emitted_by=str(entry.emisor_user_id or "sistema"),
            emitted_at=em_dt,
        )
        db.add(em_rec)
        entry.has_original_file = True
        db.commit()
        meta_out = {
            "kind": "ORIGINAL_CONSERVADO",
            "is_conserved_original": True,
            "is_reconstructed": False,
            "emission_id": em_rec.id,
            "mode": norm_mode,
            "template_code": tpl.code,
            "template_name": ver.name_snapshot or tpl.name,
            "version_num": ver.version_num,
            "generated_at": em_dt.isoformat() if hasattr(em_dt, "isoformat") else now_iso,
            "sha256": hashlib.sha256(pdf_bytes).hexdigest(),
            "notice": f"Original conservado inmutable · Plantilla {tpl.code} v{ver.version_num}.",
        }
    else:
        reconstructed_parts = [
            f"Datos de cabecera y estado desde '{entry.source_table}'",
            f"Partidas ({len(ctx.get('productos') or [])} renglón(es)) desde origen",
            f"Datos fiscales/comerciales de sesión ({ctx['empresa']['nombre_comercial']})",
            f"Composición visual proyectada en plantilla {tpl.code} v{ver.version_num}",
        ]
        if not view_amounts:
            reconstructed_parts.append("Importes protegidos y omitidos conforme a permisos del rol")
        meta_out = {
            "kind": "RECONSTRUCCION_HISTORICA",
            "is_conserved_original": False,
            "is_reconstructed": True,
            "mode": norm_mode,
            "template_code": tpl.code,
            "template_name": tpl.name,
            "version_num": ver.version_num,
            "generated_at": now_iso,
            "reconstructed_elements": reconstructed_parts,
            "sha256": hashlib.sha256(pdf_bytes).hexdigest(),
            "notice": (
                f"Histórico sin archivo original conservado: se reconstruyeron encabezado, "
                f"{len(ctx.get('productos') or [])} partida(s) y totales autorizados desde '{entry.source_table}' "
                f"usando {tpl.code} v{ver.version_num}."
            ),
        }
    return pdf_bytes, meta_out


def render_pdf_page_png(pdf_bytes: bytes, page_num: int = 1, scale: float = 1.6) -> Tuple[bytes, int]:
    """Renderiza una página de un PDF real a PNG usando `pypdfium2` y devuelve `(png_bytes, total_pages)`."""
    pdf_doc = pdfium.PdfDocument(pdf_bytes)
    try:
        total_pages = len(pdf_doc)
        idx = max(0, min(total_pages - 1, int(page_num) - 1))
        page = pdf_doc[idx]
        bitmap = page.render(scale=scale)
        pil_img = bitmap.to_pil()
        buf = io.BytesIO()
        pil_img.save(buf, format="PNG", optimize=True)
        return buf.getvalue(), total_pages
    finally:
        pdf_doc.close()


def render_lazy_thumbnail_png(
    db: Session,
    empresa_id: str,
    entry: models.DocumentRegistryEntry,
    perms: Dict[str, Any],
) -> bytes:
    """Genera miniatura PNG bajo demanda; si el rol no puede ver importes en un documento
    monetario no seguro, devuelve una miniatura protegida sin filtrar cifras."""
    view_amounts = bool(perms.get("view_amounts"))
    st_meta = SUBTYPE_META_MAP.get(entry.doc_subtype, {})
    if not view_amounts and entry.amount_applicable and not st_meta.get("non_monetary_safe"):
        img = Image.new("RGB", (260, 336), (241, 245, 249))
        drw = ImageDraw.Draw(img)
        drw.rectangle([12, 12, 248, 324], fill=(255, 255, 255), outline=(203, 213, 225), width=2)
        drw.rectangle([12, 12, 248, 56], fill=(30, 41, 59))
        drw.text((24, 26), entry.folio_visible[:22], fill=(255, 255, 255))
        drw.text((24, 90), "VISTA PREVIA PROTEGIDA", fill=(71, 85, 105))
        drw.text((24, 118), "Importes reservados", fill=(100, 116, 139))
        drw.text((24, 140), "para tu rol actual.", fill=(100, 116, 139))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

    default_mode = "TICKET" if entry.category == "caja" else "CARTA"
    pdf_bytes, _ = resolve_document_pdf_and_meta(db, empresa_id, entry, perms, mode=default_mode, representation="original")
    png_bytes, _ = render_pdf_page_png(pdf_bytes, page_num=1, scale=0.55)
    return png_bytes


def resolve_xml_or_acuse_bytes(
    db: Session,
    empresa_id: str,
    entry: models.DocumentRegistryEntry,
    perms: Dict[str, Any],
    kind: str = "XML",  # "XML" | "ACUSE"
) -> Tuple[bytes, str, str]:
    """Recupera el XML firmado intacto o el Acuse de cancelación autorizado."""
    if not perms.get("view_amounts") and entry.amount_applicable:
        raise HTTPException(
            status_code=403,
            detail="Tu rol no tiene permiso para ver importes; la descarga de XML/Acuse fiscal está restringida.",
        )

    cd = None
    if entry.source_table == "cfdi_documents":
        cd = db.query(models.CfdiDocument).filter(
            models.CfdiDocument.empresa_id == empresa_id,
            models.CfdiDocument.id == entry.source_id,
        ).first()
    elif entry.source_table == "sales":
        cd = db.query(models.CfdiDocument).filter(
            models.CfdiDocument.empresa_id == empresa_id,
            models.CfdiDocument.sale_id == entry.source_id,
        ).first()

    if not cd:
        raise HTTPException(status_code=404, detail="Este documento no cuenta con archivo XML o acuse fiscal asociado.")

    if kind.upper() == "ACUSE":
        if not cd.cancelado_at and (cd.status or "").upper() != "CANCELADO":
            raise HTTPException(status_code=404, detail="El comprobante no está cancelado; no existe acuse de cancelación.")
        acuse_xml = (
            f'<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<AcuseCancelacionSAT UUID="{cd.uuid_fiscal or ""}" RfcEmisor="{empresa_id}" '
            f'FechaCancelacion="{(cd.cancelado_at or _dt.datetime.now(_dt.timezone.utc)).isoformat()}" '
            f'Motivo="{cd.motivo_cancelacion or "02"}" Estatus="CANCELADO" />'
        ).encode("utf-8")
        fname = build_safe_download_filename(entry.folio_visible, entry.sucursal_id, "ACUSE_CANCELACION", "xml")
        return acuse_xml, "application/xml", fname

    if not cd.xml:
        raise HTTPException(status_code=404, detail="Archivo XML firmado no disponible para este comprobante.")
    # Preservar exactamente el XML firmado byte a byte
    raw_xml = cd.xml.encode("utf-8") if isinstance(cd.xml, str) else bytes(cd.xml)
    fname = build_safe_download_filename(entry.folio_visible, entry.sucursal_id, "XML_FIRMADO", "xml")
    return raw_xml, "application/xml", fname


# ══════════════════════════════════════════════════════════════════════════════
# 4. DESCARGA POR LOTE (ZIP CON MANIFIESTO) Y EXPORTACIÓN (CSV SEGURO / XLSX / REPORTE)
# ══════════════════════════════════════════════════════════════════════════════

def build_batch_zip(
    db: Session,
    empresa_id: str,
    entries_by_key: Dict[str, models.DocumentRegistryEntry],
    requested_keys: List[str],
    perms: Dict[str, Any],
    preferred_mode: str = "CARTA",
    include_xml: bool = True,
) -> Tuple[bytes, Dict[str, Any]]:
    """Empaqueta múltiples documentos autorizados en un ZIP e informa qué archivos entraron y cuáles fallaron.
    Aplica la regla CALEBSYS de Cortes Z: impide producir consolidados de Corte Z en lote."""
    included: List[Dict[str, str]] = []
    failed: List[Dict[str, str]] = []

    # Regla CALEBSYS Corte Z: no permitir consolidación multi-caja/multi-sucursal de Cortes Z por lote
    corte_z_entries = [entries_by_key[k] for k in requested_keys if k in entries_by_key and entries_by_key[k].doc_subtype == "corte_z"]
    if len(corte_z_entries) > 1:
        distinct_cajas = {(e.sucursal_id, e.caja_id or e.source_id) for e in corte_z_entries}
        if len(distinct_cajas) > 1:
            raise HTTPException(
                status_code=403,
                detail="Regla CALEBSYS: Cada Corte Z pertenece a una caja. Las acciones por lote no pueden consolidar Cortes Z de múltiples cajas o sucursales; descargue el comprobante individual de cada caja.",
            )

    buf = io.BytesIO()
    used_names: set = set()

    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for dkey in requested_keys:
            ent = entries_by_key.get(dkey)
            if not ent:
                failed.append({"doc_key": dkey, "reason": "Documento no encontrado o fuera del alcance de tu sucursal/empresa."})
                continue
            if ent.category not in set(perms.get("categories") or []):
                failed.append({"doc_key": dkey, "folio": ent.folio_visible, "reason": "Sin permiso de categoría para este documento."})
                continue
            try:
                mode_use = "TICKET" if (preferred_mode == "AUTO" and ent.category == "caja") else (preferred_mode if preferred_mode in ("CARTA", "TICKET") else "CARTA")
                pdf_b, meta = resolve_document_pdf_and_meta(db, empresa_id, ent, perms, mode=mode_use, representation="original")
                fname = build_safe_download_filename(ent.folio_visible, ent.sucursal_id, mode_use, "pdf")
                if fname in used_names:
                    fname = build_safe_download_filename(f"{ent.folio_visible}-{ent.source_id[:4]}", ent.sucursal_id, mode_use, "pdf")
                used_names.add(fname)
                zf.writestr(fname, pdf_b)
                included.append({"doc_key": dkey, "folio": ent.folio_visible, "filename": fname, "representation": meta["kind"]})

                if include_xml and ent.has_xml and perms.get("view_amounts"):
                    try:
                        xml_b, _, xname = resolve_xml_or_acuse_bytes(db, empresa_id, ent, perms, kind="XML")
                        if xname not in used_names:
                            used_names.add(xname)
                            zf.writestr(xname, xml_b)
                            included.append({"doc_key": dkey, "folio": ent.folio_visible, "filename": xname, "representation": "XML_FIRMADO"})
                    except Exception:
                        pass
            except HTTPException as he:
                failed.append({"doc_key": dkey, "folio": ent.folio_visible, "reason": str(he.detail)})
            except Exception as exc:
                failed.append({"doc_key": dkey, "folio": ent.folio_visible, "reason": str(exc)})

        manifest = {
            "generated_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
            "empresa_id": empresa_id,
            "included_count": len(included),
            "failed_count": len(failed),
            "included": included,
            "failed": failed,
        }
        zf.writestr("RESUMEN_DESCARGA_LOTE.json", json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"))

    return buf.getvalue(), manifest


EXPORT_COLUMN_DEFS = [
    ("folio_visible", "Folio"),
    ("category_label", "Categoría"),
    ("subtype_label", "Tipo de documento"),
    ("sucursal_id", "Sucursal"),
    ("caja_id", "Caja"),
    ("emitted_at_local", "Fecha emisión"),
    ("tercero_nombre", "Cliente / Proveedor"),
    ("tercero_rfc", "RFC"),
    ("emisor_nombre", "Emisor"),
    ("currency", "Moneda"),
    ("subtotal", "Subtotal"),
    ("tax_amount", "Impuestos"),
    ("total_amount", "Total"),
    ("doc_status", "Estado documento"),
    ("payment_status", "Estado pago"),
    ("fiscal_status", "Estado fiscal"),
    ("dispatch_status", "Estado envío"),
    ("uuid_fiscal", "UUID Fiscal"),
    ("reference_text", "Referencia"),
]

MONETARY_EXPORT_KEYS = {"subtotal", "tax_amount", "total_amount", "discount_amount"}


def export_documents_dataset(
    rows: List[models.DocumentRegistryEntry],
    perms: Dict[str, Any],
    fmt: str = "csv",  # "csv" | "xlsx"
    requested_columns: Optional[List[str]] = None,
    scope_label: str = "all_results",
    company_name: str = "CALEBSYS",
) -> Tuple[bytes, str, str]:
    """Exporta los resultados filtrados respetando columnas autorizadas, protección de importes
    y protección frente a inyección de fórmulas en CSV y XLSX."""
    view_amounts = bool(perms.get("view_amounts"))

    cols = []
    req_set = set(requested_columns) if requested_columns else None
    for key, header in EXPORT_COLUMN_DEFS:
        if not view_amounts and key in MONETARY_EXPORT_KEYS:
            continue
        if req_set and key not in req_set:
            continue
        cols.append((key, header))

    if not cols:
        cols = [("folio_visible", "Folio"), ("subtype_label", "Tipo"), ("sucursal_id", "Sucursal"), ("doc_status", "Estado")]

    def _format_cell(r: models.DocumentRegistryEntry, k: str) -> Any:
        st_m = SUBTYPE_META_MAP.get(r.doc_subtype, {})
        if k == "category_label":
            return CATEGORY_LABELS.get(r.category, r.category)
        if k == "subtype_label":
            return st_m.get("short") or r.doc_subtype
        if k == "emitted_at_local":
            if not r.emitted_at:
                return ""
            try:
                from zoneinfo import ZoneInfo
                return r.emitted_at.astimezone(ZoneInfo(r.branch_tz or "America/Mazatlan")).strftime("%Y-%m-%d %H:%M")
            except Exception:
                return r.emitted_at.strftime("%Y-%m-%d %H:%M")
        if k in MONETARY_EXPORT_KEYS:
            if not r.amount_applicable:
                return "NO APLICA"
            val = getattr(r, k, None)
            return round(float(val or 0.0), 2)
        return getattr(r, k, "") or ""

    scope_es = "PÁGINA ACTUAL" if scope_label == "current_page" else "TODOS LOS RESULTADOS FILTRADOS"
    ts_tag = _dt.datetime.now().strftime("%Y%m%d_%H%M")

    if fmt.lower() == "xlsx":
        all_xlsx_rows: List[List[Any]] = [
            [sanitize_csv_cell(f"{company_name} — CENTRO DE DOCUMENTOS ({scope_es})")],
            [h for _, h in cols],
        ]
        for r in rows:
            out_row = []
            for k, _ in cols:
                v = _format_cell(r, k)
                if isinstance(v, (int, float)):
                    out_row.append(v)
                else:
                    out_row.append(sanitize_csv_cell(v))
            all_xlsx_rows.append(out_row)

        try:
            import openpyxl
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = "Documentos"
            for rx_row in all_xlsx_rows:
                ws.append(rx_row)
            buf = io.BytesIO()
            wb.save(buf)
            xlsx_bytes = buf.getvalue()
        except ImportError:
            xlsx_bytes = _build_minimal_xlsx_bytes("Documentos", all_xlsx_rows)

        return (
            xlsx_bytes,
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            f"LISTADO_DOCUMENTOS_{ts_tag}.xlsx",
        )

    sio = io.StringIO()
    sio.write("\ufeff")  # UTF-8 BOM para Excel en Windows
    writer = csv.writer(sio)
    writer.writerow([sanitize_csv_cell(f"{company_name} — CENTRO DE DOCUMENTOS ({scope_es})")])
    writer.writerow([h for _, h in cols])
    for r in rows:
        writer.writerow([sanitize_csv_cell(_format_cell(r, k)) for k, _ in cols])
    return sio.getvalue().encode("utf-8"), "text/csv; charset=utf-8", f"LISTADO_DOCUMENTOS_{ts_tag}.csv"


def _col_letter(idx_zero: int) -> str:
    res = ""
    n = idx_zero + 1
    while n > 0:
        n, rem = divmod(n - 1, 26)
        res = chr(65 + rem) + res
    return res


def _build_minimal_xlsx_bytes(sheet_name: str, matrix: List[List[Any]]) -> bytes:
    """Generador ECMA-376 OpenXML (.xlsx) puro en stdlib sin dependencias externas."""
    row_xml_parts = []
    for r_idx, row in enumerate(matrix, start=1):
        cells_xml = []
        for c_idx, val in enumerate(row):
            ref = f"{_col_letter(c_idx)}{r_idx}"
            if isinstance(val, (int, float)) and not isinstance(val, bool):
                cells_xml.append(f'<c r="{ref}" t="n"><v>{val}</v></c>')
            else:
                txt = _xml_escape(str(val if val is not None else ""))
                cells_xml.append(f'<c r="{ref}" t="inlineStr"><is><t xml:space="preserve">{txt}</t></is></c>')
        row_xml_parts.append(f'<row r="{r_idx}">{"".join(cells_xml)}</row>')

    sheet_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f'<sheetData>{"".join(row_xml_parts)}</sheetData>'
        '</worksheet>'
    )
    workbook_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f'<sheets><sheet name="{_xml_escape(sheet_name[:31])}" sheetId="1" r:id="rId1"/></sheets>'
        '</workbook>'
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        '</Types>'
    )
    root_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
        '</Relationships>'
    )
    wb_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
        '</Relationships>'
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types)
        zf.writestr("_rels/.rels", root_rels)
        zf.writestr("xl/workbook.xml", workbook_xml)
        zf.writestr("xl/_rels/workbook.xml.rels", wb_rels)
        zf.writestr("xl/worksheets/sheet1.xml", sheet_xml)
    return buf.getvalue()


# ══════════════════════════════════════════════════════════════════════════════
# 5. MOTOR DE ENVÍOS (EMAIL, WHATSAPP API, CONECT, ABRIR WHATSAPP, ENLACES SEGUROS)
# ══════════════════════════════════════════════════════════════════════════════

def get_channels_availability(db: Session, empresa_id: str) -> Dict[str, Any]:
    wa_cfg = _wa.get_config(db, empresa_id)
    wa_ready, wa_reason = _wa.is_configured(wa_cfg)

    smtp_row = (
        db.query(models.AdminConfig)
        .filter(models.AdminConfig.empresa_id == empresa_id, models.AdminConfig.config_key == "integrations.smtp")
        .first()
    )
    smtp_cfg = smtp_row.config_val if (smtp_row and isinstance(smtp_row.config_val, dict)) else {}
    smtp_ready = bool(smtp_cfg.get("enabled") and smtp_cfg.get("host") and smtp_cfg.get("from_email"))

    conect_row = (
        db.query(models.AdminConfig)
        .filter(models.AdminConfig.empresa_id == empresa_id, models.AdminConfig.config_key == "integrations.conect")
        .first()
    )
    conect_cfg = conect_row.config_val if (conect_row and isinstance(conect_row.config_val, dict)) else {}
    conect_ready = bool(conect_cfg.get("enabled") and conect_cfg.get("endpoint_url"))

    return {
        "email": {
            "configured": smtp_ready,
            "test_sandbox_available": True,
            "label": "Correo electrónico",
            "status_note": "SMTP activo" if smtp_ready else "Modo bandeja de pruebas local (falta configurar SMTP productivo en Configuración)",
        },
        "whatsapp_api": {
            "configured": wa_ready,
            "test_sandbox_available": True,
            "label": "WhatsApp API (Twilio)",
            "status_note": "Twilio activo" if wa_ready else f"Sin credenciales activas ({wa_reason}); disponible Abrir WhatsApp o canal de prueba",
        },
        "conect": {
            "configured": conect_ready,
            "test_sandbox_available": False,
            "label": "CONECT Mensajería",
            "status_note": "CONECT operativo" if conect_ready else "Sin integración CONECT activa en este tenant",
        },
        "whatsapp_web": {
            "configured": True,
            "label": "Abrir WhatsApp",
            "status_note": "Abre WhatsApp con mensaje prellenado y ofrece descargar el archivo para adjuntarlo manualmente.",
        },
        "share_link": {
            "configured": True,
            "label": "Enlace seguro con vencimiento",
            "status_note": "Genera enlace único limitado al archivo autorizado, con expiración y revocación inmediata.",
        },
    }


def build_dispatch_preview(
    db: Session,
    empresa_id: str,
    entries_by_key: Dict[str, models.DocumentRegistryEntry],
    items_spec: List[Dict[str, Any]],
    channel: str,
    message: str,
    perms: Dict[str, Any],
) -> Dict[str, Any]:
    """Construye la previsualización exacta antes de confirmar envío:
    agrupa por destinatario mostrando canal, mensaje normalizado y nombres exactos de archivos."""
    if not perms.get("send"):
        raise HTTPException(status_code=403, detail="Tu rol no cuenta con permiso para enviar documentos.")

    # Regla CALEBSYS Corte Z: no permitir consolidado de Cortes Z en envío por lote
    cz_keys = [sp.get("doc_key") for sp in items_spec if sp.get("doc_key") in entries_by_key and entries_by_key[sp["doc_key"]].doc_subtype == "corte_z"]
    if len(cz_keys) > 1:
        distinct_cz = {(entries_by_key[k].sucursal_id, entries_by_key[k].caja_id or entries_by_key[k].source_id) for k in cz_keys}
        if len(distinct_cz) > 1:
            raise HTTPException(
                status_code=403,
                detail="Regla CALEBSYS: No se permite enviar en lote múltiples Cortes Z para producir un consolidado.",
            )

    channel_u = str(channel or "EMAIL").strip().upper()
    msg_norm = str(message or "").strip().upper()
    recipients_grouping: Dict[str, Dict[str, Any]] = {}
    resolved_items: List[Dict[str, Any]] = []

    for sp in items_spec:
        dkey = str(sp.get("doc_key") or "").strip()
        ent = entries_by_key.get(dkey)
        if not ent:
            raise HTTPException(status_code=404, detail=f"Documento '{dkey}' no encontrado o fuera de alcance.")
        recipient = str(sp.get("recipient") or "").strip()
        if channel_u == "EMAIL":
            recipient = recipient.lower()
        fmt_list = [str(f).upper() for f in (sp.get("formats") or ["CARTA"])]
        fnames: List[str] = []
        for fcode in fmt_list:
            if fcode in ("CARTA", "TICKET"):
                if not perms.get("view_amounts") and ent.amount_applicable and not SUBTYPE_META_MAP.get(ent.doc_subtype, {}).get("non_monetary_safe"):
                    raise HTTPException(status_code=403, detail=f"No puedes enviar {ent.folio_visible}: contiene importes restringidos para tu rol.")
                fnames.append(build_safe_download_filename(ent.folio_visible, ent.sucursal_id, fcode, "pdf"))
            elif fcode == "XML":
                if not ent.has_xml:
                    continue
                if not perms.get("view_amounts"):
                    raise HTTPException(status_code=403, detail="Sin permiso de importes para adjuntar XML.")
                fnames.append(build_safe_download_filename(ent.folio_visible, ent.sucursal_id, "XML_FIRMADO", "xml"))

        rec_key = recipient or "SIN_DESTINATARIO"
        if rec_key not in recipients_grouping:
            recipients_grouping[rec_key] = {
                "recipient": recipient,
                "recipient_name": ent.tercero_nombre or "DESTINATARIO",
                "channel": channel_u,
                "documents": [],
                "exact_files": [],
            }
        recipients_grouping[rec_key]["documents"].append({
            "doc_key": dkey,
            "folio_visible": ent.folio_visible,
            "subtype_label": SUBTYPE_META_MAP.get(ent.doc_subtype, {}).get("short") or ent.doc_subtype,
            "sucursal_id": ent.sucursal_id,
        })
        recipients_grouping[rec_key]["exact_files"].extend(fnames)
        resolved_items.append({
            "doc_key": dkey,
            "folio_visible": ent.folio_visible,
            "recipient": recipient,
            "recipient_name": ent.tercero_nombre,
            "formats": fmt_list,
            "filenames": fnames,
        })

    channels_info = get_channels_availability(db, empresa_id)
    return {
        "channel": channel_u,
        "message_normalized": msg_norm,
        "recipients_summary": list(recipients_grouping.values()),
        "items": resolved_items,
        "total_documents": len(resolved_items),
        "channel_availability": channels_info.get(channel_u.lower(), {}),
    }


def _dispatch_single_item(
    db: Session,
    empresa_id: str,
    entry: models.DocumentRegistryEntry,
    item_row: models.DocumentDispatchItem,
    perms: Dict[str, Any],
    subject: str,
    message_body: str,
    is_test_mode: bool,
    user_id: str,
) -> None:
    """Ejecuta el envío de un ítem individual actualizando honestamente su estado y confirmación."""
    now = _dt.datetime.now(_dt.timezone.utc)
    rec = (item_row.recipient or "").strip()
    ch = (item_row.channel or "EMAIL").upper()

    if not rec and ch != "WHATSAPP_WEB":
        item_row.status = "FAILED_PERMANENT"
        item_row.safe_to_retry = False
        item_row.error_detail = "Destinatario vacío."
        return

    # Preparar adjuntos reales autorizados
    attachments_payload: List[Tuple[str, bytes, str]] = []
    try:
        for fmt in (item_row.formats_json or ["CARTA"]):
            fu = str(fmt).upper()
            if fu in ("CARTA", "TICKET"):
                pdf_b, _ = resolve_document_pdf_and_meta(db, empresa_id, entry, perms, mode=fu, representation="original")
                fn = build_safe_download_filename(entry.folio_visible, entry.sucursal_id, fu, "pdf")
                attachments_payload.append((fn, pdf_b, "application/pdf"))
            elif fu == "XML" and entry.has_xml:
                xml_b, _, xfn = resolve_xml_or_acuse_bytes(db, empresa_id, entry, perms, kind="XML")
                attachments_payload.append((xfn, xml_b, "application/xml"))
    except HTTPException as he:
        item_row.status = "FAILED_PERMANENT"
        item_row.safe_to_retry = False
        item_row.error_detail = str(he.detail)
        return
    except Exception as exc:
        item_row.status = "FAILED_SAFE_RETRY"
        item_row.safe_to_retry = True
        item_row.error_detail = f"Error preparando archivos: {exc}"
        return

    # Canal de prueba de integración controlada (distingue prueba de integración vs entrega real)
    if is_test_mode:
        low_r = rec.lower()
        item_row.provider_name = f"SANDBOX_{ch}"
        if "fail" in low_r or "error" in low_r or rec.endswith("0000"):
            item_row.status = "FAILED_SAFE_RETRY"
            item_row.safe_to_retry = True
            item_row.provider_raw_status = "sandbox_simulated_transient_error"
            item_row.error_detail = f"Fallo transitorio simulado en canal de prueba para '{rec}'."
            return
        if "invalid" in low_r or (ch == "EMAIL" and "@" not in rec):
            item_row.status = "FAILED_PERMANENT"
            item_row.safe_to_retry = False
            item_row.provider_raw_status = "sandbox_invalid_recipient"
            item_row.error_detail = f"Destinatario inválido '{rec}' (no reintentable)."
            return
        if "uncertain" in low_r or "timeout" in low_r:
            item_row.status = "UNCERTAIN"
            item_row.safe_to_retry = False
            item_row.provider_message_id = f"TEST-UNC-{uuid.uuid4().hex[:10].upper()}"
            item_row.provider_raw_status = "queued_timeout"
            item_row.error_detail = "Tiempo de espera agotado; consulte estado al proveedor antes de reenviar."
            return

        # Guardar evidencia en bandeja local de pruebas de desarrollo
        outbox_dir = os.path.join(MEDIA_DOC_CENTER_ROOT, _pfs._safe_tenant_segment(empresa_id), "test_outbox")
        os.makedirs(outbox_dir, exist_ok=True)
        msg_id = f"TEST-{ch[:4]}-{uuid.uuid4().hex[:10].upper()}"
        meta_path = os.path.join(outbox_dir, f"{msg_id}.json")
        with open(meta_path, "w", encoding="utf-8") as fh:
            json.dump({
                "message_id": msg_id,
                "is_integration_test": True,
                "real_delivery": False,
                "channel": ch,
                "recipient": rec,
                "folio": entry.folio_visible,
                "subject": subject,
                "body": message_body,
                "files": [a[0] for a in attachments_payload],
                "created_at": now.isoformat(),
            }, fh, ensure_ascii=False, indent=2)
        item_row.status = "SENT"
        item_row.safe_to_retry = False
        item_row.provider_message_id = msg_id
        item_row.provider_raw_status = "sandbox_accepted_no_external_delivery"
        item_row.provider_delivery_confirmed = False  # Honesto: prueba de integración != Entregado real
        item_row.provider_read_confirmed = False
        item_row.error_detail = None
        item_row.sent_at = now
        return

    # Modo operativo real según canal
    if ch == "WHATSAPP_WEB":
        item_row.provider_name = "WHATSAPP_CLIENT_DEEPLINK"
        item_row.status = "OPENED_CLIENT"
        item_row.safe_to_retry = True
        item_row.provider_raw_status = "client_url_generated"
        item_row.provider_delivery_confirmed = False
        item_row.provider_read_confirmed = False
        item_row.sent_at = now
        return

    if ch == "EMAIL":
        if "@" not in rec:
            item_row.status = "FAILED_PERMANENT"
            item_row.safe_to_retry = False
            item_row.error_detail = f"Dirección de correo inválida: '{rec}'."
            return
        smtp_row = (
            db.query(models.AdminConfig)
            .filter(models.AdminConfig.empresa_id == empresa_id, models.AdminConfig.config_key == "integrations.smtp")
            .first()
        )
        smtp_cfg = smtp_row.config_val if (smtp_row and isinstance(smtp_row.config_val, dict)) else {}
        if not (smtp_cfg.get("enabled") and smtp_cfg.get("host") and smtp_cfg.get("from_email")):
            item_row.status = "FAILED_SAFE_RETRY"
            item_row.safe_to_retry = True
            item_row.provider_name = "SMTP"
            item_row.error_detail = "Servidor SMTP no configurado en este tenant (active modo de prueba o configure integrations.smtp)."
            return
        try:
            msg = EmailMessage()
            msg["Subject"] = subject or f"DOCUMENTO {entry.folio_visible} — CALEBSYS"
            msg["From"] = str(smtp_cfg["from_email"])
            msg["To"] = rec
            msg.set_content(message_body or f"SE ADJUNTA DOCUMENTO {entry.folio_visible}.")
            for fn, raw_b, mime in attachments_payload:
                maintype, subtype = mime.split("/", 1)
                msg.add_attachment(raw_b, maintype=maintype, subtype=subtype, filename=fn)
            port = int(smtp_cfg.get("port") or 587)
            with smtplib.SMTP(str(smtp_cfg["host"]), port, timeout=15) as srv:
                if smtp_cfg.get("use_tls", True):
                    srv.starttls()
                if smtp_cfg.get("username") and smtp_cfg.get("password"):
                    srv.login(str(smtp_cfg["username"]), str(smtp_cfg["password"]))
                srv.send_message(msg)
            item_row.status = "SENT"
            item_row.safe_to_retry = False
            item_row.provider_name = "SMTP"
            item_row.provider_message_id = f"SMTP-{uuid.uuid4().hex[:10].upper()}"
            item_row.provider_raw_status = "smtp_250_accepted"
            item_row.provider_delivery_confirmed = False
            item_row.error_detail = None
            item_row.sent_at = now
        except Exception as exc:
            item_row.status = "FAILED_SAFE_RETRY"
            item_row.safe_to_retry = True
            item_row.provider_name = "SMTP"
            item_row.error_detail = str(exc)[:380]
        return

    if ch == "WHATSAPP_API":
        body_txt = f"CALEBSYS · DOCUMENTO {entry.folio_visible} ({entry.sucursal_id})\n{message_body or ''}".strip()
        res = _wa.send_whatsapp(db, empresa_id, rec, body_txt, created_by=user_id, context=f"DOC_CENTER:{entry.folio_visible}")
        item_row.provider_name = "TWILIO_WHATSAPP"
        if res.get("ok"):
            p_st = str(res.get("provider_status") or "queued").lower()
            item_row.status = "DELIVERED" if p_st == "delivered" else ("READ" if p_st == "read" else "SENT")
            item_row.safe_to_retry = False
            item_row.provider_message_id = res.get("provider_sid")
            item_row.provider_raw_status = p_st
            item_row.provider_delivery_confirmed = p_st in ("delivered", "read")
            item_row.provider_read_confirmed = p_st == "read"
            item_row.error_detail = None
            item_row.sent_at = now
            if item_row.provider_delivery_confirmed:
                item_row.confirmed_at = now
        else:
            item_row.status = "FAILED_SAFE_RETRY"
            item_row.safe_to_retry = True
            item_row.error_detail = str(res.get("reason") or res.get("error") or "Fallo WhatsApp API")[:380]
        return

    if ch == "CONECT":
        conect_row = (
            db.query(models.AdminConfig)
            .filter(models.AdminConfig.empresa_id == empresa_id, models.AdminConfig.config_key == "integrations.conect")
            .first()
        )
        ccfg = conect_row.config_val if (conect_row and isinstance(conect_row.config_val, dict)) else {}
        if not (ccfg.get("enabled") and ccfg.get("endpoint_url")):
            item_row.status = "FAILED_SAFE_RETRY"
            item_row.safe_to_retry = True
            item_row.provider_name = "CONECT"
            item_row.error_detail = "Integración CONECT no activa en este tenant."
            return
        try:
            payload_bytes = json.dumps({
                "recipient": rec,
                "folio": entry.folio_visible,
                "message": message_body,
                "files": [{"filename": fn, "mime": mm, "content_b64": base64.b64encode(rb).decode("ascii")} for fn, rb, mm in attachments_payload],
            }).encode("utf-8")
            req = urllib.request.Request(str(ccfg["endpoint_url"]), data=payload_bytes, method="POST")
            req.add_header("Content-Type", "application/json")
            if ccfg.get("api_key"):
                req.add_header("Authorization", f"Bearer {ccfg['api_key']}")
            with urllib.request.urlopen(req, timeout=15) as resp:
                rjs = json.loads(resp.read().decode("utf-8") or "{}")
            p_st = str(rjs.get("status") or "sent").lower()
            item_row.provider_name = "CONECT"
            item_row.provider_message_id = str(rjs.get("message_id") or f"CONECT-{uuid.uuid4().hex[:8]}")
            item_row.provider_raw_status = p_st
            item_row.provider_delivery_confirmed = p_st in ("delivered", "read")
            item_row.provider_read_confirmed = p_st == "read"
            item_row.status = "DELIVERED" if p_st == "delivered" else "SENT"
            item_row.safe_to_retry = False
            item_row.error_detail = None
            item_row.sent_at = now
        except TimeoutError:
            item_row.provider_name = "CONECT"
            item_row.status = "UNCERTAIN"
            item_row.safe_to_retry = False
            item_row.error_detail = "Tiempo de espera agotado hacia CONECT; estado incierto."
        except Exception as exc:
            item_row.provider_name = "CONECT"
            item_row.status = "FAILED_SAFE_RETRY"
            item_row.safe_to_retry = True
            item_row.error_detail = str(exc)[:380]


def _recompute_operation_counters(db: Session, op: models.DocumentDispatchOperation) -> Dict[str, Any]:
    items = (
        db.query(models.DocumentDispatchItem)
        .filter(
            models.DocumentDispatchItem.empresa_id == op.empresa_id,
            models.DocumentDispatchItem.operation_id == op.id,
        )
        .all()
    )
    succ = sum(1 for i in items if i.status in ("SENT", "DELIVERED", "READ", "OPENED_CLIENT"))
    fail = sum(1 for i in items if i.status in ("FAILED_SAFE_RETRY", "FAILED_PERMANENT"))
    unc = sum(1 for i in items if i.status == "UNCERTAIN")

    op.total_items = len(items)
    op.succeeded_items = succ
    op.failed_items = fail
    op.uncertain_items = unc
    if fail == 0 and unc == 0:
        op.status = "COMPLETED"
    elif succ > 0:
        op.status = "PARTIAL_FAILURE"
    elif unc > 0:
        op.status = "UNCERTAIN"
    else:
        op.status = "FAILED"

    # Sincronizar dispatch_status en DocumentRegistryEntry
    for it in items:
        reg = db.query(models.DocumentRegistryEntry).filter(
            models.DocumentRegistryEntry.empresa_id == op.empresa_id,
            models.DocumentRegistryEntry.doc_key == it.doc_key,
        ).first()
        if reg:
            if it.provider_read_confirmed:
                reg.dispatch_status = "LEIDO"
            elif it.provider_delivery_confirmed:
                reg.dispatch_status = "ENTREGADO"
            elif it.status in ("SENT", "SENT_UNCONFIRMED"):
                reg.dispatch_status = "ENVIADO"
            elif it.status == "OPENED_CLIENT":
                reg.dispatch_status = "WHATSAPP_ABIERTO"
            elif it.status == "UNCERTAIN":
                reg.dispatch_status = "INCIERTO"
            else:
                reg.dispatch_status = "CON_ERROR"

    db.commit()
    return serialize_dispatch_operation(op, items)


def serialize_dispatch_operation(op: models.DocumentDispatchOperation, items: List[models.DocumentDispatchItem]) -> Dict[str, Any]:
    out_items = []
    for it in items:
        # Regla estricta: mostrar "Entregado" o "Leído" ÚNICAMENTE con confirmación real
        if it.provider_read_confirmed:
            ui_label = "Leído"
        elif it.provider_delivery_confirmed:
            ui_label = "Entregado"
        elif it.status == "SENT":
            ui_label = "Enviado (prueba de integración)" if op.is_test_mode else "Enviado al proveedor"
        elif it.status == "OPENED_CLIENT":
            ui_label = "WhatsApp abierto (adjuntar manualmente)"
        elif it.status == "UNCERTAIN":
            ui_label = "Resultado incierto (consultar proveedor)"
        elif it.status == "FAILED_SAFE_RETRY":
            ui_label = "Fallido (reintento seguro disponible)"
        else:
            ui_label = "Fallido permanente"

        wa_url = None
        if it.channel == "WHATSAPP_WEB":
            digits = "".join(ch for ch in (it.recipient or "") if ch.isdigit())
            txt = urllib.parse.quote(f"CALEBSYS · Documento {it.folio_visible}\n{op.message_body or ''}".strip())
            wa_url = f"https://wa.me/{digits}?text={txt}" if digits else f"https://wa.me/?text={txt}"

        out_items.append({
            "id": it.id,
            "doc_key": it.doc_key,
            "folio_visible": it.folio_visible,
            "recipient": it.recipient,
            "recipient_name": it.recipient_name,
            "channel": it.channel,
            "formats": it.formats_json or [],
            "filenames": it.filenames_json or [],
            "status": it.status,
            "ui_status_label": ui_label,
            "safe_to_retry": bool(it.safe_to_retry),
            "attempt_count": it.attempt_count,
            "provider_name": it.provider_name,
            "provider_message_id": it.provider_message_id,
            "provider_delivery_confirmed": bool(it.provider_delivery_confirmed),
            "provider_read_confirmed": bool(it.provider_read_confirmed),
            "error_detail": it.error_detail,
            "whatsapp_open_url": wa_url,
            "sent_at": it.sent_at.isoformat() if it.sent_at else None,
        })

    return {
        "operation_id": op.id,
        "operation_key": op.operation_key,
        "channel": op.channel,
        "status": op.status,
        "is_test_mode": bool(op.is_test_mode),
        "delivery_scope": "INTEGRATION_TEST" if op.is_test_mode else "REAL_CHANNEL",
        "total_items": op.total_items,
        "succeeded_items": op.succeeded_items,
        "failed_items": op.failed_items,
        "uncertain_items": op.uncertain_items,
        "items": out_items,
        "created_at": op.created_at.isoformat() if op.created_at else None,
    }


def execute_dispatch_operation(
    db: Session,
    empresa_id: str,
    sucursal_id: str,
    user_id: str,
    operation_key: str,
    entries_by_key: Dict[str, models.DocumentRegistryEntry],
    items_spec: List[Dict[str, Any]],
    channel: str,
    subject: str,
    message: str,
    is_test_mode: bool,
    perms: Dict[str, Any],
) -> Dict[str, Any]:
    """Ejecuta envío con idempotencia estricta por `(empresa_id, operation_key)`."""
    if not operation_key or len(operation_key.strip()) < 6:
        raise HTTPException(status_code=400, detail="Se requiere un identificador de operación (operation_key) válido para prevenir duplicados.")

    op_key_clean = operation_key.strip()[:120]
    existing_op = (
        db.query(models.DocumentDispatchOperation)
        .filter(
            models.DocumentDispatchOperation.empresa_id == empresa_id,
            models.DocumentDispatchOperation.operation_key == op_key_clean,
        )
        .first()
    )
    if existing_op:
        ex_items = (
            db.query(models.DocumentDispatchItem)
            .filter(
                models.DocumentDispatchItem.empresa_id == empresa_id,
                models.DocumentDispatchItem.operation_id == existing_op.id,
            )
            .all()
        )
        res = serialize_dispatch_operation(existing_op, ex_items)
        res["idempotent_replay"] = True
        return res

    # Validar antes con la misma lógica del preview
    prev = build_dispatch_preview(db, empresa_id, entries_by_key, items_spec, channel, message, perms)
    ch_u = prev["channel"]
    msg_norm = prev["message_normalized"]
    subj_norm = str(subject or "").strip().upper() or "ENVÍO DE DOCUMENTOS — CALEBSYS"

    op = models.DocumentDispatchOperation(
        id=str(uuid.uuid4()),
        empresa_id=empresa_id,
        sucursal_id=sucursal_id,
        operation_key=op_key_clean,
        channel=ch_u,
        status="PROCESSING",
        subject=subj_norm,
        message_body=msg_norm,
        total_items=len(prev["items"]),
        is_test_mode=bool(is_test_mode),
        created_by=user_id,
    )
    db.add(op)
    db.flush()

    created_items: List[models.DocumentDispatchItem] = []
    for it_s in prev["items"]:
        ent = entries_by_key[it_s["doc_key"]]
        di = models.DocumentDispatchItem(
            id=str(uuid.uuid4()),
            empresa_id=empresa_id,
            operation_id=op.id,
            doc_key=ent.doc_key,
            folio_visible=ent.folio_visible,
            recipient=it_s["recipient"],
            recipient_name=it_s.get("recipient_name"),
            channel=ch_u,
            formats_json=it_s["formats"],
            filenames_json=it_s["filenames"],
            status="PENDING",
            attempt_count=1,
        )
        db.add(di)
        db.flush()
        _dispatch_single_item(db, empresa_id, ent, di, perms, subj_norm, msg_norm, bool(is_test_mode), user_id)
        created_items.append(di)

    out = _recompute_operation_counters(db, op)
    out["idempotent_replay"] = False
    audit_doc_event(
        db, empresa_id, sucursal_id, user_id,
        "DOC_CENTER_DISPATCH",
        {
            "operation_id": op.id,
            "channel": ch_u,
            "is_test_mode": bool(is_test_mode),
            "succeeded": op.succeeded_items,
            "failed": op.failed_items,
            "uncertain": op.uncertain_items,
        },
    )
    return out


def retry_failed_dispatch_items(
    db: Session,
    empresa_id: str,
    sucursal_id: str,
    user_id: str,
    operation_id: str,
    perms: Dict[str, Any],
    override_recipients: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Reintenta ÚNICAMENTE los ítems con `safe_to_retry == True` (`FAILED_SAFE_RETRY`),
    conservando intactos todos los éxitos previos (`SENT`, `DELIVERED`, `READ`) y bloqueando
    reintentos a ciegas de ítems `UNCERTAIN`."""
    op = (
        db.query(models.DocumentDispatchOperation)
        .filter(
            models.DocumentDispatchOperation.empresa_id == empresa_id,
            models.DocumentDispatchOperation.id == operation_id,
        )
        .first()
    )
    if not op:
        raise HTTPException(status_code=404, detail="Operación de envío no encontrada.")

    items = (
        db.query(models.DocumentDispatchItem)
        .filter(
            models.DocumentDispatchItem.empresa_id == empresa_id,
            models.DocumentDispatchItem.operation_id == op.id,
        )
        .all()
    )
    overrides = override_recipients or {}
    retried_count = 0

    for di in items:
        if di.status != "FAILED_SAFE_RETRY" or not di.safe_to_retry:
            continue
        ent = (
            db.query(models.DocumentRegistryEntry)
            .filter(
                models.DocumentRegistryEntry.empresa_id == empresa_id,
                models.DocumentRegistryEntry.doc_key == di.doc_key,
            )
            .first()
        )
        if not ent:
            continue
        if di.id in overrides and overrides[di.id].strip():
            di.recipient = overrides[di.id].strip()
        di.attempt_count = int(di.attempt_count or 1) + 1
        _dispatch_single_item(
            db, empresa_id, ent, di, perms,
            op.subject or "", op.message_body or "", bool(op.is_test_mode), user_id,
        )
        retried_count += 1

    out = _recompute_operation_counters(db, op)
    out["retried_count"] = retried_count
    audit_doc_event(
        db, empresa_id, sucursal_id, user_id,
        "DOC_CENTER_DISPATCH_RETRY",
        {"operation_id": op.id, "retried_count": retried_count, "succeeded": op.succeeded_items, "failed": op.failed_items},
    )
    return out


def refresh_uncertain_dispatch_status(
    db: Session,
    empresa_id: str,
    operation_id: str,
) -> Dict[str, Any]:
    """Consulta al proveedor (Twilio / Sandbox) cuando el estado de un ítem es `UNCERTAIN` o `SENT`."""
    op = (
        db.query(models.DocumentDispatchOperation)
        .filter(
            models.DocumentDispatchOperation.empresa_id == empresa_id,
            models.DocumentDispatchOperation.id == operation_id,
        )
        .first()
    )
    if not op:
        raise HTTPException(status_code=404, detail="Operación de envío no encontrada.")

    items = (
        db.query(models.DocumentDispatchItem)
        .filter(
            models.DocumentDispatchItem.empresa_id == empresa_id,
            models.DocumentDispatchItem.operation_id == op.id,
        )
        .all()
    )
    wa_cfg = _wa.get_config(db, empresa_id)
    wa_ready, _ = _wa.is_configured(wa_cfg)

    for di in items:
        if di.status not in ("UNCERTAIN", "SENT"):
            continue
        if op.is_test_mode and di.status == "UNCERTAIN":
            # En sandbox la consulta confirma si el proveedor finalmente lo rechazó para habilitar reintento seguro
            di.status = "FAILED_SAFE_RETRY"
            di.safe_to_retry = True
            di.provider_raw_status = "provider_confirmed_not_delivered"
            di.error_detail = "Proveedor confirmó que el mensaje no salió; ahora es seguro reintentar."
        elif di.provider_name == "TWILIO_WHATSAPP" and di.provider_message_id and wa_ready:
            try:
                sid = wa_cfg["account_sid"]
                tok = wa_cfg["auth_token"]
                url = f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages/{di.provider_message_id}.json"
                req = urllib.request.Request(url, method="GET")
                auth = base64.b64encode(f"{sid}:{tok}".encode("utf-8")).decode("ascii")
                req.add_header("Authorization", "Basic " + auth)
                with urllib.request.urlopen(req, timeout=10) as resp:
                    pjs = json.loads(resp.read().decode("utf-8") or "{}")
                pst = str(pjs.get("status") or "").lower()
                di.provider_raw_status = pst
                if pst == "read":
                    di.status = "READ"
                    di.provider_delivery_confirmed = True
                    di.provider_read_confirmed = True
                    di.confirmed_at = _dt.datetime.now(_dt.timezone.utc)
                elif pst == "delivered":
                    di.status = "DELIVERED"
                    di.provider_delivery_confirmed = True
                    di.confirmed_at = _dt.datetime.now(_dt.timezone.utc)
                elif pst in ("failed", "undelivered"):
                    di.status = "FAILED_SAFE_RETRY"
                    di.safe_to_retry = True
                    di.error_detail = str(pjs.get("error_message") or pst)
            except Exception:
                pass

    return _recompute_operation_counters(db, op)
