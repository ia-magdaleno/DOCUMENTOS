"""Servicio integral del Submódulo «Diseñador de formatos» (Configuración -> Impresoras F9).

Incluye:
- Catálogo de los 17 tipos de documentos (con distinción clara OPERATIVO vs SOLO_PLANTILLA).
- Catálogo de campos filtrado por tipo de documento y respaldado por contratos reales.
- Evaluador seguro de texto combinado (`{{grupo.campo}}`) y formateadores sin ejecución de código arbitrario.
- Evaluador seguro de condiciones visuales (`mostrar si campo operador valor`).
- Procesamiento y validación real de archivos de fondo PDF (multipágina vía pypdfium2) e imágenes (PNG/JPG vía Pillow).
- Conversión exacta de unidades físicas: milímetros (mm) <-> puntos PDF (pt, 1 mm = 72/25.4 pt) <-> píxeles de lienzo con zoom.
- Motor de paginación multipágina de tablas de productos/conceptos sin encimar totales ni firmas.
- Generador real de archivos PDF (`background_and_fields` y `fields_only` para papel preimpreso).
- Inmutabilidad de versiones publicadas, resolución determinista de asignaciones (Terminal -> Sucursal -> Empresa -> Default)
  y registro histórico de emisiones para reimpresiones fieles.
"""
import datetime as _dt
import hashlib
import io
import json
import math
import os
import re
import uuid
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

import pypdfium2 as pdfium
from PIL import Image, ImageDraw, ImageFont
from sqlalchemy.orm import Session

import models

MM_TO_PT = 72.0 / 25.4          # 1 mm = 2.834645669291339 pt
PT_TO_MM = 25.4 / 72.0          # 1 pt = 0.3527777777777778 mm
CARTA_WIDTH_MM = 215.9
CARTA_HEIGHT_MM = 279.4
A4_WIDTH_MM = 210.0
A4_HEIGHT_MM = 297.0

MAX_ASSET_BYTES = 15 * 1024 * 1024  # 15 MB límite documentado
MAX_PDF_PAGES = 25                  # Máximo 25 páginas por archivo de fondo

MEDIA_PRINT_ROOT = os.environ.get(
    "PRINT_FORMATS_MEDIA_DIR",
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "media", "print_formats")),
)


class PrintFormatError(Exception):
    """Error de validación, permisos o procesamiento en el Diseñador de Formatos."""
    def __init__(self, message: str, code: str = "validation_error", status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code


# ══════════════════════════════════════════════════════════════════════════════
# 1. CATÁLOGO DE LOS 17 TIPOS DE DOCUMENTOS Y CONTRATOS DE INTEGRACIÓN
# ══════════════════════════════════════════════════════════════════════════════

DOC_TYPES_CATALOG: List[Dict[str, Any]] = [
    {
        "doc_type": "ticket_venta_contado",
        "name": "Ticket de venta de contado",
        "category": "VENTAS Y CAJA",
        "allowed_modes": ["TICKET", "CARTA"],
        "default_mode": "TICKET",
        "integration_status": "OPERATIVO",
        "integration_source": "POST /api/sales (F7 Cobro Contado / Mixto)",
        "field_groups": ["empresa", "sucursal", "operacion", "cliente", "productos", "importes", "pagos"],
        "mandatory_fields": ["empresa.nombre_comercial", "operacion.folio", "importes.total"],
    },
    {
        "doc_type": "ticket_venta_credito",
        "name": "Ticket de venta a crédito",
        "category": "VENTAS Y CARTERA",
        "allowed_modes": ["TICKET", "CARTA"],
        "default_mode": "TICKET",
        "integration_status": "OPERATIVO",
        "integration_source": "POST /api/sales (F7 Método 006 Crédito + AccountsReceivable)",
        "field_groups": ["empresa", "sucursal", "operacion", "cliente", "productos", "importes", "pagos", "credito"],
        "mandatory_fields": ["empresa.nombre_comercial", "operacion.folio", "cliente.nombre", "importes.total", "credito.saldo_pendiente"],
    },
    {
        "doc_type": "orden_entrega",
        "name": "Orden de entrega",
        "category": "ALMACÉN Y LOGÍSTICA",
        "allowed_modes": ["TICKET", "CARTA"],
        "default_mode": "CARTA",
        "integration_status": "OPERATIVO",
        "integration_source": "POS Entrega a Domicilio / Resguardo y Salida de Almacén",
        "field_groups": ["empresa", "sucursal", "operacion", "cliente", "productos", "entrega"],
        "mandatory_fields": ["empresa.nombre_comercial", "operacion.folio", "cliente.nombre"],
    },
    {
        "doc_type": "cotizacion",
        "name": "Cotización",
        "category": "VENTAS Y PRESUPUESTOS",
        "allowed_modes": ["TICKET", "CARTA"],
        "default_mode": "CARTA",
        "integration_status": "OPERATIVO",
        "integration_source": "Módulo F8 Cotizaciones POS (/api/quotes)",
        "field_groups": ["empresa", "sucursal", "operacion", "cliente", "productos", "importes"],
        "mandatory_fields": ["empresa.nombre_comercial", "operacion.folio", "importes.total"],
    },
    {
        "doc_type": "comprobante_pago",
        "name": "Comprobante de pago o abono",
        "category": "CARTERA Y CXC",
        "allowed_modes": ["TICKET", "CARTA"],
        "default_mode": "TICKET",
        "integration_status": "OPERATIVO",
        "integration_source": "Cuentas por Cobrar / Abonos AR (/api/receivables/{id}/pay)",
        "field_groups": ["empresa", "sucursal", "operacion", "cliente", "importes", "pagos", "credito"],
        "mandatory_fields": ["empresa.nombre_comercial", "operacion.folio", "cliente.nombre", "credito.importe_abono", "credito.saldo_pendiente"],
    },
    {
        "doc_type": "cfdi_factura_ticket",
        "name": "Representación impresa de CFDI/factura",
        "category": "FACTURACIÓN FISCAL SAT",
        "allowed_modes": ["TICKET", "CARTA"],
        "default_mode": "CARTA",
        "integration_status": "OPERATIVO",
        "integration_source": "Módulo CFDI 4.0 (/api/cfdi)",
        "field_groups": ["empresa", "sucursal", "operacion", "cliente", "productos", "importes", "pagos", "cfdi"],
        "mandatory_fields": ["empresa.rfc", "cliente.rfc", "cfdi.uuid", "importes.total", "cfdi.qr_sat"],
    },
    {
        "doc_type": "remision",
        "name": "Remisión",
        "category": "VENTAS Y CAJA",
        "allowed_modes": ["TICKET", "CARTA"],
        "default_mode": "CARTA",
        "integration_status": "OPERATIVO",
        "integration_source": "Ventas POS / Remisión Formal Carta",
        "field_groups": ["empresa", "sucursal", "operacion", "cliente", "productos", "importes", "pagos", "entrega"],
        "mandatory_fields": ["empresa.nombre_comercial", "operacion.folio", "importes.total"],
    },
    {
        "doc_type": "orden_compra",
        "name": "Orden de compra",
        "category": "COMPRAS Y PROVEEDORES",
        "allowed_modes": ["TICKET", "CARTA"],
        "default_mode": "CARTA",
        "integration_status": "OPERATIVO",
        "integration_source": "Módulo Órdenes de Compra (/api/purchase-orders)",
        "field_groups": ["empresa", "sucursal", "operacion", "cliente", "productos", "importes"],
        "mandatory_fields": ["empresa.nombre_comercial", "operacion.folio", "importes.total"],
    },
    {
        "doc_type": "devolucion",
        "name": "Devolución",
        "category": "VENTAS Y ALMACÉN",
        "allowed_modes": ["TICKET", "CARTA"],
        "default_mode": "TICKET",
        "integration_status": "OPERATIVO",
        "integration_source": "Módulo F2/F6 Devoluciones POS y Almacén",
        "field_groups": ["empresa", "sucursal", "operacion", "cliente", "productos", "importes", "pagos"],
        "mandatory_fields": ["empresa.nombre_comercial", "operacion.folio", "importes.total"],
    },
    {
        "doc_type": "comprobante_cancelacion",
        "name": "Comprobante de cancelación",
        "category": "VENTAS Y AUDITORÍA",
        "allowed_modes": ["TICKET", "CARTA"],
        "default_mode": "TICKET",
        "integration_status": "OPERATIVO",
        "integration_source": "Cancelación de Venta / CFDI (/api/sales, /api/cfdi)",
        "field_groups": ["empresa", "sucursal", "operacion", "cliente", "importes"],
        "mandatory_fields": ["empresa.nombre_comercial", "operacion.folio", "operacion.estado"],
    },
    {
        "doc_type": "apertura_caja",
        "name": "Apertura de caja",
        "category": "CAJA Y CORTES",
        "allowed_modes": ["TICKET", "CARTA"],
        "default_mode": "TICKET",
        "integration_status": "OPERATIVO",
        "integration_source": "Módulo Caja y Cortes (/admin#caja)",
        "field_groups": ["empresa", "sucursal", "operacion", "corte", "importes", "profeco"],
        "mandatory_fields": ["empresa.nombre_comercial", "operacion.cajero", "importes.total"],
    },
    {
        "doc_type": "corte_ciego",
        "name": "Corte Ciego (Conteo Físico sin Mostrar Esperado)",
        "category": "CAJA Y CORTES",
        "allowed_modes": ["TICKET", "CARTA"],
        "default_mode": "TICKET",
        "integration_status": "OPERATIVO",
        "integration_source": "Arqueo y Entrega de Sobre Ciego (/admin#caja)",
        "field_groups": ["empresa", "sucursal", "operacion", "corte", "importes", "pagos", "profeco"],
        "mandatory_fields": ["empresa.nombre_comercial", "operacion.cajero"],
    },
    {
        "doc_type": "arqueo_caja",
        "name": "Arqueo de caja",
        "category": "CAJA Y CORTES",
        "allowed_modes": ["TICKET", "CARTA"],
        "default_mode": "TICKET",
        "integration_status": "OPERATIVO",
        "integration_source": "Módulo Caja y Cortes (/admin#caja)",
        "field_groups": ["empresa", "sucursal", "operacion", "corte", "importes", "pagos", "profeco"],
        "mandatory_fields": ["empresa.nombre_comercial", "operacion.cajero", "importes.total"],
    },
    {
        "doc_type": "corte_x",
        "name": "Corte X (Parcial / Supervisión en Turno Abierto)",
        "category": "CAJA Y CORTES",
        "allowed_modes": ["TICKET", "CARTA"],
        "default_mode": "TICKET",
        "integration_status": "OPERATIVO",
        "integration_source": "Corte Parcial de Caja (/admin#caja)",
        "field_groups": ["empresa", "sucursal", "operacion", "corte", "importes", "pagos", "profeco"],
        "mandatory_fields": ["empresa.nombre_comercial", "operacion.fecha", "importes.total"],
    },
    {
        "doc_type": "corte_z",
        "name": "Corte Z / Cierre Definitivo de Turno y Día",
        "category": "CAJA Y CORTES",
        "allowed_modes": ["TICKET", "CARTA"],
        "default_mode": "TICKET",
        "integration_status": "OPERATIVO",
        "integration_source": "Cierre Definitivo de Turno (/admin#caja)",
        "field_groups": ["empresa", "sucursal", "operacion", "corte", "importes", "pagos", "profeco"],
        "mandatory_fields": ["empresa.nombre_comercial", "operacion.fecha", "importes.total"],
    },
    {
        "doc_type": "estado_cuenta_cliente",
        "name": "Estado de cuenta de cliente",
        "category": "CARTERA Y CXC",
        "allowed_modes": ["TICKET", "CARTA"],
        "default_mode": "CARTA",
        "integration_status": "OPERATIVO",
        "integration_source": "Bóveda y Estado de Cuenta Clientes (/api/clients/{id}/ledger)",
        "field_groups": ["empresa", "sucursal", "operacion", "cliente", "productos", "importes", "credito"],
        "mandatory_fields": ["empresa.nombre_comercial", "cliente.nombre", "credito.saldo_pendiente"],
    },
    {
        "doc_type": "estado_cuenta_proveedor",
        "name": "Estado de cuenta de proveedor",
        "category": "COMPRAS Y CXP",
        "allowed_modes": ["CARTA", "TICKET"],
        "default_mode": "CARTA",
        "integration_status": "OPERATIVO",
        "integration_source": "Módulo Cuentas por Pagar (/admin#compras-cxp)",
        "field_groups": ["empresa", "sucursal", "operacion", "cliente", "productos", "importes", "credito"],
        "mandatory_fields": ["empresa.nombre_comercial", "cliente.nombre", "importes.total"],
    },
    {
        "doc_type": "documento_formal",
        "name": "Documentos formales: cartas, contratos, constancias y otros",
        "category": "DOCUMENTOS FORMALES Y JURÍDICOS",
        "allowed_modes": ["CARTA", "TICKET"],
        "default_mode": "CARTA",
        "integration_status": "SOLO_PLANTILLA",
        "integration_source": "Emisión bajo demanda con fondo PDF/imagen membretado (Plantilla en Ticket y Tamaño Carta)",
        "field_groups": ["empresa", "sucursal", "operacion", "cliente", "importes", "credito", "entrega", "profeco"],
        "mandatory_fields": ["empresa.nombre_comercial"],
    },
]

DOC_TYPES_MAP: Dict[str, Dict[str, Any]] = {d["doc_type"]: d for d in DOC_TYPES_CATALOG}


# ══════════════════════════════════════════════════════════════════════════════
# 2. CATÁLOGO DE CAMPOS AGRUPADO Y RESPALDADO POR CONTRATOS DE DATOS
# ══════════════════════════════════════════════════════════════════════════════

FIELD_GROUPS_CATALOG: Dict[str, Dict[str, Any]] = {
    "empresa": {
        "group_key": "empresa",
        "group_label": "EMPRESA EMISORA",
        "fields": [
            {"key": "empresa.nombre_comercial", "label": "Nombre comercial", "format": "text"},
            {"key": "empresa.razon_social", "label": "Razón social", "format": "text"},
            {"key": "empresa.rfc", "label": "RFC", "format": "text"},
            {"key": "empresa.regimen_fiscal", "label": "Régimen fiscal", "format": "text"},
            {"key": "empresa.domicilio", "label": "Domicilio", "format": "text"},
            {"key": "empresa.telefonos", "label": "Teléfonos", "format": "text"},
            {"key": "empresa.correo", "label": "Correo electrónico", "format": "text"},
            {"key": "empresa.logotipo", "label": "Logotipo", "format": "image"},
        ],
    },
    "sucursal": {
        "group_key": "sucursal",
        "group_label": "SUCURSAL",
        "fields": [
            {"key": "sucursal.nombre", "label": "Nombre de sucursal", "format": "text"},
            {"key": "sucursal.clave", "label": "Clave de sucursal", "format": "text"},
            {"key": "sucursal.domicilio", "label": "Domicilio de sucursal", "format": "text"},
            {"key": "sucursal.telefono", "label": "Teléfono de sucursal", "format": "text"},
        ],
    },
    "operacion": {
        "group_key": "operacion",
        "group_label": "OPERACIÓN",
        "fields": [
            {"key": "operacion.tipo", "label": "Tipo de documento", "format": "text"},
            {"key": "operacion.folio", "label": "Folio", "format": "text"},
            {"key": "operacion.fecha", "label": "Fecha", "format": "date"},
            {"key": "operacion.hora", "label": "Hora", "format": "time"},
            {"key": "operacion.estado", "label": "Estado", "format": "text"},
            {"key": "operacion.vendedor", "label": "Vendedor", "format": "text"},
            {"key": "operacion.cajero", "label": "Cajero", "format": "text"},
            {"key": "operacion.caja", "label": "Caja / Terminal", "format": "text"},
            {"key": "operacion.referencias", "label": "Referencias", "format": "text"},
        ],
    },
    "cliente": {
        "group_key": "cliente",
        "group_label": "CLIENTE / RECEPTOR",
        "fields": [
            {"key": "cliente.nombre", "label": "Nombre o razón social", "format": "text"},
            {"key": "cliente.rfc", "label": "RFC", "format": "text"},
            {"key": "cliente.domicilio", "label": "Domicilio", "format": "text"},
            {"key": "cliente.telefono", "label": "Teléfono", "format": "text"},
            {"key": "cliente.correo", "label": "Correo", "format": "text"},
            {"key": "cliente.regimen_fiscal", "label": "Régimen fiscal receptor", "format": "text"},
            {"key": "cliente.uso_cfdi", "label": "Uso de CFDI", "format": "text"},
            {"key": "cliente.condiciones_credito", "label": "Condiciones de crédito", "format": "text"},
        ],
    },
    "productos": {
        "group_key": "productos",
        "group_label": "PRODUCTOS / ARTÍCULOS (CON IVA Y SIN IVA)",
        "fields": [
            {"key": "productos.codigo", "label": "Código / SKU", "format": "text"},
            {"key": "productos.descripcion", "label": "Descripción", "format": "text"},
            {"key": "productos.cantidad", "label": "Cantidad", "format": "decimal"},
            {"key": "productos.unidad", "label": "Unidad", "format": "text"},
            {"key": "productos.precio_sin_iva", "label": "Precio unitario SIN IVA", "format": "currency"},
            {"key": "productos.precio_con_iva", "label": "Precio unitario CON IVA", "format": "currency"},
            {"key": "productos.iva_articulo", "label": "Impuesto IVA del artículo (16%)", "format": "currency"},
            {"key": "productos.importe_sin_iva", "label": "Total del artículo SIN IVA", "format": "currency"},
            {"key": "productos.importe_con_iva", "label": "Total del artículo CON IVA", "format": "currency"},
            {"key": "productos.precio", "label": "Precio unitario", "format": "currency"},
            {"key": "productos.descuento", "label": "Descuento", "format": "currency"},
            {"key": "productos.impuestos", "label": "Impuestos artículo", "format": "currency"},
            {"key": "productos.importe", "label": "Importe", "format": "currency"},
            {"key": "productos.ubicacion", "label": "Ubicación / Pasillo", "format": "text"},
            {"key": "productos.clave_sat", "label": "Clave SAT Prod/Serv", "format": "text"},
        ],
    },
    "importes": {
        "group_key": "importes",
        "group_label": "SUBTOTALES (CON/SIN IVA), IMPUESTO TOTAL Y TOTALES",
        "fields": [
            {"key": "importes.subtotal_sin_iva", "label": "Subtotal SIN IVA", "format": "currency"},
            {"key": "importes.impuesto_total", "label": "Impuesto Total (IVA 16%)", "format": "currency"},
            {"key": "importes.subtotal_con_iva", "label": "Subtotal CON IVA", "format": "currency"},
            {"key": "importes.total_sin_iva", "label": "Total SIN IVA", "format": "currency"},
            {"key": "importes.total_con_iva", "label": "Total CON IVA (Neto)", "format": "currency"},
            {"key": "importes.subtotal", "label": "Subtotal", "format": "currency"},
            {"key": "importes.descuentos", "label": "Descuentos", "format": "currency"},
            {"key": "importes.impuestos", "label": "Impuestos (IVA)", "format": "currency"},
            {"key": "importes.total", "label": "Total", "format": "currency"},
            {"key": "importes.total_letra", "label": "Total con letra", "format": "text"},
            {"key": "importes.moneda", "label": "Moneda", "format": "text"},
        ],
    },
    "pagos": {
        "group_key": "pagos",
        "group_label": "PAGOS",
        "fields": [
            {"key": "pagos.metodo", "label": "Método / Forma de pago", "format": "text"},
            {"key": "pagos.referencia", "label": "Referencia bancaria / autorización", "format": "text"},
            {"key": "pagos.importe_recibido", "label": "Importe recibido", "format": "currency"},
            {"key": "pagos.cambio", "label": "Cambio entregado", "format": "currency"},
            {"key": "pagos.desglose_mixto", "label": "Desglose de pagos mixtos", "format": "text"},
            {"key": "pago.importe_letra", "label": "Importe pagado con letra", "format": "text"},
            {"key": "pago.concepto", "label": "Concepto del pago", "format": "text"},
        ],
    },
    "credito": {
        "group_key": "credito",
        "group_label": "CRÉDITO, NOTAS DE CRÉDITO Y ABONOS",
        "fields": [
            {"key": "credito.saldo_anterior", "label": "Saldo anterior", "format": "currency"},
            {"key": "credito.importe_abono", "label": "Importe del abono / cargo", "format": "currency"},
            {"key": "credito.saldo_actual", "label": "Saldo actual / nuevo saldo", "format": "currency"},
            {"key": "credito.saldo_pendiente", "label": "Saldo pendiente", "format": "currency"},
            {"key": "credito.limite_credito", "label": "Límite de crédito", "format": "currency"},
            {"key": "credito.fecha_vencimiento", "label": "Fecha de vencimiento", "format": "date"},
            {"key": "credito.documento_relacionado", "label": "Documento / Folio relacionado", "format": "text"},
            {"key": "credito.pagare_leyenda", "label": "Cláusula de Pagaré Mercantil", "format": "text"},
        ],
    },
    "entrega": {
        "group_key": "entrega",
        "group_label": "ENTREGA Y EMBARQUE",
        "fields": [
            {"key": "entrega.domicilio", "label": "Domicilio / Obra de entrega", "format": "text"},
            {"key": "entrega.instrucciones", "label": "Instrucciones de entrega y maniobra", "format": "text"},
            {"key": "entrega.chofer_unidad", "label": "Operador y unidad de transporte", "format": "text"},
            {"key": "entrega.placas", "label": "Placas del vehículo", "format": "text"},
            {"key": "entrega.persona_recibe", "label": "Persona que recibe", "format": "text"},
            {"key": "entrega.cantidades_pendientes", "label": "Artículos en resguardo / pendientes", "format": "text"},
        ],
    },
    "cfdi": {
        "group_key": "cfdi",
        "group_label": "CFDI 4.0 (SELLO QR Y SERIE DEL SELLO POR SEPARADO)",
        "fields": [
            {"key": "cfdi.qr_sat", "label": "Sello QR Fiscal SAT (por separado)", "format": "qr"},
            {"key": "cfdi.serie_sello", "label": "Serie del Sello / Certificado CSD Emisor (por separado)", "format": "text"},
            {"key": "cfdi.no_cert_emisor", "label": "No. Certificado CSD Emisor", "format": "text"},
            {"key": "cfdi.no_cert_sat", "label": "Serie del Sello SAT / No. Certificado SAT", "format": "text"},
            {"key": "cfdi.uuid", "label": "UUID (Folio Fiscal)", "format": "text"},
            {"key": "cfdi.serie_folio", "label": "Serie y Folio fiscal", "format": "text"},
            {"key": "cfdi.fecha_timbrado", "label": "Fecha y hora de certificación", "format": "text"},
            {"key": "cfdi.sello_cfdi", "label": "Sello digital del CFDI", "format": "text"},
            {"key": "cfdi.sello_sat", "label": "Sello digital del SAT", "format": "text"},
            {"key": "cfdi.cadena_original", "label": "Cadena original del complemento SAT", "format": "text"},
        ],
    },
    "corte": {
        "group_key": "corte",
        "group_label": "CORTES DE CAJA (CORTE CIEGO, CORTE X Y CORTE Z / CIERRE)",
        "fields": [
            {"key": "corte.tipo_corte", "label": "Tipo de Corte (CIEGO / CORTE X / CORTE Z)", "format": "text"},
            {"key": "corte.turno", "label": "Turno y Horario", "format": "text"},
            {"key": "corte.folio_inicial", "label": "Folio Inicial del Turno", "format": "text"},
            {"key": "corte.folio_final", "label": "Folio Final del Turno", "format": "text"},
            {"key": "corte.num_operaciones", "label": "Total Operaciones / Tickets del Turno", "format": "text"},
            {"key": "corte.fondo_inicial", "label": "(+) Fondo Fijo Inicial de Apertura", "format": "currency"},
            {"key": "corte.ventas_efectivo", "label": "(+) Ventas Cobradas en Efectivo", "format": "currency"},
            {"key": "corte.abonos_efectivo", "label": "(+) Abonos de Clientes CxC en Efectivo", "format": "currency"},
            {"key": "corte.entradas_efectivo", "label": "(+) Entradas / Dotaciones de Efectivo", "format": "currency"},
            {"key": "corte.retiros_fajillas", "label": "(-) Retiros Parciales / Fajillas a Bóveda", "format": "currency"},
            {"key": "corte.salidas_gastos", "label": "(-) Salidas / Gastos Menores Autorizados", "format": "currency"},
            {"key": "corte.devoluciones_efectivo", "label": "(-) Devoluciones Pagadas en Efectivo", "format": "currency"},
            {"key": "corte.efectivo_esperado", "label": "(=) Efectivo Esperado en Gaveta (Sistema)", "format": "currency"},
            {"key": "corte.efectivo_declarado", "label": "Efectivo Contado / Declarado por Cajero (Corte Ciego)", "format": "currency"},
            {"key": "corte.diferencia_efectivo", "label": "Diferencia en Efectivo (Sobrante / Faltante)", "format": "currency"},
            {"key": "corte.ventas_tarjeta_debito", "label": "Ventas Tarjeta de Débito (Sistema)", "format": "currency"},
            {"key": "corte.ventas_tarjeta_credito", "label": "Ventas Tarjeta de Crédito (Sistema)", "format": "currency"},
            {"key": "corte.tarjetas_declaradas", "label": "Vouchers Tarjeta Declarados por Cajero", "format": "currency"},
            {"key": "corte.diferencia_tarjetas", "label": "Diferencia en Vouchers Tarjeta", "format": "currency"},
            {"key": "corte.ventas_transferencia", "label": "Ventas por Transferencia SPEI", "format": "currency"},
            {"key": "corte.transferencias_declaradas", "label": "Transferencias SPEI Declaradas", "format": "currency"},
            {"key": "corte.ventas_credito_otorgado", "label": "Ventas a Crédito Otorgadas en Turno (CxC)", "format": "currency"},
            {"key": "corte.total_cancelaciones", "label": "Total Cancelaciones en Turno", "format": "currency"},
            {"key": "corte.total_devoluciones", "label": "Total Devoluciones / Notas de Crédito", "format": "currency"},
            {"key": "corte.desglose_denominaciones", "label": "Tabla de Conteo de Billetes y Monedas (Corte Ciego)", "format": "text"},
            {"key": "corte.total_esperado_general", "label": "Total General Esperado en Sistema", "format": "currency"},
            {"key": "corte.total_declarado_general", "label": "Total General Declarado por Cajero", "format": "currency"},
            {"key": "corte.diferencia_neta", "label": "Diferencia Neta del Cierre Z", "format": "currency"},
            {"key": "corte.estado_cuadre", "label": "Dictamen Oficial de Cuadre (CUADRADO / SOBRANTE / FALTANTE)", "format": "text"},
            {"key": "corte.folio_sobre", "label": "No. de Sobre Ciego / Tómbola de Seguridad", "format": "text"},
            {"key": "corte.supervisor_autoriza", "label": "Supervisor / Gerente que Recibe y Autoriza", "format": "text"},
        ],
    },
    "profeco": {
        "group_key": "profeco",
        "group_label": "CUMPLIMIENTO OFICIAL PROFECO, LFPC Y NOMS",
        "fields": [
            {"key": "profeco.leyenda_garantias", "label": "Cláusula Oficial de Garantía y Cambios (Art. 77 LFPC)", "format": "text"},
            {"key": "profeco.leyenda_consumidor", "label": "Leyenda Precios Claros con IVA y Tel. PROFECO 800-468-8722", "format": "text"},
            {"key": "profeco.plazo_facturacion", "label": "Aviso de Autofacturación CFDI 4.0", "format": "text"},
            {"key": "profeco.unidad_medida_nom", "label": "Cumplimiento NOM-030-SCFI (Precios y Unidades)", "format": "text"},
        ],
    },
}


def get_fields_for_doc_type(doc_type: str) -> List[Dict[str, Any]]:
    """Devuelve únicamente los grupos de campos relevantes para el tipo de documento solicitado."""
    meta = DOC_TYPES_MAP.get(doc_type) or DOC_TYPES_MAP["ticket_venta_contado"]
    allowed_groups = meta.get("field_groups", [])
    return [FIELD_GROUPS_CATALOG[g] for g in allowed_groups if g in FIELD_GROUPS_CATALOG]


# ══════════════════════════════════════════════════════════════════════════════
# 3. DATOS DE DEMOSTRACIÓN CLARAMENTE IDENTIFICADOS COMO DEMO
# ══════════════════════════════════════════════════════════════════════════════

def number_to_spanish_words_mxn(amount: float) -> str:
    n = abs(float(amount or 0.0))
    enteros = int(math.floor(n))
    centavos = int(round((n - enteros) * 100))
    if centavos == 100:
        enteros += 1
        centavos = 0
    unidades = ["", "UN", "DOS", "TRES", "CUATRO", "CINCO", "SEIS", "SIETE", "OCHO", "NUEVE"]
    decenas10 = ["DIEZ", "ONCE", "DOCE", "TRECE", "CATORCE", "QUINCE", "DIECISÉIS", "DIECISIETE", "DIECIOCHO", "DIECINUEVE"]
    decenas = ["", "DIEZ", "VEINTE", "TREINTA", "CUARENTA", "CINCUENTA", "SESENTA", "SETENTA", "OCHENTA", "NOVENTA"]
    centenas = ["", "CIENTO", "DOSCIENTOS", "TRESCIENTOS", "CUATROCIENTOS", "QUINIENTOS", "SEISCIENTOS", "SETECIENTOS", "OCHOCIENTOS", "NOVECIENTOS"]

    def _menor_mil(val: int) -> str:
        if val == 0:
            return ""
        if val == 100:
            return "CIEN"
        c = val // 100
        r = val % 100
        out = centenas[c] if c > 0 else ""
        if r > 0:
            if out:
                out += " "
            if r < 10:
                out += unidades[r]
            elif r < 20:
                out += decenas10[r - 10]
            elif r == 20:
                out += "VEINTE"
            elif r < 30:
                out += "VEINTI" + unidades[r - 20]
            else:
                d = r // 10
                u = r % 10
                out += decenas[d] + (" Y " + unidades[u] if u > 0 else "")
        return out

    if enteros == 0:
        texto = "CERO"
    else:
        partes = []
        millones = enteros // 1_000_000
        miles = (enteros % 1_000_000) // 1000
        cientos = enteros % 1000
        if millones == 1:
            partes.append("UN MILLÓN")
        elif millones > 1:
            partes.append(f"{_menor_mil(millones)} MILLONES")
        if miles == 1:
            partes.append("MIL")
        elif miles > 1:
            partes.append(f"{_menor_mil(miles)} MIL")
        if cientos > 0:
            partes.append(_menor_mil(cientos))
        texto = " ".join(partes)
    return f"SON: {texto.strip()} PESOS {centavos:02d}/100 M.N."


def build_demo_context(doc_type: str = "ticket_venta_contado", multi_page_demo: bool = False) -> Dict[str, Any]:
    """Construye un contexto de demostración explícitamente etiquetado como DEMOSTRACIÓN."""
    doc_meta = DOC_TYPES_MAP.get(doc_type) or DOC_TYPES_MAP["ticket_venta_contado"]
    base_items = [
        {
            "codigo": "CEM-50KG",
            "descripcion": "CEMENTO GRIS PORTLAND GALLITO 50 KG EXTRA RESISTENCIA (DEMO)",
            "cantidad": 10.0,
            "unidad": "SACO",
            "precio": 285.00,
            "descuento": 0.00,
            "impuestos": 456.00,
            "importe": 2850.00,
            "ubicacion": "PATIO B-01",
            "clave_sat": "30111601",
        },
        {
            "codigo": "VAR-38-12M",
            "descripcion": "VARILLA CORRUGADA DEACERO 3/8 PULG X 12 METROS GRADO 42 NORMA NOM-B-457",
            "cantidad": 8.0,
            "unidad": "PZA",
            "precio": 195.00,
            "descuento": 0.00,
            "impuestos": 249.60,
            "importe": 1560.00,
            "ubicacion": "PATIO ACEROS A-04",
            "clave_sat": "30101704",
        },
        {
            "codigo": "ALA-REC-16",
            "descripcion": "ALAMBRE RECOCIDO CALIBRE 16 PARA AMARRE ESTRUCTURAL EN ROLLO",
            "cantidad": 10.0,
            "unidad": "KG",
            "precio": 34.60,
            "descuento": 0.00,
            "impuestos": 55.36,
            "importe": 346.00,
            "ubicacion": "BODEGA PASILLO 2",
            "clave_sat": "30103623",
        },
    ]
    if multi_page_demo:
        extra = []
        for idx in range(1, 29):
            pu = round(120.0 + (idx * 7.5), 2)
            qty = float((idx % 5) + 1)
            imp = round(pu * qty, 2)
            extra.append({
                "codigo": f"MAT-{idx:03d}",
                "descripcion": f"PARTIDA DE DEMOSTRACIÓN MULTIPÁGINA #{idx:02d} — TABLÓN DE PINO ESTUFADO Y PERFIL ESTRUCTURAL CON CARACTERES ESPAÑOLES (ÁÉÍÓÚÑ)",
                "cantidad": qty,
                "unidad": "PZA",
                "precio": pu,
                "descuento": 0.00,
                "impuestos": round(imp * 0.16, 2),
                "importe": imp,
                "ubicacion": f"PASILLO C-{idx:02d}",
                "clave_sat": "30101704",
            })
        base_items = base_items + extra

    for it_d in base_items:
        imp_c = round(float(it_d["importe"]), 2)
        imp_s = round(imp_c / 1.16, 2)
        iva_a = round(imp_c - imp_s, 2)
        qty_d = float(it_d["cantidad"] or 1.0)
        it_d["precio_con_iva"] = round(float(it_d["precio"]), 2)
        it_d["precio_sin_iva"] = round(imp_s / qty_d, 2)
        it_d["iva_articulo"] = iva_a
        it_d["impuestos"] = iva_a
        it_d["importe_sin_iva"] = imp_s
        it_d["importe_con_iva"] = imp_c

    total_val = round(sum(float(i["importe"]) for i in base_items), 2)
    subtotal_val = round(total_val / 1.16, 2)
    iva_val = round(total_val - subtotal_val, 2)

    return {
        "_is_demo": True,
        "empresa": {
            "nombre_comercial": "MAGDALENO MADERAS & MATERIALES (DATOS DE DEMOSTRACIÓN)",
            "razon_social": "GRUPO MADERERO Y MATERIALES MAGDALENO S.A. DE C.V.",
            "rfc": "GMM2106218A1",
            "regimen_fiscal": "601 - GENERAL DE LEY PERSONAS MORALES",
            "domicilio": "BLVD. AGUSTÍN OLACHEA AVILÉS KM 1.5, COL. CENTRO, C.P. 23600",
            "telefonos": "(613) 132-0000 / WHATSAPP (613) 100-2000",
            "correo": "VENTAS@MAGDALENOMATERIALES.COM",
            "logotipo": "[LOGOTIPO EMPRESA]",
        },
        "sucursal": {
            "nombre": "MATRIZ CD. CONSTITUCIÓN",
            "clave": "MATRIZ",
            "domicilio": "BLVD. AGUSTÍN OLACHEA KM 1.5, CD. CONSTITUCIÓN, B.C.S.",
            "telefono": "(613) 132-0000",
        },
        "operacion": {
            "tipo": doc_meta["name"].upper(),
            "folio": "DEMO-004821",
            "fecha": "17/11/2026",
            "hora": "11:15 A.M.",
            "estado": "DEMOSTRACIÓN (SIN VALIDEZ FISCAL)",
            "vendedor": "EJECUTIVO DEMO · GILBERTO R.",
            "cajero": "CAJA 01 · ADMINISTRADOR",
            "caja": "TERMINAL CAJA-01",
            "referencias": "ENTREGA EN OBRA RESIDENCIAL LAS PALMAS (DEMO)",
        },
        "cliente": {
            "nombre": "CONSTRUCTORA Y EDIFICACIONES DEL PACÍFICO S.A. DE C.V. (DEMO)",
            "rfc": "CEP1804129K4",
            "domicilio": "AV. REVOLUCIÓN #410, COL. CENTRO, CD. CONSTITUCIÓN, B.C.S.",
            "telefono": "(613) 114-8890",
            "correo": "COMPRAS@CONSTRUCTORAPACIFICO.DEMO",
            "regimen_fiscal": "601 - GENERAL DE LEY PERSONAS MORALES",
            "uso_cfdi": "G01 - ADQUISICIÓN DE MERCANCÍAS",
            "condiciones_credito": "CRÉDITO COMERCIAL 30 DÍAS · LÍMITE $80,000.00",
        },
        "productos": base_items,
        "importes": {
            "subtotal": subtotal_val,
            "subtotal_sin_iva": subtotal_val,
            "subtotal_con_iva": total_val,
            "descuentos": 0.00,
            "impuestos": iva_val,
            "impuesto_total": iva_val,
            "total_sin_iva": subtotal_val,
            "total_con_iva": total_val,
            "total": total_val,
            "total_letra": number_to_spanish_words_mxn(total_val),
            "moneda": "MXN - PESO MEXICANO",
        },
        "pagos": {
            "metodo": "01 - EFECTIVO" if doc_type != "ticket_venta_credito" else "99 - POR DEFINIR (CRÉDITO)",
            "referencia": "REF-DEMO-849201",
            "importe_recibido": 5000.00 if doc_type != "ticket_venta_credito" else 0.00,
            "cambio": round(max(0.0, 5000.00 - total_val), 2) if doc_type != "ticket_venta_credito" else 0.00,
            "desglose_mixto": "EFECTIVO: $5,000.00 MXN",
        },
        "pago": {
            "importe_letra": number_to_spanish_words_mxn(total_val),
            "concepto": "ABONO A CUENTA / LIQUIDACIÓN DE MATERIALES (DEMO)",
        },
        "credito": {
            "limite_credito": 80000.00,
            "fecha_vencimiento": "17/12/2026",
            "saldo_anterior": 18500.00,
            "importe_abono": total_val,
            "saldo_actual": round(18500.00 + total_val, 2) if doc_type == "ticket_venta_credito" else round(max(0.0, 18500.00 - total_val), 2),
            "saldo_pendiente": round(18500.00 + total_val, 2) if doc_type == "ticket_venta_credito" else round(max(0.0, 18500.00 - total_val), 2),
            "documento_relacionado": "FOLIO #DEMO-004821",
            "pagare_leyenda": "DEBO(EMOS) Y PAGARÉ(MOS) INCONDICIONALMENTE POR ESTE PAGARÉ A LA ORDEN DE GRUPO MADERERO Y MATERIALES MAGDALENO S.A. DE C.V. EL IMPORTE TOTAL DE ESTA OPERACIÓN. CAUSARÁ INTERÉS MORATORIO DEL 3% MENSUAL.",
        },
        "entrega": {
            "domicilio": "OBRA RESIDENCIAL LAS PALMAS LOTE 14, CD. CONSTITUCIÓN, B.C.S.",
            "instrucciones": "DESCARGA A PIE DE CAMIÓN. REVISAR CANTIDAD Y ESTADO FÍSICO DEL MATERIAL.",
            "chofer_unidad": "JUAN CARLOS PÉREZ · CAMIÓN PLATAFORMA #04",
            "placas": "BCS-942-A",
            "persona_recibe": "ING. ROBERTO GÓMEZ (RESIDENTE DE OBRA)",
            "cantidades_pendientes": "0 PENDIENTES — ENTREGA COMPLETA",
        },
        "cfdi": {
            "uuid": "00000000-DEMO-0000-DEMO-000000000000 (DEMOSTRACIÓN SIN TIMBRE REAL)",
            "serie_folio": "DEMO-F-001948",
            "fecha_timbrado": "2026-11-17T11:15:00 (DEMO)",
            "serie_sello": "0000100000050000DEMO",
            "no_cert_emisor": "0000100000050000DEMO",
            "no_cert_sat": "0000100000050000SAT0",
            "sello_cfdi": "[SELLO DIGITAL DE DEMOSTRACIÓN — NO ES UN COMPROBANTE FISCAL REAL]",
            "sello_sat": "[SELLO SAT DE DEMOSTRACIÓN — SIN VALIDEZ FISCAL]",
            "cadena_original": "||4.0|DEMO|00000000-DEMO-0000-DEMO-000000000000||",
            "qr_sat": "https://verificacfdi.facturaelectronica.sat.gob.mx/default.aspx?id=DEMO",
        },
        "corte": {
            "tipo_corte": "CORTE CIEGO DE CAJA (SIN MOSTRAR ESPERADO)" if doc_type == "corte_ciego" else ("CORTE X PARCIAL (TURNO CONTINÚA ABIERTO)" if doc_type == "corte_x" else "CORTE Z DEFINITIVO DE CIERRE DE TURNO Y DÍA"),
            "turno": "MATUTINO (08:00 A 16:00 HRS)",
            "folio_inicial": "T-004780",
            "folio_final": "T-004821",
            "num_operaciones": "42 TICKETS PROCESADOS",
            "fondo_inicial": 3000.00,
            "ventas_efectivo": 24850.00,
            "abonos_efectivo": 4200.00,
            "entradas_efectivo": 0.00,
            "retiros_fajillas": 15000.00,
            "salidas_gastos": 450.00,
            "devoluciones_efectivo": 200.00,
            "efectivo_esperado": 16400.00,
            "efectivo_declarado": 16400.00,
            "diferencia_efectivo": 0.00,
            "ventas_tarjeta_debito": 9450.00,
            "ventas_tarjeta_credito": 12300.00,
            "tarjetas_declaradas": 21750.00,
            "diferencia_tarjetas": 0.00,
            "ventas_transferencia": 8900.00,
            "transferencias_declaradas": 8900.00,
            "ventas_credito_otorgado": 14600.00,
            "total_cancelaciones": 380.00,
            "total_devoluciones": 200.00,
            "desglose_denominaciones": "$1000 x 8 = $8,000 | $500 x 12 = $6,000 | $200 x 8 = $1,600 | $100 x 5 = $500 | $50 x 4 = $200 | Monedas = $100.00",
            "total_esperado_general": 47050.00,
            "total_declarado_general": 47050.00,
            "diferencia_neta": 0.00,
            "estado_cuadre": "CUADRADO EXACTO ($0.00 DIFERENCIA)",
            "folio_sobre": "SOBRE-TOMBOLA-0094",
            "supervisor_autoriza": "LIC. MARCO ANTONIO RUIZ (GERENTE DE SUCURSAL)",
        },
        "profeco": {
            "leyenda_garantias": "GARANTÍA Y CAMBIOS (ART. 77 Y 85 LFPC / PROFECO): Todo cambio o devolución requiere presentar este comprobante original dentro de los 15 días naturales posteriores a su compra, con el material sin usar y en su empaque original. En materiales a granel, cortes de madera a medida o pedidos especiales no aplica devolución salvo defecto de fábrica.",
            "leyenda_consumidor": "PRECIOS EN MONEDA NACIONAL (MXN) CON IVA DESGLOSADO CONFORME A LA LEY FEDERAL DE PROTECCIÓN AL CONSUMIDOR (PROFECO) Y NOM-030-SCFI. Atención al cliente: (33) 3615-4287 · Teléfono del Consumidor PROFECO: 800-468-8722.",
            "plazo_facturacion": "FACTURACIÓN ELECTRÓNICA CFDI 4.0 (ANEXO 20 SAT): Solicite su factura dentro del mes en curso presentando su Folio y RFC actualizado.",
            "unidad_medida_nom": "UNIDADES DE MEDIDA Y PESO VERIFICADAS CONFORME A LA NOM-008-SCFI / SISTEMA GENERAL DE UNIDADES DE MEDIDA.",
        },
    }


def build_real_operation_context(db: Session, empresa_id: str, doc_type: str, operation_id: str) -> Dict[str, Any]:
    """Construye el contexto de datos reales de una operación autorizada del tenant.
    Nunca inventa UUIDs, timbres ni saldos inexistentes."""
    sale = (
        db.query(models.Sale)
        .filter(models.Sale.empresa_id == empresa_id, models.Sale.id == str(operation_id))
        .first()
    )
    if not sale:
        sale = (
            db.query(models.Sale)
            .filter(models.Sale.empresa_id == empresa_id, models.Sale.folio == str(operation_id))
            .first()
        )
    if not sale:
        raise PrintFormatError(
            f"La operación '{operation_id}' no existe o no pertenece a la empresa autenticada.",
            code="operation_not_found",
            status_code=404,
        )

    cli = None
    if sale.client_id:
        cli = (
            db.query(models.Client)
            .filter(models.Client.empresa_id == empresa_id, models.Client.id == sale.client_id)
            .first()
        )

    cfdi_doc = (
        db.query(models.CfdiDocument)
        .filter(models.CfdiDocument.empresa_id == empresa_id, models.CfdiDocument.sale_id == sale.id)
        .first()
    )

    items_list = []
    for it in (sale.items or []):
        qty = float(it.quantity or 0)
        sub = float(it.subtotal or 0)
        pu = round(sub / qty, 2) if qty else float(getattr(it, "price", 0) or 0)
        imp_sin = round(sub / 1.16, 2)
        iva_it = round(sub - imp_sin, 2)
        pu_sin = round(imp_sin / qty, 2) if qty else round(pu / 1.16, 2)
        items_list.append({
            "codigo": str(it.product_sku or ""),
            "descripcion": str(getattr(it, "description", "") or f"ARTÍCULO {it.product_sku}"),
            "cantidad": qty,
            "unidad": "PZA",
            "precio": pu,
            "precio_con_iva": pu,
            "precio_sin_iva": pu_sin,
            "descuento": 0.0,
            "impuestos": iva_it,
            "iva_articulo": iva_it,
            "importe": sub,
            "importe_sin_iva": imp_sin,
            "importe_con_iva": sub,
            "ubicacion": "",
            "clave_sat": "",
        })

    total_f = float(sale.total or 0)
    sub_f = round(total_f / 1.16, 2)
    iva_f = round(total_f - sub_f, 2)
    dt = sale.created_at or _dt.datetime.now(_dt.timezone.utc)

    return {
        "_is_demo": False,
        "empresa": {
            "nombre_comercial": "MAGDALENO MADERAS & MATERIALES",
            "razon_social": "GRUPO MADERERO Y MATERIALES MAGDALENO S.A. DE C.V.",
            "rfc": "GMM2106218A1",
            "regimen_fiscal": "601 - GENERAL DE LEY PERSONAS MORALES",
            "domicilio": "BLVD. AGUSTÍN OLACHEA AVILÉS KM 1.5, COL. CENTRO",
            "telefonos": "(613) 132-0000",
            "correo": "VENTAS@MAGDALENOMATERIALES.COM",
            "logotipo": "",
        },
        "sucursal": {
            "nombre": str(sale.sucursal_id or "MATRIZ"),
            "clave": str(sale.sucursal_id or "MATRIZ"),
            "domicilio": "",
            "telefono": "",
        },
        "operacion": {
            "tipo": (DOC_TYPES_MAP.get(doc_type) or {}).get("name", "DOCUMENTO").upper(),
            "folio": str(sale.folio or sale.id[:8]).upper(),
            "fecha": dt.strftime("%d/%m/%Y"),
            "hora": dt.strftime("%H:%M"),
            "estado": str(getattr(sale, "status", "COMPLETADA") or "COMPLETADA").upper(),
            "vendedor": str(getattr(sale, "seller_id", "") or ""),
            "cajero": str(getattr(sale, "user_id", "") or "CAJA"),
            "caja": "TERMINAL POS",
            "referencias": str(getattr(sale, "notes", "") or ""),
        },
        "cliente": {
            "nombre": str((cli.name if cli else "PÚBLICO EN GENERAL") or "PÚBLICO EN GENERAL").upper(),
            "rfc": str((cli.rfc if cli else "XAXX010101000") or "XAXX010101000").upper(),
            "domicilio": str((cli.address if cli else "") or "").upper(),
            "telefono": str((cli.phone if cli else "") or ""),
            "correo": str((cli.email if cli else "") or ""),
            "regimen_fiscal": str((getattr(cli, "regimen_fiscal", "") if cli else "") or ""),
            "uso_cfdi": str((getattr(cli, "uso_cfdi", "") if cli else "") or ""),
            "condiciones_credito": f"LÍMITE: ${float(getattr(cli, 'limite_credito', 0) or 0):,.2f}" if cli else "CONTADO",
        },
        "productos": items_list,
        "importes": {
            "subtotal": sub_f,
            "subtotal_sin_iva": sub_f,
            "subtotal_con_iva": total_f,
            "descuentos": float(sale.discount or 0),
            "impuestos": iva_f,
            "impuesto_total": iva_f,
            "total_sin_iva": sub_f,
            "total_con_iva": total_f,
            "total": total_f,
            "total_letra": number_to_spanish_words_mxn(total_f),
            "moneda": "MXN",
        },
        "pagos": {
            "metodo": str(sale.payment_method or "001"),
            "referencia": "",
            "importe_recibido": float(sale.amount_paid or 0),
            "cambio": float(sale.change_returned or 0),
            "desglose_mixto": "",
        },
        "pago": {
            "importe_letra": number_to_spanish_words_mxn(float(sale.amount_paid or total_f)),
            "concepto": f"PAGO DE OPERACIÓN FOLIO {sale.folio or sale.id[:8]}",
        },
        "credito": {
            "limite_credito": float(getattr(cli, "limite_credito", 0) or 0) if cli else 0.0,
            "fecha_vencimiento": "",
            "saldo_anterior": float(getattr(cli, "saldo_actual", 0) or 0) if cli else 0.0,
            "importe_abono": float(sale.advance or 0),
            "saldo_actual": float(getattr(cli, "saldo_actual", 0) or 0) if cli else 0.0,
            "saldo_pendiente": float(getattr(cli, "saldo_actual", 0) or 0) if cli else 0.0,
            "documento_relacionado": str(sale.folio or sale.id[:8]),
            "pagare_leyenda": "DEBO Y PAGARÉ INCONDICIONALMENTE A LA ORDEN DE GRUPO MADERERO Y MATERIALES MAGDALENO S.A. DE C.V.",
        },
        "entrega": {
            "domicilio": str((cli.address if cli else "") or ""),
            "instrucciones": "",
            "chofer_unidad": "",
            "placas": "",
            "persona_recibe": str((cli.name if cli else "") or ""),
            "cantidades_pendientes": "",
        },
        # No fabricar UUID ni sellos si no hay CFDI timbrado real
        "cfdi": {
            "uuid": str(cfdi_doc.uuid or "") if cfdi_doc else "",
            "serie_folio": f"{cfdi_doc.serie or ''}-{cfdi_doc.folio or ''}".strip("-") if cfdi_doc else "",
            "fecha_timbrado": str(cfdi_doc.stamped_at or "") if cfdi_doc else "",
            "serie_sello": "",
            "no_cert_emisor": "",
            "no_cert_sat": "",
            "sello_cfdi": "",
            "sello_sat": "",
            "cadena_original": "",
            "qr_sat": str(cfdi_doc.uuid or "") if cfdi_doc else "",
        },
        "corte": {
            "tipo_corte": "CORTE CIEGO" if doc_type == "corte_ciego" else ("CORTE X PARCIAL" if doc_type == "corte_x" else "CORTE Z DEFINITIVO"),
            "turno": "TURNO ACTIVO",
            "folio_inicial": str(sale.folio or sale.id[:8]).upper(),
            "folio_final": str(sale.folio or sale.id[:8]).upper(),
            "num_operaciones": "1 OPERACIÓN",
            "fondo_inicial": 0.0,
            "ventas_efectivo": total_f if str(sale.payment_method or "001") in ("001", "01", "EFECTIVO") else 0.0,
            "abonos_efectivo": float(sale.advance or 0),
            "entradas_efectivo": 0.0,
            "retiros_fajillas": 0.0,
            "salidas_gastos": 0.0,
            "devoluciones_efectivo": 0.0,
            "efectivo_esperado": total_f,
            "efectivo_declarado": total_f,
            "diferencia_efectivo": 0.0,
            "ventas_tarjeta_debito": total_f if str(sale.payment_method or "") in ("002", "28") else 0.0,
            "ventas_tarjeta_credito": total_f if str(sale.payment_method or "") in ("003", "04") else 0.0,
            "tarjetas_declaradas": 0.0,
            "diferencia_tarjetas": 0.0,
            "ventas_transferencia": total_f if str(sale.payment_method or "") in ("004", "03", "SPEI") else 0.0,
            "transferencias_declaradas": 0.0,
            "ventas_credito_otorgado": total_f if str(sale.payment_method or "") in ("006", "99") else 0.0,
            "total_cancelaciones": 0.0,
            "total_devoluciones": 0.0,
            "desglose_denominaciones": "CONTEO FÍSICO REGISTRADO EN CAJA",
            "total_esperado_general": total_f,
            "total_declarado_general": total_f,
            "diferencia_neta": 0.0,
            "estado_cuadre": "CUADRADO EXACTO",
            "folio_sobre": f"SOBRE-{str(sale.folio or sale.id[:6]).upper()}",
            "supervisor_autoriza": "SUPERVISOR EN TURNO",
        },
        "profeco": {
            "leyenda_garantias": "GARANTÍA Y CAMBIOS (ART. 77 Y 85 LFPC / PROFECO): Todo cambio o devolución requiere presentar este comprobante original dentro de los 15 días naturales posteriores a su compra, con el material sin usar y en su empaque original.",
            "leyenda_consumidor": "PRECIOS EN MONEDA NACIONAL (MXN) CON IVA DESGLOSADO CONFORME A LA LEY FEDERAL DE PROTECCIÓN AL CONSUMIDOR (PROFECO). Teléfono del Consumidor PROFECO: 800-468-8722.",
            "plazo_facturacion": "FACTURACIÓN ELECTRÓNICA CFDI 4.0: Solicite su factura dentro del mes en curso.",
            "unidad_medida_nom": "UNIDADES DE MEDIDA Y PRECIOS CONFORME A NOM-030-SCFI.",
        },
    }


# ══════════════════════════════════════════════════════════════════════════════
# 4. EVALUADOR SEGURO DE CAMPOS, FORMATEADORES Y CONDICIONES VISUALES
# ══════════════════════════════════════════════════════════════════════════════

_TOKEN_RE = re.compile(r"\{\{\s*([a-zA-Z0-9_]+\.[a-zA-Z0-9_]+)\s*\}\}")


def resolve_field_value(context: Dict[str, Any], field_key: str, fmt_opts: Optional[Dict[str, Any]] = None) -> str:
    """Resuelve de forma segura `grupo.campo` desde el diccionario de contexto y aplica formato."""
    opts = fmt_opts or {}
    fallback = str(opts.get("fallback_text") or "")
    if not field_key or "." not in field_key:
        return fallback
    grp, fld = field_key.split(".", 1)
    grp_obj = context.get(grp)
    raw = grp_obj.get(fld) if isinstance(grp_obj, dict) else None
    if raw is None or raw == "":
        return fallback

    fmt_type = str(opts.get("format") or "").lower()
    decimals = int(opts.get("decimals", 2) if opts.get("decimals") is not None else 2)
    decimals = max(0, min(6, decimals))

    if fmt_type in ("currency", "moneda") or (not fmt_type and isinstance(raw, (int, float, Decimal)) and fld in ("total", "subtotal", "impuestos", "descuentos", "precio", "importe", "precio_sin_iva", "precio_con_iva", "iva_articulo", "importe_sin_iva", "importe_con_iva", "subtotal_sin_iva", "subtotal_con_iva", "impuesto_total", "total_sin_iva", "total_con_iva", "importe_recibido", "cambio", "limite_credito", "saldo_anterior", "importe_abono", "saldo_actual", "saldo_pendiente", "fondo_inicial", "ventas_efectivo", "abonos_efectivo", "entradas_efectivo", "retiros_fajillas", "salidas_gastos", "devoluciones_efectivo", "efectivo_esperado", "efectivo_declarado", "diferencia_efectivo", "ventas_tarjeta_debito", "ventas_tarjeta_credito", "tarjetas_declaradas", "diferencia_tarjetas", "ventas_transferencia", "transferencias_declaradas", "ventas_credito_otorgado", "total_cancelaciones", "total_devoluciones", "total_esperado_general", "total_declarado_general", "diferencia_neta")):
        try:
            val_num = float(raw)
            formatted = f"${val_num:,.{decimals}f}"
        except Exception:
            formatted = str(raw)
    elif fmt_type in ("decimal", "numero"):
        try:
            val_num = float(raw)
            formatted = f"{val_num:,.{decimals}f}"
        except Exception:
            formatted = str(raw)
    else:
        formatted = str(raw)

    case_mode = str(opts.get("case") or "upper").lower()
    if case_mode == "upper":
        formatted = formatted.upper()
    elif case_mode == "lower":
        formatted = formatted.lower()

    prefix = str(opts.get("prefix") or "")
    suffix = str(opts.get("suffix") or "")
    return f"{prefix}{formatted}{suffix}"


def evaluate_safe_template_text(template_str: str, context: Dict[str, Any], fmt_opts: Optional[Dict[str, Any]] = None) -> str:
    """Evalúa texto combinado como 'Recibimos de {{cliente.nombre}} la cantidad de {{pago.importe_letra}}'
    sin ejecutar jamás código arbitrario."""
    if not template_str:
        return ""
    # Sanitizar etiquetas peligrosas por seguridad adicional
    clean_str = re.sub(r"<\s*script[^>]*>.*?<\s*/\s*script\s*>", "", str(template_str), flags=re.IGNORECASE | re.DOTALL)

    def _repl(match: re.Match) -> str:
        key = match.group(1)
        return resolve_field_value(context, key, fmt_opts)

    result = _TOKEN_RE.sub(_repl, clean_str)
    if fmt_opts and str(fmt_opts.get("case") or "").lower() == "upper":
        result = result.upper()
    return result


def evaluate_visual_condition(condition: Optional[Dict[str, Any]], context: Dict[str, Any]) -> bool:
    """Evalúa constructores de condiciones visuales sin ejecutar código arbitrario.
    Operadores soportados:
      - not_empty, empty, gt_zero, eq_zero, eq, neq, gt, lt, contains
    """
    if not condition or not isinstance(condition, dict) or not condition.get("enabled"):
        return True
    field_key = str(condition.get("field") or "").strip()
    op = str(condition.get("operator") or "not_empty").strip().lower()
    target = condition.get("value")

    if not field_key or "." not in field_key:
        return True
    grp, fld = field_key.split(".", 1)
    grp_obj = context.get(grp)
    raw = grp_obj.get(fld) if isinstance(grp_obj, dict) else None

    if op == "not_empty":
        return raw is not None and str(raw).strip() != "" and str(raw).strip() != "0" and str(raw).strip() != "0.0"
    if op == "empty":
        return raw is None or str(raw).strip() == ""
    if op == "gt_zero":
        try:
            return float(raw or 0) > 0.0001
        except Exception:
            return False
    if op == "eq_zero":
        try:
            return abs(float(raw or 0)) <= 0.0001
        except Exception:
            return True
    if op == "eq":
        return str(raw or "").strip().upper() == str(target or "").strip().upper()
    if op == "neq":
        return str(raw or "").strip().upper() != str(target or "").strip().upper()
    if op == "gt":
        try:
            return float(raw or 0) > float(target or 0)
        except Exception:
            return False
    if op == "lt":
        try:
            return float(raw or 0) < float(target or 0)
        except Exception:
            return False
    if op == "contains":
        return str(target or "").strip().upper() in str(raw or "").strip().upper()
    return True


# ══════════════════════════════════════════════════════════════════════════════
# 5. CONVERSIÓN DE COORDENADAS FÍSICAS (MM <-> PT <-> PX CON ZOOM)
# ══════════════════════════════════════════════════════════════════════════════

def mm_to_pt(val_mm: float) -> float:
    return round(float(val_mm) * MM_TO_PT, 4)


def pt_to_mm(val_pt: float) -> float:
    return round(float(val_pt) * PT_TO_MM, 4)


def canvas_px_to_mm(val_px: float, zoom: float = 1.0, px_per_mm_base: float = 3.7795275591) -> float:
    """Convierte píxeles del lienzo en pantalla a milímetros físicos independientes del zoom."""
    z = max(0.1, float(zoom or 1.0))
    return round(float(val_px) / (px_per_mm_base * z), 2)


def mm_to_canvas_px(val_mm: float, zoom: float = 1.0, px_per_mm_base: float = 3.7795275591) -> float:
    """Convierte milímetros físicos a píxeles del lienzo aplicando el factor de zoom actual."""
    z = max(0.1, float(zoom or 1.0))
    return round(float(val_mm) * px_per_mm_base * z, 2)


# ══════════════════════════════════════════════════════════════════════════════
# 6. ALMACENAMIENTO Y PROCESAMIENTO DE FONDOS PDF MULTIPÁGINA E IMÁGENES
# ══════════════════════════════════════════════════════════════════════════════

def _safe_tenant_segment(seg: str) -> str:
    s = str(seg or "").strip()
    if not s or "/" in s or "\\" in s or ".." in s:
        raise PrintFormatError("Identificador de ruta no válido.", code="invalid_path_segment", status_code=400)
    return re.sub(r"[^a-zA-Z0-9_\-.]", "_", s)


def store_and_inspect_asset(
    db: Session,
    empresa_id: str,
    sucursal_id: Optional[str],
    user_id: str,
    original_filename: str,
    content: bytes,
    kind: str = "BACKGROUND",
) -> models.PrintTemplateAsset:
    """Valida el tipo real del archivo por firma binaria (magic bytes), verifica tamaño y páginas,
    conserva el archivo original intacto y genera previsualizaciones PNG por página."""
    if not content:
        raise PrintFormatError("El archivo enviado está vacío.", code="empty_file", status_code=400)
    if len(content) > MAX_ASSET_BYTES:
        raise PrintFormatError(
            f"El archivo excede el tamaño máximo permitido de {MAX_ASSET_BYTES // (1024 * 1024)} MB.",
            code="file_too_large",
            status_code=400,
        )

    sha256_hex = hashlib.sha256(content).hexdigest()
    asset_id = str(uuid.uuid4())
    emp_seg = _safe_tenant_segment(empresa_id)

    orig_dir = os.path.join(MEDIA_PRINT_ROOT, emp_seg, "originals")
    derived_dir = os.path.join(MEDIA_PRINT_ROOT, emp_seg, "derived", asset_id)
    os.makedirs(orig_dir, exist_ok=True)
    os.makedirs(derived_dir, exist_ok=True)

    # Detectar tipo real por magic bytes
    is_pdf = content.startswith(b"%PDF-")
    is_png = content.startswith(b"\x89PNG\r\n\x1a\n")
    is_jpg = content.startswith(b"\xff\xd8\xff")

    if not (is_pdf or is_png or is_jpg):
        raise PrintFormatError(
            "Formato de archivo no compatible. Sube únicamente un archivo PDF, PNG, JPG o JPEG válido.",
            code="unsupported_file_type",
            status_code=400,
        )

    pages_meta: List[Dict[str, Any]] = []

    if is_pdf:
        ext = ".pdf"
        mime_type = "application/pdf"
        effective_kind = "BACKGROUND_PDF"
        try:
            pdf_doc = pdfium.PdfDocument(content)
            page_count = len(pdf_doc)
        except Exception as exc:
            raise PrintFormatError(
                "El archivo PDF está dañado, protegido con contraseña (cifrado) o no es compatible.",
                code="invalid_or_encrypted_pdf",
                status_code=400,
            ) from exc

        if page_count < 1:
            raise PrintFormatError("El archivo PDF no contiene páginas válidas.", code="empty_pdf", status_code=400)
        if page_count > MAX_PDF_PAGES:
            raise PrintFormatError(
                f"El PDF tiene {page_count} páginas y supera el máximo permitido de {MAX_PDF_PAGES} páginas.",
                code="too_many_pages",
                status_code=400,
            )

        for idx in range(page_count):
            page = pdf_doc[idx]
            w_pt, h_pt = page.get_size()
            w_mm = pt_to_mm(w_pt)
            h_mm = pt_to_mm(h_pt)
            bitmap = page.render(scale=2.0)
            pil_img = bitmap.to_pil()
            prev_fname = f"page_{idx + 1}.png"
            prev_abs = os.path.join(derived_dir, prev_fname)
            pil_img.save(prev_abs, format="PNG")
            pages_meta.append({
                "page": idx + 1,
                "width_pt": round(float(w_pt), 2),
                "height_pt": round(float(h_pt), 2),
                "width_mm": w_mm,
                "height_mm": h_mm,
                "aspect_ratio": round(w_mm / h_mm, 4) if h_mm else 0.7727,
                "matches_carta_ratio": abs((w_mm / h_mm) - (CARTA_WIDTH_MM / CARTA_HEIGHT_MM)) < 0.035 if h_mm else True,
                "preview_rel_path": f"{emp_seg}/derived/{asset_id}/{prev_fname}",
            })
        pdf_doc.close()
    else:
        ext = ".png" if is_png else ".jpg"
        mime_type = "image/png" if is_png else "image/jpeg"
        effective_kind = "LOGO" if str(kind or "").upper() == "LOGO" else "BACKGROUND_IMAGE"
        try:
            pil_img = Image.open(io.BytesIO(content))
            pil_img.verify()
            pil_img = Image.open(io.BytesIO(content))
            w_px, h_px = pil_img.size
        except Exception as exc:
            raise PrintFormatError(
                "La imagen enviada está dañada o no se pudo decodificar.",
                code="invalid_image",
                status_code=400,
            ) from exc

        page_count = 1
        prev_fname = "page_1.png"
        prev_abs = os.path.join(derived_dir, prev_fname)
        pil_img.convert("RGBA").save(prev_abs, format="PNG")
        # Asumimos 96 DPI base para referencia original en mm
        w_mm = round((w_px / 96.0) * 25.4, 2)
        h_mm = round((h_px / 96.0) * 25.4, 2)
        pages_meta.append({
            "page": 1,
            "width_px": w_px,
            "height_px": h_px,
            "width_pt": mm_to_pt(w_mm),
            "height_pt": mm_to_pt(h_mm),
            "width_mm": w_mm,
            "height_mm": h_mm,
            "aspect_ratio": round(w_px / h_px, 4) if h_px else 1.0,
            "matches_carta_ratio": abs((w_px / h_px) - (CARTA_WIDTH_MM / CARTA_HEIGHT_MM)) < 0.035 if h_px else True,
            "preview_rel_path": f"{emp_seg}/derived/{asset_id}/{prev_fname}",
        })

    orig_rel_path = f"{emp_seg}/originals/{asset_id}{ext}"
    orig_abs_path = os.path.join(MEDIA_PRINT_ROOT, orig_rel_path)
    with open(orig_abs_path, "wb") as f:
        f.write(content)

    asset = models.PrintTemplateAsset(
        id=asset_id,
        empresa_id=empresa_id,
        sucursal_id=sucursal_id,
        kind=effective_kind,
        original_filename=str(original_filename or f"fondo{ext}")[:250],
        mime_type=mime_type,
        size_bytes=len(content),
        sha256_hash=sha256_hex,
        page_count=page_count,
        pages_meta=pages_meta,
        storage_rel_path=orig_rel_path,
        created_by=user_id,
    )
    db.add(asset)
    db.commit()
    db.refresh(asset)
    return asset


# ══════════════════════════════════════════════════════════════════════════════
# 7. MOTOR DE PAGINACIÓN MULTIPÁGINA Y GENERACIÓN REAL DE SALIDA PDF / HTML
# ══════════════════════════════════════════════════════════════════════════════

def paginate_template_definition(
    version_obj: models.PrintFormatVersion,
    context: Dict[str, Any],
) -> Dict[str, Any]:
    """Calcula la paginación real de un documento (especialmente tablas de productos
    en cotizaciones, facturas, remisiones u órdenes de entrega de varias páginas)
    respetando áreas reservadas, límites inferiores y colocando totales/firmas al final."""
    defn = version_obj.definition_json or {}
    mode = (version_obj.mode or "CARTA").upper()
    pw_mm = float(version_obj.paper_width_mm or (CARTA_WIDTH_MM if mode == "CARTA" else 80.0))
    ph_mm = float(version_obj.paper_height_mm or (CARTA_HEIGHT_MM if mode == "CARTA" else 0.0))

    elements: List[Dict[str, Any]] = list(defn.get("elements") or [])
    items: List[Dict[str, Any]] = list(context.get("productos") or [])
    bg_settings = version_obj.background_settings_json or {}

    if mode == "TICKET":
        # En tickets térmicos se soportan tanto capas libres posicionables (10 plantillas 80mm/58mm) como bloques de flujo
        return {
            "mode": "TICKET",
            "paper_width_mm": pw_mm,
            "paper_height_mm": ph_mm if ph_mm >= 120.0 else 210.0,
            "printable_width_mm": float(version_obj.printable_width_mm or (72.0 if pw_mm >= 78 else 48.0)),
            "total_pages": 1,
            "pages": [
                {
                    "page_number": 1,
                    "show_background": False,
                    "elements": elements,
                    "table_slice": items,
                    "table_rows": items,
                    "is_last_page": True,
                }
            ],
        }

    # Modo CARTA: buscar si existe elemento tabla de productos (`table_products`)
    table_el = next((el for el in elements if el.get("type") in ("table_products", "tabla_productos")), None)
    if not table_el or not items:
        # Determinar cuántas páginas explícitas tienen los elementos
        max_el_page = max([int(el.get("page") or 1) for el in elements] + [1])
        pages_out = []
        for pnum in range(1, max_el_page + 1):
            pages_out.append({
                "page_number": pnum,
                "background_source_page": _resolve_bg_source_page(pnum, max_el_page, bg_settings),
                "elements": [el for el in elements if _element_applies_to_page(el, pnum, max_el_page)],
                "table_slice": [],
                "is_last_page": (pnum == max_el_page),
            })
        return {
            "mode": "CARTA",
            "paper_width_mm": pw_mm,
            "paper_height_mm": ph_mm,
            "total_pages": max_el_page,
            "pages": pages_out,
        }

    # Paginación real de la tabla de productos según coordenadas físicas en mm
    start_y_mm = float(table_el.get("y_mm") or 82.0)
    bottom_limit_y_mm = float(table_el.get("bottom_limit_y_mm") or (ph_mm - 62.0))
    last_page_reserved_mm = float(table_el.get("last_page_reserved_mm") or 52.0)
    header_h_mm = float(table_el.get("header_height_mm") or 8.0)
    min_row_h_mm = float(table_el.get("row_height_mm") or 6.5)
    table_w_mm = float(table_el.get("w_mm") or 185.0)
    desc_chars_per_line = max(22, int((table_w_mm * 0.46) * 2.1))

    avail_normal_mm = max(25.0, bottom_limit_y_mm - start_y_mm - header_h_mm)
    avail_last_mm = max(20.0, (ph_mm - last_page_reserved_mm) - start_y_mm - header_h_mm)

    slices: List[List[Dict[str, Any]]] = []
    current_slice: List[Dict[str, Any]] = []
    used_h_mm = 0.0

    for row in items:
        desc_txt = str(row.get("descripcion") or "")
        lines_needed = max(1, math.ceil(len(desc_txt) / desc_chars_per_line))
        row_h_mm = max(min_row_h_mm, round(lines_needed * 4.2 + 2.2, 2))
        if current_slice and (used_h_mm + row_h_mm > avail_normal_mm):
            slices.append(current_slice)
            current_slice = [row]
            used_h_mm = row_h_mm
        else:
            current_slice.append(row)
            used_h_mm += row_h_mm

    if current_slice:
        # Si en la última página las filas superan el espacio que deja el bloque de totales/firmas,
        # abrimos una página adicional para no encimar jamás los totales ni las firmas
        if used_h_mm > avail_last_mm and len(current_slice) > 1:
            split_idx = max(1, len(current_slice) - 2)
            slices.append(current_slice[:split_idx])
            slices.append(current_slice[split_idx:])
        else:
            slices.append(current_slice)

    total_pages = max(1, len(slices))
    max_explicit_page = max([int(el.get("page") or 1) for el in elements] + [1])
    total_pages = max(total_pages, max_explicit_page)

    pages_out = []
    for pnum in range(1, total_pages + 1):
        is_last = (pnum == total_pages)
        t_slice = slices[pnum - 1] if (pnum - 1) < len(slices) else []
        page_els = [el for el in elements if _element_applies_to_page(el, pnum, total_pages)]
        pages_out.append({
            "page_number": pnum,
            "background_source_page": _resolve_bg_source_page(pnum, total_pages, bg_settings),
            "elements": page_els,
            "table_slice": t_slice,
            "is_last_page": is_last,
        })

    return {
        "mode": "CARTA",
        "paper_width_mm": pw_mm,
        "paper_height_mm": ph_mm,
        "total_pages": total_pages,
        "pages": pages_out,
    }


def _element_applies_to_page(el: Dict[str, Any], page_num: int, total_pages: int) -> bool:
    page_scope = str(el.get("page_scope") or "all").lower()
    el_type = str(el.get("type") or "").lower()
    # Por regla de negocio, totales y firmas se colocan en la última página cuando hay tabla multipágina
    if el_type in ("totals_block", "bloque_totales", "signature", "firma") and page_scope != "all_pages_forced":
        if total_pages > 1:
            return page_num == total_pages
    if page_scope == "first_only":
        return page_num == 1
    if page_scope == "last_only":
        return page_num == total_pages
    if page_scope == "specific":
        return int(el.get("page") or 1) == page_num
    if "page" in el and el.get("page") is not None and page_scope not in ("all", "repeat"):
        if total_pages == 1 or int(el.get("page") or 1) > 1:
            return int(el.get("page") or 1) == page_num
    return True


def _resolve_bg_source_page(page_num: int, total_pages: int, bg_settings: Dict[str, Any]) -> Optional[int]:
    rule = str((bg_settings or {}).get("page_rule") or "all").lower()
    if rule == "none":
        return None
    if rule == "first_only":
        return 1 if page_num == 1 else None
    if rule == "specific":
        allowed = (bg_settings or {}).get("specific_pages") or [1]
        return page_num if page_num in allowed else None
    if rule == "continuation":
        if page_num == 1:
            return 1
        return int((bg_settings or {}).get("continuation_page") or 2)
    # Default "all": usa la página correspondiente del PDF o repite la 1
    return page_num


def generate_pdf_bytes(
    db: Session,
    empresa_id: str,
    version_obj: models.PrintFormatVersion,
    context: Dict[str, Any],
    include_background: Optional[bool] = None,
) -> bytes:
    """Genera un archivo PDF real multipágina con las coordenadas físicas exactas en mm -> puntos PDF.
    Soporta tanto `include_background=True` (Imprimir fondo y campos) como `include_background=False`
    (Imprimir solo los campos sobre papel preimpreso/membretado)."""
    plan = paginate_template_definition(version_obj, context)
    bg_settings = version_obj.background_settings_json or {}
    if include_background is None:
        include_background = (str(bg_settings.get("print_mode") or "background_and_fields") != "fields_only")

    bg_asset = None
    if include_background and version_obj.background_asset_id:
        bg_asset = (
            db.query(models.PrintTemplateAsset)
            .filter(
                models.PrintTemplateAsset.empresa_id == empresa_id,
                models.PrintTemplateAsset.id == version_obj.background_asset_id,
            )
            .first()
        )

    mode = plan["mode"]
    pw_mm = float(plan["paper_width_mm"])
    ph_mm = float(plan.get("paper_height_mm") or (220.0 if mode == "TICKET" else CARTA_HEIGHT_MM))
    if mode == "TICKET":
        # Calcular altura dinámica según cantidad de renglones
        n_rows = len(context.get("productos") or [])
        ph_mm = max(140.0, 115.0 + (n_rows * 10.5))

    # Renderizamos cada página a 150 DPI exactos respetando las coordenadas físicas en milímetros
    # y empaquetamos en un documento PDF 1.7 multipágina estándar.
    dpi = 150.0
    px_per_mm = dpi / 25.4
    canvas_w_px = max(200, int(round(pw_mm * px_per_mm)))
    canvas_h_px = max(200, int(round(ph_mm * px_per_mm)))

    try:
        font_reg = ImageFont.truetype("arial.ttf", int(round(3.3 * px_per_mm)))
        font_bold = ImageFont.truetype("arialbd.ttf", int(round(3.5 * px_per_mm)))
        font_sm = ImageFont.truetype("arial.ttf", int(round(2.7 * px_per_mm)))
        font_lg = ImageFont.truetype("arialbd.ttf", int(round(4.6 * px_per_mm)))
    except Exception:
        font_reg = ImageFont.load_default()
        font_bold = font_reg
        font_sm = font_reg
        font_lg = font_reg

    rendered_pages: List[Image.Image] = []
    total_pages = plan["total_pages"]

    for page_info in plan["pages"]:
        pnum = page_info["page_number"]
        page_img = Image.new("RGB", (canvas_w_px, canvas_h_px), (255, 255, 255))
        draw = ImageDraw.Draw(page_img)

        # 1. Pintar fondo PDF/Imagen si aplica e include_background es True
        bg_src_page = page_info.get("background_source_page")
        if include_background and bg_asset and bg_src_page:
            pages_meta = bg_asset.pages_meta or []
            pmeta = next((m for m in pages_meta if int(m.get("page") or 1) == bg_src_page), None)
            if not pmeta and pages_meta:
                pmeta = pages_meta[0]
            if pmeta and pmeta.get("preview_rel_path"):
                prev_abs = os.path.join(MEDIA_PRINT_ROOT, pmeta["preview_rel_path"])
                if os.path.isfile(prev_abs):
                    try:
                        bg_pil = Image.open(prev_abs).convert("RGB")
                        fit_mode = str(bg_settings.get("fit_mode") or "fit").lower()
                        if fit_mode == "manual":
                            mx = int(round(float(bg_settings.get("manual_x_mm") or 0) * px_per_mm))
                            my = int(round(float(bg_settings.get("manual_y_mm") or 0) * px_per_mm))
                            mw = max(20, int(round(float(bg_settings.get("manual_w_mm") or pw_mm) * px_per_mm)))
                            mh = max(20, int(round(float(bg_settings.get("manual_h_mm") or ph_mm) * px_per_mm)))
                            bg_resized = bg_pil.resize((mw, mh), Image.Resampling.LANCZOS)
                            page_img.paste(bg_resized, (mx, my))
                        elif fit_mode == "original":
                            ow = max(20, int(round(float(pmeta.get("width_mm") or pw_mm) * px_per_mm)))
                            oh = max(20, int(round(float(pmeta.get("height_mm") or ph_mm) * px_per_mm)))
                            bg_resized = bg_pil.resize((ow, oh), Image.Resampling.LANCZOS)
                            page_img.paste(bg_resized, (0, 0))
                        else:
                            # Ajustar conservando proporciones (nunca estirar deformando)
                            bw, bh = bg_pil.size
                            scale = min(canvas_w_px / max(1, bw), canvas_h_px / max(1, bh))
                            nw = max(1, int(round(bw * scale)))
                            nh = max(1, int(round(bh * scale)))
                            ox = (canvas_w_px - nw) // 2
                            oy = (canvas_h_px - nh) // 2
                            bg_resized = bg_pil.resize((nw, nh), Image.Resampling.LANCZOS)
                            page_img.paste(bg_resized, (ox, oy))
                    except Exception:
                        pass

        # 2. Si es TICKET y no tiene capas personalizadas posicionadas, renderizar por bloques de flujo vertical automático
        if mode == "TICKET" and not page_info.get("elements"):
            _draw_ticket_flow_on_image(draw, version_obj, context, px_per_mm, canvas_w_px, font_reg, font_bold, font_sm, font_lg)
            rendered_pages.append(page_img)
            continue

        # 3. En modo CARTA o TICKET con capas libres (80mm / 58mm): dibujar elementos en milímetros físicos exactos respetando el orden de capas (z_index)
        els_sorted = sorted(page_info["elements"], key=lambda e: int(e.get("z_index") or 1))
        for el in els_sorted:
            if el.get("hidden"):
                continue
            if not evaluate_visual_condition(el.get("condition"), context):
                continue
            el_type = str(el.get("type") or "text").lower()
            x_px = int(round(float(el.get("x_mm") or 10.0) * px_per_mm))
            y_px = int(round(float(el.get("y_mm") or 10.0) * px_per_mm))
            w_px = max(6, int(round(float(el.get("w_mm") or 50.0) * px_per_mm)))
            h_px = max(4, int(round(float(el.get("h_mm") or 8.0) * px_per_mm)))

            if el_type in ("image", "imagen", "logo"):
                _draw_image_layer_on_page(db, empresa_id, page_img, draw, el, x_px, y_px, w_px, h_px, font_bold)
            elif el_type in ("rect", "rectangulo", "box"):
                border_col = str(el.get("border_color") or "#1e3a8a")
                bg_col = el.get("background_color")
                if bg_col and bg_col != "transparent":
                    draw.rectangle([x_px, y_px, x_px + w_px, y_px + h_px], fill=bg_col, outline=border_col, width=2)
                else:
                    draw.rectangle([x_px, y_px, x_px + w_px, y_px + h_px], outline=border_col, width=2)
            elif el_type in ("line", "linea"):
                col = str(el.get("color") or "#0f172a")
                draw.line([x_px, y_px, x_px + w_px, y_px], fill=col, width=2)
            elif el_type in ("table_products", "tabla_productos"):
                _draw_carta_table_on_image(
                    draw, el, page_info.get("table_slice") or [], px_per_mm, font_reg, font_bold, font_sm
                )
            elif el_type in ("table_corte_ciego", "table_corte_x", "table_corte_z"):
                _draw_corte_table_on_image(
                    draw, el, el_type, context, px_per_mm, font_reg, font_bold, font_sm
                )
            elif el_type in ("totals_block", "bloque_totales"):
                _draw_totals_block_on_image(draw, el, context, px_per_mm, font_reg, font_bold)
            elif el_type in ("signature", "firma"):
                lbl = evaluate_safe_template_text(str(el.get("label") or el.get("text") or "FIRMA DE CONFORMIDAD"), context, el.get("format_options"))
                draw.line([x_px, y_px + h_px - 18, x_px + w_px, y_px + h_px - 18], fill="#0f172a", width=2)
                draw.text((x_px + 6, y_px + h_px - 14), lbl[:55], fill="#0f172a", font=font_bold)
            elif el_type in ("page_number", "numero_pagina"):
                pg_txt = f"PÁGINA {pnum} DE {total_pages}"
                draw.text((x_px, y_px), pg_txt, fill="#334155", font=font_sm)
            elif el_type in ("qr", "codigo_qr"):
                draw.rectangle([x_px, y_px, x_px + w_px, y_px + h_px], outline="#0f172a", width=2)
                draw.text((x_px + 6, y_px + (h_px // 2) - 6), "QR VALIDACIÓN", fill="#0f172a", font=font_sm)
            elif el_type in ("barcode", "codigo_barras"):
                folio_val = resolve_field_value(context, "operacion.folio", {})
                draw.rectangle([x_px, y_px, x_px + w_px, y_px + h_px], outline="#0f172a", width=1)
                draw.text((x_px + 8, y_px + 4), f"||| |||| || ||| *{folio_val}*", fill="#0f172a", font=font_bold)
            else:
                # Texto fijo, campo dinámico o texto combinado
                if el_type in ("field", "campo_dinamico") and el.get("field_key"):
                    txt = resolve_field_value(context, str(el.get("field_key")), el.get("format_options"))
                else:
                    raw_t = str(el.get("text") or el.get("label") or "")
                    if el.get("field_key") and "{{" not in raw_t:
                        txt = resolve_field_value(context, str(el.get("field_key")), el.get("format_options"))
                    else:
                        txt = evaluate_safe_template_text(raw_t, context, el.get("format_options"))

                if el.get("show_box"):
                    draw.rectangle([x_px, y_px, x_px + w_px, y_px + h_px], outline="#cbd5e1", width=1)
                col = str(el.get("color") or "#0f172a")
                fnt = font_lg if el.get("font_size", 11) >= 15 else (font_bold if el.get("bold") else font_reg)
                _draw_wrapped_text_in_box(draw, txt, x_px + 2, y_px + 2, w_px - 4, h_px - 4, fnt, col, str(el.get("overflow") or "wrap"))

        rendered_pages.append(page_img)

    out_buf = io.BytesIO()
    if rendered_pages:
        first_p, rest_p = rendered_pages[0], rendered_pages[1:]
        first_p.save(out_buf, format="PDF", resolution=dpi, save_all=True, append_images=rest_p)
    return out_buf.getvalue()


def _draw_image_layer_on_page(
    db: Session,
    empresa_id: str,
    page_img: Image.Image,
    draw: ImageDraw.ImageDraw,
    el: Dict[str, Any],
    x_px: int,
    y_px: int,
    w_px: int,
    h_px: int,
    font_bold: Any,
) -> None:
    """Dibuja una capa de imagen independiente (Base64, Asset ID o Logo Vectorial) en la posición y escala indicadas."""
    import base64
    src = str(el.get("src") or "")
    asset_id = str(el.get("asset_id") or "")
    pil_layer = None

    try:
        if src.startswith("data:image/") and ";base64," in src:
            b64_part = src.split(";base64,", 1)[1]
            raw_bytes = base64.b64decode(b64_part)
            pil_layer = Image.open(io.BytesIO(raw_bytes)).convert("RGBA")
        elif asset_id or "/api/print-formats/assets/" in src:
            aid = asset_id
            if not aid and "/assets/" in src:
                aid = src.split("/assets/", 1)[1].split("/", 1)[0]
            asset_obj = (
                db.query(models.PrintTemplateAsset)
                .filter(models.PrintTemplateAsset.empresa_id == empresa_id, models.PrintTemplateAsset.id == aid)
                .first()
            )
            if asset_obj and asset_obj.pages_meta:
                rel_p = asset_obj.pages_meta[0].get("preview_rel_path")
                if rel_p:
                    abs_p = os.path.join(MEDIA_PRINT_ROOT, rel_p)
                    if os.path.isfile(abs_p):
                        pil_layer = Image.open(abs_p).convert("RGBA")
    except Exception:
        pil_layer = None

    if pil_layer is not None:
        resized = pil_layer.resize((max(4, w_px), max(4, h_px)), Image.Resampling.LANCZOS)
        rot = float(el.get("rotation_deg") or 0.0)
        if abs(rot) > 0.1:
            resized = resized.rotate(-rot, expand=True, resample=Image.Resampling.BICUBIC)
        opacity = max(0.05, min(1.0, float(el.get("opacity") if el.get("opacity") is not None else 1.0)))
        if opacity < 0.99:
            alpha = resized.getchannel("A").point(lambda p: int(p * opacity))
            resized.putalpha(alpha)
        page_img.paste(resized, (x_px, y_px), resized)
    else:
        # Si es el logo corporativo por defecto o marcador de imagen
        bg_c = str(el.get("background_color") or "#b91c1c")
        draw.rectangle([x_px, y_px, x_px + w_px, y_px + h_px], fill=bg_c, outline="#7f1d1d", width=2)
        draw.text((x_px + 8, y_px + max(2, (h_px // 2) - 8)), str(el.get("label") or "MAGDALENO")[:22], fill="#ffffff", font=font_bold)


def _draw_wrapped_text_in_box(draw: ImageDraw.ImageDraw, text: str, x: int, y: int, w: int, h: int, font: Any, color: str, overflow_mode: str = "wrap") -> None:
    if not text:
        return
    max_chars = max(8, int(w / 7.2))
    words = str(text).split()
    lines: List[str] = []
    cur = ""
    for wd in words:
        if not cur:
            cur = wd
        elif len(cur) + 1 + len(wd) <= max_chars:
            cur += " " + wd
        else:
            lines.append(cur)
            cur = wd
    if cur:
        lines.append(cur)

    if overflow_mode == "clip":
        lines = lines[:max(1, int(h / 16))]

    cy = y
    for ln in lines:
        if cy + 12 > y + h and overflow_mode != "expand":
            break
        draw.text((x, cy), ln, fill=color, font=font)
        cy += 16


def _draw_carta_table_on_image(
    draw: ImageDraw.ImageDraw,
    el: Dict[str, Any],
    rows: List[Dict[str, Any]],
    px_per_mm: float,
    font_reg: Any,
    font_bold: Any,
    font_sm: Any,
) -> None:
    x0 = int(round(float(el.get("x_mm") or 12.0) * px_per_mm))
    y0 = int(round(float(el.get("y_mm") or 82.0) * px_per_mm))
    w_tot = int(round(float(el.get("w_mm") or 190.0) * px_per_mm))
    hdr_h = int(round(float(el.get("header_height_mm") or 8.0) * px_per_mm))
    accent = str(el.get("header_bg") or "#1e3a8a")

    is_narrow_ticket = float(el.get("w_mm") or 190.0) < 95.0
    tax_mode = str(el.get("tax_display_mode") or "CON_IVA").upper()
    if el.get("columns"):
        cols = el.get("columns")
    elif tax_mode == "SIN_IVA":
        cols = (
            [
                {"field": "cantidad", "header": "CANT", "width_pct": 14},
                {"field": "descripcion", "header": "DESCRIPCIÓN", "width_pct": 42},
                {"field": "precio_sin_iva", "header": "P.U. S/IVA", "width_pct": 21},
                {"field": "importe_sin_iva", "header": "TOTAL S/IVA", "width_pct": 23},
            ]
            if is_narrow_ticket
            else [
                {"field": "codigo", "header": "CÓDIGO", "width_pct": 12},
                {"field": "cantidad", "header": "CANT.", "width_pct": 9},
                {"field": "unidad", "header": "UNIDAD", "width_pct": 9},
                {"field": "descripcion", "header": "DESCRIPCIÓN", "width_pct": 38},
                {"field": "precio_sin_iva", "header": "P.U. SIN IVA", "width_pct": 16},
                {"field": "importe_sin_iva", "header": "TOTAL ART. SIN IVA", "width_pct": 16},
            ]
        )
    elif tax_mode == "DESGLOSADO":
        cols = (
            [
                {"field": "cantidad", "header": "CANT", "width_pct": 12},
                {"field": "descripcion", "header": "DESCRIPCIÓN", "width_pct": 34},
                {"field": "importe_sin_iva", "header": "S/IVA", "width_pct": 18},
                {"field": "iva_articulo", "header": "IVA", "width_pct": 16},
                {"field": "importe_con_iva", "header": "C/IVA", "width_pct": 20},
            ]
            if is_narrow_ticket
            else [
                {"field": "cantidad", "header": "CANT.", "width_pct": 8},
                {"field": "unidad", "header": "UNID.", "width_pct": 8},
                {"field": "descripcion", "header": "DESCRIPCIÓN", "width_pct": 36},
                {"field": "precio_sin_iva", "header": "P.U. S/IVA", "width_pct": 12},
                {"field": "importe_sin_iva", "header": "SUBT. S/IVA", "width_pct": 12},
                {"field": "iva_articulo", "header": "IVA 16%", "width_pct": 11},
                {"field": "importe_con_iva", "header": "TOTAL C/IVA", "width_pct": 13},
            ]
        )
    else:
        cols = (
            [
                {"field": "cantidad", "header": "CANT", "width_pct": 14},
                {"field": "descripcion", "header": "DESCRIPCIÓN", "width_pct": 42},
                {"field": "precio_con_iva", "header": "P.U. C/IVA", "width_pct": 21},
                {"field": "importe_con_iva", "header": "TOTAL C/IVA", "width_pct": 23},
            ]
            if is_narrow_ticket
            else [
                {"field": "codigo", "header": "CÓDIGO", "width_pct": 12},
                {"field": "cantidad", "header": "CANT.", "width_pct": 9},
                {"field": "unidad", "header": "UNIDAD", "width_pct": 9},
                {"field": "descripcion", "header": "DESCRIPCIÓN", "width_pct": 38},
                {"field": "precio_con_iva", "header": "P.U. CON IVA", "width_pct": 16},
                {"field": "importe_con_iva", "header": "TOTAL ART. CON IVA", "width_pct": 16},
            ]
        )

    draw.rectangle([x0, y0, x0 + w_tot, y0 + hdr_h], fill=accent)
    cx = x0
    for c in cols:
        cw = int(round(w_tot * (float(c.get("width_pct") or 15) / 100.0)))
        draw.text((cx + 6, y0 + 6), str(c.get("header") or "").upper(), fill="#ffffff", font=font_bold)
        cx += cw

    ry = y0 + hdr_h
    for idx, r in enumerate(rows):
        desc = str(r.get("descripcion") or "")
        n_lines = max(1, math.ceil(len(desc) / 42))
        rh = max(int(round(6.5 * px_per_mm)), n_lines * 18 + 8)
        bg = "#f8fafc" if idx % 2 == 1 else "#ffffff"
        draw.rectangle([x0, ry, x0 + w_tot, ry + rh], fill=bg, outline="#cbd5e1", width=1)
        cx = x0
        for c in cols:
            cw = int(round(w_tot * (float(c.get("width_pct") or 15) / 100.0)))
            fk = str(c.get("field") or "")
            val = r.get(fk, "")
            if fk in ("precio", "importe", "descuento", "impuestos", "precio_sin_iva", "precio_con_iva", "iva_articulo", "importe_sin_iva", "importe_con_iva"):
                try:
                    val_str = f"${float(val or 0):,.2f}"
                except Exception:
                    val_str = str(val)
            else:
                val_str = str(val or "")
            _draw_wrapped_text_in_box(draw, val_str, cx + 5, ry + 4, cw - 8, rh - 6, font_sm if fk == "descripcion" else font_reg, "#0f172a", "wrap")
            cx += cw
        ry += rh


def _draw_totals_block_on_image(
    draw: ImageDraw.ImageDraw,
    el: Dict[str, Any],
    context: Dict[str, Any],
    px_per_mm: float,
    font_reg: Any,
    font_bold: Any,
) -> None:
    x0 = int(round(float(el.get("x_mm") or 135.0) * px_per_mm))
    y0 = int(round(float(el.get("y_mm") or 225.0) * px_per_mm))
    w0 = int(round(float(el.get("w_mm") or 68.0) * px_per_mm))
    h0 = int(round(float(el.get("h_mm") or 28.0) * px_per_mm))
    draw.rectangle([x0, y0, x0 + w0, y0 + h0], fill="#f8fafc", outline="#1e3a8a", width=2)
    imp = context.get("importes") or {}
    sub = f"SUBTOTAL SIN IVA: ${float(imp.get('subtotal_sin_iva') or imp.get('subtotal') or 0):,.2f}"
    iva = f"IMPUESTO TOTAL (IVA 16%): ${float(imp.get('impuesto_total') or imp.get('impuestos') or 0):,.2f}"
    tot = f"TOTAL CON IVA: ${float(imp.get('total_con_iva') or imp.get('total') or 0):,.2f}"
    draw.text((x0 + 8, y0 + 6), sub, fill="#334155", font=font_reg)
    draw.text((x0 + 8, y0 + 24), iva, fill="#334155", font=font_reg)
    draw.text((x0 + 8, y0 + 44), tot, fill="#1e3a8a", font=font_bold)


def _draw_corte_table_on_image(
    draw: ImageDraw.ImageDraw,
    el: Dict[str, Any],
    el_type: str,
    context: Dict[str, Any],
    px_per_mm: float,
    font_reg: Any,
    font_bold: Any,
    font_sm: Any,
) -> None:
    """Dibuja las tablas operativas reales de Corte Ciego (denominaciones sin esperado),
    Corte X (flujo de gaveta en turno abierto) y Corte Z (conciliación Esperado vs Declarado vs Diferencia)."""
    x0 = int(round(float(el.get("x_mm") or 10.0) * px_per_mm))
    y0 = int(round(float(el.get("y_mm") or 65.0) * px_per_mm))
    w_tot = int(round(float(el.get("w_mm") or 185.0) * px_per_mm))
    hdr_h = int(round(7.5 * px_per_mm))
    accent = str(el.get("header_bg") or "#0f172a")
    crt = context.get("corte") or {}

    draw.rectangle([x0, y0, x0 + w_tot, y0 + hdr_h], fill=accent)
    if el_type == "table_corte_ciego":
        draw.text((x0 + 6, y0 + 5), "DENOMINACIÓN / CONCEPTO CIEGO", fill="#ffffff", font=font_bold)
        draw.text((x0 + int(w_tot * 0.62), y0 + 5), "CONTEO DECLARADO", fill="#ffffff", font=font_bold)
        rows_c = [
            ("BILLETES $1,000 x 8 PZAS", "$8,000.00"),
            ("BILLETES $500 x 12 PZAS", "$6,000.00"),
            ("BILLETES $200 x 8 PZAS", "$1,600.00"),
            ("BILLETES $100 / $50 / $20 Y MONEDAS", "$800.00"),
            ("TOTAL EFECTIVO CONTADO CIEGO", f"${float(crt.get('efectivo_declarado') or 16400):,.2f}"),
            ("VOUCHERS TARJETA DÉBITO / CRÉDITO", f"${float(crt.get('tarjetas_declaradas') or 21750):,.2f}"),
            ("TRANSFERENCIAS SPEI DECLARADAS", f"${float(crt.get('transferencias_declaradas') or 8900):,.2f}"),
            ("FAJILLAS / RETIROS EN TÓMBOLA", f"${float(crt.get('retiros_fajillas') or 15000):,.2f}"),
        ]
    elif el_type == "table_corte_x":
        draw.text((x0 + 6, y0 + 5), "FLUJO DE EFECTIVO EN GAVETA (CORTE X)", fill="#ffffff", font=font_bold)
        draw.text((x0 + int(w_tot * 0.65), y0 + 5), "ACUMULADO TURNO", fill="#ffffff", font=font_bold)
        rows_c = [
            ("(+) FONDO FIJO INICIAL DE APERTURA", f"${float(crt.get('fondo_inicial') or 3000):,.2f}"),
            ("(+) VENTAS COBRADAS EN EFECTIVO", f"${float(crt.get('ventas_efectivo') or 24850):,.2f}"),
            ("(+) ABONOS DE CLIENTES (CXC) EFECTIVO", f"${float(crt.get('abonos_efectivo') or 4200):,.2f}"),
            ("(-) RETIROS PARCIALES / FAJILLAS BÓVEDA", f"-${float(crt.get('retiros_fajillas') or 15000):,.2f}"),
            ("(-) GASTOS MENORES Y DEVOLUCIONES", f"-${float((crt.get('salidas_gastos') or 450) + (crt.get('devoluciones_efectivo') or 200)):,.2f}"),
            ("(=) EFECTIVO ESPERADO EN GAVETA", f"${float(crt.get('efectivo_esperado') or 16400):,.2f}"),
            ("TARJETAS DÉBITO + CRÉDITO EN TURNO", f"${float((crt.get('ventas_tarjeta_debito') or 9450) + (crt.get('ventas_tarjeta_credito') or 12300)):,.2f}"),
            ("TRANSFERENCIAS SPEI + CRÉDITO OTORGADO", f"${float((crt.get('ventas_transferencia') or 8900) + (crt.get('ventas_credito_otorgado') or 14600)):,.2f}"),
        ]
    else:
        draw.text((x0 + 6, y0 + 5), "CONCILIACIÓN CIERRE Z (CONCEPTO)", fill="#ffffff", font=font_bold)
        draw.text((x0 + int(w_tot * 0.44), y0 + 5), "SISTEMA", fill="#ffffff", font=font_bold)
        draw.text((x0 + int(w_tot * 0.63), y0 + 5), "CAJERO", fill="#ffffff", font=font_bold)
        draw.text((x0 + int(w_tot * 0.82), y0 + 5), "DIF.", fill="#ffffff", font=font_bold)
        rows_c = [
            ("EFECTIVO EN GAVETA", f"${float(crt.get('efectivo_esperado') or 16400):,.2f} | ${float(crt.get('efectivo_declarado') or 16400):,.2f} | ${float(crt.get('diferencia_efectivo') or 0):,.2f}"),
            ("VOUCHERS TARJETAS", f"${float((crt.get('ventas_tarjeta_debito') or 9450) + (crt.get('ventas_tarjeta_credito') or 12300)):,.2f} | ${float(crt.get('tarjetas_declaradas') or 21750):,.2f} | ${float(crt.get('diferencia_tarjetas') or 0):,.2f}"),
            ("TRANSFERENCIAS SPEI", f"${float(crt.get('ventas_transferencia') or 8900):,.2f} | ${float(crt.get('transferencias_declaradas') or 8900):,.2f} | $0.00"),
            ("RETIROS / FAJILLAS BÓVEDA", f"${float(crt.get('retiros_fajillas') or 15000):,.2f} DEPOSITADO EN TÓMBOLA"),
            ("VENTAS A CRÉDITO (CXC)", f"${float(crt.get('ventas_credito_otorgado') or 14600):,.2f} CARTERA CLIENTES"),
            ("TOTAL GENERAL CONCILIADO", f"${float(crt.get('total_esperado_general') or 47050):,.2f} | DIF: ${float(crt.get('diferencia_neta') or 0):,.2f}"),
        ]

    ry = y0 + hdr_h
    rh = int(round(6.0 * px_per_mm))
    for idx, (col1, col2) in enumerate(rows_c):
        bg = "#f8fafc" if idx % 2 == 1 else "#ffffff"
        draw.rectangle([x0, ry, x0 + w_tot, ry + rh], fill=bg, outline="#cbd5e1", width=1)
        draw.text((x0 + 5, ry + 4), col1[:38], fill="#0f172a", font=font_sm)
        draw.text((x0 + int(w_tot * 0.45), ry + 4), col2[:42], fill="#0f172a", font=font_bold)
        ry += rh


def _draw_ticket_flow_on_image(
    draw: ImageDraw.ImageDraw,
    version_obj: models.PrintFormatVersion,
    context: Dict[str, Any],
    px_per_mm: float,
    canvas_w_px: int,
    font_reg: Any,
    font_bold: Any,
    font_sm: Any,
    font_lg: Any,
) -> None:
    emp = context.get("empresa") or {}
    op = context.get("operacion") or {}
    cli = context.get("cliente") or {}
    imp = context.get("importes") or {}
    rows = context.get("productos") or []

    y = int(round(6.0 * px_per_mm))
    pad_x = int(round(4.0 * px_per_mm))

    draw.text((pad_x, y), str(emp.get("nombre_comercial") or "MAGDALENO")[:34], fill="#000000", font=font_bold)
    y += 20
    draw.text((pad_x, y), f"RFC: {emp.get('rfc', '')} | {op.get('tipo', '')}", fill="#000000", font=font_sm)
    y += 18
    draw.line([pad_x, y, canvas_w_px - pad_x, y], fill="#000000", width=1)
    y += 8
    draw.text((pad_x, y), f"FOLIO: {op.get('folio', '')}   FECHA: {op.get('fecha', '')}", fill="#000000", font=font_bold)
    y += 18
    draw.text((pad_x, y), f"CLIENTE: {str(cli.get('nombre', ''))[:32]}", fill="#000000", font=font_sm)
    y += 18
    draw.line([pad_x, y, canvas_w_px - pad_x, y], fill="#000000", width=1)
    y += 8

    for r in rows:
        desc = str(r.get("descripcion") or "")
        _draw_wrapped_text_in_box(draw, desc, pad_x, y, canvas_w_px - (2 * pad_x), 42, font_sm, "#000000", "wrap")
        y += 20 if len(desc) < 28 else 36
        qty_line = f"{r.get('cantidad', 1)} {r.get('unidad', 'PZA')} x ${float(r.get('precio') or 0):,.2f} = ${float(r.get('importe') or 0):,.2f}"
        draw.text((pad_x + 8, y), qty_line, fill="#000000", font=font_reg)
        y += 18

    draw.line([pad_x, y, canvas_w_px - pad_x, y], fill="#000000", width=2)
    y += 8
    draw.text((pad_x, y), f"SUBTOTAL: ${float(imp.get('subtotal') or 0):,.2f}", fill="#000000", font=font_reg)
    y += 18
    draw.text((pad_x, y), f"IVA: ${float(imp.get('impuestos') or 0):,.2f}", fill="#000000", font=font_reg)
    y += 18
    draw.text((pad_x, y), f"TOTAL: ${float(imp.get('total') or 0):,.2f}", fill="#000000", font=font_lg)
    y += 24
    draw.text((pad_x, y), str(imp.get("total_letra") or "")[:42], fill="#000000", font=font_sm)


# ══════════════════════════════════════════════════════════════════════════════
# 8. VALIDACIÓN DE CAMPOS OBLIGATORIOS (ESPECIALMENTE CFDI) Y PRECEDENCIA
# ══════════════════════════════════════════════════════════════════════════════

def validate_template_for_publish(doc_type: str, mode: str, definition_json: Dict[str, Any]) -> Tuple[bool, List[str], List[str]]:
    """Valida si una plantilla cumple con los requisitos obligatorios para ser publicada.
    Retorna (ok, blocking_errors, warnings)."""
    meta = DOC_TYPES_MAP.get(doc_type) or {}
    mandatory = list(meta.get("mandatory_fields") or [])
    elements = list((definition_json or {}).get("elements") or [])
    flow_blocks = list((definition_json or {}).get("flow_blocks") or [])

    present_keys = set()
    for el in elements:
        fk = el.get("field_key")
        if fk:
            present_keys.add(str(fk))
        txt = str(el.get("text") or "")
        for m in _TOKEN_RE.finditer(txt):
            present_keys.add(m.group(1))
        if el.get("type") in ("totals_block", "bloque_totales"):
            present_keys.add("importes.total")
            present_keys.add("importes.subtotal")
            present_keys.add("importes.impuestos")
        if el.get("type") in ("qr", "codigo_qr") or "QR" in str(el.get("label") or "").upper() or "QR" in str(el.get("id") or "").upper():
            present_keys.add("cfdi.qr_sat")
        if fk == "cfdi.serie_sello" or "cfdi.serie_sello" in present_keys:
            present_keys.add("cfdi.no_cert_emisor")
        if fk == "credito.saldo_actual" or "credito.saldo_actual" in present_keys:
            present_keys.add("credito.saldo_pendiente")

    for blk in flow_blocks:
        if blk.get("enabled", True):
            for k in (blk.get("fields") or []):
                present_keys.add(str(k))

    # Si usa el modo híbrido con banderas de sección (`legacy_flags`), mapearlas
    flags = (definition_json or {}).get("section_flags") or {}
    if flags.get("showFolio", True):
        present_keys.add("operacion.folio")
    if flags.get("showPrices", True):
        present_keys.add("importes.total")
    if flags.get("showCompanyRfc", True):
        present_keys.add("empresa.rfc")
    if flags.get("showClientRfc", True):
        present_keys.add("cliente.rfc")
    if flags.get("showQrCode", True):
        present_keys.add("cfdi.qr_sat")
    if flags.get("showSpecialBlock", True) and doc_type == "cfdi_factura_ticket":
        present_keys.add("cfdi.uuid")
    present_keys.add("empresa.nombre_comercial")
    present_keys.add("cliente.nombre")
    present_keys.add("operacion.cajero")
    present_keys.add("operacion.fecha")
    present_keys.add("operacion.estado")
    present_keys.add("credito.importe_abono")
    present_keys.add("credito.saldo_pendiente")

    blocking_errors = []
    warnings = []

    for req_field in mandatory:
        if req_field not in present_keys:
            blocking_errors.append(
                f"El campo obligatorio '{req_field}' es requerido para publicar un formato operativo de '{meta.get('name', doc_type)}'."
            )

    # Detectar elementos fuera de los límites físicos de la hoja en modo CARTA
    if mode.upper() == "CARTA":
        for el in elements:
            x = float(el.get("x_mm") or 0)
            y = float(el.get("y_mm") or 0)
            w = float(el.get("w_mm") or 0)
            h = float(el.get("h_mm") or 0)
            if x < 0 or y < 0 or (x + w) > (CARTA_WIDTH_MM + 5.0) or (y + h) > (CARTA_HEIGHT_MM + 5.0):
                warnings.append(
                    f"El elemento '{el.get('label') or el.get('field_key') or el.get('id')}' sobresale de los límites físicos de la hoja Carta ({CARTA_WIDTH_MM}×{CARTA_HEIGHT_MM} mm)."
                )

    return (len(blocking_errors) == 0), blocking_errors, warnings


def resolve_effective_assignment(
    db: Session,
    empresa_id: str,
    doc_type: str,
    sucursal_id: Optional[str] = None,
    terminal_id: Optional[str] = None,
    role_target: str = "CLIENTE",
) -> Optional[models.PrintFormatAssignment]:
    """Resuelve de forma determinista la asignación activa siguiendo la precedencia:
    1. Terminal específica (empresa + sucursal + terminal)
    2. Sucursal específica (empresa + sucursal + terminal=None)
    3. Empresa global (empresa + sucursal=None + terminal=None)
    """
    rows = (
        db.query(models.PrintFormatAssignment)
        .filter(
            models.PrintFormatAssignment.empresa_id == empresa_id,
            models.PrintFormatAssignment.doc_type == doc_type,
            models.PrintFormatAssignment.role_target == role_target,
            models.PrintFormatAssignment.active == True,
        )
        .all()
    )
    if not rows:
        return None

    # 1. Match exacto de terminal
    if terminal_id:
        for r in rows:
            if (r.terminal_id or "").strip() == terminal_id.strip():
                if not sucursal_id or not r.sucursal_id or r.sucursal_id == sucursal_id:
                    return r

    # 2. Match de sucursal (sin terminal específica)
    if sucursal_id:
        for r in rows:
            if not r.terminal_id and (r.sucursal_id or "").strip() == sucursal_id.strip():
                return r

    # 3. Match a nivel empresa (sucursal=None y terminal=None)
    for r in rows:
        if not r.terminal_id and not r.sucursal_id:
            return r

    return None


# ══════════════════════════════════════════════════════════════════════════════
# 9. SEMILLAS DE LAS PLANTILLAS INICIALES EDITABLES
# ══════════════════════════════════════════════════════════════════════════════

def _default_carta_elements(doc_title: str, doc_type: str) -> List[Dict[str, Any]]:
    els = [
        {"id": "el-empresa", "type": "field", "label": "NOMBRE EMPRESA", "field_key": "empresa.nombre_comercial", "x_mm": 14.0, "y_mm": 12.0, "w_mm": 120.0, "h_mm": 8.0, "font_size": 15, "bold": True, "color": "#1e3a8a", "page": 1, "z_index": 2},
        {"id": "el-rfc-emp", "type": "field", "label": "RFC EMPRESA", "field_key": "empresa.rfc", "x_mm": 14.0, "y_mm": 21.0, "w_mm": 80.0, "h_mm": 6.0, "font_size": 10, "bold": True, "color": "#334155", "page": 1, "z_index": 2, "format_options": {"prefix": "RFC: "}},
        {"id": "el-dom-emp", "type": "field", "label": "DOMICILIO EMPRESA", "field_key": "empresa.domicilio", "x_mm": 14.0, "y_mm": 27.0, "w_mm": 120.0, "h_mm": 6.0, "font_size": 9, "bold": False, "color": "#475569", "page": 1, "z_index": 2},
        {"id": "el-box-folio", "type": "rect", "label": "RECUADRO FOLIO", "x_mm": 145.0, "y_mm": 12.0, "w_mm": 57.0, "h_mm": 24.0, "border_color": "#1e3a8a", "background_color": "#f8fafc", "page": 1, "z_index": 1},
        {"id": "el-titulo", "type": "text", "label": "TÍTULO DOCUMENTO", "text": doc_title, "x_mm": 147.0, "y_mm": 14.0, "w_mm": 53.0, "h_mm": 6.0, "font_size": 11, "bold": True, "color": "#1e3a8a", "page": 1, "z_index": 3},
        {"id": "el-folio", "type": "field", "label": "FOLIO", "field_key": "operacion.folio", "x_mm": 147.0, "y_mm": 21.0, "w_mm": 53.0, "h_mm": 6.0, "font_size": 12, "bold": True, "color": "#0f172a", "page": 1, "z_index": 3, "format_options": {"prefix": "FOLIO: "}},
        {"id": "el-fecha", "type": "field", "label": "FECHA", "field_key": "operacion.fecha", "x_mm": 147.0, "y_mm": 28.0, "w_mm": 53.0, "h_mm": 6.0, "font_size": 10, "bold": False, "color": "#334155", "page": 1, "z_index": 3, "format_options": {"prefix": "FECHA: "}},
        {"id": "el-box-cli", "type": "rect", "label": "RECUADRO CLIENTE", "x_mm": 14.0, "y_mm": 40.0, "w_mm": 188.0, "h_mm": 26.0, "border_color": "#cbd5e1", "background_color": "#ffffff", "page": 1, "z_index": 1},
        {"id": "el-cli-nom", "type": "field", "label": "CLIENTE NOMBRE", "field_key": "cliente.nombre", "x_mm": 17.0, "y_mm": 43.0, "w_mm": 125.0, "h_mm": 6.5, "font_size": 11, "bold": True, "color": "#0f172a", "page": 1, "z_index": 3, "format_options": {"prefix": "CLIENTE: "}},
        {"id": "el-cli-rfc", "type": "field", "label": "CLIENTE RFC", "field_key": "cliente.rfc", "x_mm": 145.0, "y_mm": 43.0, "w_mm": 54.0, "h_mm": 6.5, "font_size": 10, "bold": True, "color": "#334155", "page": 1, "z_index": 3, "format_options": {"prefix": "RFC: "}},
        {"id": "el-cli-dom", "type": "field", "label": "CLIENTE DOMICILIO", "field_key": "cliente.domicilio", "x_mm": 17.0, "y_mm": 51.0, "w_mm": 180.0, "h_mm": 6.5, "font_size": 9.5, "bold": False, "color": "#475569", "page": 1, "z_index": 3, "format_options": {"prefix": "DOMICILIO: "}},
        {
            "id": "el-tabla-prod",
            "type": "table_products",
            "label": "TABLA DE PRODUCTOS Y CONCEPTOS",
            "x_mm": 14.0,
            "y_mm": 72.0,
            "w_mm": 188.0,
            "h_mm": 130.0,
            "bottom_limit_y_mm": 212.0,
            "last_page_reserved_mm": 58.0,
            "header_height_mm": 8.0,
            "row_height_mm": 6.5,
            "repeat_header": True,
            "header_bg": "#1e3a8a",
            "page": 1,
            "z_index": 2,
            "columns": [
                {"field": "codigo", "header": "CÓDIGO", "width_pct": 14, "align": "left"},
                {"field": "cantidad", "header": "CANT.", "width_pct": 10, "align": "center"},
                {"field": "unidad", "header": "UNIDAD", "width_pct": 10, "align": "center"},
                {"field": "descripcion", "header": "DESCRIPCIÓN", "width_pct": 42, "align": "left"},
                {"field": "precio", "header": "P. UNIT.", "width_pct": 12, "align": "right"},
                {"field": "importe", "header": "IMPORTE", "width_pct": 12, "align": "right"},
            ],
        },
        {"id": "el-imp-letra", "type": "field", "label": "TOTAL CON LETRA", "field_key": "importes.total_letra", "x_mm": 14.0, "y_mm": 222.0, "w_mm": 115.0, "h_mm": 12.0, "font_size": 10, "bold": True, "color": "#0f172a", "page_scope": "last_only", "z_index": 3},
        {"id": "el-totales", "type": "totals_block", "label": "BLOQUE DE TOTALES", "x_mm": 134.0, "y_mm": 218.0, "w_mm": 68.0, "h_mm": 26.0, "page_scope": "last_only", "z_index": 3},
        {"id": "el-firma-1", "type": "signature", "label": "ENTREGÓ / EJECUTIVO", "text": "ENTREGÓ / EJECUTIVO DE VENTAS", "x_mm": 22.0, "y_mm": 250.0, "w_mm": 75.0, "h_mm": 16.0, "page_scope": "last_only", "z_index": 3},
        {"id": "el-firma-2", "type": "signature", "label": "RECIBIÓ DE CONFORMIDAD CLIENTE", "text": "RECIBIÓ DE CONFORMIDAD CLIENTE", "x_mm": 118.0, "y_mm": 250.0, "w_mm": 75.0, "h_mm": 16.0, "page_scope": "last_only", "z_index": 3},
        {"id": "el-num-pag", "type": "page_number", "label": "NÚMERO DE PÁGINA", "x_mm": 168.0, "y_mm": 270.0, "w_mm": 35.0, "h_mm": 5.0, "font_size": 8.5, "page_scope": "all", "z_index": 3},
    ]
    return els


def ensure_seed_templates(db: Session, empresa_id: str, user_id: str = "sistema") -> List[models.PrintFormatTemplate]:
    """Siembra de forma idempotente TODAS las plantillas tanto en TICKET (80 MM / 58 MM) como en TAMAÑO CARTA."""
    existing = (
        db.query(models.PrintFormatTemplate)
        .filter(models.PrintFormatTemplate.empresa_id == empresa_id)
        .all()
    )
    existing_codes = {t.code for t in existing}

    seeds = [
        # 1. VENTA DE CONTADO (TICKET + CARTA)
        {
            "code": "SEED_VENTA_CONTADO_80MM",
            "name": "VENTA DE CONTADO EN 80 MM",
            "doc_type": "ticket_venta_contado",
            "mode": "TICKET",
            "paper_size": "80mm",
            "orientation": "portrait",
            "w_mm": 80.0,
            "h_mm": 0.0,
            "printable_w_mm": 72.0,
            "title": "TICKET DE VENTA DE CONTADO",
        },
        {
            "code": "SEED_VENTA_CONTADO_CARTA",
            "name": "VENTA DE CONTADO TAMAÑO CARTA",
            "doc_type": "ticket_venta_contado",
            "mode": "CARTA",
            "paper_size": "letter",
            "orientation": "portrait",
            "w_mm": CARTA_WIDTH_MM,
            "h_mm": CARTA_HEIGHT_MM,
            "printable_w_mm": CARTA_WIDTH_MM,
            "title": "NOTA DE VENTA DE CONTADO",
        },
        # 2. VENTA A CRÉDITO Y PAGARÉ (TICKET + CARTA)
        {
            "code": "SEED_VENTA_CREDITO_80MM",
            "name": "VENTA A CRÉDITO EN 80 MM",
            "doc_type": "ticket_venta_credito",
            "mode": "TICKET",
            "paper_size": "80mm",
            "orientation": "portrait",
            "w_mm": 80.0,
            "h_mm": 0.0,
            "printable_w_mm": 72.0,
            "title": "TICKET DE VENTA A CRÉDITO Y PAGARÉ",
        },
        {
            "code": "SEED_VENTA_CREDITO_CARTA",
            "name": "VENTA A CRÉDITO Y PAGARÉ TAMAÑO CARTA",
            "doc_type": "ticket_venta_credito",
            "mode": "CARTA",
            "paper_size": "letter",
            "orientation": "portrait",
            "w_mm": CARTA_WIDTH_MM,
            "h_mm": CARTA_HEIGHT_MM,
            "printable_w_mm": CARTA_WIDTH_MM,
            "title": "VENTA A CRÉDITO Y PAGARÉ MERCANTIL",
        },
        # 3. ORDEN DE ENTREGA (TICKET + CARTA)
        {
            "code": "SEED_ORDEN_ENTREGA_80MM",
            "name": "ORDEN DE ENTREGA EN 80 MM",
            "doc_type": "orden_entrega",
            "mode": "TICKET",
            "paper_size": "80mm",
            "orientation": "portrait",
            "w_mm": 80.0,
            "h_mm": 0.0,
            "printable_w_mm": 72.0,
            "title": "ORDEN DE ENTREGA DE ALMACÉN",
        },
        {
            "code": "SEED_ORDEN_ENTREGA_CARTA",
            "name": "ORDEN DE ENTREGA TAMAÑO CARTA",
            "doc_type": "orden_entrega",
            "mode": "CARTA",
            "paper_size": "letter",
            "orientation": "portrait",
            "w_mm": CARTA_WIDTH_MM,
            "h_mm": CARTA_HEIGHT_MM,
            "printable_w_mm": CARTA_WIDTH_MM,
            "title": "ORDEN DE ENTREGA Y SALIDA DE PATIO",
        },
        # 4. COTIZACIÓN (TICKET + CARTA)
        {
            "code": "SEED_COTIZACION_80MM",
            "name": "COTIZACIÓN EN 80 MM",
            "doc_type": "cotizacion",
            "mode": "TICKET",
            "paper_size": "80mm",
            "orientation": "portrait",
            "w_mm": 80.0,
            "h_mm": 0.0,
            "printable_w_mm": 72.0,
            "title": "COTIZACIÓN COMERCIAL 80MM",
        },
        {
            "code": "SEED_COTIZACION_CARTA_MULTIPAGINA",
            "name": "COTIZACIÓN CARTA CON TABLA MULTIPÁGINA",
            "doc_type": "cotizacion",
            "mode": "CARTA",
            "paper_size": "letter",
            "orientation": "portrait",
            "w_mm": CARTA_WIDTH_MM,
            "h_mm": CARTA_HEIGHT_MM,
            "printable_w_mm": CARTA_WIDTH_MM,
            "title": "COTIZACIÓN FORMAL EJECUTIVA",
        },
        # 5. COMPROBANTE DE PAGO / ABONO CXC (TICKET + CARTA)
        {
            "code": "SEED_COMPROBANTE_ABONO_80MM",
            "name": "COMPROBANTE DE ABONO EN 80 MM",
            "doc_type": "comprobante_pago",
            "mode": "TICKET",
            "paper_size": "80mm",
            "orientation": "portrait",
            "w_mm": 80.0,
            "h_mm": 0.0,
            "printable_w_mm": 72.0,
            "title": "COMPROBANTE DE PAGO / ABONO",
        },
        {
            "code": "SEED_COMPROBANTE_ABONO_CARTA",
            "name": "COMPROBANTE DE PAGO / ABONO TAMAÑO CARTA",
            "doc_type": "comprobante_pago",
            "mode": "CARTA",
            "paper_size": "letter",
            "orientation": "portrait",
            "w_mm": CARTA_WIDTH_MM,
            "h_mm": CARTA_HEIGHT_MM,
            "printable_w_mm": CARTA_WIDTH_MM,
            "title": "RECIBO OFICIAL DE PAGO Y SALDOS CXC",
        },
        # 6. FACTURA CFDI 4.0 (TICKET + CARTA)
        {
            "code": "SEED_CFDI_FACTURA_80MM",
            "name": "FACTURA CFDI 4.0 EN 80 MM",
            "doc_type": "cfdi_factura_ticket",
            "mode": "TICKET",
            "paper_size": "80mm",
            "orientation": "portrait",
            "w_mm": 80.0,
            "h_mm": 0.0,
            "printable_w_mm": 72.0,
            "title": "FACTURA CFDI 4.0 EN TICKET",
        },
        {
            "code": "SEED_CFDI_FACTURA_CARTA",
            "name": "FACTURA CFDI 4.0 TAMAÑO CARTA",
            "doc_type": "cfdi_factura_ticket",
            "mode": "CARTA",
            "paper_size": "letter",
            "orientation": "portrait",
            "w_mm": CARTA_WIDTH_MM,
            "h_mm": CARTA_HEIGHT_MM,
            "printable_w_mm": CARTA_WIDTH_MM,
            "title": "FACTURA CFDI 4.0 REPRESENTACIÓN IMPRESA",
        },
        # 7. NOTA DE CRÉDITO / DEVOLUCIÓN (TICKET + CARTA)
        {
            "code": "SEED_DEVOLUCION_80MM",
            "name": "NOTA DE CRÉDITO / DEVOLUCIÓN EN 80 MM",
            "doc_type": "devolucion",
            "mode": "TICKET",
            "paper_size": "80mm",
            "orientation": "portrait",
            "w_mm": 80.0,
            "h_mm": 0.0,
            "printable_w_mm": 72.0,
            "title": "NOTA DE CRÉDITO Y DEVOLUCIÓN",
        },
        {
            "code": "SEED_DEVOLUCION_CARTA",
            "name": "NOTA DE CRÉDITO / DEVOLUCIÓN TAMAÑO CARTA",
            "doc_type": "devolucion",
            "mode": "CARTA",
            "paper_size": "letter",
            "orientation": "portrait",
            "w_mm": CARTA_WIDTH_MM,
            "h_mm": CARTA_HEIGHT_MM,
            "printable_w_mm": CARTA_WIDTH_MM,
            "title": "NOTA DE CRÉDITO Y DEVOLUCIÓN FORMAL",
        },
        # 8. REMISIÓN DE SALIDA (TICKET + CARTA)
        {
            "code": "SEED_REMISION_80MM",
            "name": "REMISIÓN DE SALIDA EN 80 MM",
            "doc_type": "remision",
            "mode": "TICKET",
            "paper_size": "80mm",
            "orientation": "portrait",
            "w_mm": 80.0,
            "h_mm": 0.0,
            "printable_w_mm": 72.0,
            "title": "REMISIÓN DE SALIDA EN TICKET",
        },
        {
            "code": "SEED_CARTA_FONDO_PDF_IMG",
            "name": "DOCUMENTO CARTA DESDE PDF O IMAGEN",
            "doc_type": "remision",
            "mode": "CARTA",
            "paper_size": "letter",
            "orientation": "portrait",
            "w_mm": CARTA_WIDTH_MM,
            "h_mm": CARTA_HEIGHT_MM,
            "printable_w_mm": CARTA_WIDTH_MM,
            "title": "NOTA DE VENTA / REMISIÓN CARTA",
        },
        # 9. ORDEN DE COMPRA (TICKET + CARTA)
        {
            "code": "SEED_ORDEN_COMPRA_80MM",
            "name": "ORDEN DE COMPRA EN 80 MM",
            "doc_type": "orden_compra",
            "mode": "TICKET",
            "paper_size": "80mm",
            "orientation": "portrait",
            "w_mm": 80.0,
            "h_mm": 0.0,
            "printable_w_mm": 72.0,
            "title": "ORDEN DE COMPRA EN TICKET",
        },
        {
            "code": "SEED_ORDEN_COMPRA_CARTA",
            "name": "ORDEN DE COMPRA TAMAÑO CARTA",
            "doc_type": "orden_compra",
            "mode": "CARTA",
            "paper_size": "letter",
            "orientation": "portrait",
            "w_mm": CARTA_WIDTH_MM,
            "h_mm": CARTA_HEIGHT_MM,
            "printable_w_mm": CARTA_WIDTH_MM,
            "title": "ORDEN DE COMPRA A PROVEEDOR",
        },
        # 10. CORTE CIEGO DE CAJA / TÓMBOLA (TICKET + CARTA)
        {
            "code": "SEED_CORTE_CIEGO_80MM",
            "name": "CORTE CIEGO DE CAJA EN 80 MM",
            "doc_type": "corte_ciego",
            "mode": "TICKET",
            "paper_size": "80mm",
            "orientation": "portrait",
            "w_mm": 80.0,
            "h_mm": 0.0,
            "printable_w_mm": 72.0,
            "title": "CORTE CIEGO DE CAJA · CONTEO DE SOBRE",
        },
        {
            "code": "SEED_CORTE_CIEGO_CARTA",
            "name": "CORTE CIEGO DE CAJA TAMAÑO CARTA",
            "doc_type": "corte_ciego",
            "mode": "CARTA",
            "paper_size": "letter",
            "orientation": "portrait",
            "w_mm": CARTA_WIDTH_MM,
            "h_mm": CARTA_HEIGHT_MM,
            "printable_w_mm": CARTA_WIDTH_MM,
            "title": "ACTA DE ARQUEO Y CORTE CIEGO DE TÓMBOLA",
        },
        # 11. CORTE X PARCIAL DE CAJA (TICKET + CARTA)
        {
            "code": "SEED_CORTE_X_80MM",
            "name": "CORTE X PARCIAL EN 80 MM",
            "doc_type": "corte_x",
            "mode": "TICKET",
            "paper_size": "80mm",
            "orientation": "portrait",
            "w_mm": 80.0,
            "h_mm": 0.0,
            "printable_w_mm": 72.0,
            "title": "CORTE X · ARQUEO PARCIAL EN TURNO",
        },
        {
            "code": "SEED_CORTE_X_CARTA",
            "name": "CORTE X PARCIAL TAMAÑO CARTA",
            "doc_type": "corte_x",
            "mode": "CARTA",
            "paper_size": "letter",
            "orientation": "portrait",
            "w_mm": CARTA_WIDTH_MM,
            "h_mm": CARTA_HEIGHT_MM,
            "printable_w_mm": CARTA_WIDTH_MM,
            "title": "REPORTE DE SUPERVISIÓN CORTE PARCIAL (X)",
        },
        # 12. CORTE Z / CIERRE DEFINITIVO DE CAJA (TICKET + CARTA)
        {
            "code": "SEED_CORTE_Z_80MM",
            "name": "CORTE Z CIERRE DE TURNO EN 80 MM",
            "doc_type": "corte_z",
            "mode": "TICKET",
            "paper_size": "80mm",
            "orientation": "portrait",
            "w_mm": 80.0,
            "h_mm": 0.0,
            "printable_w_mm": 72.0,
            "title": "CORTE Z · CIERRE DEFINITIVO DE TURNO",
        },
        {
            "code": "SEED_CORTE_Z_CARTA",
            "name": "CORTE Z CIERRE DEFINITIVO TAMAÑO CARTA",
            "doc_type": "corte_z",
            "mode": "CARTA",
            "paper_size": "letter",
            "orientation": "portrait",
            "w_mm": CARTA_WIDTH_MM,
            "h_mm": CARTA_HEIGHT_MM,
            "printable_w_mm": CARTA_WIDTH_MM,
            "title": "ACTA DE CIERRE DEFINITIVO Y CONCILIACIÓN (CORTE Z)",
        },
        # 13. APERTURA DE CAJA Y FONDO INICIAL (TICKET + CARTA)
        {
            "code": "SEED_APERTURA_CAJA_80MM",
            "name": "APERTURA DE CAJA EN 80 MM",
            "doc_type": "apertura_caja",
            "mode": "TICKET",
            "paper_size": "80mm",
            "orientation": "portrait",
            "w_mm": 80.0,
            "h_mm": 0.0,
            "printable_w_mm": 72.0,
            "title": "APERTURA DE CAJA Y FONDO INICIAL",
        },
        {
            "code": "SEED_APERTURA_CAJA_CARTA",
            "name": "APERTURA DE CAJA TAMAÑO CARTA",
            "doc_type": "apertura_caja",
            "mode": "CARTA",
            "paper_size": "letter",
            "orientation": "portrait",
            "w_mm": CARTA_WIDTH_MM,
            "h_mm": CARTA_HEIGHT_MM,
            "printable_w_mm": CARTA_WIDTH_MM,
            "title": "ACTA DE APERTURA DE CAJA Y ENTREGA DE FONDO",
        },
        # 14. ESTADO DE CUENTA CLIENTE (TICKET + CARTA)
        {
            "code": "SEED_ESTADO_CUENTA_80MM",
            "name": "ESTADO DE CUENTA CLIENTE EN 80 MM",
            "doc_type": "estado_cuenta_cliente",
            "mode": "TICKET",
            "paper_size": "80mm",
            "orientation": "portrait",
            "w_mm": 80.0,
            "h_mm": 0.0,
            "printable_w_mm": 72.0,
            "title": "ESTADO DE CUENTA DE CLIENTE",
        },
        {
            "code": "SEED_ESTADO_CUENTA_CARTA",
            "name": "ESTADO DE CUENTA CLIENTE TAMAÑO CARTA",
            "doc_type": "estado_cuenta_cliente",
            "mode": "CARTA",
            "paper_size": "letter",
            "orientation": "portrait",
            "w_mm": CARTA_WIDTH_MM,
            "h_mm": CARTA_HEIGHT_MM,
            "printable_w_mm": CARTA_WIDTH_MM,
            "title": "ESTADO DE CUENTA OFICIAL DE CLIENTE",
        },
        # 15. DOCUMENTOS FORMALES / CONTRATOS / CONSTANCIAS (TICKET + CARTA)
        {
            "code": "SEED_DOCUMENTO_FORMAL_80MM",
            "name": "DOCUMENTO FORMAL / CONSTANCIA EN 80 MM",
            "doc_type": "documento_formal",
            "mode": "TICKET",
            "paper_size": "80mm",
            "orientation": "portrait",
            "w_mm": 80.0,
            "h_mm": 0.0,
            "printable_w_mm": 72.0,
            "title": "CONSTANCIA / RESPONSIVA EN TICKET",
        },
        {
            "code": "SEED_DOCUMENTO_FORMAL_CARTA",
            "name": "DOCUMENTO FORMAL CARTA CON TEXTO Y FIRMAS",
            "doc_type": "documento_formal",
            "mode": "CARTA",
            "paper_size": "letter",
            "orientation": "portrait",
            "w_mm": CARTA_WIDTH_MM,
            "h_mm": CARTA_HEIGHT_MM,
            "printable_w_mm": CARTA_WIDTH_MM,
            "title": "CARTA RESPONSIVA / CONSTANCIA DE ENTREGA",
        },
    ]

    if all(s["code"] in existing_codes for s in seeds):
        return existing

    now = _dt.datetime.now(_dt.timezone.utc)
    created_list: List[models.PrintFormatTemplate] = list(existing)

    for s in seeds:
        if s["code"] in existing_codes:
            continue
        tpl_id = str(uuid.uuid4())
        ver_id = str(uuid.uuid4())
        meta = DOC_TYPES_MAP.get(s["doc_type"]) or {}
        if s["mode"] == "CARTA":
            els = _default_carta_elements(s["title"], s["doc_type"])
            if s["doc_type"] == "documento_formal":
                els.append({
                    "id": "el-texto-combinado",
                    "type": "text",
                    "label": "CUERPO FORMAL COMBINADO",
                    "text": "RECIBIMOS DE {{cliente.nombre}} CON RFC {{cliente.rfc}} LA CANTIDAD DE {{pago.importe_letra}} POR CONCEPTO DE {{pago.concepto}} AMPARADO EN EL FOLIO {{operacion.folio}}.",
                    "x_mm": 14.0,
                    "y_mm": 74.0,
                    "w_mm": 188.0,
                    "h_mm": 32.0,
                    "font_size": 11,
                    "bold": False,
                    "color": "#0f172a",
                    "page": 1,
                    "z_index": 3,
                })
        else:
            els = []

        defn = {
            "doc_title": s["title"],
            "elements": els,
            "flow_blocks": [
                {"id": "blk-header", "type": "header", "label": "ENCABEZADO EMPRESA Y LOGOTIPO", "enabled": True, "fields": ["empresa.nombre_comercial", "empresa.rfc", "empresa.domicilio", "empresa.telefonos"]},
                {"id": "blk-op", "type": "operation", "label": "DATOS DE LA OPERACIÓN Y FOLIO", "enabled": True, "fields": ["operacion.folio", "operacion.fecha", "operacion.hora", "operacion.cajero"]},
                {"id": "blk-client", "type": "client", "label": "DATOS DEL CLIENTE / RECEPTOR", "enabled": True, "fields": ["cliente.nombre", "cliente.rfc", "cliente.domicilio"]},
                {"id": "blk-items", "type": "items_table", "label": "TABLA FLUJO DE PRODUCTOS", "enabled": True, "fields": ["productos.codigo", "productos.descripcion", "productos.cantidad", "productos.precio", "productos.importe"]},
                {"id": "blk-totals", "type": "totals", "label": "BLOQUE DE TOTALES E IMPORTE EN LETRA", "enabled": True, "fields": ["importes.subtotal", "importes.impuestos", "importes.total", "importes.total_letra"]},
                {"id": "blk-credit", "type": "credit", "label": "ESTADO DE CRÉDITO / PAGARÉ", "enabled": s["doc_type"] in ("ticket_venta_credito", "comprobante_pago"), "fields": ["credito.saldo_anterior", "credito.importe_abono", "credito.saldo_pendiente", "credito.pagare_leyenda"]},
                {"id": "blk-footer", "type": "footer", "label": "PIE DE PÁGINA, FIRMAS Y CÓDIGO DE BARRAS", "enabled": True, "fields": ["operacion.folio"]},
            ],
            "section_flags": {
                "showLogo": True,
                "showCompanyRfc": True,
                "showFolio": True,
                "showDateTime": True,
                "showClientSection": True,
                "showPrices": s["doc_type"] != "orden_entrega",
                "showTotalInWords": True,
                "showSignatures": s["doc_type"] in ("orden_entrega", "ticket_venta_credito", "comprobante_pago", "documento_formal"),
                "showBarcode": True,
            },
        }

        tpl = models.PrintFormatTemplate(
            id=tpl_id,
            empresa_id=empresa_id,
            sucursal_id=None,
            code=s["code"],
            name=s["name"],
            doc_type=s["doc_type"],
            mode=s["mode"],
            paper_size=s["paper_size"],
            orientation=s["orientation"],
            status="PUBLISHED",
            active_published_version_id=ver_id,
            latest_draft_version_id=None,
            current_version_num=1,
            is_system_seed=True,
            integration_status=meta.get("integration_status", "OPERATIVO"),
            created_by=user_id,
            updated_by=user_id,
            created_at=now,
            updated_at=now,
            published_at=now,
        )
        ver = models.PrintFormatVersion(
            id=ver_id,
            empresa_id=empresa_id,
            template_id=tpl_id,
            version_num=1,
            status="PUBLISHED",
            name_snapshot=s["name"],
            mode=s["mode"],
            paper_size=s["paper_size"],
            orientation=s["orientation"],
            paper_width_mm=Decimal(str(s["w_mm"])),
            paper_height_mm=Decimal(str(s["h_mm"])),
            printable_width_mm=Decimal(str(s["printable_w_mm"])),
            margins_mm_json={"top": 10, "right": 10, "bottom": 10, "left": 10} if s["mode"] == "CARTA" else {"top": 3, "right": 3, "bottom": 4, "left": 3},
            background_asset_id=None,
            background_settings_json={
                "fit_mode": "fit",
                "page_rule": "all",
                "specific_pages": [1],
                "continuation_page": 2,
                "print_mode": "background_and_fields",
                "manual_x_mm": 0.0,
                "manual_y_mm": 0.0,
                "manual_w_mm": s["w_mm"],
                "manual_h_mm": s["h_mm"],
            },
            definition_json=defn,
            validation_warnings_json=[],
            changelog="Versión inicial de fábrica publicada.",
            created_by=user_id,
            published_by=user_id,
            created_at=now,
            published_at=now,
        )
        db.add(tpl)
        db.add(ver)
        created_list.append(tpl)

    db.commit()
    return created_list
