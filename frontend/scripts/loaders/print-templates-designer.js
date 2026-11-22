/* loaders/print-templates-designer.js — Motor Gráfico 100% Editable tipo Photoshop / CorelDRAW / Paint para CALEBSYS
   + Biblioteca de 10 Plantillas Precargadas Distintas para CADA Tipo de Formato en:
     1) CARTA (215.9 × 279.4 mm) — 10 Diseños Distintos 100% Movibles y Modificables por Capas
     2) TICKET 80 MM (80 × 210 mm) — 10 Diseños Distintos 100% Movibles y Modificables por Capas
     3) TICKET 58 MM (58 × 195 mm) — 10 Diseños Distintos 100% Movibles y Modificables por Capas
*/
(function (global) {
  'use strict';

  var LS_TEMPLATES_KEY = 'calebsys_print_templates_v1';
  var PX_PER_MM_BASE = 3.05;

  var _activeInternalTab = 'editor'; // 'biblioteca' | 'editor' | 'asignacion' | 'versiones'
  var _leftSegment = 'campos';       // 'campos' | 'elementos' | 'capas'
  var _openAccGroup = '';
  var _zoom = 0.85;
  var _activePageNum = 1;
  var _isDirty = false;
  var _undoStack = [];
  var _redoStack = [];
  var _dragState = null;
  var _uploadTargetMode = 'FREE_IMAGE';

  // Estado activo de la Biblioteca de 10 Plantillas Precargadas
  var _activePresetNumber = 1;       // 1 .. 10
  var _galleryDocType = 'cotizacion';
  var _galleryPaperFormat = 'letter'; // 'letter' | '80mm' | '58mm'

  var _backendCatalog = null;
  var _backendTemplates = [];
  var _activeBackendTpl = null;
  var _workingVersion = null;
  var _selectedElementId = 'f-cli-nombre';
  var _assignmentsList = [];
  var _emissionsList = [];

  /* ═══════════════════════════════════════════════════════════════════════════
     GENERADOR DE LOGOTIPOS VECTORIALES SVG POR PALETA DE COLOR (CAPAS DE IMAGEN MOVIBLES)
     ═══════════════════════════════════════════════════════════════════════════ */
  function buildLogoSvgDataUrl(primaryHex, secondaryHex, darkBgHex) {
    var p = primaryHex || '#b91c1c';
    var s = secondaryHex || '#1e3a8a';
    var bgRect = darkBgHex ? ('<rect width="320" height="78" rx="6" fill="' + darkBgHex + '"/>') : '';
    var txtFill = darkBgHex ? '#ffffff' : p;
    var subFill = darkBgHex ? '#93c5fd' : s;
    return 'data:image/svg+xml;utf8,' + encodeURIComponent(
      '<svg xmlns="http://www.w3.org/2000/svg" width="320" height="78" viewBox="0 0 320 78">' +
        bgRect +
        '<polygon points="8,42 32,16 44,22 20,48" fill="' + p + '" stroke="#ffffff" stroke-width="1"/>' +
        '<polygon points="20,52 44,26 56,32 32,58" fill="' + s + '" stroke="#ffffff" stroke-width="1"/>' +
        '<polygon points="32,62 56,36 68,42 44,68" fill="' + p + '" stroke="#ffffff" stroke-width="1"/>' +
        '<text x="80" y="42" font-family="Arial, sans-serif" font-size="30" font-weight="900" fill="' + txtFill + '" letter-spacing="1">MAGDALENO</text>' +
        '<text x="81" y="61" font-family="Arial, sans-serif" font-size="13" font-weight="800" fill="' + subFill + '" letter-spacing="1.4">MADERAS Y MATERIALES</text>' +
      '</svg>'
    );
  }

  var DEFAULT_MAGDALENO_LOGO_SVG = buildLogoSvgDataUrl('#b91c1c', '#1e3a8a', null);

  var SAMPLE_QR_SVG = 'data:image/svg+xml;utf8,' + encodeURIComponent(
    '<svg xmlns="http://www.w3.org/2000/svg" width="120" height="120" viewBox="0 0 120 120">' +
      '<rect width="120" height="120" fill="#ffffff" stroke="#0f172a" stroke-width="4"/>' +
      '<rect x="10" y="10" width="32" height="32" fill="none" stroke="#0f172a" stroke-width="6"/>' +
      '<rect x="18" y="18" width="16" height="16" fill="#0f172a"/>' +
      '<rect x="78" y="10" width="32" height="32" fill="none" stroke="#0f172a" stroke-width="6"/>' +
      '<rect x="86" y="18" width="16" height="16" fill="#0f172a"/>' +
      '<rect x="10" y="78" width="32" height="32" fill="none" stroke="#0f172a" stroke-width="6"/>' +
      '<rect x="18" y="86" width="16" height="16" fill="#0f172a"/>' +
      '<rect x="52" y="14" width="10" height="10" fill="#0f172a"/>' +
      '<rect x="52" y="34" width="18" height="10" fill="#0f172a"/>' +
      '<rect x="48" y="52" width="22" height="22" fill="#0f172a"/>' +
      '<rect x="80" y="54" width="14" height="24" fill="#0f172a"/>' +
      '<rect x="52" y="84" width="24" height="12" fill="#0f172a"/>' +
      '<rect x="84" y="86" width="22" height="22" fill="#0f172a"/>' +
    '</svg>'
  );

  /* ═══════════════════════════════════════════════════════════════════════════
     CATÁLOGO DE TIPOS DE DOCUMENTO Y DE LAS 10 PLANTILLAS PRECARGADAS DISTINTAS
     ═══════════════════════════════════════════════════════════════════════════ */
  var DOC_TYPES_LIST = [
    { id: 'cotizacion', name: 'Cotización Comercial', shortTitle: 'COTIZACIÓN', icon: 'fa-file-lines' },
    { id: 'ticket_venta_contado', name: 'Ticket / Nota de Venta Contado', shortTitle: 'NOTA DE VENTA DE CONTADO', icon: 'fa-receipt' },
    { id: 'ticket_venta_credito', name: 'Nota / Ticket de Crédito y Pagaré', shortTitle: 'NOTA DE CRÉDITO Y PAGARÉ', icon: 'fa-handshake' },
    { id: 'corte_ciego', name: 'Corte Ciego (Conteo Físico sin Esperado)', shortTitle: 'CORTE CIEGO DE CAJA · SOBRE TÓMBOLA', icon: 'fa-eye-slash' },
    { id: 'corte_x', name: 'Corte X (Arqueo Parcial Turno Abierto)', shortTitle: 'CORTE X · ARQUEO PARCIAL EN TURNO', icon: 'fa-chart-pie' },
    { id: 'corte_z', name: 'Corte Z / Cierre Definitivo de Turno', shortTitle: 'CORTE Z · CIERRE DEFINITIVO DE CAJA', icon: 'fa-cash-register' },
    { id: 'apertura_caja', name: 'Apertura de Caja (Fondo Inicial)', shortTitle: 'APERTURA DE CAJA Y FONDO FIJO', icon: 'fa-Lock-open' },
    { id: 'orden_entrega', name: 'Orden de Entrega / Almacén', shortTitle: 'ORDEN DE ENTREGA DE MATERIAL', icon: 'fa-truck-ramp-box' },
    { id: 'comprobante_pago', name: 'Comprobante de Pago / Abono', shortTitle: 'COMPROBANTE DE PAGO / ABONO', icon: 'fa-money-bill-transfer' },
    { id: 'cfdi_factura_ticket', name: 'Factura CFDI 4.0 (Ticket y Carta)', shortTitle: 'FACTURA CFDI 4.0', icon: 'fa-file-invoice-dollar' },
    { id: 'devolucion', name: 'Nota de Crédito / Devolución', shortTitle: 'NOTA DE CRÉDITO / DEVOLUCIÓN', icon: 'fa-rotate-left' },
    { id: 'remision', name: 'Remisión de Salida', shortTitle: 'REMISIÓN DE MATERIALES', icon: 'fa-clipboard-check' },
    { id: 'orden_compra', name: 'Orden de Compra Proveedor', shortTitle: 'ORDEN DE COMPRA', icon: 'fa-cart-flatbed' },
    { id: 'estado_cuenta_cliente', name: 'Estado de Cuenta Cliente', shortTitle: 'ESTADO DE CUENTA', icon: 'fa-scale-balanced' },
    { id: 'documento_formal', name: 'Carta / Contrato Formal', shortTitle: 'CARTA RESPONSIVA FORMAL', icon: 'fa-file-signature' }
  ];

  var TEN_PRESET_STYLES = [
    { num: 1, code: 'MOD_01_HOME_DEPOT_PRO', name: '01 · Home Depot Pro (Obra + Checklist + PROFECO)', subtitle: 'Doble panel Cliente/Obra, código de barras superior, checklist de carga y cláusula Art. 77 LFPC', primary: '#c2410c', secondary: '#18181b', badgeBg: '#ffedd5', layoutKind: 'homedepot_pro' },
    { num: 2, code: 'MOD_02_COSTCO_SAMS_CLUB', name: '02 · Costco / Sam’s Mayorista (Auditoría Puerta)', subtitle: 'Logo centrado, barra de membresía/RFC, conteo de bultos verificados en salida y garantía PROFECO', primary: '#1e3a8a', secondary: '#dc2626', badgeBg: '#dbeafe', layoutKind: 'costco_wholesale' },
    { num: 3, code: 'MOD_03_WALMART_SUPERCENTER', name: '03 · Walmart Retail (Precios Claros PROFECO)', subtitle: 'Tira de precios claros NOM-030-SCFI, tabla amplia y pie simétrico en 3 columnas (QR / PROFECO / Totales)', primary: '#0369a1', secondary: '#eab308', badgeBg: '#e0f2fe', layoutKind: 'walmart_retail' },
    { num: 4, code: 'MOD_04_LIVERPOOL_DEPARTAMENTAL', name: '04 · Liverpool / Palacio (Marco Editorial + Póliza)', subtitle: 'Marco perimetral completo, medallón de folio, tabla fina y talón inferior de garantía PROFECO', primary: '#9d174d', secondary: '#334155', badgeBg: '#fce7f3', layoutKind: 'liverpool_frame' },
    { num: 5, code: 'MOD_05_OXXO_EXPRESS_CAJA', name: '05 · OXXO / 7-Eleven Express (Cuadrícula 4 Celdas)', subtitle: 'Cintillo bicolor, cuadrícula rápida Folio/Caja/Cajero/Hora, desglose directo de IVA y aviso consumidor', primary: '#b91c1c', secondary: '#f59e0b', badgeBg: '#fee2e2', layoutKind: 'oxxo_grid' },
    { num: 6, code: 'MOD_06_CEMEX_CONSTRURAMA_PATIO', name: '06 · Cemex / Construrama (Patio, Báscula y Placas)', subtitle: 'Panel de Chofer/Placas/Maniobra, barra de despacho en patio, IVA desglosado y 3 firmas operativas', primary: '#1d4ed8', secondary: '#dc2626', badgeBg: '#dbeafe', layoutKind: 'cemex_patio' },
    { num: 7, code: 'MOD_07_COPPEL_ELEKTRA_CREDITO', name: '07 · Coppel / Elektra (Saldos + Pagaré Mercantil)', subtitle: 'Tablero de 3 cajas (Saldo Anterior → Abono → Saldo Actual), pagaré mercantil oficial y firma deudor', primary: '#3730a3', secondary: '#ca8a04', badgeBg: '#e0e7ff', layoutKind: 'coppel_credit' },
    { num: 8, code: 'MOD_08_SAT_CFDI40_ANEXO20', name: '08 · SAT CFDI 4.0 Anexo 20 (Doble Panel Fiscal)', subtitle: 'Paneles gemelos Emisor/Receptor, caja UUID, tabla desglosada S/IVA+IVA+C/IVA y Sello QR + Serie Sello', primary: '#065f46', secondary: '#047857', badgeBg: '#d1fae5', layoutKind: 'sat_anexo20' },
    { num: 9, code: 'MOD_09_AMAZON_MELI_LOGISTICS', name: '09 · Amazon / MercadoLibre (Guía + QR Superior)', subtitle: 'QR de rastreo arriba a la izquierda, caja gigante de domicilio de entrega y talón de acuse con INE', primary: '#0f172a', secondary: '#d97706', badgeBg: '#fef3c7', layoutKind: 'amazon_logistics' },
    { num: 10, code: 'MOD_10_APPLE_MINIMAL_SWISS', name: '10 · Apple Store / Suizo (Columna Izquierda Datos)', subtitle: 'Rejilla asimétrica B/N: columna izquierda de metadatos/QR/Sellos y lienzo derecho limpio sin bordes', primary: '#09090b', secondary: '#52525b', badgeBg: '#f4f4f5', layoutKind: 'apple_asymmetric' },
    { num: 11, code: 'MOD_11_AUTOZONE_TECNICO', name: '11 · AutoZone / Refaccionaria (Header Invertido)', subtitle: 'Encabezado oscuro invertido con folio en caja blanca, énfasis en SKU y póliza de garantía por defecto', primary: '#9a3412', secondary: '#18181b', badgeBg: '#ffedd5', layoutKind: 'autozone_inverted' },
    { num: 12, code: 'MOD_12_SEARS_CORPORATIVO', name: '12 · Sears / Sanborns (Columna Lateral Vertical)', subtitle: 'Barra vertical lateral a todo lo alto, membrete escalonado, caja de cliente y cláusulas LFPC', primary: '#991b1b', secondary: '#1e293b', badgeBg: '#fef2f2', layoutKind: 'sears_sidebar' },
    { num: 13, code: 'MOD_13_OFFICE_DEPOT_MAYOREO', name: '13 · Office Depot Corporativo (Autofacturación)', subtitle: 'Encabezado tripartito, tabla cebrada y recuadro inferior de instrucciones para autofacturación CFDI', primary: '#b91c1c', secondary: '#334155', badgeBg: '#fee2e2', layoutKind: 'officedepot_corp' },
    { num: 14, code: 'MOD_14_TRUPER_DISTRIBUIDOR', name: '14 · Truper Ferretero (Comparativo Sin/Con IVA)', subtitle: 'Doble cintillo industrial naranja/grafito, precios sin IVA y con IVA y totales doblemente resaltados', primary: '#d97706', secondary: '#18181b', badgeBg: '#fef3c7', layoutKind: 'truper_industrial' },
    { num: 15, code: 'MOD_15_BBVA_BANCARIO_BOVEDA', name: '15 · BBVA / Santander (Ficha Bancaria de Bóveda)', subtitle: 'Diseño financiero de alta seguridad con sello horario, referencia bancaria e importe en letra enmarcado', primary: '#1e3a8a', secondary: '#0284c7', badgeBg: '#e0f2fe', layoutKind: 'bbva_vault' },
    { num: 16, code: 'MOD_16_CORTE_CIEGO_TOMBOLA', name: '16 · Corte Ciego Oficial (Conteo sin Esperado)', subtitle: 'Tabla de conteo físico de Billetes ($1000-$20), Monedas y Vouchers sin revelar el saldo del sistema', primary: '#4338ca', secondary: '#1e1b4b', badgeBg: '#e0e7ff', layoutKind: 'corte_ciego_pro' },
    { num: 17, code: 'MOD_17_CORTE_X_SUPERVISION', name: '17 · Corte X Parcial (Flujo Gaveta Turno Abierto)', subtitle: 'Arqueo intra-turno: (+) Fondo (+) Ventas (-) Retiros = Efectivo Esperado + Desglose Formas de Pago', primary: '#0f766e', secondary: '#134e4a', badgeBg: '#ccfbf1', layoutKind: 'corte_x_pro' },
    { num: 18, code: 'MOD_18_CORTE_Z_CIERRE_DIA', name: '18 · Corte Z Oficial (Conciliación Cierre y Cuadre)', subtitle: 'Cierre definitivo: Tabla Sistema Esperado vs. Cajero Declarado vs. Diferencia Sobrante/Faltante + 3 Firmas', primary: '#15803d', secondary: '#14532d', badgeBg: '#dcfce7', layoutKind: 'corte_z_pro' },
    { num: 19, code: 'MOD_19_NOTARIAL_CONTRATO_LEGAL', name: '19 · Notarial / Jurídico (Contrato y Pagaré Legal)', subtitle: 'Estructura simétrica solemne con cuerpo declarativo combinado, cláusulas PROFECO y firma con testigos', primary: '#7c2d12', secondary: '#431407', badgeBg: '#ffedd5', layoutKind: 'notarial_legal' },
    { num: 20, code: 'MOD_20_PAPEL_PREIMPRESO_LIMPIO', name: '20 · Papel Preimpreso (Solo Campos Milimétricos)', subtitle: 'Sin fondos ni adornos gráficos: campos puros listos para ajustar sobre papelería membretada física', primary: '#334155', secondary: '#64748b', badgeBg: '#f8fafc', layoutKind: 'preprinted_clean' }
  ];

  var BINDING_OPTIONS = [
    { key: '', label: '— Sin vinculación (Texto / Imagen libre) —', defaultName: 'Elemento libre', token: '' },
    { key: 'cliente.nombre', label: 'Cliente → Nombre', defaultName: 'Nombre del cliente', token: '{{cliente.nombre}}' },
    { key: 'cliente.domicilio', label: 'Cliente → Dirección', defaultName: 'Dirección del cliente', token: '{{cliente.direccion}}' },
    { key: 'cliente.telefono', label: 'Cliente → Teléfono', defaultName: 'Teléfono del cliente', token: '{{cliente.telefono}}' },
    { key: 'cliente.correo', label: 'Cliente → Correo', defaultName: 'Correo del cliente', token: '{{cliente.correo}}' },
    { key: 'cliente.rfc', label: 'Cliente → RFC', defaultName: 'RFC del cliente', token: '{{cliente.rfc}}' },
    { key: 'operacion.folio', label: 'Documento → Folio', defaultName: 'Folio del documento', token: '{{documento.folio}}' },
    { key: 'operacion.fecha', label: 'Documento → Fecha', defaultName: 'Fecha de emisión', token: '{{documento.fecha}}' },
    { key: 'operacion.hora', label: 'Documento → Hora', defaultName: 'Hora de emisión', token: '{{operacion.hora}}' },
    { key: 'operacion.vendedor', label: 'Documento → Vendedor', defaultName: 'Ejecutivo de ventas', token: '{{operacion.vendedor}}' },
    { key: 'productos.precio_sin_iva', label: 'Artículo → Precio Unitario SIN IVA', defaultName: 'Precio Unitario SIN IVA', token: 'P.U. s/IVA: {{productos.precio_sin_iva}}' },
    { key: 'productos.precio_con_iva', label: 'Artículo → Precio Unitario CON IVA', defaultName: 'Precio Unitario CON IVA', token: 'P.U. c/IVA: {{productos.precio_con_iva}}' },
    { key: 'productos.iva_articulo', label: 'Artículo → Impuesto IVA Artículo (16%)', defaultName: 'IVA del Artículo (16%)', token: 'IVA Art.: {{productos.iva_articulo}}' },
    { key: 'productos.importe_sin_iva', label: 'Artículo → Total del Artículo SIN IVA', defaultName: 'Total del Artículo SIN IVA', token: 'Total Art. SIN IVA: {{productos.importe_sin_iva}}' },
    { key: 'productos.importe_con_iva', label: 'Artículo → Total del Artículo CON IVA', defaultName: 'Total del Artículo CON IVA', token: 'Total Art. CON IVA: {{productos.importe_con_iva}}' },
    { key: 'importes.subtotal_sin_iva', label: 'Totales → Subtotal SIN IVA (Por separado)', defaultName: 'Subtotal SIN IVA', token: 'Subtotal SIN IVA: {{importes.subtotal_sin_iva}}' },
    { key: 'importes.impuesto_total', label: 'Totales → Impuesto Total IVA 16% (Por separado)', defaultName: 'Impuesto Total (IVA 16%)', token: 'Impuesto Total (IVA 16%): {{importes.impuesto_total}}' },
    { key: 'importes.subtotal_con_iva', label: 'Totales → Subtotal CON IVA (Por separado)', defaultName: 'Subtotal CON IVA', token: 'Subtotal CON IVA: {{importes.subtotal_con_iva}}' },
    { key: 'importes.total_sin_iva', label: 'Totales → Total SIN IVA', defaultName: 'Total SIN IVA', token: 'Total SIN IVA: {{importes.total_sin_iva}}' },
    { key: 'importes.total_con_iva', label: 'Totales → Total CON IVA (Neto)', defaultName: 'Total CON IVA', token: 'Total CON IVA: {{importes.total_con_iva}}' },
    { key: 'importes.subtotal', label: 'Totales → Subtotal', defaultName: 'Subtotal', token: '{{totales.subtotal}}' },
    { key: 'importes.impuestos', label: 'Totales → IVA (16%)', defaultName: 'IVA (16%)', token: '{{totales.iva}}' },
    { key: 'importes.total', label: 'Totales → Total', defaultName: 'Total del documento', token: '{{totales.total}}' },
    { key: 'importes.total_letra', label: 'Totales → Total con letra', defaultName: 'Importe con letra', token: '{{importes.total_letra}}' },
    { key: 'empresa.nombre_comercial', label: 'Empresa → Nombre comercial', defaultName: 'Nombre empresa', token: '{{empresa.nombre_comercial}}' },
    { key: 'empresa.rfc', label: 'Empresa → RFC', defaultName: 'RFC empresa', token: '{{empresa.rfc}}' },
    { key: 'credito.saldo_anterior', label: 'Crédito / Nota Crédito → Saldo Anterior', defaultName: 'Saldo anterior', token: 'Saldo Anterior: {{credito.saldo_anterior}}' },
    { key: 'credito.importe_abono', label: 'Crédito / Nota Crédito → Cargo / Abono', defaultName: 'Cargo o abono', token: 'Cargo / Abono: {{credito.importe_abono}}' },
    { key: 'credito.saldo_actual', label: 'Crédito / Nota Crédito → Saldo Actual', defaultName: 'Saldo actual', token: 'Saldo Actual: {{credito.saldo_actual}}' },
    { key: 'credito.saldo_pendiente', label: 'Crédito / Nota Crédito → Saldo Pendiente', defaultName: 'Saldo pendiente', token: 'Saldo Pendiente: {{credito.saldo_pendiente}}' },
    { key: 'credito.limite_credito', label: 'Crédito → Límite de crédito', defaultName: 'Límite de crédito', token: 'Límite: {{credito.limite_credito}}' },
    { key: 'credito.pagare_leyenda', label: 'Crédito → Pagaré Mercantil', defaultName: 'Pagaré Mercantil', token: '{{credito.pagare_leyenda}}' },
    { key: 'entrega.domicilio', label: 'Entrega → Domicilio de obra', defaultName: 'Domicilio de entrega', token: '{{entrega.domicilio}}' },
    { key: 'cfdi.qr_sat', label: 'CFDI / Ticket → Sello QR Fiscal (Por separado)', defaultName: 'Sello QR Fiscal SAT', token: '{{cfdi.qr_sat}}' },
    { key: 'cfdi.serie_sello', label: 'CFDI / Ticket → Serie del Sello CSD (Por separado)', defaultName: 'Serie del Sello CSD', token: 'Serie Sello CSD: {{cfdi.serie_sello}}' },
    { key: 'cfdi.no_cert_emisor', label: 'CFDI / Ticket → No. Certificado Emisor', defaultName: 'No. Certificado Emisor', token: 'No. Cert. Emisor: {{cfdi.no_cert_emisor}}' },
    { key: 'cfdi.no_cert_sat', label: 'CFDI / Ticket → Serie del Sello SAT', defaultName: 'Serie del Sello SAT', token: 'Serie Sello SAT: {{cfdi.no_cert_sat}}' },
    { key: 'cfdi.sello_cfdi', label: 'CFDI / Ticket → Sello Digital CFDI', defaultName: 'Sello Digital CFDI', token: 'Sello CFDI: {{cfdi.sello_cfdi}}' },
    { key: 'cfdi.sello_sat', label: 'CFDI / Ticket → Sello Digital SAT', defaultName: 'Sello Digital SAT', token: 'Sello SAT: {{cfdi.sello_sat}}' },
    { key: 'cfdi.cadena_original', label: 'CFDI / Ticket → Cadena Original SAT', defaultName: 'Cadena Original SAT', token: '{{cfdi.cadena_original}}' },
    { key: 'cfdi.uuid', label: 'CFDI → Folio Fiscal UUID', defaultName: 'Folio Fiscal UUID', token: 'UUID: {{cfdi.uuid}}' },
    { key: 'corte.tipo_corte', label: 'Corte de Caja → Tipo de Corte (Ciego / X / Z)', defaultName: 'Tipo de Corte', token: 'MODALIDAD: {{corte.tipo_corte}}' },
    { key: 'corte.turno', label: 'Corte de Caja → Turno Operativo', defaultName: 'Turno Operativo', token: 'Turno: {{corte.turno}}' },
    { key: 'corte.folio_inicial', label: 'Corte de Caja → Folio Inicial del Turno', defaultName: 'Folio Inicial', token: 'Folio Inicial: {{corte.folio_inicial}}' },
    { key: 'corte.folio_final', label: 'Corte de Caja → Folio Final del Turno', defaultName: 'Folio Final', token: 'Folio Final: {{corte.folio_final}}' },
    { key: 'corte.num_operaciones', label: 'Corte de Caja → Número de Operaciones', defaultName: 'No. Operaciones', token: 'Operaciones: {{corte.num_operaciones}}' },
    { key: 'corte.fondo_inicial', label: 'Corte de Caja → (+) Fondo Inicial de Caja', defaultName: 'Fondo Inicial', token: '(+) Fondo Inicial: {{corte.fondo_inicial}}' },
    { key: 'corte.ventas_efectivo', label: 'Corte de Caja → (+) Ventas en Efectivo', defaultName: 'Ventas en Efectivo', token: '(+) Ventas Efectivo: {{corte.ventas_efectivo}}' },
    { key: 'corte.abonos_efectivo', label: 'Corte de Caja → (+) Cobranza / Abonos Efectivo', defaultName: 'Abonos Efectivo', token: '(+) Abonos CxC Efectivo: {{corte.abonos_efectivo}}' },
    { key: 'corte.entradas_efectivo', label: 'Corte de Caja → (+) Otras Entradas de Efectivo', defaultName: 'Entradas de Efectivo', token: '(+) Entradas Efectivo: {{corte.entradas_efectivo}}' },
    { key: 'corte.retiros_fajillas', label: 'Corte de Caja → (-) Retiros Parciales / Fajillas Tómbola', defaultName: 'Retiros / Fajillas', token: '(-) Retiros / Fajillas: {{corte.retiros_fajillas}}' },
    { key: 'corte.salidas_gastos', label: 'Corte de Caja → (-) Salidas / Gastos de Caja Chica', defaultName: 'Gastos de Caja', token: '(-) Gastos Caja: {{corte.salidas_gastos}}' },
    { key: 'corte.devoluciones_efectivo', label: 'Corte de Caja → (-) Devoluciones en Efectivo', defaultName: 'Devoluciones Efectivo', token: '(-) Devoluciones Efectivo: {{corte.devoluciones_efectivo}}' },
    { key: 'corte.efectivo_esperado', label: 'Corte X/Z → (=) Efectivo Esperado en Gaveta (Sistema)', defaultName: 'Efectivo Esperado Sistema', token: '(=) Efectivo Esperado: {{corte.efectivo_esperado}}' },
    { key: 'corte.efectivo_declarado', label: 'Corte Ciego/Z → Efectivo Físico Declarado por Cajero', defaultName: 'Efectivo Declarado Cajero', token: 'Efectivo Declarado: {{corte.efectivo_declarado}}' },
    { key: 'corte.diferencia_efectivo', label: 'Corte Z → Diferencia Efectivo (Sobrante / Faltante)', defaultName: 'Diferencia en Efectivo', token: 'Diferencia Efectivo: {{corte.diferencia_efectivo}}' },
    { key: 'corte.ventas_tarjeta_debito', label: 'Corte de Caja → Ventas Tarjeta Débito', defaultName: 'Ventas Tarjeta Débito', token: 'Tarjeta Débito: {{corte.ventas_tarjeta_debito}}' },
    { key: 'corte.ventas_tarjeta_credito', label: 'Corte de Caja → Ventas Tarjeta Crédito', defaultName: 'Ventas Tarjeta Crédito', token: 'Tarjeta Crédito: {{corte.ventas_tarjeta_credito}}' },
    { key: 'corte.tarjetas_declaradas', label: 'Corte Ciego/Z → Vouchers Tarjetas Declarados', defaultName: 'Vouchers Declarados', token: 'Vouchers Declarados: {{corte.tarjetas_declaradas}}' },
    { key: 'corte.ventas_transferencia', label: 'Corte de Caja → Ventas Transferencia SPEI', defaultName: 'Ventas SPEI', token: 'Transferencia SPEI: {{corte.ventas_transferencia}}' },
    { key: 'corte.ventas_credito_otorgado', label: 'Corte de Caja → Ventas a Crédito Otorgado (CxC)', defaultName: 'Ventas Crédito CxC', token: 'Crédito Otorgado CxC: {{corte.ventas_credito_otorgado}}' },
    { key: 'corte.desglose_denominaciones', label: 'Corte Ciego/Z → Desglose Billetes y Monedas', defaultName: 'Arqueo de Denominaciones', token: '{{corte.desglose_denominaciones}}' },
    { key: 'corte.total_esperado_general', label: 'Corte X/Z → Total General Esperado Sistema', defaultName: 'Total Esperado General', token: 'TOTAL ESPERADO SISTEMA: {{corte.total_esperado_general}}' },
    { key: 'corte.total_declarado_general', label: 'Corte Ciego/Z → Total General Declarado Cajero', defaultName: 'Total Declarado General', token: 'TOTAL DECLARADO CAJERO: {{corte.total_declarado_general}}' },
    { key: 'corte.diferencia_neta', label: 'Corte Z → Diferencia Neta Total del Turno', defaultName: 'Diferencia Neta Total', token: 'DIFERENCIA NETA: {{corte.diferencia_neta}}' },
    { key: 'corte.estado_cuadre', label: 'Corte Z → Dictamen de Conciliación y Cuadre', defaultName: 'Dictamen de Cuadre', token: 'DICTAMEN: {{corte.estado_cuadre}}' },
    { key: 'corte.folio_sobre', label: 'Corte Ciego/Z → Folio Sobre de Valores / Tómbola', defaultName: 'Folio Sobre Tómbola', token: 'Sobre Tómbola: {{corte.folio_sobre}}' },
    { key: 'corte.supervisor_autoriza', label: 'Corte de Caja → Supervisor / Auditor que Autoriza', defaultName: 'Supervisor Autoriza', token: 'Autoriza: {{corte.supervisor_autoriza}}' },
    { key: 'profeco.leyenda_garantias', label: 'PROFECO → Cláusula de Garantía y Cambios (LFPC Art. 77)', defaultName: 'Cláusula Garantía PROFECO', token: '{{profeco.leyenda_garantias}}' },
    { key: 'profeco.leyenda_consumidor', label: 'PROFECO → Normatividad Precios con IVA (LFPC Art. 12)', defaultName: 'Normatividad PROFECO', token: '{{profeco.leyenda_consumidor}}' },
    { key: 'profeco.plazo_facturacion', label: 'SAT / PROFECO → Regla Autofacturación CFDI 4.0', defaultName: 'Regla Autofacturación', token: '{{profeco.plazo_facturacion}}' },
    { key: 'profeco.unidad_medida_nom', label: 'NOM-030-SCFI → Certificación de Unidad y Precio', defaultName: 'Certificación NOM-030-SCFI', token: '{{profeco.unidad_medida_nom}}' }
  ];

  var DATA_SOURCES_TREE = [
    {
      id: 'empresa',
      icon: 'fa-building',
      label: 'Empresa',
      fields: [
        { key: 'empresa.nombre_comercial', name: 'Nombre comercial', token: '{{empresa.nombre_comercial}}' },
        { key: 'empresa.rfc', name: 'RFC Emisor', token: '{{empresa.rfc}}' },
        { key: 'empresa.domicilio', name: 'Domicilio fiscal', token: '{{empresa.domicilio}}' },
        { key: 'empresa.telefonos', name: 'Teléfonos', token: '{{empresa.telefonos}}' }
      ]
    },
    {
      id: 'cliente',
      icon: 'fa-user',
      label: 'Cliente',
      fields: [
        { key: 'cliente.nombre', name: 'Nombre del cliente', token: '{{cliente.nombre}}' },
        { key: 'cliente.domicilio', name: 'Dirección', token: '{{cliente.direccion}}' },
        { key: 'cliente.telefono', name: 'Teléfono', token: '{{cliente.telefono}}' },
        { key: 'cliente.correo', name: 'Correo', token: '{{cliente.correo}}' },
        { key: 'cliente.rfc', name: 'RFC Cliente', token: '{{cliente.rfc}}' }
      ]
    },
    {
      id: 'documento',
      icon: 'fa-file-lines',
      label: 'Documento',
      fields: [
        { key: 'operacion.folio', name: 'Folio', token: '{{documento.folio}}' },
        { key: 'operacion.fecha', name: 'Fecha', token: '{{documento.fecha}}' },
        { key: 'operacion.hora', name: 'Hora', token: '{{operacion.hora}}' },
        { key: 'operacion.vendedor', name: 'Vendedor / Ejecutivo', token: '{{operacion.vendedor}}' }
      ]
    },
    {
      id: 'corte_caja',
      icon: 'fa-cash-register',
      label: 'Cortes de Caja (Ciego, X y Z)',
      fields: [
        { key: 'corte.tipo_corte', name: 'Tipo de Corte (Ciego / X / Z)', token: 'MODALIDAD: {{corte.tipo_corte}}' },
        { key: 'corte.turno', name: 'Turno y Horario', token: 'Turno: {{corte.turno}}' },
        { key: 'corte.folio_inicial', name: 'Folio Inicial Turno', token: 'Folio Inicial: {{corte.folio_inicial}}' },
        { key: 'corte.folio_final', name: 'Folio Final Turno', token: 'Folio Final: {{corte.folio_final}}' },
        { key: 'corte.num_operaciones', name: 'Total Operaciones', token: 'Operaciones: {{corte.num_operaciones}}' },
        { key: 'corte.fondo_inicial', name: '(+) Fondo Inicial Caja', token: '(+) Fondo Inicial: {{corte.fondo_inicial}}' },
        { key: 'corte.ventas_efectivo', name: '(+) Ventas en Efectivo', token: '(+) Ventas Efectivo: {{corte.ventas_efectivo}}' },
        { key: 'corte.abonos_efectivo', name: '(+) Abonos CxC Efectivo', token: '(+) Abonos CxC Efectivo: {{corte.abonos_efectivo}}' },
        { key: 'corte.retiros_fajillas', name: '(-) Retiros / Fajillas Tómbola', token: '(-) Retiros / Fajillas: {{corte.retiros_fajillas}}' },
        { key: 'corte.salidas_gastos', name: '(-) Gastos Caja Chica', token: '(-) Gastos Caja: {{corte.salidas_gastos}}' },
        { key: 'corte.efectivo_esperado', name: '(=) Efectivo Esperado (Corte X/Z)', token: '(=) Efectivo Esperado: {{corte.efectivo_esperado}}' },
        { key: 'corte.efectivo_declarado', name: 'Efectivo Declarado (Corte Ciego/Z)', token: 'Efectivo Declarado: {{corte.efectivo_declarado}}' },
        { key: 'corte.diferencia_efectivo', name: 'Diferencia Efectivo (Corte Z)', token: 'Diferencia Efectivo: {{corte.diferencia_efectivo}}' },
        { key: 'corte.ventas_tarjeta_debito', name: 'Ventas Tarjeta Débito', token: 'Tarjeta Débito: {{corte.ventas_tarjeta_debito}}' },
        { key: 'corte.ventas_tarjeta_credito', name: 'Ventas Tarjeta Crédito', token: 'Tarjeta Crédito: {{corte.ventas_tarjeta_credito}}' },
        { key: 'corte.tarjetas_declaradas', name: 'Vouchers Tarjetas Declarados', token: 'Vouchers Declarados: {{corte.tarjetas_declaradas}}' },
        { key: 'corte.ventas_transferencia', name: 'Transferencias SPEI', token: 'Transferencia SPEI: {{corte.ventas_transferencia}}' },
        { key: 'corte.ventas_credito_otorgado', name: 'Crédito Otorgado (CxC)', token: 'Crédito Otorgado CxC: {{corte.ventas_credito_otorgado}}' },
        { key: 'corte.total_esperado_general', name: 'Total Esperado Sistema (X/Z)', token: 'TOTAL ESPERADO SISTEMA: {{corte.total_esperado_general}}' },
        { key: 'corte.total_declarado_general', name: 'Total Declarado Cajero (Ciego/Z)', token: 'TOTAL DECLARADO CAJERO: {{corte.total_declarado_general}}' },
        { key: 'corte.diferencia_neta', name: 'Diferencia Neta (Sobrante/Faltante)', token: 'DIFERENCIA NETA: {{corte.diferencia_neta}}' },
        { key: 'corte.estado_cuadre', name: 'Dictamen de Cuadre (Exacto/Dif)', token: 'DICTAMEN: {{corte.estado_cuadre}}' },
        { key: 'corte.folio_sobre', name: 'Folio Sobre / Tómbola', token: 'Sobre Tómbola: {{corte.folio_sobre}}' },
        { key: 'corte.supervisor_autoriza', name: 'Supervisor que Autoriza', token: 'Autoriza: {{corte.supervisor_autoriza}}' }
      ]
    },
    {
      id: 'credito_saldos',
      icon: 'fa-scale-balanced',
      label: 'Notas de Crédito y Saldos',
      fields: [
        { key: 'credito.saldo_anterior', name: 'Saldo Anterior (Por separado)', token: 'Saldo Anterior: {{credito.saldo_anterior}}' },
        { key: 'credito.importe_abono', name: 'Cargo / Abono Operación', token: 'Cargo / Abono: {{credito.importe_abono}}' },
        { key: 'credito.saldo_actual', name: 'Saldo Actual (Por separado)', token: 'Saldo Actual: {{credito.saldo_actual}}' },
        { key: 'credito.limite_credito', name: 'Límite de Crédito', token: 'Límite: {{credito.limite_credito}}' },
        { key: 'credito.pagare_leyenda', name: 'Pagaré Mercantil', token: '{{credito.pagare_leyenda}}' }
      ]
    },
    {
      id: 'cfdi_sellos',
      icon: 'fa-qrcode',
      label: 'Sello QR y Serie Sello (CFDI)',
      fields: [
        { key: 'cfdi.qr_sat', name: 'Sello QR Fiscal (Por separado)', token: '{{cfdi.qr_sat}}', isQrLayer: true },
        { key: 'cfdi.serie_sello', name: 'Serie del Sello CSD (Por separado)', token: 'Serie Sello CSD: {{cfdi.serie_sello}}' },
        { key: 'cfdi.no_cert_sat', name: 'Serie del Sello SAT (Por separado)', token: 'Serie Sello SAT: {{cfdi.no_cert_sat}}' },
        { key: 'cfdi.uuid', name: 'Folio Fiscal UUID', token: 'UUID: {{cfdi.uuid}}' },
        { key: 'cfdi.sello_cfdi', name: 'Sello Digital CFDI', token: 'Sello CFDI: {{cfdi.sello_cfdi}}' },
        { key: 'cfdi.sello_sat', name: 'Sello Digital SAT', token: 'Sello SAT: {{cfdi.sello_sat}}' },
        { key: 'cfdi.cadena_original', name: 'Cadena Original SAT', token: '{{cfdi.cadena_original}}' }
      ]
    },
    {
      id: 'profeco_reglamentos',
      icon: 'fa-shield-halved',
      label: 'PROFECO y Reglamentos Oficiales',
      fields: [
        { key: 'profeco.leyenda_garantias', name: 'Cláusula Garantía PROFECO (Art. 77)', token: '{{profeco.leyenda_garantias}}' },
        { key: 'profeco.leyenda_consumidor', name: 'Normatividad Precios con IVA (Art. 12)', token: '{{profeco.leyenda_consumidor}}' },
        { key: 'profeco.plazo_facturacion', name: 'Regla Autofacturación SAT CFDI 4.0', token: '{{profeco.plazo_facturacion}}' },
        { key: 'profeco.unidad_medida_nom', name: 'Certificación NOM-030-SCFI', token: '{{profeco.unidad_medida_nom}}' }
      ]
    },
    {
      id: 'productos',
      icon: 'fa-cube',
      label: 'Artículos (Con IVA / Sin IVA)',
      fields: [
        { key: 'productos.codigo', name: 'Código / SKU', token: '{{productos.codigo}}' },
        { key: 'productos.descripcion', name: 'Descripción', token: '{{productos.descripcion}}' },
        { key: 'productos.cantidad', name: 'Cantidad', token: '{{productos.cantidad}}' },
        { key: 'productos.precio_sin_iva', name: 'Precio Unitario SIN IVA', token: 'P.U. SIN IVA: {{productos.precio_sin_iva}}' },
        { key: 'productos.precio_con_iva', name: 'Precio Unitario CON IVA', token: 'P.U. CON IVA: {{productos.precio_con_iva}}' },
        { key: 'productos.iva_articulo', name: 'Impuesto IVA Artículo (16%)', token: 'IVA Art.: {{productos.iva_articulo}}' },
        { key: 'productos.importe_sin_iva', name: 'Total Artículo SIN IVA', token: 'Total Art. SIN IVA: {{productos.importe_sin_iva}}' },
        { key: 'productos.importe_con_iva', name: 'Total Artículo CON IVA', token: 'Total Art. CON IVA: {{productos.importe_con_iva}}' }
      ]
    },
    {
      id: 'totales',
      icon: 'fa-calculator',
      label: 'Subtotales (Con/Sin IVA) e Impuestos',
      fields: [
        { key: 'importes.subtotal_sin_iva', name: 'Subtotal SIN IVA (Por separado)', token: 'Subtotal SIN IVA: {{importes.subtotal_sin_iva}}' },
        { key: 'importes.impuesto_total', name: 'Impuesto Total IVA 16% (Por separado)', token: 'Impuesto Total (IVA 16%): {{importes.impuesto_total}}' },
        { key: 'importes.subtotal_con_iva', name: 'Subtotal CON IVA (Por separado)', token: 'Subtotal CON IVA: {{importes.subtotal_con_iva}}' },
        { key: 'importes.total_sin_iva', name: 'Total SIN IVA', token: 'Total SIN IVA: {{importes.total_sin_iva}}' },
        { key: 'importes.total_con_iva', name: 'Total CON IVA (Neto)', token: 'Total CON IVA: {{importes.total_con_iva}}' },
        { key: 'importes.total_letra', name: 'Importe con letra', token: '{{importes.total_letra}}' }
      ]
    }
  ];

  function esc(v) {
    return String(v == null ? '' : v).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  function mmToPx(mm) {
    return Math.round(Number(mm || 0) * PX_PER_MM_BASE * _zoom);
  }

  function pxToMm(px) {
    var denom = PX_PER_MM_BASE * (_zoom || 0.85);
    return Math.round((Number(px || 0) / (denom || 1)) * 2) / 2;
  }

  function pushUndo() {
    if (!_workingVersion || !_workingVersion.definition_json) return;
    _undoStack.push(JSON.stringify(_workingVersion.definition_json.elements || []));
    if (_undoStack.length > 40) _undoStack.shift();
    _redoStack = [];
    _isDirty = true;
  }

  function resolveDocShortTitle(docTypeOrTitle) {
    var raw = String(docTypeOrTitle || 'COTIZACIÓN').toUpperCase();
    for (var i = 0; i < DOC_TYPES_LIST.length; i++) {
      if (DOC_TYPES_LIST[i].id.toUpperCase() === raw) return DOC_TYPES_LIST[i].shortTitle;
    }
    if (raw.indexOf('CIEGO') >= 0) return 'ARQUEO / CORTE CIEGO DE CAJA';
    if (raw.indexOf('CORTE_X') >= 0 || raw.indexOf('CORTE X') >= 0) return 'CORTE PARCIAL DE CAJA (X)';
    if (raw.indexOf('CORTE_Z') >= 0 || raw.indexOf('CORTE Z') >= 0 || raw.indexOf('CIERRE') >= 0) return 'CORTE Z · CIERRE DEFINITIVO DE CAJA';
    if (raw.indexOf('APERTURA') >= 0) return 'APERTURA DE CAJA Y FONDO INICIAL';
    if (raw.indexOf('COTIZAC') >= 0) return 'COTIZACIÓN';
    if (raw.indexOf('ENTREGA') >= 0) return 'ORDEN DE ENTREGA';
    if (raw.indexOf('CRÉDITO') >= 0 || raw.indexOf('CREDITO') >= 0) return 'VENTA A CRÉDITO Y PAGARÉ';
    if (raw.indexOf('ABONO') >= 0 || raw.indexOf('PAGO') >= 0) return 'COMPROBANTE DE PAGO';
    if (raw.indexOf('FACTURA') >= 0 || raw.indexOf('CFDI') >= 0) return 'FACTURA CFDI 4.0';
    if (raw.indexOf('REMISI') >= 0) return 'REMISIÓN DE SALIDA';
    if (raw.indexOf('COMPRA') >= 0) return 'ORDEN DE COMPRA';
    if (raw.indexOf('CORTE') >= 0) return 'CORTE Z · CIERRE DEFINITIVO DE CAJA';
    if (raw.indexOf('ESTADO') >= 0) return 'ESTADO DE CUENTA';
    if (raw.indexOf('VENTA') >= 0) return 'NOTA DE VENTA';
    return raw;
  }

  /* ═══════════════════════════════════════════════════════════════════════════
     MOTOR GENERADOR DE LAS 20 PLANTILLAS PRECARGADAS DISTINTAS (100% MOVIBLES)
     MODELOS DE GRANDES TIENDAS (PROFECO / SAT) + CORTE CIEGO, CORTE X Y CORTE Z
     PARA CARTA (215.9 × 279.4 mm), TICKET 80 MM Y TICKET 58 MM
     ═══════════════════════════════════════════════════════════════════════════ */
  function generatePresetLayers(docType, paperFormat, styleNum, fallbackTitle) {
    var pNum = Math.max(1, Math.min(20, parseInt(styleNum || 1, 10)));
    var styleMeta = TEN_PRESET_STYLES[pNum - 1] || TEN_PRESET_STYLES[0];
    var titleUpper = resolveDocShortTitle(docType || fallbackTitle);
    var pFmt = String(paperFormat || 'letter').toLowerCase();

    if (pFmt === '80mm' || pFmt === '58mm') {
      return generateThermalTicketLayers(docType, pFmt, styleMeta, titleUpper);
    }
    return generateLetterCartaLayers(docType, styleMeta, titleUpper);
  }

  /* ── A) 20 DISEÑOS ESTRUCTURALES DISTINTOS EN TAMAÑO CARTA (215.9 × 279.4 mm) ── */
  function generateLetterCartaLayers(docType, styleMeta, titleUpper) {
    var sNum = styleMeta.num;
    var pri = styleMeta.primary;
    var sec = styleMeta.secondary;
    var logoUrl = (sNum === 2 || sNum === 11 || sNum === 15)
      ? buildLogoSvgDataUrl('#ffffff', '#93c5fd', pri)
      : buildLogoSvgDataUrl(pri, sec, null);

    var dTypeLow = String(docType || '').toLowerCase();
    var isCorteCiego = (dTypeLow === 'corte_ciego' || sNum === 16);
    var isCorteX = (dTypeLow === 'corte_x' || dTypeLow === 'apertura_caja' || dTypeLow === 'arqueo_caja' || sNum === 17);
    var isCorteZ = (dTypeLow === 'corte_z' || sNum === 18);
    var isAnyCorte = (isCorteCiego || isCorteX || isCorteZ);

    var els = [];

    /* --- 20 ARQUITECTURAS DE ENCABEZADO Y ESTRUCTURA DISTINTAS (NO SOLO COLORES) --- */
    if (sNum === 1) {
      // 01: Home Depot Pro Constructor (Logo izq, Contacto der, Cintillo naranja/carbón, Título centrado)
      els.push(
        { id: 'layer-logo-magdaleno', type: 'image', label: 'LOGO MAGDALENO (IMAGEN)', src: logoUrl, x_mm: 14.0, y_mm: 12.0, w_mm: 86.0, h_mm: 21.0, page: 1, z_index: 2 },
        { id: 'layer-contact-header', type: 'text', label: 'DATOS DE CONTACTO EMPRESA', text: '📍 Av. Reforma No. 1250, Col. Centro, C.P. 44100\n📞 (33) 3615 4287  |  ✉️ ventas@magdaleno.com.mx\n🌐 www.magdaleno.com.mx · PROFECO 800-468-8722', x_mm: 132.0, y_mm: 12.0, w_mm: 70.0, h_mm: 16.0, font_family: 'Arial', font_size: 8.5, color: '#1e293b', wrap: true, page: 1, z_index: 2 },
        { id: 'layer-top-accent-bar', type: 'rect', label: 'CINTILLO SUPERIOR PRO CONSTRUCTOR', x_mm: 132.0, y_mm: 29.5, w_mm: 70.0, h_mm: 2.5, background_color: pri, border_color: sec, page: 1, z_index: 1 },
        { id: 'layer-doc-title', type: 'text', label: 'TÍTULO DEL DOCUMENTO', text: titleUpper, x_mm: 42.0, y_mm: 35.0, w_mm: 132.0, h_mm: 10.0, font_family: 'Arial', font_size: 18, bold: true, align: 'center', color: '#0f172a', page: 1, z_index: 3 }
      );
    } else if (sNum === 2) {
      // 02: Costco / Sam's Club Mayorista (Franja superior completa de lado a lado + Cajas de membresía/cliente)
      els.push(
        { id: 'layer-top-accent-bar', type: 'rect', label: 'BANDA SUPERIOR MAYORISTA', x_mm: 0.0, y_mm: 0.0, w_mm: 215.9, h_mm: 32.0, background_color: pri, border_color: pri, page: 1, z_index: 1 },
        { id: 'layer-doc-title', type: 'text', label: 'TÍTULO DEL DOCUMENTO (BLANCO)', text: titleUpper, x_mm: 14.0, y_mm: 7.0, w_mm: 112.0, h_mm: 11.0, font_family: 'Arial', font_size: 18, bold: true, align: 'left', color: '#ffffff', page: 1, z_index: 3 },
        { id: 'layer-contact-header', type: 'text', label: 'DATOS EMPRESA EN BANDA', text: 'MAGDALENO CLUB MAYORISTA · RFC: GMM2106218A1 · PRECIOS AUDITADOS NOM-030-SCFI', x_mm: 14.0, y_mm: 20.0, w_mm: 115.0, h_mm: 8.0, font_family: 'Arial', font_size: 8.5, color: '#dbeafe', page: 1, z_index: 3 },
        { id: 'layer-logo-magdaleno', type: 'image', label: 'LOGO MAGDALENO (IMAGEN)', src: logoUrl, x_mm: 132.0, y_mm: 5.5, w_mm: 70.0, h_mm: 20.0, page: 1, z_index: 3 },
        { id: 'layer-cli-bg-box', type: 'rect', label: 'CAJA FONDO SOCIO / CLIENTE', x_mm: 12.0, y_mm: 44.0, w_mm: 116.0, h_mm: 36.0, background_color: '#f8fafc', border_color: '#cbd5e1', page: 1, z_index: 1 },
        { id: 'layer-doc-bg-box', type: 'rect', label: 'CAJA FONDO FOLIO/FECHA', x_mm: 132.0, y_mm: 44.0, w_mm: 71.0, h_mm: 36.0, background_color: '#eff6ff', border_color: '#93c5fd', page: 1, z_index: 1 }
      );
    } else if (sNum === 3) {
      // 03: Walmart Supercenter Comercial (Cabezal centrado + Franja Ámbar de Precios Bajos PROFECO)
      els.push(
        { id: 'layer-logo-magdaleno', type: 'image', label: 'LOGO MAGDALENO SUPERCENTER', src: logoUrl, x_mm: 14.0, y_mm: 10.0, w_mm: 78.0, h_mm: 19.0, page: 1, z_index: 2 },
        { id: 'layer-top-accent-bar', type: 'rect', label: 'FRANJA COMERCIAL SUPERCENTER', x_mm: 96.0, y_mm: 10.0, w_mm: 106.0, h_mm: 19.0, background_color: '#eff6ff', border_color: pri, page: 1, z_index: 1 },
        { id: 'layer-doc-title', type: 'text', label: 'TÍTULO SUPERCENTER', text: titleUpper, x_mm: 98.0, y_mm: 12.0, w_mm: 102.0, h_mm: 8.5, font_family: 'Arial', font_size: 15, bold: true, align: 'center', color: pri, page: 1, z_index: 3 },
        { id: 'layer-contact-header', type: 'text', label: 'GARANTÍA PRECIOS CLAROS PROFECO', text: 'PRECIOS CLAROS CON IVA INCLUIDO · ART. 12 LFPC PROFECO · TEL. (33) 3615 4287', x_mm: 98.0, y_mm: 21.0, w_mm: 102.0, h_mm: 6.5, font_family: 'Arial', font_size: 7.5, bold: true, align: 'center', color: '#b45309', page: 1, z_index: 3 },
        { id: 'layer-amber-strip', type: 'rect', label: 'CINTA ÁMBAR SUPERCENTER', x_mm: 14.0, y_mm: 32.0, w_mm: 188.0, h_mm: 3.0, background_color: '#f59e0b', border_color: '#d97706', page: 1, z_index: 1 }
      );
    } else if (sNum === 4) {
      // 04: Liverpool / Palacio Marco Editorial (Marco perimetral elegante alrededor de toda la hoja)
      els.push(
        { id: 'layer-outer-frame', type: 'rect', label: 'MARCO PERIMETRAL EDITORIAL', x_mm: 8.0, y_mm: 8.0, w_mm: 200.0, h_mm: 263.0, background_color: 'transparent', border_color: pri, page: 1, z_index: 1 },
        { id: 'layer-logo-magdaleno', type: 'image', label: 'LOGO MAGDALENO DEPARTAMENTAL', src: logoUrl, x_mm: 68.0, y_mm: 12.0, w_mm: 80.0, h_mm: 18.0, page: 1, z_index: 2 },
        { id: 'layer-doc-title', type: 'text', label: 'TÍTULO EDITORIAL CENTRADO', text: titleUpper, x_mm: 38.0, y_mm: 31.0, w_mm: 140.0, h_mm: 8.5, font_family: 'Georgia', font_size: 16, bold: true, align: 'center', color: pri, page: 1, z_index: 3 },
        { id: 'layer-contact-header', type: 'text', label: 'PÓLIZA DEPARTAMENTAL', text: 'Av. Reforma 1250, Col. Centro · Garantía y Cambios conforme a Art. 77 LFPC PROFECO', x_mm: 24.0, y_mm: 39.5, w_mm: 168.0, h_mm: 5.5, font_family: 'Georgia', font_size: 8.5, align: 'center', color: '#475569', page: 1, z_index: 2 }
      );
    } else if (sNum === 5) {
      // 05: OXXO / 7-Eleven Express (Cuadrícula superior compacta de 4 celdas con bordes marcados)
      els.push(
        { id: 'layer-grid-c1', type: 'rect', label: 'CELDA 1 LOGO EXPRESS', x_mm: 14.0, y_mm: 11.0, w_mm: 88.0, h_mm: 20.0, background_color: '#fffbeb', border_color: pri, page: 1, z_index: 1 },
        { id: 'layer-grid-c2', type: 'rect', label: 'CELDA 2 TÍTULO EXPRESS', x_mm: 102.0, y_mm: 11.0, w_mm: 100.0, h_mm: 20.0, background_color: pri, border_color: pri, page: 1, z_index: 1 },
        { id: 'layer-grid-c3', type: 'rect', label: 'CELDA 3 EMISOR FISCAL', x_mm: 14.0, y_mm: 31.0, w_mm: 88.0, h_mm: 11.0, background_color: '#fef2f2', border_color: pri, page: 1, z_index: 1 },
        { id: 'layer-grid-c4', type: 'rect', label: 'CELDA 4 SUCURSAL Y CAJA', x_mm: 102.0, y_mm: 31.0, w_mm: 100.0, h_mm: 11.0, background_color: '#f8fafc', border_color: pri, page: 1, z_index: 1 },
        { id: 'layer-logo-magdaleno', type: 'image', label: 'LOGO MAGDALENO EXPRESS', src: logoUrl, x_mm: 18.0, y_mm: 12.5, w_mm: 78.0, h_mm: 17.0, page: 1, z_index: 3 },
        { id: 'layer-doc-title', type: 'text', label: 'TÍTULO CUADRÍCULA EXPRESS', text: titleUpper, x_mm: 105.0, y_mm: 16.0, w_mm: 94.0, h_mm: 10.0, font_family: 'Arial', font_size: 15, bold: true, align: 'center', color: '#ffffff', page: 1, z_index: 3 },
        { id: 'layer-contact-header', type: 'text', label: 'DATOS CELDA 3 Y 4', text: 'RFC: GMM2106218A1 · Tel. (33) 3615 4287          |          TERMINAL EXPRESS POS · CUMPLIMIENTO PROFECO', x_mm: 16.0, y_mm: 33.5, w_mm: 182.0, h_mm: 6.5, font_family: 'Arial', font_size: 8, bold: true, color: '#0f172a', page: 1, z_index: 3 }
      );
    } else if (sNum === 6) {
      // 06: Cemex / Construrama Patio y Báscula (Cintillo Carbón + Ámbar + Caja de Control de Patio y 3 Firmas)
      els.push(
        { id: 'layer-top-dark', type: 'rect', label: 'FRANJA SUPERIOR CARBÓN', x_mm: 10.0, y_mm: 10.0, w_mm: 196.0, h_mm: 6.0, background_color: '#18181b', border_color: '#18181b', page: 1, z_index: 1 },
        { id: 'layer-top-amber', type: 'rect', label: 'FRANJA ÁMBAR PATIO Y BÁSCULA', x_mm: 10.0, y_mm: 16.0, w_mm: 196.0, h_mm: 2.5, background_color: '#d97706', border_color: '#d97706', page: 1, z_index: 1 },
        { id: 'layer-logo-magdaleno', type: 'image', label: 'LOGO MAGDALENO PATIO', src: logoUrl, x_mm: 14.0, y_mm: 20.5, w_mm: 78.0, h_mm: 19.0, page: 1, z_index: 2 },
        { id: 'layer-box-logistica', type: 'rect', label: 'CAJA CONTROL DE BÁSCULA Y PATIO', x_mm: 96.0, y_mm: 20.0, w_mm: 106.0, h_mm: 21.0, background_color: '#e0f2fe', border_color: pri, page: 1, z_index: 1 },
        { id: 'layer-doc-title', type: 'text', label: 'TÍTULO PATIO Y OBRA', text: titleUpper, x_mm: 98.0, y_mm: 21.5, w_mm: 102.0, h_mm: 8.5, font_family: 'Arial', font_size: 14, bold: true, align: 'center', color: pri, page: 1, z_index: 3 },
        { id: 'layer-contact-header', type: 'text', label: 'CONTROL SALIDA DE MATERIAL', text: 'CERTIFICACIÓN DE PESO Y VOLUMEN NOM-030-SCFI · PATIO MATRIZ', x_mm: 98.0, y_mm: 31.0, w_mm: 102.0, h_mm: 7.0, font_family: 'Arial', font_size: 8, bold: true, align: 'center', color: '#0f172a', page: 1, z_index: 3 }
      );
    } else if (sNum === 7) {
      // 07: Coppel / Elektra Estado de Cuenta y Pagaré (Cajas de Saldos Destacadas + Marco Pagaré Mercantil)
      els.push(
        { id: 'layer-logo-magdaleno', type: 'image', label: 'LOGO MAGDALENO CRÉDITO', src: logoUrl, x_mm: 14.0, y_mm: 11.0, w_mm: 82.0, h_mm: 19.0, page: 1, z_index: 2 },
        { id: 'layer-top-accent-bar', type: 'rect', label: 'CAJA ENCABEZADO CRÉDITO', x_mm: 100.0, y_mm: 11.0, w_mm: 102.0, h_mm: 21.0, background_color: '#fefce8', border_color: '#eab308', page: 1, z_index: 1 },
        { id: 'layer-doc-title', type: 'text', label: 'TÍTULO CRÉDITO Y COBRANZA', text: titleUpper, x_mm: 102.0, y_mm: 13.0, w_mm: 98.0, h_mm: 8.5, font_family: 'Arial', font_size: 14, bold: true, align: 'center', color: pri, page: 1, z_index: 3 },
        { id: 'layer-contact-header', type: 'text', label: 'LEYENDA ESTADO DE CUENTA', text: 'ESTADO DE CUENTA CON SALDO ANTERIOR Y SALDO ACTUAL DESGLOSADOS', x_mm: 102.0, y_mm: 22.5, w_mm: 98.0, h_mm: 7.0, font_family: 'Arial', font_size: 7.5, bold: true, align: 'center', color: '#854d0e', page: 1, z_index: 3 }
      );
    } else if (sNum === 8) {
      // 08: SAT CFDI 4.0 Anexo 20 Doble Panel Fiscal (Emisor Fiscal Izq + Timbre UUID Der)
      els.push(
        { id: 'layer-emisor-panel', type: 'rect', label: 'PANEL EMISOR FISCAL CFDI 4.0', x_mm: 14.0, y_mm: 10.0, w_mm: 102.0, h_mm: 32.0, background_color: '#f8fafc', border_color: '#94a3b8', page: 1, z_index: 1 },
        { id: 'layer-logo-magdaleno', type: 'image', label: 'LOGO MAGDALENO FISCAL', src: logoUrl, x_mm: 16.0, y_mm: 11.5, w_mm: 74.0, h_mm: 17.5, page: 1, z_index: 2 },
        { id: 'layer-contact-header', type: 'text', label: 'EMISOR FISCAL RFC Y RÉGIMEN', text: 'GRUPO MADERERO MAGDALENO S.A. DE C.V. · RFC: GMM2106218A1\nRégimen Fiscal: 601 General de Ley Personas Morales · Lugar Exp: 44100', x_mm: 16.0, y_mm: 30.0, w_mm: 98.0, h_mm: 10.5, font_family: 'Arial', font_size: 8, bold: true, color: '#064e3b', page: 1, z_index: 3 },
        { id: 'layer-uuid-box', type: 'rect', label: 'PANEL TIMBRE FISCAL UUID SAT', x_mm: 119.0, y_mm: 10.0, w_mm: 83.0, h_mm: 32.0, background_color: '#ecfdf5', border_color: '#059669', page: 1, z_index: 1 },
        { id: 'layer-doc-title', type: 'text', label: 'TÍTULO COMPROBANTE FISCAL', text: titleUpper, x_mm: 121.0, y_mm: 12.0, w_mm: 79.0, h_mm: 7.5, font_family: 'Arial', font_size: 12.5, bold: true, align: 'center', color: '#065f46', page: 1, z_index: 3 },
        { id: 'layer-cfdi-uuid', type: 'field', label: 'FOLIO FISCAL UUID SAT', field_key: 'cfdi.uuid', text: 'FOLIO FISCAL UUID:\n{{cfdi.uuid}}', x_mm: 121.0, y_mm: 21.0, w_mm: 79.0, h_mm: 18.0, font_family: 'Courier New', font_size: 8, bold: true, align: 'center', color: '#0f172a', page: 1, z_index: 4 }
      );
    } else if (sNum === 9) {
      // 09: Amazon / MercadoLibre Guía Logística (QR Superior Izquierdo + Bloque de Guía y Rastreo)
      els.push(
        { id: 'layer-top-qr-guide', type: 'image', label: 'QR RASTREO LOGÍSTICO SUPERIOR', src: SAMPLE_QR_SVG, x_mm: 14.0, y_mm: 11.0, w_mm: 22.0, h_mm: 22.0, page: 1, z_index: 4 },
        { id: 'layer-logo-magdaleno', type: 'image', label: 'LOGO MAGDALENO FULFILLMENT', src: logoUrl, x_mm: 39.0, y_mm: 12.0, w_mm: 74.0, h_mm: 18.0, page: 1, z_index: 2 },
        { id: 'layer-guide-box', type: 'rect', label: 'CAJA GUÍA DE DESPACHO Y RUTA', x_mm: 117.0, y_mm: 11.0, w_mm: 85.0, h_mm: 24.0, background_color: '#fff7ed', border_color: '#ea580c', page: 1, z_index: 1 },
        { id: 'layer-doc-title', type: 'text', label: 'TÍTULO GUÍA LOGÍSTICA', text: titleUpper, x_mm: 119.0, y_mm: 13.0, w_mm: 81.0, h_mm: 8.5, font_family: 'Arial', font_size: 13.5, bold: true, align: 'center', color: '#c2410c', page: 1, z_index: 3 },
        { id: 'layer-contact-header', type: 'text', label: 'CÓDIGO RUTA Y PRIORIDAD', text: 'PRIORIDAD: ENTREGA MISMO DÍA · RUTA ZONA METROPOLITANA', x_mm: 119.0, y_mm: 23.0, w_mm: 81.0, h_mm: 9.0, font_family: 'Courier New', font_size: 8, bold: true, align: 'center', color: '#0f172a', page: 1, z_index: 3 }
      );
    } else if (sNum === 10) {
      // 10: Apple Store / Suizo Minimalista Asimétrico (Línea fina + Tipografía limpia de alto aire visual)
      els.push(
        { id: 'layer-doc-title', type: 'text', label: 'TÍTULO SUIZO ASIMÉTRICO', text: titleUpper, x_mm: 14.0, y_mm: 13.0, w_mm: 115.0, h_mm: 11.0, font_family: 'Arial', font_size: 20, bold: true, align: 'left', color: '#000000', page: 1, z_index: 3 },
        { id: 'layer-contact-header', type: 'text', label: 'MEMBRETE MINIMALISTA SUIZO', text: 'MAGDALENO MADERAS Y MATERIALES · RFC: GMM2106218A1 · Av. Reforma 1250 · Tel. (33) 3615 4287', x_mm: 14.0, y_mm: 26.0, w_mm: 120.0, h_mm: 10.0, font_family: 'Arial', font_size: 8.5, color: '#334155', page: 1, z_index: 3 },
        { id: 'layer-logo-magdaleno', type: 'image', label: 'LOGO MAGDALENO SUIZO', src: logoUrl, x_mm: 136.0, y_mm: 13.0, w_mm: 66.0, h_mm: 17.0, page: 1, z_index: 2 },
        { id: 'layer-top-accent-bar', type: 'line', label: 'LÍNEA SUIZA SUPERIOR', x_mm: 14.0, y_mm: 39.0, w_mm: 188.0, h_mm: 2.0, color: '#000000', page: 1, z_index: 2 }
      );
    } else if (sNum === 11) {
      // 11: AutoZone / Refaccionaria Header Invertido (Cabezal oscuro de alto contraste + Sello Garantía)
      els.push(
        { id: 'layer-top-accent-bar', type: 'rect', label: 'CABEZAL INVERTIDO ALTO CONTRASTE', x_mm: 12.0, y_mm: 10.0, w_mm: 192.0, h_mm: 28.0, background_color: '#18181b', border_color: pri, page: 1, z_index: 1 },
        { id: 'layer-stripe-orange', type: 'rect', label: 'FRANJA NARANJA AUTOZONE', x_mm: 12.0, y_mm: 38.0, w_mm: 192.0, h_mm: 3.0, background_color: pri, border_color: pri, page: 1, z_index: 2 },
        { id: 'layer-logo-magdaleno', type: 'image', label: 'LOGO MAGDALENO INVERTIDO', src: logoUrl, x_mm: 16.0, y_mm: 13.5, w_mm: 78.0, h_mm: 20.0, page: 1, z_index: 3 },
        { id: 'layer-doc-title', type: 'text', label: 'TÍTULO BLANCO INVERTIDO', text: titleUpper, x_mm: 98.0, y_mm: 14.0, w_mm: 102.0, h_mm: 10.0, font_family: 'Arial', font_size: 16, bold: true, align: 'right', color: '#ffffff', page: 1, z_index: 3 },
        { id: 'layer-contact-header', type: 'text', label: 'PÓLIZA GARANTÍA PROFECO', text: 'PÓLIZA DE GARANTÍA Y CAMBIO FÍSICO ART. 77 LFPC · RFC: GMM2106218A1', x_mm: 98.0, y_mm: 26.0, w_mm: 102.0, h_mm: 8.0, font_family: 'Arial', font_size: 8, bold: true, align: 'right', color: '#fed7aa', page: 1, z_index: 3 }
      );
    } else if (sNum === 12) {
      // 12: Sears / Sanborns Columna Vertical (Barra vertical izquierda a todo lo alto de la hoja)
      els.push(
        { id: 'layer-left-sidebar', type: 'rect', label: 'COLUMNA VERTICAL IZQUIERDA', x_mm: 0.0, y_mm: 0.0, w_mm: 9.5, h_mm: 279.4, background_color: pri, border_color: pri, page: 1, z_index: 1 },
        { id: 'layer-logo-magdaleno', type: 'image', label: 'LOGO MAGDALENO', src: logoUrl, x_mm: 16.0, y_mm: 12.0, w_mm: 82.0, h_mm: 20.0, page: 1, z_index: 2 },
        { id: 'layer-folio-card', type: 'rect', label: 'RECUADRO SUPERIOR FOLIO', x_mm: 126.0, y_mm: 11.0, w_mm: 76.0, h_mm: 24.0, background_color: '#fef2f2', border_color: pri, page: 1, z_index: 1 },
        { id: 'layer-doc-title', type: 'text', label: 'TÍTULO DEL DOCUMENTO', text: titleUpper, x_mm: 128.0, y_mm: 14.0, w_mm: 72.0, h_mm: 16.0, font_family: 'Arial', font_size: 13, bold: true, align: 'center', color: pri, page: 1, z_index: 3 },
        { id: 'layer-contact-header', type: 'text', label: 'DATOS DE CONTACTO', text: 'Av. Reforma No. 1250 · Tel. (33) 3615 4287 · www.magdaleno.com.mx', x_mm: 16.0, y_mm: 34.0, w_mm: 108.0, h_mm: 6.5, font_family: 'Arial', font_size: 8.5, color: '#475569', page: 1, z_index: 2 }
      );
    } else if (sNum === 13) {
      // 13: Office Depot / Lumen Corporativo (3 Bloques Superiores + Portal Autofacturación SAT CFDI 4.0)
      els.push(
        { id: 'layer-logo-magdaleno', type: 'image', label: 'LOGO MAGDALENO CORPORATIVO', src: logoUrl, x_mm: 14.0, y_mm: 11.0, w_mm: 70.0, h_mm: 18.0, page: 1, z_index: 2 },
        { id: 'layer-center-title-box', type: 'rect', label: 'BLOQUE CENTRAL TÍTULO', x_mm: 86.0, y_mm: 11.0, w_mm: 60.0, h_mm: 22.0, background_color: '#fef2f2', border_color: pri, page: 1, z_index: 1 },
        { id: 'layer-doc-title', type: 'text', label: 'TÍTULO CENTRAL', text: titleUpper, x_mm: 88.0, y_mm: 14.0, w_mm: 56.0, h_mm: 16.0, font_family: 'Arial', font_size: 12, bold: true, align: 'center', color: pri, page: 1, z_index: 3 },
        { id: 'layer-autofactura-box', type: 'rect', label: 'CAJA AUTOFACTURACIÓN WEB SAT', x_mm: 148.0, y_mm: 11.0, w_mm: 54.0, h_mm: 22.0, background_color: '#f8fafc', border_color: '#64748b', page: 1, z_index: 1 },
        { id: 'layer-contact-header', type: 'text', label: 'INSTRUCCIONES AUTOFACTURACIÓN', text: 'FACTURACIÓN EN LÍNEA CFDI 4.0:\nwww.magdaleno.com.mx/facturacion\nDisponible en el mes de emisión', x_mm: 150.0, y_mm: 13.0, w_mm: 50.0, h_mm: 18.0, font_family: 'Arial', font_size: 7.5, bold: true, align: 'center', color: '#0f172a', page: 1, z_index: 3 }
      );
    } else if (sNum === 14) {
      // 14: Truper / Ferretera Industrial (Doble Franja Acero/Naranja + Tabla Comparativa SIN IVA y CON IVA)
      els.push(
        { id: 'layer-top-steel', type: 'rect', label: 'BARRA ACERO INDUSTRIAL', x_mm: 14.0, y_mm: 10.0, w_mm: 188.0, h_mm: 4.5, background_color: '#334155', border_color: '#334155', page: 1, z_index: 1 },
        { id: 'layer-top-orange', type: 'rect', label: 'BARRA NARANJA TRUPER', x_mm: 14.0, y_mm: 14.5, w_mm: 188.0, h_mm: 4.5, background_color: pri, border_color: pri, page: 1, z_index: 1 },
        { id: 'layer-logo-magdaleno', type: 'image', label: 'LOGO MAGDALENO INDUSTRIAL', src: logoUrl, x_mm: 14.0, y_mm: 21.0, w_mm: 80.0, h_mm: 19.0, page: 1, z_index: 2 },
        { id: 'layer-doc-title', type: 'text', label: 'TÍTULO INDUSTRIAL', text: titleUpper, x_mm: 98.0, y_mm: 21.0, w_mm: 104.0, h_mm: 9.5, font_family: 'Arial', font_size: 16, bold: true, align: 'right', color: '#0f172a', page: 1, z_index: 3 },
        { id: 'layer-contact-header', type: 'text', label: 'ESPECIFICACIÓN DESGLOSE IVA', text: 'CATÁLOGO INDUSTRIAL CON PRECIOS UNITARIOS SIN IVA, IVA 16% Y TOTAL CON IVA', x_mm: 98.0, y_mm: 31.5, w_mm: 104.0, h_mm: 7.5, font_family: 'Arial', font_size: 8, bold: true, align: 'right', color: pri, page: 1, z_index: 3 }
      );
    } else if (sNum === 15) {
      // 15: BBVA / Santander Ficha de Bóveda (Cabezal Bancario Azul + Certificación de Caja y Valores)
      els.push(
        { id: 'layer-top-accent-bar', type: 'rect', label: 'CABEZAL BANCARIO BÓVEDA', x_mm: 14.0, y_mm: 10.0, w_mm: 188.0, h_mm: 24.0, background_color: pri, border_color: '#0284c7', page: 1, z_index: 1 },
        { id: 'layer-logo-magdaleno', type: 'image', label: 'LOGO MAGDALENO TESORERÍA', src: logoUrl, x_mm: 18.0, y_mm: 12.5, w_mm: 74.0, h_mm: 18.5, page: 1, z_index: 3 },
        { id: 'layer-doc-title', type: 'text', label: 'TÍTULO COMPROBANTE BÓVEDA', text: titleUpper, x_mm: 96.0, y_mm: 13.0, w_mm: 102.0, h_mm: 9.0, font_family: 'Arial', font_size: 15, bold: true, align: 'right', color: '#ffffff', page: 1, z_index: 3 },
        { id: 'layer-contact-header', type: 'text', label: 'SELLO CERTIFICACIÓN CAJA', text: ' TESORERÍA Y CONTROL DE VALORES · CERTIFICACIÓN ELECTRÓNICA CALEBSYS POS', x_mm: 96.0, y_mm: 23.5, w_mm: 102.0, h_mm: 7.0, font_family: 'Courier New', font_size: 8, bold: true, align: 'right', color: '#bae6fd', page: 1, z_index: 3 }
      );
    } else if (sNum === 16) {
      // 16: Corte Ciego Oficial · Conteo de Tómbola (Diseño de Seguridad Ciega sin Saldos Esperados)
      els.push(
        { id: 'layer-top-accent-bar', type: 'rect', label: 'CABEZAL CORTE CIEGO DE SEGURIDAD', x_mm: 14.0, y_mm: 10.0, w_mm: 188.0, h_mm: 26.0, background_color: '#f5f3ff', border_color: pri, page: 1, z_index: 1 },
        { id: 'layer-logo-magdaleno', type: 'image', label: 'LOGO MAGDALENO AUDITORÍA', src: logoUrl, x_mm: 17.0, y_mm: 13.0, w_mm: 74.0, h_mm: 19.0, page: 1, z_index: 2 },
        { id: 'layer-doc-title', type: 'text', label: 'TÍTULO CORTE CIEGO', text: 'ARQUEO / CORTE CIEGO DE CAJA Y TÓMBOLA', x_mm: 94.0, y_mm: 13.0, w_mm: 105.0, h_mm: 9.0, font_family: 'Arial', font_size: 14, bold: true, align: 'right', color: pri, page: 1, z_index: 3 },
        { id: 'layer-contact-header', type: 'text', label: 'REGLA DE SEGURIDAD CORTE CIEGO', text: 'CONTEO FÍSICO A CIEGAS: EL SISTEMA OCULTA EL SALDO ESPERADO HASTA CERRAR EL SOBRE', x_mm: 94.0, y_mm: 23.0, w_mm: 105.0, h_mm: 9.5, font_family: 'Arial', font_size: 8, bold: true, align: 'right', color: '#4c1d95', page: 1, z_index: 3 }
      );
    } else if (sNum === 17) {
      // 17: Corte X Supervisión · Flujo de Gaveta (Arqueo Parcial sin Reiniciar Acumuladores)
      els.push(
        { id: 'layer-top-accent-bar', type: 'rect', label: 'CABEZAL CORTE X SUPERVISIÓN', x_mm: 14.0, y_mm: 10.0, w_mm: 188.0, h_mm: 26.0, background_color: '#ecfeff', border_color: pri, page: 1, z_index: 1 },
        { id: 'layer-logo-magdaleno', type: 'image', label: 'LOGO MAGDALENO SUPERVISIÓN', src: logoUrl, x_mm: 17.0, y_mm: 13.0, w_mm: 74.0, h_mm: 19.0, page: 1, z_index: 2 },
        { id: 'layer-doc-title', type: 'text', label: 'TÍTULO CORTE X PARCIAL', text: 'CORTE PARCIAL DE CAJA (X) · TURNO ABIERTO', x_mm: 94.0, y_mm: 13.0, w_mm: 105.0, h_mm: 9.0, font_family: 'Arial', font_size: 14, bold: true, align: 'right', color: pri, page: 1, z_index: 3 },
        { id: 'layer-contact-header', type: 'text', label: 'LEYENDA CORTE X', text: 'AUDITORÍA DE FLUJO DE EFECTIVO EN GAVETA · NO REINICIA ACUMULADORES Z', x_mm: 94.0, y_mm: 23.0, w_mm: 105.0, h_mm: 9.5, font_family: 'Arial', font_size: 8, bold: true, align: 'right', color: '#155e75', page: 1, z_index: 3 }
      );
    } else if (sNum === 18) {
      // 18: Corte Z Cierre Definitivo · Conciliación y Cuadre (Esperado vs Declarado vs Diferencia)
      els.push(
        { id: 'layer-top-accent-bar', type: 'rect', label: 'CABEZAL CORTE Z DEFINITIVO', x_mm: 14.0, y_mm: 10.0, w_mm: 188.0, h_mm: 26.0, background_color: '#ecfdf5', border_color: pri, page: 1, z_index: 1 },
        { id: 'layer-logo-magdaleno', type: 'image', label: 'LOGO MAGDALENO CIERRE Z', src: logoUrl, x_mm: 17.0, y_mm: 13.0, w_mm: 74.0, h_mm: 19.0, page: 1, z_index: 2 },
        { id: 'layer-doc-title', type: 'text', label: 'TÍTULO CORTE Z CIERRE', text: 'CORTE Z · CIERRE DEFINITIVO Y CONCILIACIÓN', x_mm: 94.0, y_mm: 13.0, w_mm: 105.0, h_mm: 9.0, font_family: 'Arial', font_size: 14, bold: true, align: 'right', color: pri, page: 1, z_index: 3 },
        { id: 'layer-contact-header', type: 'text', label: 'LEYENDA CONCILIACIÓN Z', text: 'CONCILIACIÓN SISTEMA ESPERADO VS. DECLARADO CAJERO · DETERMINACIÓN DE DIFERENCIAS', x_mm: 94.0, y_mm: 23.0, w_mm: 105.0, h_mm: 9.5, font_family: 'Arial', font_size: 8, bold: true, align: 'right', color: '#065f46', page: 1, z_index: 3 }
      );
    } else if (sNum === 19) {
      // 19: Notarial / Contrato Marco Legal (Simétrico Centrado con Doble Filete)
      els.push(
        { id: 'layer-logo-magdaleno', type: 'image', label: 'LOGO MAGDALENO CENTRADO', src: logoUrl, x_mm: 66.0, y_mm: 10.0, w_mm: 84.0, h_mm: 19.0, page: 1, z_index: 2 },
        { id: 'layer-contact-header', type: 'text', label: 'DIRECCIÓN CENTRADA', text: 'Av. Reforma No. 1250, Col. Centro · Tel. (33) 3615 4287 · Cumplimiento LFPC PROFECO', x_mm: 28.0, y_mm: 30.0, w_mm: 160.0, h_mm: 6.0, font_family: 'Georgia', font_size: 8.5, align: 'center', color: '#475569', page: 1, z_index: 2 },
        { id: 'layer-top-accent-bar', type: 'rect', label: 'MARCO TÍTULO NOTARIAL', x_mm: 42.0, y_mm: 36.5, w_mm: 132.0, h_mm: 9.0, background_color: '#fff1f2', border_color: pri, page: 1, z_index: 1 },
        { id: 'layer-doc-title', type: 'text', label: 'TÍTULO CENTRADO NOTARIAL', text: titleUpper, x_mm: 44.0, y_mm: 37.5, w_mm: 128.0, h_mm: 7.5, font_family: 'Georgia', font_size: 14, bold: true, align: 'center', color: pri, page: 1, z_index: 3 }
      );
    } else {
      // 20: Papel Preimpreso (Solo Campos Dinámicos sin fondos ni logotipos)
      els.push(
        { id: 'layer-doc-title', type: 'text', label: 'TÍTULO (GUÍA PREIMPRESO)', text: titleUpper, x_mm: 55.0, y_mm: 26.0, w_mm: 106.0, h_mm: 9.0, font_family: 'Arial', font_size: 15, bold: true, align: 'center', color: '#334155', page: 1, z_index: 3 }
      );
    }

    var leftMargin = (sNum === 12) ? 16.0 : 14.0;

    /* ═══════════════════════════════════════════════════════════════════════════
       CASO ESPECIAL A1: DOCUMENTOS DE CORTE DE CAJA (CORTE CIEGO, CORTE X, CORTE Z) EN CARTA
       ═══════════════════════════════════════════════════════════════════════════ */
    if (isAnyCorte) {
      var corteTableType = isCorteCiego ? 'table_corte_ciego' : (isCorteX ? 'table_corte_x' : 'table_corte_z');
      var corteTableLabel = isCorteCiego
        ? 'TABLA DE ARQUEO CIEGO (BILLETES, MONEDAS Y VOUCHERS SIN SALDO ESPERADO)'
        : (isCorteX ? 'TABLA DE FLUJO DE EFECTIVO EN GAVETA Y FORMAS DE PAGO (CORTE X)' : 'TABLA DE CONCILIACIÓN: ESPERADO VS. DECLARADO VS. DIFERENCIA (CORTE Z)');

      els.push(
        { id: 'f-corte-modalidad', type: 'field', label: 'MODALIDAD DEL CORTE', field_key: 'corte.tipo_corte', text: 'MODALIDAD: {{corte.tipo_corte}}', x_mm: leftMargin, y_mm: 44.0, w_mm: 112.0, h_mm: 7.0, font_family: 'Arial', font_size: 10, bold: true, align: 'left', color: pri, show_box: true, page: 1, z_index: 5 },
        { id: 'f-doc-folio', type: 'field', label: 'FOLIO DEL CORTE', field_key: 'operacion.folio', text: 'Folio Corte: {{documento.folio}}', x_mm: 132.0, y_mm: 44.0, w_mm: 70.0, h_mm: 7.0, font_family: 'Arial', font_size: 10, bold: true, align: 'center', color: '#0f172a', show_box: true, page: 1, z_index: 5 },
        { id: 'f-corte-turno', type: 'field', label: 'TURNO Y CAJERO RESPONSABLE', field_key: 'corte.turno', text: 'Turno: {{corte.turno}}  |  Cajero: {{operacion.vendedor}}', x_mm: leftMargin, y_mm: 52.5, w_mm: 112.0, h_mm: 7.0, font_family: 'Arial', font_size: 9.5, bold: true, align: 'left', color: '#0f172a', show_box: true, page: 1, z_index: 5 },
        { id: 'f-doc-fecha', type: 'field', label: 'FECHA Y HORA DEL CORTE', field_key: 'operacion.fecha', text: 'Fecha: {{documento.fecha}} {{operacion.hora}}', x_mm: 132.0, y_mm: 52.5, w_mm: 70.0, h_mm: 7.0, font_family: 'Arial', font_size: 9.5, bold: false, align: 'center', color: '#0f172a', show_box: true, page: 1, z_index: 5 },
        { id: 'f-corte-folios', type: 'field', label: 'RANGO DE FOLIOS Y OPERACIONES', field_key: 'corte.folio_inicial', text: 'Folios: {{corte.folio_inicial}} al {{corte.folio_final}} ({{corte.num_operaciones}} ops)', x_mm: leftMargin, y_mm: 61.0, w_mm: 112.0, h_mm: 7.0, font_family: 'Arial', font_size: 9.5, bold: false, align: 'left', color: '#334155', show_box: true, page: 1, z_index: 5 },
        { id: 'f-corte-sobre', type: 'field', label: 'FOLIO SOBRE DE VALORES / TÓMBOLA', field_key: 'corte.folio_sobre', text: 'Sobre Tómbola: {{corte.folio_sobre}}', x_mm: 132.0, y_mm: 61.0, w_mm: 70.0, h_mm: 7.0, font_family: 'Courier New', font_size: 9.5, bold: true, align: 'center', color: '#0f172a', show_box: true, page: 1, z_index: 5 },
        { id: 'layer-table-corte', type: corteTableType, label: corteTableLabel, header_bg: pri, x_mm: leftMargin, y_mm: 71.0, w_mm: 188.0, h_mm: 74.0, page: 1, z_index: 3 }
      );

      if (isCorteCiego) {
        // Corte Ciego: NO muestra esperado, solo desglose declarado y firma de depósito en tómbola
        els.push(
          { id: 'f-corte-denom', type: 'field', label: 'ARQUEO FÍSICO DE DENOMINACIONES', field_key: 'corte.desglose_denominaciones', text: 'CONTEO FÍSICO DECLARADO: {{corte.desglose_denominaciones}}', x_mm: leftMargin, y_mm: 148.0, w_mm: 188.0, h_mm: 10.0, font_family: 'Courier New', font_size: 9, bold: true, align: 'left', color: '#0f172a', show_box: true, page: 1, z_index: 5 },
          { id: 'f-corte-efec-dec', type: 'field', label: 'EFECTIVO FÍSICO DECLARADO EN SOBRE', field_key: 'corte.efectivo_declarado', text: 'Efectivo Físico Declarado: {{corte.efectivo_declarado}}', x_mm: leftMargin, y_mm: 160.0, w_mm: 92.0, h_mm: 8.5, font_family: 'Arial', font_size: 10.5, bold: true, align: 'left', color: '#0f172a', show_box: true, page: 1, z_index: 6 },
          { id: 'f-corte-tot-dec', type: 'field', label: 'TOTAL GENERAL DECLARADO A CIEGAS', field_key: 'corte.total_declarado_general', text: 'TOTAL DECLARADO CAJERO: {{corte.total_declarado_general}}', x_mm: 108.0, y_mm: 160.0, w_mm: 94.0, h_mm: 8.5, font_family: 'Arial', font_size: 11, bold: true, align: 'right', color: pri, is_total_highlight: true, show_box: true, page: 1, z_index: 6 }
        );
      } else if (isCorteX) {
        // Corte X: Flujo de efectivo esperado en gaveta + Totales por forma de pago
        els.push(
          { id: 'f-corte-fondo', type: 'field', label: '(+) FONDO INICIAL DE CAJA', field_key: 'corte.fondo_inicial', text: '(+) Fondo Inicial: {{corte.fondo_inicial}}', x_mm: leftMargin, y_mm: 148.0, w_mm: 60.0, h_mm: 7.5, font_family: 'Arial', font_size: 9.5, bold: true, align: 'left', color: '#0f172a', show_box: true, page: 1, z_index: 5 },
          { id: 'f-corte-retiros', type: 'field', label: '(-) RETIROS / FAJILLAS A TÓMBOLA', field_key: 'corte.retiros_fajillas', text: '(-) Retiros / Fajillas: {{corte.retiros_fajillas}}', x_mm: leftMargin + 63.0, y_mm: 148.0, w_mm: 62.0, h_mm: 7.5, font_family: 'Arial', font_size: 9.5, bold: true, align: 'left', color: '#b45309', show_box: true, page: 1, z_index: 5 },
          { id: 'f-corte-efec-esp', type: 'field', label: '(=) EFECTIVO ESPERADO EN GAVETA', field_key: 'corte.efectivo_esperado', text: '(=) Efectivo en Gaveta: {{corte.efectivo_esperado}}', x_mm: leftMargin + 128.0, y_mm: 148.0, w_mm: 60.0, h_mm: 7.5, font_family: 'Arial', font_size: 10, bold: true, align: 'right', color: pri, is_total_highlight: true, show_box: true, page: 1, z_index: 6 },
          { id: 'f-corte-tot-esp', type: 'field', label: 'TOTAL ACUMULADO DEL TURNO (CORTE X)', field_key: 'corte.total_esperado_general', text: 'TOTAL ACUMULADO TURNO ABIERTO: {{corte.total_esperado_general}}', x_mm: 96.0, y_mm: 158.0, w_mm: 106.0, h_mm: 8.5, font_family: 'Arial', font_size: 11, bold: true, align: 'right', color: pri, is_total_highlight: true, show_box: true, page: 1, z_index: 6 }
        );
      } else {
        // Corte Z: Conciliación completa Sistema Esperado vs Cajero Declarado vs Diferencia + Dictamen + Resumen Fiscal IVA
        els.push(
          { id: 'f-corte-tot-esp', type: 'field', label: 'TOTAL ESPERADO SISTEMA (CORTE Z)', field_key: 'corte.total_esperado_general', text: 'Esperado Sistema: {{corte.total_esperado_general}}', x_mm: leftMargin, y_mm: 148.0, w_mm: 60.0, h_mm: 8.0, font_family: 'Arial', font_size: 9.5, bold: true, align: 'left', color: '#0f172a', show_box: true, page: 1, z_index: 6 },
          { id: 'f-corte-tot-dec', type: 'field', label: 'TOTAL DECLARADO CAJERO (CORTE Z)', field_key: 'corte.total_declarado_general', text: 'Declarado Cajero: {{corte.total_declarado_general}}', x_mm: leftMargin + 63.0, y_mm: 148.0, w_mm: 60.0, h_mm: 8.0, font_family: 'Arial', font_size: 9.5, bold: true, align: 'left', color: '#0f172a', show_box: true, page: 1, z_index: 6 },
          { id: 'f-corte-dif-neta', type: 'field', label: 'DIFERENCIA NETA (SOBRANTE / FALTANTE)', field_key: 'corte.diferencia_neta', text: 'DIFERENCIA: {{corte.diferencia_neta}}', x_mm: leftMargin + 126.0, y_mm: 148.0, w_mm: 62.0, h_mm: 8.0, font_family: 'Arial', font_size: 10, bold: true, align: 'right', color: pri, is_total_highlight: true, show_box: true, page: 1, z_index: 6 },
          { id: 'f-corte-dictamen', type: 'field', label: 'DICTAMEN DE CUADRE Y AUDITORÍA', field_key: 'corte.estado_cuadre', text: 'DICTAMEN DE CIERRE Z: {{corte.estado_cuadre}}', x_mm: leftMargin, y_mm: 158.0, w_mm: 188.0, h_mm: 8.0, font_family: 'Arial', font_size: 10, bold: true, align: 'center', color: '#065f46', show_box: true, page: 1, z_index: 6 },
          { id: 'f-sub-sin-iva', type: 'field', label: 'VENTAS SUBTOTAL SIN IVA (CORTE Z)', field_key: 'importes.subtotal_sin_iva', text: 'Ventas SIN IVA: {{importes.subtotal_sin_iva}}', x_mm: leftMargin, y_mm: 168.0, w_mm: 60.0, h_mm: 7.0, font_family: 'Arial', font_size: 9, bold: true, align: 'left', color: '#334155', show_box: true, page: 1, z_index: 5 },
          { id: 'f-imp-total', type: 'field', label: 'IMPUESTO IVA 16% TRASLADADO (CORTE Z)', field_key: 'importes.impuesto_total', text: 'IVA 16% Turno: {{importes.impuesto_total}}', x_mm: leftMargin + 63.0, y_mm: 168.0, w_mm: 60.0, h_mm: 7.0, font_family: 'Arial', font_size: 9, bold: true, align: 'left', color: '#334155', show_box: true, page: 1, z_index: 5 },
          { id: 'f-tot-total', type: 'field', label: 'VENTAS NETAS CON IVA (CORTE Z)', field_key: 'importes.total_con_iva', text: 'Ventas CON IVA: {{importes.total_con_iva}}', x_mm: leftMargin + 126.0, y_mm: 168.0, w_mm: 62.0, h_mm: 7.0, font_family: 'Arial', font_size: 9.5, bold: true, align: 'right', color: '#0f172a', show_box: true, page: 1, z_index: 5 }
        );
      }

      // Sello QR, Serie del Sello y 3 Firmas Oficiales de Corte de Caja (Cajero, Supervisor, Auditoría)
      els.push(
        { id: 'layer-qr-sat', type: 'image', label: 'SELLO QR AUDITORÍA DE CORTE', src: SAMPLE_QR_SVG, field_key: 'cfdi.qr_sat', x_mm: leftMargin, y_mm: 179.0, w_mm: 24.0, h_mm: 24.0, page: 1, z_index: 5 },
        { id: 'f-cfdi-serie-sello', type: 'field', label: 'SERIE DEL SELLO CSD', field_key: 'cfdi.serie_sello', text: 'Serie Sello CSD: {{cfdi.serie_sello}}', x_mm: leftMargin + 27.0, y_mm: 180.0, w_mm: 82.0, h_mm: 7.0, font_family: 'Courier New', font_size: 8.5, bold: true, align: 'left', color: '#0f172a', show_box: true, page: 1, z_index: 5 },
        { id: 'f-corte-supervisor', type: 'field', label: 'SUPERVISOR QUE AUTORIZA EL CORTE', field_key: 'corte.supervisor_autoriza', text: 'Autoriza Corte: {{corte.supervisor_autoriza}}', x_mm: leftMargin + 27.0, y_mm: 189.0, w_mm: 120.0, h_mm: 7.0, font_family: 'Arial', font_size: 9, bold: true, align: 'left', color: '#0f172a', show_box: true, page: 1, z_index: 5 },
        { id: 'layer-sig-cajero', type: 'signature', label: 'FIRMA CAJERO QUE ENTREGA', text: 'Cajero Responsable\nEntrega Efectivo y Vouchers', x_mm: leftMargin, y_mm: 215.0, w_mm: 58.0, h_mm: 24.0, font_family: 'Arial', font_size: 9, bold: true, align: 'center', color: '#0f172a', page: 1, z_index: 4 },
        { id: 'layer-sig-supervisor', type: 'signature', label: 'FIRMA SUPERVISOR / GERENTE', text: 'Supervisor de Caja\nRecibe y Verifica Tómbola', x_mm: leftMargin + 65.0, y_mm: 215.0, w_mm: 58.0, h_mm: 24.0, font_family: 'Arial', font_size: 9, bold: true, align: 'center', color: '#0f172a', page: 1, z_index: 4 },
        { id: 'layer-signature', type: 'signature', label: 'FIRMA AUDITORÍA / BÓVEDA', text: 'Auditoría / Tesorería\nValidación de Cierre', x_mm: leftMargin + 130.0, y_mm: 215.0, w_mm: 58.0, h_mm: 24.0, font_family: 'Arial', font_size: 9, bold: true, align: 'center', color: '#0f172a', page: 1, z_index: 4 }
      );

      if (sNum !== 20) {
        els.push({
          id: 'layer-bottom-ribbon',
          type: 'rect',
          label: 'CINTILLO INFERIOR AUDITORÍA DE CAJA',
          x_mm: leftMargin,
          y_mm: 262.0,
          w_mm: 188.0,
          h_mm: 4.5,
          background_color: pri,
          border_color: sec,
          page: 1,
          z_index: 1
        });
      }
      return els;
    }

    /* ═══════════════════════════════════════════════════════════════════════════
       CASO GENERAL A2: DOCUMENTOS COMERCIALES, FISCALES, CRÉDITO Y LOGÍSTICOS (20 ESTILOS)
       ═══════════════════════════════════════════════════════════════════════════ */
    els.push(
      { id: 'lbl-cliente', type: 'text', label: 'ETIQUETA CLIENTE:', text: 'Cliente:', x_mm: leftMargin, y_mm: 48.0, w_mm: 18.0, h_mm: 7.0, font_family: 'Arial', font_size: 10, bold: true, align: 'left', color: '#0f172a', page: 1, z_index: 3 },
      { id: 'f-cli-nombre', type: 'field', label: 'NOMBRE DEL CLIENTE', field_key: 'cliente.nombre', text: '{{cliente.nombre}}', x_mm: leftMargin + 19.0, y_mm: 48.0, w_mm: 90.0, h_mm: 7.5, font_family: 'Arial', font_size: 11, bold: true, align: 'left', color: '#000000', show_box: true, page: 1, z_index: 6 },

      { id: 'lbl-dir', type: 'text', label: 'ETIQUETA DIRECCIÓN:', text: 'Dirección:', x_mm: leftMargin, y_mm: 57.0, w_mm: 18.0, h_mm: 6.5, font_family: 'Arial', font_size: 10, bold: true, align: 'left', color: '#0f172a', page: 1, z_index: 3 },
      { id: 'f-cli-dir', type: 'field', label: 'DIRECCIÓN DEL CLIENTE', field_key: 'cliente.domicilio', text: '{{cliente.direccion}}', x_mm: leftMargin + 19.0, y_mm: 57.0, w_mm: 90.0, h_mm: 6.5, font_family: 'Arial', font_size: 10, bold: false, align: 'left', color: '#1e293b', page: 1, z_index: 5 },

      { id: 'lbl-tel', type: 'text', label: 'ETIQUETA TELÉFONO:', text: 'Teléfono:', x_mm: leftMargin, y_mm: 64.5, w_mm: 18.0, h_mm: 6.5, font_family: 'Arial', font_size: 10, bold: true, align: 'left', color: '#0f172a', page: 1, z_index: 3 },
      { id: 'f-cli-tel', type: 'field', label: 'TELÉFONO DEL CLIENTE', field_key: 'cliente.telefono', text: '{{cliente.telefono}}', x_mm: leftMargin + 19.0, y_mm: 64.5, w_mm: 70.0, h_mm: 6.5, font_family: 'Arial', font_size: 10, bold: false, align: 'left', color: '#1e293b', page: 1, z_index: 5 },

      { id: 'lbl-correo', type: 'text', label: 'ETIQUETA CORREO:', text: 'Correo:', x_mm: leftMargin, y_mm: 72.0, w_mm: 18.0, h_mm: 6.5, font_family: 'Arial', font_size: 10, bold: true, align: 'left', color: '#0f172a', page: 1, z_index: 3 },
      { id: 'f-cli-correo', type: 'field', label: 'CORREO DEL CLIENTE', field_key: 'cliente.correo', text: '{{cliente.correo}}', x_mm: leftMargin + 19.0, y_mm: 72.0, w_mm: 85.0, h_mm: 6.5, font_family: 'Arial', font_size: 10, bold: false, align: 'left', color: '#1e293b', page: 1, z_index: 5 },

      { id: 'lbl-folio', type: 'text', label: 'ETIQUETA FOLIO:', text: 'Folio:', x_mm: 136.0, y_mm: 48.0, w_mm: 18.0, h_mm: 7.0, font_family: 'Arial', font_size: 10, bold: true, align: 'left', color: '#0f172a', page: 1, z_index: 3 },
      { id: 'f-doc-folio', type: 'field', label: 'FOLIO DEL DOCUMENTO', field_key: 'operacion.folio', text: '{{documento.folio}}', x_mm: 156.0, y_mm: 48.0, w_mm: 45.0, h_mm: 7.0, font_family: 'Arial', font_size: 10, bold: true, align: 'center', color: '#0f172a', show_box: true, page: 1, z_index: 5 },

      { id: 'lbl-fecha', type: 'text', label: 'ETIQUETA FECHA:', text: 'Fecha:', x_mm: 136.0, y_mm: 57.0, w_mm: 18.0, h_mm: 7.0, font_family: 'Arial', font_size: 10, bold: true, align: 'left', color: '#0f172a', page: 1, z_index: 3 },
      { id: 'f-doc-fecha', type: 'field', label: 'FECHA DE EMISIÓN', field_key: 'operacion.fecha', text: '{{documento.fecha}}', x_mm: 156.0, y_mm: 57.0, w_mm: 45.0, h_mm: 7.0, font_family: 'Arial', font_size: 10, bold: false, align: 'center', color: '#0f172a', show_box: true, page: 1, z_index: 5 },

      { id: 'lbl-vigencia', type: 'text', label: 'VIGENCIA / CONDICIÓN', text: 'Vigencia:     15 días', x_mm: 136.0, y_mm: 66.0, w_mm: 60.0, h_mm: 6.5, font_family: 'Arial', font_size: 10, bold: true, align: 'left', color: '#0f172a', page: 1, z_index: 3 },

      {
        id: 'layer-intro-saludo',
        type: 'text',
        label: 'SALUDO / INTRODUCCIÓN',
        text: 'Estimado(a) cliente:\nA continuación, ponemos a su consideración el detalle de materiales y conceptos conforme a la NOM-030-SCFI:',
        x_mm: leftMargin,
        y_mm: 82.0,
        w_mm: 185.0,
        h_mm: 9.5,
        font_family: 'Arial',
        font_size: 9,
        color: '#0f172a',
        wrap: true,
        page: 1,
        z_index: 3
      },
      {
        id: 'layer-table-products',
        type: 'table_products',
        label: 'TABLA DE ARTÍCULOS (CON/SIN IVA)',
        tax_display_mode: ((sNum === 8 || sNum === 14) ? 'DESGLOSADO' : (sNum === 10 ? 'SIN_IVA' : 'CON_IVA')),
        x_mm: leftMargin,
        y_mm: 93.0,
        w_mm: (sNum === 12) ? 185.0 : 187.0,
        h_mm: 50.0,
        header_bg: pri,
        bottom_limit_y_mm: 212.0,
        last_page_reserved_mm: 58.0,
        page: 1,
        z_index: 2
      },
      {
        id: 'layer-totals-box',
        type: 'totals_block',
        label: 'CUADRO SUBTOTAL SIN/CON IVA E IMPUESTO TOTAL',
        x_mm: 116.0,
        y_mm: 145.5,
        w_mm: 85.0,
        h_mm: 27.0,
        page: 1,
        z_index: 3
      },
      {
        id: 'f-sub-sin-iva',
        type: 'field',
        label: 'SUBTOTAL SIN IVA (POR SEPARADO)',
        field_key: 'importes.subtotal_sin_iva',
        text: '{{importes.subtotal_sin_iva}}',
        x_mm: 162.0,
        y_mm: 146.0,
        w_mm: 37.0,
        h_mm: 6.0,
        font_family: 'Arial',
        font_size: 9.5,
        bold: true,
        align: 'right',
        color: '#0f172a',
        page: 1,
        z_index: 6
      },
      {
        id: 'f-imp-total',
        type: 'field',
        label: 'IMPUESTO TOTAL IVA 16% (POR SEPARADO)',
        field_key: 'importes.impuesto_total',
        text: '{{importes.impuesto_total}}',
        x_mm: 162.0,
        y_mm: 152.5,
        w_mm: 37.0,
        h_mm: 6.0,
        font_family: 'Arial',
        font_size: 9.5,
        bold: true,
        align: 'right',
        color: '#0f172a',
        page: 1,
        z_index: 6
      },
      {
        id: 'f-sub-con-iva',
        type: 'field',
        label: 'SUBTOTAL CON IVA (POR SEPARADO)',
        field_key: 'importes.subtotal_con_iva',
        text: '{{importes.subtotal_con_iva}}',
        x_mm: 162.0,
        y_mm: 159.0,
        w_mm: 37.0,
        h_mm: 6.0,
        font_family: 'Arial',
        font_size: 9.5,
        bold: true,
        align: 'right',
        color: '#0f172a',
        page: 1,
        z_index: 6
      },
      {
        id: 'f-tot-total',
        type: 'field',
        label: 'TOTAL CON IVA (POR SEPARADO)',
        field_key: 'importes.total_con_iva',
        text: '{{importes.total_con_iva}}',
        x_mm: 162.0,
        y_mm: 165.5,
        w_mm: 37.0,
        h_mm: 6.5,
        font_family: 'Arial',
        font_size: 10.5,
        bold: true,
        align: 'right',
        color: pri,
        is_total_highlight: true,
        page: 1,
        z_index: 6
      },
      {
        id: 'layer-conditions',
        type: 'text',
        label: 'CONDICIONES COMERCIALES',
        text: 'Condiciones comerciales:\n• Precios en moneda nacional (MXN).\n• Sujeto a disponibilidad de inventario.\n• Revisar su mercancía al momento de recibir.\n• Forma de pago: Contado, transferencia o crédito autorizado.',
        x_mm: leftMargin,
        y_mm: (sNum === 7) ? 208.0 : 193.0,
        w_mm: 108.0,
        h_mm: 28.0,
        font_family: 'Arial',
        font_size: 8.5,
        color: '#1e293b',
        wrap: true,
        page: 1,
        z_index: 3
      },
      {
        id: 'layer-profeco-norma',
        type: 'field',
        label: 'CLÁUSULA Y NORMATIVIDAD OFICIAL PROFECO (ART. 12 Y 77 LFPC)',
        field_key: 'profeco.leyenda_garantias',
        text: '{{profeco.leyenda_garantias}}',
        x_mm: leftMargin,
        y_mm: 242.0,
        w_mm: 187.0,
        h_mm: 16.0,
        font_family: 'Arial',
        font_size: 7.5,
        bold: false,
        align: 'left',
        color: '#334155',
        show_box: true,
        page: 1,
        z_index: 4
      },
      {
        id: 'layer-signature',
        type: 'signature',
        label: 'FIRMA AUTORIZADA / CONFORMIDAD',
        text: 'Atentamente\nEquipo de Ventas y Operaciones\nMAGDALENO MADERAS Y MATERIALES',
        x_mm: (sNum === 19) ? 75.0 : 132.0,
        y_mm: (sNum === 7) ? 210.0 : 196.0,
        w_mm: 66.0,
        h_mm: 24.0,
        font_family: 'Arial',
        font_size: 9,
        bold: true,
        align: 'center',
        color: '#0f172a',
        page: 1,
        z_index: 3
      }
    );

    if (sNum === 6 || sNum === 9) {
      els.push({
        id: 'layer-sig-extra',
        type: 'signature',
        label: 'FIRMA DESPACHADOR / CHOFER PATIO',
        text: 'Entregó Almacén / Chofer\nNombre, Placas y Firma',
        x_mm: leftMargin,
        y_mm: 221.0,
        w_mm: 62.0,
        h_mm: 19.0,
        font_family: 'Arial',
        font_size: 8.5,
        bold: true,
        align: 'center',
        color: '#0f172a',
        page: 1,
        z_index: 3
      });
    }

    /* --- SELLO QR Y SERIE DEL SELLO POR SEPARADO (100% INDEPENDIENTES Y MOVIBLES EN CARTA) --- */
    els.push(
      {
        id: 'layer-qr-sat',
        type: 'image',
        label: 'SELLO QR FISCAL (POR SEPARADO)',
        src: SAMPLE_QR_SVG,
        field_key: 'cfdi.qr_sat',
        x_mm: leftMargin,
        y_mm: 147.0,
        w_mm: 24.0,
        h_mm: 24.0,
        page: 1,
        z_index: 5
      },
      {
        id: 'f-cfdi-serie-sello',
        type: 'field',
        label: 'SERIE DEL SELLO CSD (POR SEPARADO)',
        field_key: 'cfdi.serie_sello',
        text: 'Serie del Sello CSD: {{cfdi.serie_sello}}',
        x_mm: leftMargin + 27.0,
        y_mm: 147.5,
        w_mm: 72.0,
        h_mm: 7.0,
        font_family: 'Courier New',
        font_size: 8.5,
        bold: true,
        align: 'left',
        color: '#0f172a',
        show_box: true,
        page: 1,
        z_index: 5
      },
      {
        id: 'f-cfdi-cert-sat',
        type: 'field',
        label: 'SERIE DEL SELLO SAT (POR SEPARADO)',
        field_key: 'cfdi.no_cert_sat',
        text: 'Serie Sello SAT: {{cfdi.no_cert_sat}}',
        x_mm: leftMargin + 27.0,
        y_mm: 156.0,
        w_mm: 72.0,
        h_mm: 6.5,
        font_family: 'Courier New',
        font_size: 8.5,
        bold: false,
        align: 'left',
        color: '#334155',
        show_box: true,
        page: 1,
        z_index: 5
      }
    );

    if (sNum === 8 || String(docType).indexOf('cfdi') >= 0) {
      els.push({
        id: 'f-cfdi-sello-digital',
        type: 'field',
        label: 'SELLO DIGITAL CFDI (POR SEPARADO)',
        field_key: 'cfdi.sello_cfdi',
        text: 'Sello Digital CFDI: {{cfdi.sello_cfdi}}',
        x_mm: leftMargin + 27.0,
        y_mm: 164.0,
        w_mm: 72.0,
        h_mm: 9.0,
        font_family: 'Courier New',
        font_size: 7.5,
        bold: false,
        align: 'left',
        color: '#334155',
        show_box: true,
        page: 1,
        z_index: 5
      });
    }

    /* --- SALDO ANTERIOR Y SALDO ACTUAL POR SEPARADO (NOTAS DE CRÉDITO / CRÉDITO / ABONO / ESTADO DE CUENTA) --- */
    var isCreditDocCarta = (sNum === 7 || /credito|comprobante_pago|devolucion|estado_cuenta/i.test(String(docType || '')));
    if (isCreditDocCarta) {
      els.push(
        {
          id: 'f-cred-saldo-anterior',
          type: 'field',
          label: 'SALDO ANTERIOR (POR SEPARADO)',
          field_key: 'credito.saldo_anterior',
          text: 'Saldo Anterior: {{credito.saldo_anterior}}',
          x_mm: leftMargin,
          y_mm: 175.0,
          w_mm: 58.0,
          h_mm: 7.0,
          font_family: 'Arial',
          font_size: 9.5,
          bold: true,
          align: 'left',
          color: '#1e293b',
          show_box: true,
          page: 1,
          z_index: 6
        },
        {
          id: 'f-cred-importe-abono',
          type: 'field',
          label: 'CARGO / ABONO OPERACIÓN (POR SEPARADO)',
          field_key: 'credito.importe_abono',
          text: 'Cargo / Abono: {{credito.importe_abono}}',
          x_mm: leftMargin + 61.0,
          y_mm: 175.0,
          w_mm: 58.0,
          h_mm: 7.0,
          font_family: 'Arial',
          font_size: 9.5,
          bold: true,
          align: 'left',
          color: '#0f172a',
          show_box: true,
          page: 1,
          z_index: 6
        },
        {
          id: 'f-cred-saldo-actual',
          type: 'field',
          label: 'SALDO ACTUAL (POR SEPARADO)',
          field_key: 'credito.saldo_actual',
          text: 'Saldo Actual: {{credito.saldo_actual}}',
          x_mm: leftMargin + 122.0,
          y_mm: 175.0,
          w_mm: 63.0,
          h_mm: 7.5,
          font_family: 'Arial',
          font_size: 10,
          bold: true,
          align: 'right',
          color: pri,
          is_total_highlight: true,
          page: 1,
          z_index: 6
        },
        {
          id: 'layer-pagare-txt',
          type: 'field',
          label: 'LEYENDA PAGARÉ MERCANTIL',
          field_key: 'credito.pagare_leyenda',
          text: 'PAGARÉ MERCANTIL: {{credito.pagare_leyenda}}',
          x_mm: leftMargin,
          y_mm: 184.0,
          w_mm: 185.0,
          h_mm: 18.0,
          font_family: 'Arial',
          font_size: 8,
          bold: true,
          color: '#1e293b',
          show_box: true,
          page: 1,
          z_index: 4
        }
      );
    }

    if (sNum !== 20) {
      els.push({
        id: 'layer-bottom-ribbon',
        type: 'rect',
        label: 'CINTILLO INFERIOR DECORATIVO',
        x_mm: leftMargin,
        y_mm: 262.0,
        w_mm: (sNum === 12) ? 185.0 : 187.0,
        h_mm: 4.5,
        background_color: pri,
        border_color: sec,
        page: 1,
        z_index: 1
      });
    }

    return els;
  }

  /* ── B) 20 DISEÑOS ESTRUCTURALES DISTINTOS EN TICKET TÉRMICO DE 80 MM Y 58 MM (100% MOVIBLES POR CAPAS) ── */
  function generateThermalTicketLayers(docType, paperFormat, styleMeta, titleUpper) {
    var is58 = (paperFormat === '58mm');
    var pw = is58 ? 58.0 : 80.0;
    var padX = is58 ? 2.5 : 4.0;
    var innerW = Number((pw - padX * 2).toFixed(1));
    var sNum = styleMeta.num;
    var pri = styleMeta.primary;
    var sec = styleMeta.secondary;
    var logoUrl = (sNum === 2 || sNum === 11 || sNum === 15)
      ? buildLogoSvgDataUrl('#ffffff', '#93c5fd', pri)
      : buildLogoSvgDataUrl(pri, sec, null);

    var dTypeLow = String(docType || '').toLowerCase();
    var isCorteCiego = (dTypeLow === 'corte_ciego' || sNum === 16);
    var isCorteX = (dTypeLow === 'corte_x' || dTypeLow === 'apertura_caja' || dTypeLow === 'arqueo_caja' || sNum === 17);
    var isCorteZ = (dTypeLow === 'corte_z' || sNum === 18);
    var isAnyCorte = (isCorteCiego || isCorteX || isCorteZ);

    var fTitle = is58 ? 9.5 : 11.5;
    var fBody = is58 ? 8 : 9.5;
    var fSmall = is58 ? 7.2 : 8.2;

    var els = [];

    // 1. Variación arquitectónica de encabezado térmico según los 20 estilos profesionales
    if (sNum === 2 || sNum === 11 || sNum === 15) {
      // Estilos 02 (Costco), 11 (AutoZone Invertido), 15 (BBVA Bóveda): Cabezal invertido de color a todo el ancho
      els.push(
        { id: 't-top-banner', type: 'rect', label: 'CABEZAL INVERTIDO TICKET', x_mm: 0.0, y_mm: 0.0, w_mm: pw, h_mm: 18.0, background_color: (sNum === 11 ? '#18181b' : pri), border_color: pri, page: 1, z_index: 1 },
        { id: 't-logo', type: 'image', label: 'LOGO MAGDALENO TICKET', src: logoUrl, x_mm: padX + 2.0, y_mm: 2.0, w_mm: innerW - 4.0, h_mm: 14.0, page: 1, z_index: 3 }
      );
    } else if (sNum === 4 || sNum === 19) {
      // Estilos 04 (Liverpool) y 19 (Notarial): Marco perimetral completo alrededor del ticket
      els.push(
        { id: 't-perimeter-frame', type: 'rect', label: 'MARCO PERIMETRAL TICKET', x_mm: 1.5, y_mm: 1.5, w_mm: Number((pw - 3.0).toFixed(1)), h_mm: 205.0, background_color: 'transparent', border_color: pri, page: 1, z_index: 1 },
        { id: 't-logo', type: 'image', label: 'LOGO MAGDALENO TICKET', src: logoUrl, x_mm: padX + 2.0, y_mm: 4.0, w_mm: innerW - 4.0, h_mm: 13.5, page: 1, z_index: 2 }
      );
    } else if (sNum === 5) {
      // Estilo 05 (OXXO / 7-Eleven Express): Cuadrícula superior de 2 celdas
      els.push(
        { id: 't-grid-top', type: 'rect', label: 'CELDA EXPRESS SUPERIOR', x_mm: padX, y_mm: 3.0, w_mm: innerW, h_mm: 15.0, background_color: '#fffbeb', border_color: pri, page: 1, z_index: 1 },
        { id: 't-logo', type: 'image', label: 'LOGO MAGDALENO EXPRESS', src: logoUrl, x_mm: padX + 2.0, y_mm: 4.0, w_mm: innerW - 4.0, h_mm: 13.0, page: 1, z_index: 3 }
      );
    } else if (sNum === 9) {
      // Estilo 09 (Amazon / MercadoLibre): QR Logístico arriba a la izquierda + Logo a la derecha
      els.push(
        { id: 't-top-qr-guide', type: 'image', label: 'QR GUÍA SUPERIOR TICKET', src: SAMPLE_QR_SVG, x_mm: padX, y_mm: 3.5, w_mm: 14.0, h_mm: 14.0, page: 1, z_index: 4 },
        { id: 't-logo', type: 'image', label: 'LOGO MAGDALENO LOGÍSTICO', src: logoUrl, x_mm: padX + 15.5, y_mm: 4.0, w_mm: Number((innerW - 15.5).toFixed(1)), h_mm: 13.0, page: 1, z_index: 2 }
      );
    } else if (sNum === 12) {
      // Estilo 12 (Sears / Sanborns): Barra vertical lateral izquierda a todo lo alto del ticket
      els.push(
        { id: 't-left-bar', type: 'rect', label: 'BARRA LATERAL TICKET', x_mm: 0.0, y_mm: 0.0, w_mm: 2.5, h_mm: 205.0, background_color: pri, border_color: pri, page: 1, z_index: 1 },
        { id: 't-logo', type: 'image', label: 'LOGO MAGDALENO TICKET', src: logoUrl, x_mm: padX + 2.0, y_mm: 4.0, w_mm: innerW - 2.0, h_mm: 14.0, page: 1, z_index: 2 }
      );
    } else if (sNum === 6 || sNum === 14) {
      // Estilos 06 (Cemex) y 14 (Truper): Doble cinta industrial superior
      els.push(
        { id: 't-top-dark', type: 'rect', label: 'FRANJA INDUSTRIAL SUPERIOR', x_mm: 0.0, y_mm: 0.0, w_mm: pw, h_mm: 3.0, background_color: '#18181b', border_color: '#18181b', page: 1, z_index: 1 },
        { id: 't-top-amber', type: 'rect', label: 'FRANJA INDUSTRIAL ACENTO', x_mm: 0.0, y_mm: 3.0, w_mm: pw, h_mm: 2.0, background_color: pri, border_color: pri, page: 1, z_index: 1 },
        { id: 't-logo', type: 'image', label: 'LOGO MAGDALENO TICKET', src: logoUrl, x_mm: padX + 2.0, y_mm: 6.0, w_mm: innerW - 4.0, h_mm: 13.0, page: 1, z_index: 2 }
      );
    } else if (sNum !== 20) {
      // Resto de estilos (excepto 20 Papel Preimpreso): Logo superior movible
      els.push(
        { id: 't-logo', type: 'image', label: 'LOGO MAGDALENO TICKET', src: logoUrl, x_mm: padX + 2.0, y_mm: 4.0, w_mm: innerW - 4.0, h_mm: 14.0, page: 1, z_index: 2 }
      );
    }

    // 2. Datos Fiscales del Emisor y Cumplimiento PROFECO (Movible)
    els.push({
      id: 't-empresa-info',
      type: 'text',
      label: 'DATOS EMISOR Y PROFECO TICKET',
      text: 'MAGDALENO MADERAS Y MATERIALES\nRFC: GMM2106218A1 · Tel. (33) 3615 4287\nAv. Reforma 1250 · PROFECO 800-468-8722',
      x_mm: padX,
      y_mm: 19.5,
      w_mm: innerW,
      h_mm: 13.0,
      font_family: 'Arial',
      font_size: fSmall,
      bold: false,
      align: 'center',
      color: '#0f172a',
      wrap: true,
      page: 1,
      z_index: 3
    });

    // 3. Cintillo y Título del Ticket (Movible y Escalable)
    var effectiveTicketTitle = isCorteCiego
      ? 'CORTE CIEGO DE CAJA Y TÓMBOLA'
      : (isCorteX ? 'CORTE PARCIAL DE CAJA (X)' : (isCorteZ ? 'CORTE Z · CIERRE DEFINITIVO' : titleUpper));

    els.push(
      {
        id: 't-title-bg',
        type: 'rect',
        label: 'FRANJA TÍTULO TICKET',
        x_mm: padX,
        y_mm: 33.5,
        w_mm: innerW,
        h_mm: 8.0,
        background_color: (sNum === 10 || sNum === 20) ? '#f8fafc' : styleMeta.badgeBg,
        border_color: pri,
        page: 1,
        z_index: 1
      },
      {
        id: 't-doc-title',
        type: 'text',
        label: 'TÍTULO DEL TICKET',
        text: effectiveTicketTitle,
        x_mm: padX + 1.0,
        y_mm: 34.5,
        w_mm: innerW - 2.0,
        h_mm: 6.5,
        font_family: 'Arial',
        font_size: fTitle,
        bold: true,
        align: 'center',
        color: pri,
        page: 1,
        z_index: 4
      }
    );

    /* ═══════════════════════════════════════════════════════════════════════════
       CASO ESPECIAL B1: TICKETS DE CORTE DE CAJA (CORTE CIEGO, CORTE X, CORTE Z) EN 80MM / 58MM
       ═══════════════════════════════════════════════════════════════════════════ */
    if (isAnyCorte) {
      var corteTblType = isCorteCiego ? 'table_corte_ciego' : (isCorteX ? 'table_corte_x' : 'table_corte_z');
      var corteTblLabel = isCorteCiego
        ? 'TABLA ARQUEO CIEGO (BILLETES, MONEDAS Y VOUCHERS)'
        : (isCorteX ? 'TABLA FLUJO DE EFECTIVO EN GAVETA (CORTE X)' : 'TABLA CONCILIACIÓN: ESPERADO VS DECLARADO (CORTE Z)');

      els.push(
        { id: 'f-doc-folio', type: 'field', label: 'FOLIO DEL CORTE', field_key: 'operacion.folio', text: 'Folio: {{documento.folio}}', x_mm: padX, y_mm: 43.0, w_mm: Number((innerW * 0.52).toFixed(1)), h_mm: 6.0, font_family: 'Arial', font_size: fBody, bold: true, align: 'left', color: '#000000', show_box: true, page: 1, z_index: 5 },
        { id: 'f-doc-fecha', type: 'field', label: 'FECHA Y HORA CORTE', field_key: 'operacion.fecha', text: '{{documento.fecha}}', x_mm: Number((padX + innerW * 0.54).toFixed(1)), y_mm: 43.0, w_mm: Number((innerW * 0.46).toFixed(1)), h_mm: 6.0, font_family: 'Arial', font_size: fSmall, bold: false, align: 'right', color: '#0f172a', show_box: true, page: 1, z_index: 5 },
        { id: 'f-corte-turno', type: 'field', label: 'TURNO Y CAJERO', field_key: 'corte.turno', text: 'Turno: {{corte.turno}} | {{operacion.vendedor}}', x_mm: padX, y_mm: 50.0, w_mm: innerW, h_mm: 6.5, font_family: 'Arial', font_size: fSmall, bold: true, align: 'left', color: '#0f172a', show_box: true, page: 1, z_index: 5 },
        { id: 'f-corte-folios', type: 'field', label: 'RANGO DE FOLIOS Y OPERACIONES', field_key: 'corte.folio_inicial', text: 'Folios: {{corte.folio_inicial}} a {{corte.folio_final}} ({{corte.num_operaciones}} ops)', x_mm: padX, y_mm: 57.5, w_mm: innerW, h_mm: 6.0, font_family: 'Arial', font_size: fSmall, bold: false, align: 'left', color: '#334155', show_box: true, page: 1, z_index: 5 },
        { id: 'layer-table-corte', type: corteTblType, label: corteTblLabel, header_bg: pri, x_mm: padX, y_mm: 65.0, w_mm: innerW, h_mm: 56.0, page: 1, z_index: 3 }
      );

      if (isCorteCiego) {
        els.push(
          { id: 'f-corte-sobre', type: 'field', label: 'FOLIO SOBRE / TÓMBOLA', field_key: 'corte.folio_sobre', text: 'Sobre Tómbola: {{corte.folio_sobre}}', x_mm: padX, y_mm: 123.0, w_mm: innerW, h_mm: 6.5, font_family: 'Courier New', font_size: fSmall, bold: true, align: 'center', color: '#0f172a', show_box: true, page: 1, z_index: 5 },
          { id: 'f-corte-efec-dec', type: 'field', label: 'EFECTIVO FÍSICO DECLARADO', field_key: 'corte.efectivo_declarado', text: 'Efectivo Declarado: {{corte.efectivo_declarado}}', x_mm: padX, y_mm: 130.5, w_mm: innerW, h_mm: 6.5, font_family: 'Arial', font_size: fBody, bold: true, align: 'right', color: '#0f172a', show_box: true, page: 1, z_index: 6 },
          { id: 'f-corte-tot-dec', type: 'field', label: 'TOTAL DECLARADO A CIEGAS', field_key: 'corte.total_declarado_general', text: 'TOTAL DECLARADO: {{corte.total_declarado_general}}', x_mm: padX, y_mm: 138.0, w_mm: innerW, h_mm: 7.5, font_family: 'Arial', font_size: fBody, bold: true, align: 'right', color: pri, is_total_highlight: true, show_box: true, page: 1, z_index: 6 }
        );
      } else if (isCorteX) {
        els.push(
          { id: 'f-corte-fondo', type: 'field', label: '(+) FONDO INICIAL CAJA', field_key: 'corte.fondo_inicial', text: '(+) Fondo Inicial: {{corte.fondo_inicial}}', x_mm: padX, y_mm: 123.0, w_mm: innerW, h_mm: 6.0, font_family: 'Arial', font_size: fSmall, bold: true, align: 'left', color: '#0f172a', show_box: true, page: 1, z_index: 5 },
          { id: 'f-corte-efec-esp', type: 'field', label: '(=) EFECTIVO ESPERADO EN GAVETA', field_key: 'corte.efectivo_esperado', text: '(=) Efectivo en Gaveta: {{corte.efectivo_esperado}}', x_mm: padX, y_mm: 130.0, w_mm: innerW, h_mm: 6.5, font_family: 'Arial', font_size: fBody, bold: true, align: 'right', color: '#0f172a', show_box: true, page: 1, z_index: 6 },
          { id: 'f-corte-tot-esp', type: 'field', label: 'TOTAL ACUMULADO TURNO ABIERTO (X)', field_key: 'corte.total_esperado_general', text: 'TOTAL TURNO (X): {{corte.total_esperado_general}}', x_mm: padX, y_mm: 137.5, w_mm: innerW, h_mm: 7.5, font_family: 'Arial', font_size: fBody, bold: true, align: 'right', color: pri, is_total_highlight: true, show_box: true, page: 1, z_index: 6 }
        );
      } else {
        els.push(
          { id: 'f-corte-tot-esp', type: 'field', label: 'TOTAL ESPERADO SISTEMA (Z)', field_key: 'corte.total_esperado_general', text: 'Esperado Sistema: {{corte.total_esperado_general}}', x_mm: padX, y_mm: 122.5, w_mm: innerW, h_mm: 6.0, font_family: 'Arial', font_size: fSmall, bold: true, align: 'right', color: '#0f172a', show_box: true, page: 1, z_index: 5 },
          { id: 'f-corte-tot-dec', type: 'field', label: 'TOTAL DECLARADO CAJERO (Z)', field_key: 'corte.total_declarado_general', text: 'Declarado Cajero: {{corte.total_declarado_general}}', x_mm: padX, y_mm: 129.0, w_mm: innerW, h_mm: 6.0, font_family: 'Arial', font_size: fSmall, bold: true, align: 'right', color: '#0f172a', show_box: true, page: 1, z_index: 5 },
          { id: 'f-corte-dif-neta', type: 'field', label: 'DIFERENCIA NETA (SOBRANTE / FALTANTE)', field_key: 'corte.diferencia_neta', text: 'DIFERENCIA NETA: {{corte.diferencia_neta}}', x_mm: padX, y_mm: 135.5, w_mm: innerW, h_mm: 7.0, font_family: 'Arial', font_size: fBody, bold: true, align: 'right', color: pri, is_total_highlight: true, show_box: true, page: 1, z_index: 6 },
          { id: 'f-corte-dictamen', type: 'field', label: 'DICTAMEN DE CUADRE Z', field_key: 'corte.estado_cuadre', text: '{{corte.estado_cuadre}}', x_mm: padX, y_mm: 143.5, w_mm: innerW, h_mm: 6.5, font_family: 'Arial', font_size: fSmall, bold: true, align: 'center', color: '#065f46', show_box: true, page: 1, z_index: 6 }
        );
      }

      els.push(
        { id: 'f-cfdi-serie-sello', type: 'field', label: 'SERIE DEL SELLO CSD', field_key: 'cfdi.serie_sello', text: 'Serie Sello: {{cfdi.serie_sello}}', x_mm: padX, y_mm: 151.5, w_mm: innerW, h_mm: 6.0, font_family: 'Courier New', font_size: fSmall, bold: true, align: 'center', color: '#0f172a', show_box: true, page: 1, z_index: 5 },
        { id: 't-qr', type: 'image', label: 'SELLO QR AUDITORÍA CORTE', src: SAMPLE_QR_SVG, field_key: 'cfdi.qr_sat', x_mm: padX, y_mm: 159.0, w_mm: 17.0, h_mm: 17.0, page: 1, z_index: 5 },
        { id: 't-firma-cajero', type: 'signature', label: 'FIRMA CAJERO RESPONSABLE', text: 'Firma Cajero Responsable', x_mm: padX + 19.0, y_mm: 159.0, w_mm: Number((innerW - 19.0).toFixed(1)), h_mm: 17.0, font_family: 'Arial', font_size: fSmall, bold: true, align: 'center', color: '#0f172a', page: 1, z_index: 4 },
        { id: 't-firma', type: 'signature', label: 'FIRMA SUPERVISOR / AUDITORÍA', text: 'Firma Supervisor / Auditoría de Caja', x_mm: padX, y_mm: 178.0, w_mm: innerW, h_mm: 16.0, font_family: 'Arial', font_size: fSmall, bold: true, align: 'center', color: '#0f172a', page: 1, z_index: 4 }
      );

      return els;
    }

    /* ═══════════════════════════════════════════════════════════════════════════
       CASO GENERAL B2: TICKETS COMERCIALES, CRÉDITO, PAGOS Y CFDI (20 ESTILOS + PROFECO)
       ═══════════════════════════════════════════════════════════════════════════ */
    els.push(
      {
        id: 'f-doc-folio',
        type: 'field',
        label: 'FOLIO DEL TICKET',
        field_key: 'operacion.folio',
        text: 'Folio: {{documento.folio}}',
        x_mm: padX,
        y_mm: 43.0,
        w_mm: Number((innerW * 0.52).toFixed(1)),
        h_mm: 6.5,
        font_family: 'Arial',
        font_size: fBody,
        bold: true,
        align: 'left',
        color: '#000000',
        show_box: true,
        page: 1,
        z_index: 5
      },
      {
        id: 'f-doc-fecha',
        type: 'field',
        label: 'FECHA DEL TICKET',
        field_key: 'operacion.fecha',
        text: '{{documento.fecha}}',
        x_mm: Number((padX + innerW * 0.54).toFixed(1)),
        y_mm: 43.0,
        w_mm: Number((innerW * 0.46).toFixed(1)),
        h_mm: 6.5,
        font_family: 'Arial',
        font_size: fSmall,
        bold: false,
        align: 'right',
        color: '#0f172a',
        show_box: true,
        page: 1,
        z_index: 5
      },
      {
        id: 'f-cli-nombre',
        type: 'field',
        label: 'NOMBRE DEL CLIENTE',
        field_key: 'cliente.nombre',
        text: 'Cliente: {{cliente.nombre}}',
        x_mm: padX,
        y_mm: 51.0,
        w_mm: innerW,
        h_mm: 7.0,
        font_family: 'Arial',
        font_size: fBody,
        bold: true,
        align: 'left',
        color: '#000000',
        show_box: true,
        page: 1,
        z_index: 6
      },
      {
        id: 'f-cli-dir',
        type: 'field',
        label: 'DIRECCIÓN / RFC CLIENTE',
        field_key: 'cliente.domicilio',
        text: 'Dir: {{cliente.direccion}}',
        x_mm: padX,
        y_mm: 59.0,
        w_mm: innerW,
        h_mm: 6.5,
        font_family: 'Arial',
        font_size: fSmall,
        bold: false,
        align: 'left',
        color: '#334155',
        page: 1,
        z_index: 5
      }
    );

    // 5. Tabla Compacta de Productos para Ticket 80mm / 58mm (Movible y Escalable con modo CON IVA / SIN IVA)
    els.push({
      id: 'layer-table-products',
      type: 'table_products',
      label: 'TABLA ARTÍCULOS TICKET (' + paperFormat.toUpperCase() + ')',
      tax_display_mode: ((sNum === 8 || sNum === 14) ? 'DESGLOSADO' : (sNum === 10 ? 'SIN_IVA' : 'CON_IVA')),
      x_mm: padX,
      y_mm: 67.0,
      w_mm: innerW,
      h_mm: 42.0,
      header_bg: pri,
      page: 1,
      z_index: 2
    });

    // 6. Bloque de Totales + Campos Separados (Subtotal SIN IVA, Impuesto Total IVA, Subtotal CON IVA y Total CON IVA)
    els.push(
      {
        id: 'layer-totals-box',
        type: 'totals_block',
        label: 'CUADRO SUBTOTAL SIN/CON IVA E IMPUESTO TOTAL',
        x_mm: padX,
        y_mm: 110.5,
        w_mm: innerW,
        h_mm: 24.5,
        page: 1,
        z_index: 3
      },
      {
        id: 'f-sub-sin-iva',
        type: 'field',
        label: 'SUBTOTAL SIN IVA (POR SEPARADO)',
        field_key: 'importes.subtotal_sin_iva',
        text: '{{importes.subtotal_sin_iva}}',
        x_mm: Number((padX + innerW * 0.52).toFixed(1)),
        y_mm: 111.0,
        w_mm: Number((innerW * 0.46).toFixed(1)),
        h_mm: 5.5,
        font_family: 'Arial',
        font_size: fSmall,
        bold: true,
        align: 'right',
        color: '#0f172a',
        page: 1,
        z_index: 6
      },
      {
        id: 'f-imp-total',
        type: 'field',
        label: 'IMPUESTO TOTAL IVA 16% (POR SEPARADO)',
        field_key: 'importes.impuesto_total',
        text: '{{importes.impuesto_total}}',
        x_mm: Number((padX + innerW * 0.52).toFixed(1)),
        y_mm: 117.0,
        w_mm: Number((innerW * 0.46).toFixed(1)),
        h_mm: 5.5,
        font_family: 'Arial',
        font_size: fSmall,
        bold: true,
        align: 'right',
        color: '#0f172a',
        page: 1,
        z_index: 6
      },
      {
        id: 'f-sub-con-iva',
        type: 'field',
        label: 'SUBTOTAL CON IVA (POR SEPARADO)',
        field_key: 'importes.subtotal_con_iva',
        text: '{{importes.subtotal_con_iva}}',
        x_mm: Number((padX + innerW * 0.52).toFixed(1)),
        y_mm: 123.0,
        w_mm: Number((innerW * 0.46).toFixed(1)),
        h_mm: 5.5,
        font_family: 'Arial',
        font_size: fSmall,
        bold: true,
        align: 'right',
        color: '#0f172a',
        page: 1,
        z_index: 6
      },
      {
        id: 'f-tot-total',
        type: 'field',
        label: 'TOTAL CON IVA DEL TICKET (POR SEPARADO)',
        field_key: 'importes.total_con_iva',
        text: '{{importes.total_con_iva}}',
        x_mm: Number((padX + innerW * 0.48).toFixed(1)),
        y_mm: 128.5,
        w_mm: Number((innerW * 0.50).toFixed(1)),
        h_mm: 6.2,
        font_family: 'Arial',
        font_size: fBody,
        bold: true,
        align: 'right',
        color: pri,
        is_total_highlight: true,
        page: 1,
        z_index: 6
      },
      {
        id: 'f-tot-letra',
        type: 'field',
        label: 'IMPORTE CON LETRA',
        field_key: 'importes.total_letra',
        text: '{{importes.total_letra}}',
        x_mm: padX,
        y_mm: 136.5,
        w_mm: innerW,
        h_mm: 8.0,
        font_family: 'Arial',
        font_size: fSmall,
        bold: true,
        align: 'center',
        color: '#1e293b',
        page: 1,
        z_index: 4
      }
    );

    // 7. Pie de Ticket: Saldo Anterior y Saldo Actual (Notas de Crédito / Crédito) + Serie del Sello, Sello QR y PROFECO
    var isCreditTicket = (sNum === 7 || /credito|comprobante_pago|devolucion|estado_cuenta/i.test(String(docType || '')));
    var isCfdiTicket = (sNum === 8 || /cfdi|factura/i.test(String(docType || '')));

    if (isCreditTicket) {
      els.push(
        { id: 'f-cred-saldo-anterior', type: 'field', label: 'SALDO ANTERIOR (POR SEPARADO)', field_key: 'credito.saldo_anterior', text: 'Saldo Anterior: {{credito.saldo_anterior}}', x_mm: padX, y_mm: 145.5, w_mm: innerW, h_mm: 6.5, font_family: 'Arial', font_size: fBody, bold: true, align: 'left', color: '#0f172a', show_box: true, page: 1, z_index: 5 },
        { id: 'f-cred-abono', type: 'field', label: 'CARGO / ABONO (POR SEPARADO)', field_key: 'credito.importe_abono', text: 'Cargo / Abono: {{credito.importe_abono}}', x_mm: padX, y_mm: 152.5, w_mm: innerW, h_mm: 6.5, font_family: 'Arial', font_size: fSmall, bold: false, align: 'left', color: '#334155', show_box: true, page: 1, z_index: 5 },
        { id: 'f-cred-saldo-actual', type: 'field', label: 'SALDO ACTUAL (POR SEPARADO)', field_key: 'credito.saldo_actual', text: 'Saldo Actual: {{credito.saldo_actual}}', x_mm: padX, y_mm: 159.5, w_mm: innerW, h_mm: 7.0, font_family: 'Arial', font_size: fBody, bold: true, align: 'left', color: pri, is_total_highlight: true, show_box: true, page: 1, z_index: 6 },
        { id: 'f-cfdi-serie-sello', type: 'field', label: 'SERIE DEL SELLO CSD (POR SEPARADO)', field_key: 'cfdi.serie_sello', text: 'Serie Sello: {{cfdi.serie_sello}}', x_mm: padX, y_mm: 167.5, w_mm: innerW, h_mm: 6.0, font_family: 'Courier New', font_size: fSmall, bold: true, align: 'center', color: '#334155', show_box: true, page: 1, z_index: 5 },
        { id: 't-pagare', type: 'field', label: 'PAGARÉ MERCANTIL TICKET', field_key: 'credito.pagare_leyenda', text: '{{credito.pagare_leyenda}}', x_mm: padX, y_mm: 174.5, w_mm: innerW, h_mm: 14.0, font_family: 'Arial', font_size: fSmall, bold: false, align: 'left', color: '#0f172a', show_box: true, page: 1, z_index: 4 },
        { id: 't-qr', type: 'image', label: 'SELLO QR FISCAL (POR SEPARADO)', src: SAMPLE_QR_SVG, field_key: 'cfdi.qr_sat', x_mm: padX, y_mm: 190.0, w_mm: 16.0, h_mm: 16.0, page: 1, z_index: 5 },
        { id: 't-firma', type: 'signature', label: 'FIRMA ACEPTACIÓN CLIENTE', text: 'Firma de Conformidad Cliente', x_mm: padX + 18.0, y_mm: 190.0, w_mm: innerW - 18.0, h_mm: 16.0, font_family: 'Arial', font_size: fSmall, bold: true, align: 'center', color: '#0f172a', page: 1, z_index: 4 }
      );
    } else if (isCfdiTicket) {
      els.push(
        { id: 't-uuid', type: 'field', label: 'FOLIO FISCAL UUID (POR SEPARADO)', field_key: 'cfdi.uuid', text: 'UUID: {{cfdi.uuid}}', x_mm: padX, y_mm: 145.5, w_mm: innerW, h_mm: 8.5, font_family: 'Courier New', font_size: fSmall, bold: true, align: 'center', color: '#065f46', show_box: true, page: 1, z_index: 5 },
        { id: 'f-cfdi-serie-sello', type: 'field', label: 'SERIE DEL SELLO CSD (POR SEPARADO)', field_key: 'cfdi.serie_sello', text: 'Serie del Sello CSD: {{cfdi.serie_sello}}', x_mm: padX, y_mm: 155.0, w_mm: innerW, h_mm: 6.5, font_family: 'Courier New', font_size: fSmall, bold: true, align: 'center', color: '#0f172a', show_box: true, page: 1, z_index: 5 },
        { id: 'f-cfdi-cert-sat', type: 'field', label: 'SERIE DEL SELLO SAT (POR SEPARADO)', field_key: 'cfdi.no_cert_sat', text: 'Serie Sello SAT: {{cfdi.no_cert_sat}}', x_mm: padX, y_mm: 162.5, w_mm: innerW, h_mm: 6.5, font_family: 'Courier New', font_size: fSmall, bold: false, align: 'center', color: '#334155', show_box: true, page: 1, z_index: 5 },
        { id: 'f-cfdi-sello-digital', type: 'field', label: 'SELLO DIGITAL CFDI (POR SEPARADO)', field_key: 'cfdi.sello_cfdi', text: 'Sello CFDI: {{cfdi.sello_cfdi}}', x_mm: padX, y_mm: 170.0, w_mm: innerW, h_mm: 9.5, font_family: 'Courier New', font_size: fSmall, bold: false, align: 'left', color: '#334155', show_box: true, page: 1, z_index: 5 },
        { id: 't-qr', type: 'image', label: 'SELLO QR FISCAL SAT (POR SEPARADO)', src: SAMPLE_QR_SVG, field_key: 'cfdi.qr_sat', x_mm: Number(((pw - 22) / 2).toFixed(1)), y_mm: 181.0, w_mm: 22.0, h_mm: 22.0, page: 1, z_index: 5 }
      );
    } else {
      els.push(
        { id: 'f-cfdi-serie-sello', type: 'field', label: 'SERIE DEL SELLO CSD (POR SEPARADO)', field_key: 'cfdi.serie_sello', text: 'Serie del Sello: {{cfdi.serie_sello}}', x_mm: padX, y_mm: 145.5, w_mm: innerW, h_mm: 6.0, font_family: 'Courier New', font_size: fSmall, bold: true, align: 'center', color: '#0f172a', show_box: true, page: 1, z_index: 5 },
        { id: 'layer-profeco-norma', type: 'field', label: 'CLÁUSULA GARANTÍA PROFECO TICKET (ART. 12 Y 77 LFPC)', field_key: 'profeco.leyenda_consumidor', text: '{{profeco.leyenda_consumidor}}', x_mm: padX, y_mm: 152.5, w_mm: innerW, h_mm: 11.5, font_family: 'Arial', font_size: fSmall, bold: false, align: 'center', color: '#334155', show_box: true, page: 1, z_index: 4 },
        { id: 't-qr', type: 'image', label: 'SELLO QR FISCAL (POR SEPARADO)', src: SAMPLE_QR_SVG, field_key: 'cfdi.qr_sat', x_mm: Number(((pw - 19) / 2).toFixed(1)), y_mm: 165.0, w_mm: 19.0, h_mm: 19.0, page: 1, z_index: 5 },
        { id: 't-firma', type: 'signature', label: 'FIRMA RECIBIDO', text: 'Firma de Recibido / Conformidad', x_mm: padX + 4.0, y_mm: 186.0, w_mm: innerW - 8.0, h_mm: 15.0, font_family: 'Arial', font_size: fSmall, bold: true, align: 'center', color: '#0f172a', page: 1, z_index: 3 }
      );
    }

    return els;
  }

  function createFullEditableLayersForDoc(docTitleText) {
    var pFormat = (_workingVersion && _workingVersion.mode === 'TICKET')
      ? ((Number(_workingVersion.paper_width_mm || 80) < 70) ? '58mm' : '80mm')
      : 'letter';
    var dType = (_activeBackendTpl && _activeBackendTpl.doc_type) || 'cotizacion';
    return generatePresetLayers(dType, pFormat, _activePresetNumber || 1, docTitleText);
  }

  function ensureOverlayFields(ver, docTitle) {
    if (!ver) return [];
    if (!ver.definition_json) ver.definition_json = {};
    var els = ver.definition_json.elements;
    if (!Array.isArray(els) || !els.length || els[0].id === 'el-empresa' || (els.length === 7 && els[0].id === 'f-cli-nombre')) {
      ver.definition_json.elements = createFullEditableLayersForDoc(docTitle || ver.name_snapshot || 'COTIZACIÓN');
    }
    return ver.definition_json.elements;
  }

  function apiCall(path, opts) {
    if (global.AdminAPI && typeof global.AdminAPI.apiFetch === 'function') {
      return global.AdminAPI.apiFetch(path, opts);
    }
    var headers = (opts && opts.headers) ? Object.assign({}, opts.headers) : {};
    var tok = localStorage.getItem('calebsys_token') || sessionStorage.getItem('calebsys_token') || '';
    if (tok && !headers['Authorization']) headers['Authorization'] = 'Bearer ' + tok;
    if (opts && opts.body && typeof opts.body === 'string' && !headers['Content-Type']) {
      headers['Content-Type'] = 'application/json';
    }
    return fetch(path, Object.assign({}, opts || {}, { headers: headers })).then(function (r) {
      if (!r.ok) {
        return r.json().catch(function () { return { detail: 'Error HTTP ' + r.status }; }).then(function (err) {
          var msg = (err && err.detail && (err.detail.message || err.detail)) || ('Error ' + r.status);
          throw new Error(typeof msg === 'string' ? msg : JSON.stringify(msg));
        });
      }
      return r.json();
    });
  }

  function showBannerToast(msg, isError) {
    var b = document.getElementById('ptd-save-toast-banner');
    if (!b) return;
    b.style.display = 'block';
    b.style.background = isError ? 'rgba(239,68,68,0.22)' : 'rgba(16,185,129,0.20)';
    b.style.borderColor = isError ? 'rgba(239,68,68,0.5)' : 'rgba(16,185,129,0.45)';
    b.style.color = isError ? '#fca5a5' : '#34d399';
    b.textContent = (isError ? '⚠️ ' : '✅ ') + msg;
    clearTimeout(b._timer);
    b._timer = setTimeout(function () { b.style.display = 'none'; }, 5500);
  }

  function loadBackendStudioData(preferredTplId) {
    return Promise.all([
      apiCall('/api/print-formats/catalog').catch(function () { return null; }),
      apiCall('/api/print-formats/templates').catch(function () { return null; }),
      apiCall('/api/print-formats/assignments').catch(function () { return null; }),
      apiCall('/api/print-formats/emissions').catch(function () { return null; })
    ]).then(function (results) {
      if (results[0]) _backendCatalog = results[0];
      if (results[1] && Array.isArray(results[1].templates)) _backendTemplates = results[1].templates;
      if (results[2] && Array.isArray(results[2].assignments)) _assignmentsList = results[2].assignments;
      if (results[3] && Array.isArray(results[3].emissions)) _emissionsList = results[3].emissions;

      var cotSeed = _backendTemplates.filter(function (t) { return t.code === 'SEED_COTIZACION_CARTA_MULTIPAGINA' || (t.doc_type === 'cotizacion' && t.mode === 'CARTA'); })[0];
      var targetId = preferredTplId || (_activeBackendTpl && _activeBackendTpl.id) || (cotSeed && cotSeed.id) || (_backendTemplates[0] && _backendTemplates[0].id);

      if (targetId) {
        return apiCall('/api/print-formats/templates/' + encodeURIComponent(targetId)).then(function (detail) {
          _activeBackendTpl = detail;
          _galleryDocType = detail.doc_type || 'cotizacion';
          _workingVersion = JSON.parse(JSON.stringify(detail.working_version || {}));
          _galleryPaperFormat = (_workingVersion.mode === 'TICKET')
            ? ((Number(_workingVersion.paper_width_mm || 80) < 70) ? '58mm' : '80mm')
            : 'letter';
          if (_workingVersion.definition_json && _workingVersion.definition_json.preset_style_num) {
            _activePresetNumber = Number(_workingVersion.definition_json.preset_style_num) || 1;
          }
          var els = ensureOverlayFields(_workingVersion, detail.name);
          if (!_selectedElementId || !els.some(function (e) { return e.id === _selectedElementId; })) {
            _selectedElementId = 'f-cli-nombre';
          }
          _isDirty = false;
          _undoStack = [];
          _redoStack = [];
          renderAllSections();
        });
      } else {
        renderAllSections();
      }
    }).catch(function () {
      renderAllSections();
    });
  }

  function renderAllSections() {
    renderDesignerStudioUI();
    renderAssignmentsRulesSection();
    renderVersionHistoryAndReprintsSection();
  }

  /* ═══════════════════════════════════════════════════════════════════════════
     RENDERIZADOR DE CADA CAPA / OBJETO SOBRE EL LIENZO (IMÁGENES, TABLAS, FORMAS, TEXTOS Y CAMPOS)
     ═══════════════════════════════════════════════════════════════════════════ */
  function renderSingleCanvasElementHtml(el, isSel) {
    if (el.hidden) return '';
    var xPx = mmToPx(el.x_mm || 0);
    var yPx = mmToPx(el.y_mm || 0);
    var wPx = Math.max(12, mmToPx(el.w_mm || 40));
    var hPx = Math.max(8, mmToPx(el.h_mm || 8));
    var zIdx = Number(el.z_index != null ? el.z_index : 3);
    var opacity = el.opacity != null ? Number(el.opacity) : 1.0;
    var rot = Number(el.rotation_deg || 0);
    var transformCss = rot ? ('transform:rotate(' + rot + 'deg);') : '';

    var handlesHtml = (isSel && !el.locked) ? (
      '<span class="df-handle tl" data-resize-dir="tl" data-resize-el="' + esc(el.id) + '" title="Escalar esquina superior izquierda"></span>' +
      '<span class="df-handle tm" data-resize-dir="tm" data-resize-el="' + esc(el.id) + '" title="Estirar arriba"></span>' +
      '<span class="df-handle tr" data-resize-dir="tr" data-resize-el="' + esc(el.id) + '" title="Escalar esquina superior derecha"></span>' +
      '<span class="df-handle mr" data-resize-dir="mr" data-resize-el="' + esc(el.id) + '" title="Estirar derecha"></span>' +
      '<span class="df-handle br" data-resize-dir="br" data-resize-el="' + esc(el.id) + '" title="Escalar esquina inferior derecha"></span>' +
      '<span class="df-handle bm" data-resize-dir="bm" data-resize-el="' + esc(el.id) + '" title="Estirar abajo"></span>' +
      '<span class="df-handle bl" data-resize-dir="bl" data-resize-el="' + esc(el.id) + '" title="Escalar esquina inferior izquierda"></span>' +
      '<span class="df-handle ml" data-resize-dir="ml" data-resize-el="' + esc(el.id) + '" title="Estirar izquierda"></span>'
    ) : '';

    var innerHtml = '';
    var boxClasses = 'df-field-box' + (isSel ? ' selected' : '') + (el.is_total_highlight ? ' total-highlight' : '') + (el.locked ? ' locked-layer' : '');
    var extraBoxStyle = '';
    var isNarrowTicket = Number(el.w_mm || 180) < 90;

    if (el.type === 'image') {
      var imgSrc = el.src || DEFAULT_MAGDALENO_LOGO_SVG;
      innerHtml = '<img src="' + esc(imgSrc) + '" alt="' + esc(el.label || 'Imagen') + '" style="width:100%;height:100%;object-fit:fill;pointer-events:none;display:block;">';
      extraBoxStyle = 'padding:0;';
    } else if (el.type === 'rect') {
      var bgCol = el.background_color || '#b91c1c';
      var bdCol = el.border_color || 'transparent';
      extraBoxStyle = 'padding:0;background:' + esc(bgCol) + ';border:1px solid ' + esc(bdCol) + ';';
      innerHtml = '<div style="width:100%;height:100%;pointer-events:none;"></div>';
    } else if (el.type === 'line') {
      var lnCol = el.color || '#0f172a';
      extraBoxStyle = 'padding:0;background:transparent;';
      innerHtml = '<div style="width:100%;height:2px;background:' + esc(lnCol) + ';pointer-events:none;"></div>';
    } else if (el.type === 'table_products') {
      var hdrBg = el.header_bg || '#a31616';
      var taxMode = String(el.tax_display_mode || 'CON_IVA').toUpperCase();
      extraBoxStyle = 'padding:0;background:#ffffff;align-items:stretch;';
      if (isNarrowTicket) {
        var thPu = taxMode === 'SIN_IVA' ? 'P.U. s/IVA' : 'P.U. c/IVA';
        var thImp = taxMode === 'SIN_IVA' ? 'Total s/IVA' : 'Total c/IVA';
        if (taxMode === 'DESGLOSADO') {
          innerHtml =
            '<table style="width:100%;height:100%;border-collapse:collapse;font-family:Arial,sans-serif;font-size:' + Math.max(6, Math.round(7 * _zoom)) + 'px;pointer-events:none;color:#0f172a;">' +
              '<thead>' +
                '<tr style="background:' + esc(hdrBg) + ';color:#ffffff;font-weight:700;">' +
                  '<th style="padding:2px;border:1px solid #cbd5e1;width:12%;">Cant</th>' +
                  '<th style="padding:2px;border:1px solid #cbd5e1;">Artículo</th>' +
                  '<th style="padding:2px;border:1px solid #cbd5e1;width:20%;">Sin IVA</th>' +
                  '<th style="padding:2px;border:1px solid #cbd5e1;width:16%;">IVA</th>' +
                  '<th style="padding:2px;border:1px solid #cbd5e1;width:21%;">Con IVA</th>' +
                '</tr>' +
              '</thead>' +
              '<tbody>' +
                '<tr><td style="padding:2px;border:1px solid #cbd5e1;text-align:center;">100</td><td style="padding:2px;border:1px solid #cbd5e1;">Tornillo 1 1/2"</td><td style="padding:2px;border:1px solid #cbd5e1;text-align:right;">$64.66</td><td style="padding:2px;border:1px solid #cbd5e1;text-align:right;">$10.34</td><td style="padding:2px;border:1px solid #cbd5e1;text-align:right;font-weight:700;">$75.00</td></tr>' +
                '<tr style="background:#f8fafc;"><td style="padding:2px;border:1px solid #cbd5e1;text-align:center;">10</td><td style="padding:2px;border:1px solid #cbd5e1;">Bisagra 3" niq.</td><td style="padding:2px;border:1px solid #cbd5e1;text-align:right;">$142.24</td><td style="padding:2px;border:1px solid #cbd5e1;text-align:right;">$22.76</td><td style="padding:2px;border:1px solid #cbd5e1;text-align:right;font-weight:700;">$165.00</td></tr>' +
                '<tr><td style="padding:2px;border:1px solid #cbd5e1;text-align:center;">2</td><td style="padding:2px;border:1px solid #cbd5e1;">Cerradura pomo</td><td style="padding:2px;border:1px solid #cbd5e1;text-align:right;">$491.38</td><td style="padding:2px;border:1px solid #cbd5e1;text-align:right;">$78.62</td><td style="padding:2px;border:1px solid #cbd5e1;text-align:right;font-weight:700;">$570.00</td></tr>' +
                '<tr style="background:#f8fafc;"><td style="padding:2px;border:1px solid #cbd5e1;text-align:center;">6</td><td style="padding:2px;border:1px solid #cbd5e1;">Jaladera 128mm</td><td style="padding:2px;border:1px solid #cbd5e1;text-align:right;">$217.24</td><td style="padding:2px;border:1px solid #cbd5e1;text-align:right;">$34.76</td><td style="padding:2px;border:1px solid #cbd5e1;text-align:right;font-weight:700;">$252.00</td></tr>' +
              '</tbody>' +
            '</table>';
        } else {
          var r1p = taxMode === 'SIN_IVA' ? '$0.65' : '$0.75';
          var r1t = taxMode === 'SIN_IVA' ? '$64.66' : '$75.00';
          var r2p = taxMode === 'SIN_IVA' ? '$14.22' : '$16.50';
          var r2t = taxMode === 'SIN_IVA' ? '$142.24' : '$165.00';
          var r3p = taxMode === 'SIN_IVA' ? '$245.69' : '$285.00';
          var r3t = taxMode === 'SIN_IVA' ? '$491.38' : '$570.00';
          var r4p = taxMode === 'SIN_IVA' ? '$36.21' : '$42.00';
          var r4t = taxMode === 'SIN_IVA' ? '$217.24' : '$252.00';
          innerHtml =
            '<table style="width:100%;height:100%;border-collapse:collapse;font-family:Arial,sans-serif;font-size:' + Math.max(6.5, Math.round(7.5 * _zoom)) + 'px;pointer-events:none;color:#0f172a;">' +
              '<thead>' +
                '<tr style="background:' + esc(hdrBg) + ';color:#ffffff;font-weight:700;">' +
                  '<th style="padding:2px;border:1px solid #cbd5e1;width:14%;">Cant</th>' +
                  '<th style="padding:2px 3px;border:1px solid #cbd5e1;">Descripción</th>' +
                  '<th style="padding:2px;border:1px solid #cbd5e1;width:22%;">' + thPu + '</th>' +
                  '<th style="padding:2px;border:1px solid #cbd5e1;width:24%;">' + thImp + '</th>' +
                '</tr>' +
              '</thead>' +
              '<tbody>' +
                '<tr><td style="padding:2px;border:1px solid #cbd5e1;text-align:center;">100</td><td style="padding:2px 3px;border:1px solid #cbd5e1;">Tornillo 1 1/2"</td><td style="padding:2px;border:1px solid #cbd5e1;text-align:right;">' + r1p + '</td><td style="padding:2px;border:1px solid #cbd5e1;text-align:right;font-weight:700;">' + r1t + '</td></tr>' +
                '<tr style="background:#f8fafc;"><td style="padding:2px;border:1px solid #cbd5e1;text-align:center;">10</td><td style="padding:2px 3px;border:1px solid #cbd5e1;">Bisagra 3" niq.</td><td style="padding:2px;border:1px solid #cbd5e1;text-align:right;">' + r2p + '</td><td style="padding:2px;border:1px solid #cbd5e1;text-align:right;font-weight:700;">' + r2t + '</td></tr>' +
                '<tr><td style="padding:2px;border:1px solid #cbd5e1;text-align:center;">2</td><td style="padding:2px 3px;border:1px solid #cbd5e1;">Cerradura pomo</td><td style="padding:2px;border:1px solid #cbd5e1;text-align:right;">' + r3p + '</td><td style="padding:2px;border:1px solid #cbd5e1;text-align:right;font-weight:700;">' + r3t + '</td></tr>' +
                '<tr style="background:#f8fafc;"><td style="padding:2px;border:1px solid #cbd5e1;text-align:center;">6</td><td style="padding:2px 3px;border:1px solid #cbd5e1;">Jaladera 128mm</td><td style="padding:2px;border:1px solid #cbd5e1;text-align:right;">' + r4p + '</td><td style="padding:2px;border:1px solid #cbd5e1;text-align:right;font-weight:700;">' + r4t + '</td></tr>' +
              '</tbody>' +
            '</table>';
        }
      } else {
        if (taxMode === 'DESGLOSADO') {
          innerHtml =
            '<table style="width:100%;height:100%;border-collapse:collapse;font-family:Arial,sans-serif;font-size:' + Math.max(7, Math.round(8.5 * _zoom)) + 'px;pointer-events:none;color:#0f172a;">' +
              '<thead>' +
                '<tr style="background:' + esc(hdrBg) + ';color:#ffffff;font-weight:700;">' +
                  '<th style="padding:3px;border:1px solid #cbd5e1;width:6%;">No.</th>' +
                  '<th style="padding:3px 5px;border:1px solid #cbd5e1;">Descripción del Artículo</th>' +
                  '<th style="padding:3px;border:1px solid #cbd5e1;width:9%;">Cant.</th>' +
                  '<th style="padding:3px;border:1px solid #cbd5e1;width:13%;">P.U. SIN IVA</th>' +
                  '<th style="padding:3px;border:1px solid #cbd5e1;width:14%;">Total Art. SIN IVA</th>' +
                  '<th style="padding:3px;border:1px solid #cbd5e1;width:12%;">IVA (16%)</th>' +
                  '<th style="padding:3px;border:1px solid #cbd5e1;width:15%;">Total Art. CON IVA</th>' +
                '</tr>' +
              '</thead>' +
              '<tbody>' +
                '<tr><td style="padding:3px;border:1px solid #cbd5e1;text-align:center;">1</td><td style="padding:3px 5px;border:1px solid #cbd5e1;">Tornillo para madera 1 1/2"</td><td style="padding:3px;border:1px solid #cbd5e1;text-align:center;">100 Pza</td><td style="padding:3px 4px;border:1px solid #cbd5e1;text-align:right;">$0.65</td><td style="padding:3px 4px;border:1px solid #cbd5e1;text-align:right;">$64.66</td><td style="padding:3px 4px;border:1px solid #cbd5e1;text-align:right;">$10.34</td><td style="padding:3px 4px;border:1px solid #cbd5e1;text-align:right;font-weight:700;">$75.00</td></tr>' +
                '<tr style="background:#f8fafc;"><td style="padding:3px;border:1px solid #cbd5e1;text-align:center;">2</td><td style="padding:3px 5px;border:1px solid #cbd5e1;">Bisagra de libro 3" niquelada</td><td style="padding:3px;border:1px solid #cbd5e1;text-align:center;">10 Pza</td><td style="padding:3px 4px;border:1px solid #cbd5e1;text-align:right;">$14.22</td><td style="padding:3px 4px;border:1px solid #cbd5e1;text-align:right;">$142.24</td><td style="padding:3px 4px;border:1px solid #cbd5e1;text-align:right;">$22.76</td><td style="padding:3px 4px;border:1px solid #cbd5e1;text-align:right;font-weight:700;">$165.00</td></tr>' +
                '<tr><td style="padding:3px;border:1px solid #cbd5e1;text-align:center;">3</td><td style="padding:3px 5px;border:1px solid #cbd5e1;">Cerradura de pomo (recámara)</td><td style="padding:3px;border:1px solid #cbd5e1;text-align:center;">2 Pza</td><td style="padding:3px 4px;border:1px solid #cbd5e1;text-align:right;">$245.69</td><td style="padding:3px 4px;border:1px solid #cbd5e1;text-align:right;">$491.38</td><td style="padding:3px 4px;border:1px solid #cbd5e1;text-align:right;">$78.62</td><td style="padding:3px 4px;border:1px solid #cbd5e1;text-align:right;font-weight:700;">$570.00</td></tr>' +
                '<tr style="background:#f8fafc;"><td style="padding:3px;border:1px solid #cbd5e1;text-align:center;">4</td><td style="padding:3px 5px;border:1px solid #cbd5e1;">Jaladera de aluminio 128 mm</td><td style="padding:3px;border:1px solid #cbd5e1;text-align:center;">6 Pza</td><td style="padding:3px 4px;border:1px solid #cbd5e1;text-align:right;">$36.21</td><td style="padding:3px 4px;border:1px solid #cbd5e1;text-align:right;">$217.24</td><td style="padding:3px 4px;border:1px solid #cbd5e1;text-align:right;">$34.76</td><td style="padding:3px 4px;border:1px solid #cbd5e1;text-align:right;font-weight:700;">$252.00</td></tr>' +
              '</tbody>' +
            '</table>';
        } else {
          var hdrPuCarta = taxMode === 'SIN_IVA' ? 'P. Unitario (SIN IVA)' : 'P. Unitario (CON IVA)';
          var hdrTotCarta = taxMode === 'SIN_IVA' ? 'Total Artículo (SIN IVA)' : 'Total Artículo (CON IVA)';
          var c1p = taxMode === 'SIN_IVA' ? '$0.65' : '$0.75';
          var c1t = taxMode === 'SIN_IVA' ? '$64.66' : '$75.00';
          var c2p = taxMode === 'SIN_IVA' ? '$14.22' : '$16.50';
          var c2t = taxMode === 'SIN_IVA' ? '$142.24' : '$165.00';
          var c3p = taxMode === 'SIN_IVA' ? '$245.69' : '$285.00';
          var c3t = taxMode === 'SIN_IVA' ? '$491.38' : '$570.00';
          var c4p = taxMode === 'SIN_IVA' ? '$36.21' : '$42.00';
          var c4t = taxMode === 'SIN_IVA' ? '$217.24' : '$252.00';
          innerHtml =
            '<table style="width:100%;height:100%;border-collapse:collapse;font-family:Arial,sans-serif;font-size:' + Math.max(7, Math.round(9 * _zoom)) + 'px;pointer-events:none;color:#0f172a;">' +
              '<thead>' +
                '<tr style="background:' + esc(hdrBg) + ';color:#ffffff;font-weight:700;">' +
                  '<th style="padding:3px 4px;border:1px solid #cbd5e1;width:7%;">No.</th>' +
                  '<th style="padding:3px 6px;border:1px solid #cbd5e1;">Descripción</th>' +
                  '<th style="padding:3px 4px;border:1px solid #cbd5e1;width:11%;">Cantidad</th>' +
                  '<th style="padding:3px 4px;border:1px solid #cbd5e1;width:10%;">Unidad</th>' +
                  '<th style="padding:3px 4px;border:1px solid #cbd5e1;width:19%;">' + hdrPuCarta + '</th>' +
                  '<th style="padding:3px 4px;border:1px solid #cbd5e1;width:20%;">' + hdrTotCarta + '</th>' +
                '</tr>' +
              '</thead>' +
              '<tbody>' +
                '<tr><td style="padding:3px;border:1px solid #cbd5e1;text-align:center;">1</td><td style="padding:3px 6px;border:1px solid #cbd5e1;">Tornillo para madera 1 1/2"</td><td style="padding:3px;border:1px solid #cbd5e1;text-align:center;">100</td><td style="padding:3px;border:1px solid #cbd5e1;text-align:center;">Pza</td><td style="padding:3px 5px;border:1px solid #cbd5e1;text-align:right;">' + c1p + '</td><td style="padding:3px 5px;border:1px solid #cbd5e1;text-align:right;font-weight:700;">' + c1t + '</td></tr>' +
                '<tr style="background:#f8fafc;"><td style="padding:3px;border:1px solid #cbd5e1;text-align:center;">2</td><td style="padding:3px 6px;border:1px solid #cbd5e1;">Bisagra de libro 3" niquelada</td><td style="padding:3px;border:1px solid #cbd5e1;text-align:center;">10</td><td style="padding:3px;border:1px solid #cbd5e1;text-align:center;">Pza</td><td style="padding:3px 5px;border:1px solid #cbd5e1;text-align:right;">' + c2p + '</td><td style="padding:3px 5px;border:1px solid #cbd5e1;text-align:right;font-weight:700;">' + c2t + '</td></tr>' +
                '<tr><td style="padding:3px;border:1px solid #cbd5e1;text-align:center;">3</td><td style="padding:3px 6px;border:1px solid #cbd5e1;">Cerradura de pomo (recámara)</td><td style="padding:3px;border:1px solid #cbd5e1;text-align:center;">2</td><td style="padding:3px;border:1px solid #cbd5e1;text-align:center;">Pza</td><td style="padding:3px 5px;border:1px solid #cbd5e1;text-align:right;">' + c3p + '</td><td style="padding:3px 5px;border:1px solid #cbd5e1;text-align:right;font-weight:700;">' + c3t + '</td></tr>' +
                '<tr style="background:#f8fafc;"><td style="padding:3px;border:1px solid #cbd5e1;text-align:center;">4</td><td style="padding:3px 6px;border:1px solid #cbd5e1;">Jaladera de aluminio 128 mm</td><td style="padding:3px;border:1px solid #cbd5e1;text-align:center;">6</td><td style="padding:3px;border:1px solid #cbd5e1;text-align:center;">Pza</td><td style="padding:3px 5px;border:1px solid #cbd5e1;text-align:right;">' + c4p + '</td><td style="padding:3px 5px;border:1px solid #cbd5e1;text-align:right;font-weight:700;">' + c4t + '</td></tr>' +
              '</tbody>' +
            '</table>';
        }
      }
    } else if (el.type === 'table_corte_ciego') {
      var hdrCiego = el.header_bg || '#4f46e5';
      extraBoxStyle = 'padding:0;background:#ffffff;align-items:stretch;';
      var fCiego = isNarrowTicket ? Math.max(6, Math.round(7 * _zoom)) : Math.max(7, Math.round(8.5 * _zoom));
      innerHtml =
        '<table style="width:100%;height:100%;border-collapse:collapse;font-family:Arial,sans-serif;font-size:' + fCiego + 'px;pointer-events:none;color:#0f172a;">' +
          '<thead>' +
            '<tr style="background:' + esc(hdrCiego) + ';color:#ffffff;font-weight:700;">' +
              '<th style="padding:2px 4px;border:1px solid #cbd5e1;text-align:left;">Denominación / Medio</th>' +
              '<th style="padding:2px 4px;border:1px solid #cbd5e1;width:22%;text-align:center;">Cant. Física</th>' +
              '<th style="padding:2px 4px;border:1px solid #cbd5e1;width:28%;text-align:right;">Declarado Cajero</th>' +
            '</tr>' +
          '</thead>' +
          '<tbody>' +
            '<tr><td style="padding:2px 4px;border:1px solid #cbd5e1;">Billetes de $1,000.00 MXN</td><td style="padding:2px;border:1px solid #cbd5e1;text-align:center;">12</td><td style="padding:2px 4px;border:1px solid #cbd5e1;text-align:right;font-weight:700;">$12,000.00</td></tr>' +
            '<tr style="background:#f8fafc;"><td style="padding:2px 4px;border:1px solid #cbd5e1;">Billetes de $500.00 MXN</td><td style="padding:2px;border:1px solid #cbd5e1;text-align:center;">42</td><td style="padding:2px 4px;border:1px solid #cbd5e1;text-align:right;font-weight:700;">$21,000.00</td></tr>' +
            '<tr><td style="padding:2px 4px;border:1px solid #cbd5e1;">Billetes de $200.00 y $100.00</td><td style="padding:2px;border:1px solid #cbd5e1;text-align:center;">48</td><td style="padding:2px 4px;border:1px solid #cbd5e1;text-align:right;font-weight:700;">$7,700.00</td></tr>' +
            '<tr style="background:#f8fafc;"><td style="padding:2px 4px;border:1px solid #cbd5e1;">Billetes $50/$20 y Morralla</td><td style="padding:2px;border:1px solid #cbd5e1;text-align:center;">Lote</td><td style="padding:2px 4px;border:1px solid #cbd5e1;text-align:right;font-weight:700;">$720.00</td></tr>' +
            '<tr><td style="padding:2px 4px;border:1px solid #cbd5e1;">Vouchers Tarjeta Débito / Crédito</td><td style="padding:2px;border:1px solid #cbd5e1;text-align:center;">19</td><td style="padding:2px 4px;border:1px solid #cbd5e1;text-align:right;font-weight:700;">$33,380.00</td></tr>' +
            '<tr style="background:#f8fafc;"><td style="padding:2px 4px;border:1px solid #cbd5e1;">Transferencias SPEI + Fajillas Tómbola</td><td style="padding:2px;border:1px solid #cbd5e1;text-align:center;">8</td><td style="padding:2px 4px;border:1px solid #cbd5e1;text-align:right;font-weight:700;">$36,150.00</td></tr>' +
            '<tr style="background:#ede9fe;"><td colspan="2" style="padding:2px 4px;border:1px solid #c4b5fd;font-weight:800;color:#4c1d95;">TOTAL DECLARADO A CIEGAS (SIN MOSTRAR ESPERADO):</td><td style="padding:2px 4px;border:1px solid #c4b5fd;text-align:right;font-weight:900;color:#4c1d95;">$110,950.00</td></tr>' +
          '</tbody>' +
        '</table>';
    } else if (el.type === 'table_corte_x') {
      var hdrX = el.header_bg || '#0891b2';
      extraBoxStyle = 'padding:0;background:#ffffff;align-items:stretch;';
      var fX = isNarrowTicket ? Math.max(6, Math.round(7 * _zoom)) : Math.max(7, Math.round(8.5 * _zoom));
      innerHtml =
        '<table style="width:100%;height:100%;border-collapse:collapse;font-family:Arial,sans-serif;font-size:' + fX + 'px;pointer-events:none;color:#0f172a;">' +
          '<thead>' +
            '<tr style="background:' + esc(hdrX) + ';color:#ffffff;font-weight:700;">' +
              '<th style="padding:2px 4px;border:1px solid #cbd5e1;text-align:left;">Flujo de Caja y Formas de Pago (Corte X)</th>' +
              '<th style="padding:2px 4px;border:1px solid #cbd5e1;width:18%;text-align:center;">Tipo</th>' +
              '<th style="padding:2px 4px;border:1px solid #cbd5e1;width:28%;text-align:right;">Acumulado Sistema</th>' +
            '</tr>' +
          '</thead>' +
          '<tbody>' +
            '<tr><td style="padding:2px 4px;border:1px solid #cbd5e1;">(+) Fondo Inicial de Apertura</td><td style="padding:2px;border:1px solid #cbd5e1;text-align:center;">GAVETA</td><td style="padding:2px 4px;border:1px solid #cbd5e1;text-align:right;font-weight:700;">$2,500.00</td></tr>' +
            '<tr style="background:#f8fafc;"><td style="padding:2px 4px;border:1px solid #cbd5e1;">(+) Ventas Cobradas en Efectivo</td><td style="padding:2px;border:1px solid #cbd5e1;text-align:center;">ENTRADA</td><td style="padding:2px 4px;border:1px solid #cbd5e1;text-align:right;font-weight:700;">$48,320.00</td></tr>' +
            '<tr><td style="padding:2px 4px;border:1px solid #cbd5e1;">(+) Abonos CxC + Entradas Efectivo</td><td style="padding:2px;border:1px solid #cbd5e1;text-align:center;">ENTRADA</td><td style="padding:2px 4px;border:1px solid #cbd5e1;text-align:right;font-weight:700;">$14,000.00</td></tr>' +
            '<tr style="background:#f8fafc;"><td style="padding:2px 4px;border:1px solid #cbd5e1;">(-) Retiros / Fajillas Tómbola / Gastos</td><td style="padding:2px;border:1px solid #cbd5e1;text-align:center;">SALIDA</td><td style="padding:2px 4px;border:1px solid #cbd5e1;text-align:right;font-weight:700;color:#b45309;">-$23,400.00</td></tr>' +
            '<tr style="background:#ecfeff;"><td style="padding:2px 4px;border:1px solid #a5f3fc;font-weight:800;">(=) EFECTIVO ESPERADO EN GAVETA</td><td style="padding:2px;border:1px solid #a5f3fc;text-align:center;font-weight:800;">CAJA</td><td style="padding:2px 4px;border:1px solid #a5f3fc;text-align:right;font-weight:900;color:#0e7490;">$41,420.00</td></tr>' +
            '<tr><td style="padding:2px 4px;border:1px solid #cbd5e1;">(+) Tarjetas Débito/Crédito + SPEI</td><td style="padding:2px;border:1px solid #cbd5e1;text-align:center;">BANCOS</td><td style="padding:2px 4px;border:1px solid #cbd5e1;text-align:right;font-weight:700;">$51,030.00</td></tr>' +
            '<tr style="background:#f8fafc;"><td style="padding:2px 4px;border:1px solid #cbd5e1;">(+) Ventas a Crédito Otorgado (CxC)</td><td style="padding:2px;border:1px solid #cbd5e1;text-align:center;">CARTERA</td><td style="padding:2px 4px;border:1px solid #cbd5e1;text-align:right;font-weight:700;">$18,500.00</td></tr>' +
          '</tbody>' +
        '</table>';
    } else if (el.type === 'table_corte_z') {
      var hdrZ = el.header_bg || '#065f46';
      extraBoxStyle = 'padding:0;background:#ffffff;align-items:stretch;';
      var fZ = isNarrowTicket ? Math.max(5.8, Math.round(6.8 * _zoom)) : Math.max(7, Math.round(8.5 * _zoom));
      innerHtml =
        '<table style="width:100%;height:100%;border-collapse:collapse;font-family:Arial,sans-serif;font-size:' + fZ + 'px;pointer-events:none;color:#0f172a;">' +
          '<thead>' +
            '<tr style="background:' + esc(hdrZ) + ';color:#ffffff;font-weight:700;">' +
              '<th style="padding:2px 4px;border:1px solid #cbd5e1;text-align:left;">Concepto Conciliación (Corte Z)</th>' +
              '<th style="padding:2px 3px;border:1px solid #cbd5e1;width:22%;text-align:right;">Esperado Sist.</th>' +
              '<th style="padding:2px 3px;border:1px solid #cbd5e1;width:22%;text-align:right;">Declarado Caj.</th>' +
              '<th style="padding:2px 3px;border:1px solid #cbd5e1;width:19%;text-align:right;">Diferencia</th>' +
            '</tr>' +
          '</thead>' +
          '<tbody>' +
            '<tr><td style="padding:2px 4px;border:1px solid #cbd5e1;">Efectivo Físico en Gaveta</td><td style="padding:2px 3px;border:1px solid #cbd5e1;text-align:right;">$41,420.00</td><td style="padding:2px 3px;border:1px solid #cbd5e1;text-align:right;">$41,420.00</td><td style="padding:2px 3px;border:1px solid #cbd5e1;text-align:right;font-weight:700;color:#065f46;">$0.00</td></tr>' +
            '<tr style="background:#f8fafc;"><td style="padding:2px 4px;border:1px solid #cbd5e1;">Fajillas Retiradas a Tómbola</td><td style="padding:2px 3px;border:1px solid #cbd5e1;text-align:right;">$18,500.00</td><td style="padding:2px 3px;border:1px solid #cbd5e1;text-align:right;">$18,500.00</td><td style="padding:2px 3px;border:1px solid #cbd5e1;text-align:right;font-weight:700;color:#065f46;">$0.00</td></tr>' +
            '<tr><td style="padding:2px 4px;border:1px solid #cbd5e1;">Tarjetas Débito y Crédito</td><td style="padding:2px 3px;border:1px solid #cbd5e1;text-align:right;">$33,380.00</td><td style="padding:2px 3px;border:1px solid #cbd5e1;text-align:right;">$33,380.00</td><td style="padding:2px 3px;border:1px solid #cbd5e1;text-align:right;font-weight:700;color:#065f46;">$0.00</td></tr>' +
            '<tr style="background:#f8fafc;"><td style="padding:2px 4px;border:1px solid #cbd5e1;">Transferencias Bancarias SPEI</td><td style="padding:2px 3px;border:1px solid #cbd5e1;text-align:right;">$17,650.00</td><td style="padding:2px 3px;border:1px solid #cbd5e1;text-align:right;">$17,650.00</td><td style="padding:2px 3px;border:1px solid #cbd5e1;text-align:right;font-weight:700;color:#065f46;">$0.00</td></tr>' +
            '<tr><td style="padding:2px 4px;border:1px solid #cbd5e1;">Ventas a Crédito Otorgado (CxC)</td><td style="padding:2px 3px;border:1px solid #cbd5e1;text-align:right;">$18,500.00</td><td style="padding:2px 3px;border:1px solid #cbd5e1;text-align:right;">$18,500.00</td><td style="padding:2px 3px;border:1px solid #cbd5e1;text-align:right;font-weight:700;color:#065f46;">$0.00</td></tr>' +
            '<tr style="background:#ecfdf5;"><td style="padding:2px 4px;border:1px solid #6ee7b7;font-weight:800;color:#065f46;">TOTAL CIERRE DEFINITIVO Z</td><td style="padding:2px 3px;border:1px solid #6ee7b7;text-align:right;font-weight:800;">$110,950.00</td><td style="padding:2px 3px;border:1px solid #6ee7b7;text-align:right;font-weight:800;">$110,950.00</td><td style="padding:2px 3px;border:1px solid #6ee7b7;text-align:right;font-weight:900;color:#065f46;">$0.00</td></tr>' +
          '</tbody>' +
        '</table>';
    } else if (el.type === 'totals_block') {
      extraBoxStyle = 'padding:0;background:#ffffff;align-items:stretch;';
      var fSzTot = isNarrowTicket ? Math.max(6.5, Math.round(7.5 * _zoom)) : Math.max(7.5, Math.round(9 * _zoom));
      innerHtml =
        '<table style="width:100%;height:100%;border-collapse:collapse;font-family:Arial,sans-serif;font-size:' + fSzTot + 'px;pointer-events:none;color:#0f172a;">' +
          '<tr><td style="padding:2px 5px;border:1px solid #cbd5e1;font-weight:700;">Subtotal SIN IVA:</td><td style="padding:2px 5px;border:1px solid #cbd5e1;text-align:right;font-weight:700;">$915.52</td></tr>' +
          '<tr style="background:#f8fafc;"><td style="padding:2px 5px;border:1px solid #cbd5e1;font-weight:700;">Impuesto Total (IVA 16%):</td><td style="padding:2px 5px;border:1px solid #cbd5e1;text-align:right;font-weight:700;">$146.48</td></tr>' +
          '<tr><td style="padding:2px 5px;border:1px solid #cbd5e1;font-weight:700;">Subtotal CON IVA:</td><td style="padding:2px 5px;border:1px solid #cbd5e1;text-align:right;font-weight:700;">$1,062.00</td></tr>' +
          '<tr style="background:#fee2e2;"><td style="padding:3px 5px;border:1px solid #fca5a5;font-weight:800;color:#7f1d1d;">Total CON IVA:</td><td style="padding:3px 5px;border:1px solid #fca5a5;"></td></tr>' +
        '</table>';
    } else if (el.type === 'signature') {
      var sigLines = String(el.text || 'Atentamente\nEquipo de Ventas\nMAGDALENO').split('\n').map(function (ln) { return esc(ln); }).join('<br>');
      extraBoxStyle = 'align-items:flex-end;justify-content:center;text-align:center;';
      innerHtml =
        '<div style="width:100%;border-top:1.5px solid #0f172a;padding-top:3px;pointer-events:none;font-family:' + esc(el.font_family || 'Arial') + ';font-size:' + Math.max(7, Math.round(Number(el.font_size || 9) * _zoom)) + 'px;font-weight:700;line-height:1.2;color:' + esc(el.color || '#0f172a') + ';">' +
          sigLines +
        '</div>';
    } else {
      var rawTxt = el.text != null && el.text !== '' ? String(el.text) : ('{{' + (el.field_key || 'campo') + '}}');
      var htmlLines = rawTxt.split('\n').map(function (ln) { return esc(ln); }).join('<br>');
      var bgFill = el.background_color && el.background_color !== 'transparent' ? ('background:' + esc(el.background_color) + ';') : (el.show_box ? 'background:rgba(255,255,255,0.88);border:1px dashed #64748b;' : '');
      extraBoxStyle =
        bgFill +
        'font-family:' + esc(el.font_family || 'Arial') + ';' +
        'font-size:' + Math.max(7, Math.round(Number(el.font_size || 10.5) * _zoom)) + 'px;' +
        'font-weight:' + (el.bold ? '700' : '500') + ';' +
        'font-style:' + (el.italic ? 'italic' : 'normal') + ';' +
        'text-decoration:' + (el.underline ? 'underline' : 'none') + ';' +
        'justify-content:' + (el.align === 'right' ? 'flex-end' : el.align === 'center' ? 'center' : 'flex-start') + ';' +
        'text-align:' + esc(el.align || 'left') + ';' +
        'color:' + esc(el.color || '#000000') + ';';
      innerHtml = '<div style="pointer-events:none;line-height:1.25;width:100%;' + (el.wrap === false ? 'white-space:nowrap;overflow:hidden;text-overflow:ellipsis;' : 'word-break:break-word;') + '">' + htmlLines + '</div>';
    }

    return '<div class="' + boxClasses + '" data-el-id="' + esc(el.id) + '" ' +
      'style="left:' + xPx + 'px;top:' + yPx + 'px;width:' + wPx + 'px;height:' + hPx + 'px;z-index:' + zIdx + ';opacity:' + opacity + ';' + transformCss + extraBoxStyle + '">' +
      innerHtml +
      handlesHtml +
    '</div>';
  }

  /* ═══════════════════════════════════════════════════════════════════════════
     GALERÍA VISUAL DE LAS 10 PLANTILLAS PRECARGADAS (PESTAÑA «BIBLIOTECA DE FORMATOS»)
     ═══════════════════════════════════════════════════════════════════════════ */
  function renderLibraryOfTenTemplatesHtml() {
    var docButtonsHtml = DOC_TYPES_LIST.map(function (dt) {
      var isAct = (_galleryDocType === dt.id);
      return '<button type="button" class="df-gallery-doc-btn' + (isAct ? ' active' : '') + '" data-click="ptdSetGalleryDocType" data-click-arg="' + esc(dt.id) + '">' +
        '<i class="fa-solid ' + esc(dt.icon) + '"></i> ' + esc(dt.name) +
      '</button>';
    }).join('');

    var docMeta = DOC_TYPES_LIST.filter(function (d) { return d.id === _galleryDocType; })[0] || DOC_TYPES_LIST[0];
    var formatLabel = _galleryPaperFormat === '80mm' ? 'Ticket 80 mm (80 × 210 mm)' : _galleryPaperFormat === '58mm' ? 'Ticket 58 mm (58 × 195 mm)' : 'Tamaño Carta (215.9 × 279.4 mm)';

    var cardsHtml = TEN_PRESET_STYLES.map(function (st) {
      var isSelectedStyle = (_activePresetNumber === st.num);
      var miniWidth = _galleryPaperFormat === '58mm' ? '74px' : _galleryPaperFormat === '80mm' ? '98px' : '116px';
      var miniHeight = '140px';
      var topBarStyle = st.layoutKind === 'top_banner'
        ? ('background:' + st.primary + ';color:#fff;padding:5px;border-radius:3px 3px 0 0;')
        : ('border-bottom:2px solid ' + st.primary + ';padding:4px;color:' + st.primary + ';');
      var leftSidebarHtml = st.layoutKind === 'left_sidebar'
        ? ('<div style="position:absolute;left:0;top:0;bottom:0;width:5px;background:' + st.primary + ';"></div>')
        : '';

      return '<div class="df-gallery-card' + (isSelectedStyle ? ' active' : '') + '" data-click="ptdLoadPresetIntoCanvas" data-click-arg="' + st.num + '" data-click-arg2="' + esc(_galleryDocType) + '" data-click-arg3="' + esc(_galleryPaperFormat) + '">' +
        '<div style="display:flex;align-items:center;justify-content:space-between;gap:6px;">' +
          '<span style="font-size:10px;font-weight:800;padding:2px 8px;border-radius:999px;background:rgba(37,99,235,0.2);color:#60a5fa;border:1px solid rgba(59,130,246,0.35);">PLANTILLA #' + st.num + '</span>' +
          '<span style="font-size:10px;font-weight:700;color:#34d399;"><i class="fa-solid fa-layer-group"></i> 100% Movible</span>' +
        '</div>' +
        '<div class="df-gallery-preview">' +
          '<div style="width:' + miniWidth + ';height:' + miniHeight + ';background:#ffffff;color:#0f172a;border-radius:4px;box-shadow:0 6px 18px rgba(0,0,0,0.55);position:relative;overflow:hidden;display:flex;flex-direction:column;font-family:Arial,sans-serif;font-size:6.5px;padding:' + (st.layoutKind === 'left_sidebar' ? '4px 5px 4px 8px' : '4px 5px') + ';">' +
            leftSidebarHtml +
            '<div style="' + topBarStyle + 'font-weight:900;text-align:' + (st.layoutKind === 'centered_gala' ? 'center' : 'left') + ';font-size:7px;">MAGDALENO</div>' +
            '<div style="text-align:center;font-weight:800;color:' + st.primary + ';margin:3px 0;font-size:6.5px;">' + esc(docMeta.shortTitle.slice(0, 18)) + '</div>' +
            '<div style="display:flex;justify-content:space-between;font-size:5.5px;color:#334155;margin-bottom:3px;"><span>Cliente: {{cliente}}</span><span>Folio: #001</span></div>' +
            '<div style="background:' + st.primary + ';color:#fff;font-weight:700;padding:1.5px 3px;font-size:5.5px;display:flex;justify-content:space-between;"><span>Descripción</span><span>Importe</span></div>' +
            '<div style="border:1px solid #cbd5e1;padding:2px 3px;font-size:5.5px;display:flex;justify-content:space-between;"><span>Tornillo 1 1/2"</span><span>$75.00</span></div>' +
            '<div style="border:1px solid #cbd5e1;border-top:none;padding:2px 3px;font-size:5.5px;display:flex;justify-content:space-between;background:#f8fafc;"><span>Cerradura pomo</span><span>$570.00</span></div>' +
            '<div style="margin-top:auto;display:flex;justify-content:space-between;align-items:flex-end;padding-top:3px;border-top:1px dashed #cbd5e1;">' +
              '<span style="font-size:5px;color:#64748b;">Firma / QR</span>' +
              '<span style="background:' + st.badgeBg + ';color:' + st.primary + ';font-weight:900;padding:1px 4px;border-radius:2px;font-size:6px;">Total: $1,231</span>' +
            '</div>' +
          '</div>' +
        '</div>' +
        '<div>' +
          '<div style="font-size:12.5px;font-weight:800;color:#ffffff;line-height:1.25;">' + esc(st.name) + '</div>' +
          '<div style="font-size:10.5px;color:#94a3b8;margin-top:3px;line-height:1.35;">' + esc(st.subtitle) + '</div>' +
        '</div>' +
        '<button type="button" class="df-btn df-btn-primary" style="width:100%;height:32px;font-size:11.5px;margin-top:auto;" data-click="ptdLoadPresetIntoCanvas" data-click-arg="' + st.num + '" data-click-arg2="' + esc(_galleryDocType) + '" data-click-arg3="' + esc(_galleryPaperFormat) + '">' +
          '<i class="fa-solid fa-wand-magic-sparkles"></i> Usar y Editar en ' + (_galleryPaperFormat === 'letter' ? 'Carta' : _galleryPaperFormat.toUpperCase()) +
        '</button>' +
      '</div>';
    }).join('');

    return '<div class="df-gallery-wrap">' +
      '<div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:12px;margin-bottom:14px;">' +
        '<div>' +
          '<h3 style="margin:0;font-size:16px;font-weight:800;color:#ffffff;">📚 20 Estilos Profesionales (Modelos Grandes Tiendas + PROFECO / SAT + Cortes Ciego, X y Z) para «' + esc(docMeta.name) + '» en ' + esc(formatLabel) + '</h3>' +
          '<p style="margin:3px 0 0;font-size:12px;color:#94a3b8;">Cada uno de los 20 modelos cambia la estructura arquitectónica (no solo colores) y cumple con PROFECO (Art. 12 y 77 LFPC, NOM-030-SCFI) y SAT CFDI 4.0. Todas las capas son 100% libres de mover, escalar y modificar.</p>' +
        '</div>' +
        '<div style="display:flex;align-items:center;gap:6px;background:#111c33;padding:5px;border-radius:9px;border:1px solid #243558;">' +
          '<button type="button" class="df-paper-pill' + (_galleryPaperFormat === 'letter' ? ' active' : '') + '" data-click="ptdSetGalleryPaperFormat" data-click-arg="letter"><i class="fa-regular fa-file-lines"></i> Carta (215.9×279.4 mm)</button>' +
          '<button type="button" class="df-paper-pill' + (_galleryPaperFormat === '80mm' ? ' active' : '') + '" data-click="ptdSetGalleryPaperFormat" data-click-arg="80mm"><i class="fa-solid fa-receipt"></i> Ticket 80 mm</button>' +
          '<button type="button" class="df-paper-pill' + (_galleryPaperFormat === '58mm' ? ' active' : '') + '" data-click="ptdSetGalleryPaperFormat" data-click-arg="58mm"><i class="fa-solid fa-receipt"></i> Ticket 58 mm</button>' +
        '</div>' +
      '</div>' +
      '<div class="df-gallery-doc-bar">' + docButtonsHtml + '</div>' +
      '<div class="df-gallery-grid">' + cardsHtml + '</div>' +
    '</div>';
  }

  /* ═══════════════════════════════════════════════════════════════════════════
     RENDERIZADOR PRINCIPAL DE LA PANTALLA «DISEÑADOR DE FORMATOS»
     ═══════════════════════════════════════════════════════════════════════════ */
  function renderDesignerStudioUI() {
    var host = document.getElementById('prt-designer-studio-root');
    if (!host) return;

    var tpl = _activeBackendTpl;
    var ver = _workingVersion;
    if (!tpl || !ver) {
      host.innerHTML = '<div style="padding:32px;text-align:center;color:#94a3b8;">Cargando Diseñador de formatos...</div>';
      return;
    }

    var els = ensureOverlayFields(ver, tpl.name);
    var selEl = els.filter(function (e) { return e.id === _selectedElementId; })[0] || els[0] || null;
    if (selEl && !_selectedElementId) _selectedElementId = selEl.id;

    var bgAsset = tpl.background_asset || null;
    var bgSettings = ver.background_settings_json || {};
    var isTicketMode = (ver.mode === 'TICKET');
    var pwMm = Number(ver.paper_width_mm || (isTicketMode ? 80.0 : 215.9));
    var phMm = Number(ver.paper_height_mm || (isTicketMode ? 210.0 : 279.4));
    if (phMm < 60) phMm = isTicketMode ? 210.0 : 279.4;

    var currentPaperKey = isTicketMode ? (pwMm < 70 ? '58mm' : '80mm') : 'letter';

    var sheetWpx = mmToPx(pwMm);
    var sheetHpx = mmToPx(phMm);

    var tplSelectorHtml = _backendTemplates.map(function (t) {
      var isSel = (t.id === tpl.id) ? ' selected' : '';
      var modeLabel = t.mode === 'CARTA' ? '📄 Tamaño Carta' : ('🧾 Ticket ' + (t.paper_size || '80 mm'));
      var cleanName = t.name
        .replace(' EN 80 MM', '')
        .replace(' TAMAÑO CARTA', '')
        .replace(' CARTA CON TABLA MULTIPÁGINA', '')
        .replace(' DESDE PDF O IMAGEN', '');
      return '<option value="' + esc(t.id) + '"' + isSel + '>' + esc(cleanName) + ' · ' + esc(modeLabel) + '</option>';
    }).join('');

    // Selector de los 20 Estilos Profesionales Precargados
    var presetDropdownHtml = TEN_PRESET_STYLES.map(function (st) {
      var isSel = (_activePresetNumber === st.num) ? ' selected' : '';
      return '<option value="' + st.num + '"' + isSel + '>Estilo ' + esc(st.name) + '</option>';
    }).join('');

    var presetButtonsHtml = TEN_PRESET_STYLES.map(function (st) {
      var isAct = (_activePresetNumber === st.num) ? ' active' : '';
      return '<button type="button" class="df-preset-num-btn' + isAct + '" data-click="ptdApplyPresetStyleNumber" data-click-arg="' + st.num + '" title="' + esc(st.name + ' — ' + st.subtitle) + '">#' + st.num + '</button>';
    }).join('');

    // Reglas Milimétricas
    var rulerHMarks = '';
    for (var xm = 0; xm <= Math.min(215, pwMm); xm += 2) {
      var xPx = mmToPx(xm);
      var isMajor = (xm % 20 === 0);
      var isMid = (xm % 10 === 0 && !isMajor);
      var tickH = isMajor ? 8 : isMid ? 5 : 3;
      rulerHMarks += '<div style="position:absolute;left:' + xPx + 'px;bottom:0;width:1px;height:' + tickH + 'px;background:#64748b;"></div>';
      if (isMajor) {
        var labelTxt = (xm === 200) ? '200 mm' : String(xm);
        rulerHMarks += '<span style="position:absolute;left:' + (xPx - 6) + 'px;top:2px;font-size:10px;color:#cbd5e1;font-family:monospace;">' + labelTxt + '</span>';
      }
    }

    var rulerVMarks = '';
    for (var ym = 0; ym <= Math.min(275, phMm); ym += 2) {
      var yPx = mmToPx(ym);
      var isMajY = (ym % 20 === 0);
      var isMidY = (ym % 10 === 0 && !isMajY);
      var tickW = isMajY ? 8 : isMidY ? 5 : 3;
      rulerVMarks += '<div style="position:absolute;top:' + (yPx + 24) + 'px;right:0;height:1px;width:' + tickW + 'px;background:#64748b;"></div>';
      if (isMajY) {
        rulerVMarks += '<span style="position:absolute;top:' + (yPx + 18) + 'px;left:3px;font-size:9.5px;color:#cbd5e1;font-family:monospace;">' + ym + '</span>';
      }
    }
    rulerVMarks += '<span style="position:absolute;bottom:6px;left:4px;font-size:9px;color:#94a3b8;font-family:monospace;">mm</span>';

    var sheetBackgroundHtml = '';
    if (bgAsset && bgAsset.id) {
      var bgPage = Math.min(_activePageNum, bgAsset.page_count || 1);
      var bgUrl = '/api/print-formats/assets/' + encodeURIComponent(bgAsset.id) + '/page/' + bgPage;
      var opacity = (bgSettings.print_mode === 'fields_only') ? '0.42' : '1';
      sheetBackgroundHtml = '<img src="' + esc(bgUrl) + '" alt="Fondo PDF/Imagen" style="position:absolute;inset:0;width:100%;height:100%;object-fit:contain;pointer-events:none;z-index:0;opacity:' + opacity + ';">';
    }

    var guidesHtml = '';
    if (selEl && !selEl.hidden) {
      guidesHtml =
        '<div class="df-guide-h" style="top:' + mmToPx(selEl.y_mm) + 'px;"></div>' +
        '<div class="df-guide-h" style="top:' + mmToPx(Number(selEl.y_mm) + Number(selEl.h_mm)) + 'px;"></div>' +
        '<div class="df-guide-v" style="left:' + mmToPx(selEl.x_mm) + 'px;"></div>';
    }

    var sortedForCanvas = els.slice().sort(function (a, b) {
      return Number(a.z_index || 1) - Number(b.z_index || 1);
    });
    var boxesHtml = sortedForCanvas.map(function (el) {
      return renderSingleCanvasElementHtml(el, el.id === _selectedElementId);
    }).join('');

    var layersTopToBottom = els.slice().sort(function (a, b) {
      return Number(b.z_index || 1) - Number(a.z_index || 1);
    });
    var layersListHtml = layersTopToBottom.map(function (ly) {
      var isAct = (ly.id === _selectedElementId);
      var typeIco = ly.type === 'image' ? 'fa-image' : (String(ly.type).indexOf('table') === 0 ? 'fa-table' : ly.type === 'rect' ? 'fa-square' : ly.type === 'field' ? 'fa-database' : 'fa-font');
      return '<div class="df-layer-row' + (isAct ? ' active' : '') + '" data-click="ptdSelectLayerById" data-click-arg="' + esc(ly.id) + '">' +
        '<div class="df-layer-left">' +
          '<i class="fa-solid ' + typeIco + '" style="color:#60a5fa;width:14px;text-align:center;"></i>' +
          '<span class="df-layer-name">' + esc(ly.label || ly.text || ly.type) + '</span>' +
          '<small style="color:#64748b;font-size:9.5px;">(z:' + Number(ly.z_index || 1) + ')</small>' +
        '</div>' +
        '<div class="df-layer-actions">' +
          '<button type="button" class="df-layer-icobtn" title="Subir capa adelante" data-click="ptdMoveLayerOrder" data-click-arg="' + esc(ly.id) + '" data-click-arg2="up">▲</button>' +
          '<button type="button" class="df-layer-icobtn" title="Bajar capa atrás" data-click="ptdMoveLayerOrder" data-click-arg="' + esc(ly.id) + '" data-click-arg2="down">▼</button>' +
          '<button type="button" class="df-layer-icobtn" title="Mostrar / Ocultar capa" data-click="ptdToggleLayerHidden" data-click-arg="' + esc(ly.id) + '">' + (ly.hidden ? '🚫' : '👁') + '</button>' +
          '<button type="button" class="df-layer-icobtn" title="Bloquear / Desbloquear capa" data-click="ptdToggleLayerLock" data-click-arg="' + esc(ly.id) + '">' + (ly.locked ? '🔒' : '🔓') + '</button>' +
        '</div>' +
      '</div>';
    }).join('');

    var accordionsHtml = DATA_SOURCES_TREE.map(function (src) {
      var isOpen = (_openAccGroup === src.id);
      var subItems = isOpen ? (
        '<div class="df-acc-body">' +
          src.fields.map(function (f) {
            return '<button type="button" class="df-sub-field" data-click="ptdInsertFieldFromSource" data-click-arg="' + esc(f.key) + '" data-click-arg2="' + esc(f.name) + '" data-click-arg3="' + esc(f.token) + '">' +
              '<span>' + esc(f.name) + '</span><code>' + esc(f.token) + '</code>' +
            '</button>';
          }).join('') +
        '</div>'
      ) : '';
      return '<div class="df-acc-item">' +
        '<button type="button" class="df-acc-head" data-click="ptdToggleSourceAcc" data-click-arg="' + esc(src.id) + '">' +
          '<span class="df-acc-head-left"><i class="fa-solid ' + esc(src.icon) + '"></i> ' + esc(src.label) + '</span>' +
          '<i class="fa-solid fa-chevron-' + (isOpen ? 'up' : 'down') + '" style="font-size:10px;color:#94a3b8;"></i>' +
        '</button>' +
        subItems +
      '</div>';
    }).join('');

    var activePresetMeta = TEN_PRESET_STYLES[_activePresetNumber - 1] || TEN_PRESET_STYLES[0];
    var loadedFileName = bgAsset ? bgAsset.original_filename : ('Estilo #' + _activePresetNumber + ' · ' + activePresetMeta.name.slice(5));
    var loadedFileSize = bgAsset ? ((bgAsset.size_bytes / (1024 * 1024)).toFixed(1) + ' MB') : (els.length + ' capas libres (' + (currentPaperKey === 'letter' ? 'Carta' : currentPaperKey) + ')');

    var bindingOptsHtml = BINDING_OPTIONS.map(function (bo) {
      var isSel = (selEl && (selEl.field_key || '') === bo.key) ? ' selected' : '';
      return '<option value="' + esc(bo.key) + '"' + isSel + '>' + esc(bo.label) + '</option>';
    }).join('');

    var printBgOn = (bgSettings.print_mode !== 'fields_only');
    var curOpacityPct = selEl && selEl.opacity != null ? Math.round(Number(selEl.opacity) * 100) : 100;

    host.innerHTML =
      '<div class="df-shell">' +

        /* 1. BREADCRUMB SUPERIOR */
        '<div class="df-breadcrumb">' +
          '<i class="fa-solid fa-gear"></i> <span>Configuración</span> <i class="fa-solid fa-chevron-right" style="font-size:9px;"></i> ' +
          '<span>Impresoras</span> <i class="fa-solid fa-chevron-right" style="font-size:9px;"></i> ' +
          '<b>Diseñador de formatos</b>' +
        '</div>' +

        /* 2. TÍTULO PRINCIPAL */
        '<div class="df-title-bar">' +
          '<div class="df-title-main">' +
            '<i class="fa-solid fa-print"></i> <span>Diseñador de formatos</span>' +
          '</div>' +
          '<div style="display:flex;gap:8px;">' +
            '<button type="button" class="df-btn" style="height:30px;font-size:11.5px;border-color:#3b82f6;color:#93c5fd;" data-click="ptdSwitchInternalTab" data-click-arg="biblioteca">' +
              '<i class="fa-solid fa-swatchbook"></i> Ver Galería (20 Estilos Profesionales PROFECO / SAT + Cortes)' +
            '</button>' +
            '<button type="button" class="df-btn" style="height:30px;font-size:11.5px;" data-click="ptdResetMagdalenoLayers" title="Restaurar todas las capas de la plantilla actual">' +
              '<i class="fa-solid fa-rotate-left"></i> Restaurar Capas' +
            '</button>' +
            '<button type="button" class="df-btn" style="height:30px;font-size:11.5px;" data-click="ptdToggleFullscreen">' +
              '<i class="fa-solid fa-expand"></i> Pantalla Completa' +
            '</button>' +
          '</div>' +
        '</div>' +

        /* 3. PESTAÑAS ESTILO FOLDER */
        '<div class="df-nav-tabs">' +
          '<button type="button" class="df-nav-tab' + (_activeInternalTab === 'biblioteca' ? ' active' : '') + '" data-click="ptdSwitchInternalTab" data-click-arg="biblioteca"><i class="fa-solid fa-swatchbook" style="margin-right:5px;"></i> Biblioteca de formatos (20 Estilos)</button>' +
          '<button type="button" class="df-nav-tab' + (_activeInternalTab === 'editor' ? ' active' : '') + '" data-click="ptdSwitchInternalTab" data-click-arg="editor"><i class="fa-solid fa-wand-magic-sparkles" style="margin-right:5px;"></i> Editor visual</button>' +
          '<button type="button" class="df-nav-tab' + (_activeInternalTab === 'asignacion' ? ' active' : '') + '" data-click="ptdSwitchInternalTab" data-click-arg="asignacion">Asignación y reglas</button>' +
          '<button type="button" class="df-nav-tab' + (_activeInternalTab === 'versiones' ? ' active' : '') + '" data-click="ptdSwitchInternalTab" data-click-arg="versiones">Versiones</button>' +
        '</div>' +

        /* 4. SUB-BARRA DE HERRAMIENTAS */
        '<div class="df-subtoolbar">' +
          '<div class="df-subtoolbar-left">' +
            '<div class="df-doc-select-wrap">' +
              '<i class="fa-regular fa-file-lines"></i>' +
              '<select class="df-doc-select" data-change="ptdSwitchBackendTemplate">' +
                tplSelectorHtml +
              '</select>' +
            '</div>' +
            '<div class="df-doc-select-wrap" style="border-color:#3b82f6;">' +
              '<i class="fa-solid fa-palette" style="color:#34d399;"></i>' +
              '<select class="df-doc-select" style="min-width:255px;" data-change="ptdSwitchPresetSelect">' +
                presetDropdownHtml +
              '</select>' +
            '</div>' +
            '<span class="df-draft-pill' + (ver.status === 'PUBLISHED' && !_isDirty ? ' published' : '') + '" id="ptd-dirty-indicator">' +
              '<i class="fa-solid fa-pen" style="font-size:10px;"></i> ' +
              (_isDirty ? 'Borrador (Editando)' : 'Borrador') +
            '</span>' +
            '<button type="button" class="df-btn" style="height:32px;padding:0 10px;font-size:11.5px;" data-click="ptdCreateNewTemplatePrompt">+ Nueva</button>' +
          '</div>' +
          '<div class="df-subtoolbar-right">' +
            '<button type="button" class="df-btn" data-click="ptdDownloadBackendPdf" data-click-arg="' + (printBgOn ? 'true' : 'false') + '">' +
              '<i class="fa-regular fa-eye"></i> Vista previa' +
            '</button>' +
            '<button type="button" class="df-btn" data-click="ptdSaveBackendDraft">' +
              '<i class="fa-regular fa-floppy-disk"></i> Guardar' +
            '</button>' +
            '<button type="button" class="df-btn df-btn-primary" data-click="ptdPublishActiveTemplate">' +
              '<i class="fa-solid fa-arrow-up-from-bracket"></i> Publicar' +
            '</button>' +
          '</div>' +
        '</div>' +

        /* BARRA RÁPIDA DE LOS 20 ESTILOS PRECARGADOS + SELECTOR DE MEDIDA (CARTA / TICKET 80 MM / TICKET 58 MM) */
        '<div class="df-presets-strip">' +
          '<div style="display:flex;align-items:center;gap:5px;flex-wrap:wrap;">' +
            '<span style="font-weight:800;color:#93c5fd;"><i class="fa-solid fa-layer-group"></i> 20 Estilos Profesionales (PROFECO / SAT / Cortes):</span>' +
            presetButtonsHtml +
          '</div>' +
          '<div style="display:flex;align-items:center;gap:6px;">' +
            '<span style="color:#94a3b8;font-weight:700;">Tamaño de hoja:</span>' +
            '<button type="button" class="df-paper-pill' + (currentPaperKey === 'letter' ? ' active' : '') + '" data-click="ptdQuickSwitchThermalFormat" data-click-arg="letter"><i class="fa-regular fa-file-lines"></i> Carta</button>' +
            '<button type="button" class="df-paper-pill' + (currentPaperKey === '80mm' ? ' active' : '') + '" data-click="ptdQuickSwitchThermalFormat" data-click-arg="80mm"><i class="fa-solid fa-receipt"></i> Ticket 80 mm</button>' +
            '<button type="button" class="df-paper-pill' + (currentPaperKey === '58mm' ? ' active' : '') + '" data-click="ptdQuickSwitchThermalFormat" data-click-arg="58mm"><i class="fa-solid fa-receipt"></i> Ticket 58 mm</button>' +
          '</div>' +
        '</div>' +

        (_activeInternalTab === 'biblioteca' ? renderLibraryOfTenTemplatesHtml() : (

        /* 5. ÁREA DE TRABAJO EN 3 COLUMNAS */
        '<div class="df-main-grid">' +

          /* ── COLUMNA IZQUIERDA (Campos | Elementos | Capas + Subida de Imágenes Libres / PDF) ── */
          '<div class="df-left-col">' +
            '<div class="df-seg-switch">' +
              '<button type="button" class="df-seg-btn' + (_leftSegment === 'campos' ? ' active' : '') + '" data-click="ptdSetLeftSegment" data-click-arg="campos">Campos</button>' +
              '<button type="button" class="df-seg-btn' + (_leftSegment === 'elementos' ? ' active' : '') + '" data-click="ptdSetLeftSegment" data-click-arg="elementos">Elementos</button>' +
              '<button type="button" class="df-seg-btn' + (_leftSegment === 'capas' ? ' active' : '') + '" data-click="ptdSetLeftSegment" data-click-arg="capas">Capas (' + els.length + ')</button>' +
            '</div>' +

            /* Zona Drag & Drop: Subir Imagen Libre (como Capa) o PDF de Fondo */
            '<div class="df-upload-zone" id="df-upload-dropzone" data-click="ptdTriggerFreeImageUpload">' +
              '<i class="fa-solid fa-cloud-arrow-up"></i>' +
              '<b>Subir PDF o imagen</b>' +
              '<span>Sube cualquier imagen para moverla, escalarla y acomodarla en capas</span>' +
              '<small>PNG, JPG, SVG o PDF (máx. 10 MB)</small>' +
              '<input type="file" id="ptd-free-img-inp" accept="image/*,.pdf" style="display:none;" data-change="ptdHandleUniversalUpload">' +
            '</div>' +

            '<div style="display:grid;grid-template-columns:1fr 1fr;gap:6px;">' +
              '<button type="button" class="df-btn" style="height:30px;font-size:11px;padding:0 8px;" data-click="ptdTriggerFreeImageUpload" title="Sube una imagen que puedes mover, hacer más chica/grande y cambiar de capa">' +
                '<i class="fa-regular fa-image" style="color:#60a5fa;"></i> + Imagen Libre' +
              '</button>' +
              '<button type="button" class="df-btn" style="height:30px;font-size:11px;padding:0 8px;" data-click="ptdTriggerPageBgUpload" title="Sube un PDF o imagen como hoja de fondo">' +
                '<i class="fa-regular fa-file-pdf" style="color:#f87171;"></i> + Fondo Hoja' +
              '</button>' +
            '</div>' +

            /* Tarjeta del archivo / plantilla cargada */
            '<div class="df-file-pill">' +
              '<div class="df-file-pill-left">' +
                '<i class="fa-solid fa-swatchbook" style="color:#60a5fa;"></i>' +
                '<div style="min-width:0;">' +
                  '<span class="df-file-pill-name">' + esc(loadedFileName) + '</span>' +
                  '<span class="df-file-pill-size">' + esc(loadedFileSize) + '</span>' +
                '</div>' +
              '</div>' +
              (bgAsset ? '<button type="button" class="df-file-pill-del" data-click="ptdRemoveBgAsset" title="Quitar archivo de fondo"><i class="fa-solid fa-xmark"></i></button>' : '') +
            '</div>' +

            (_leftSegment === 'campos' ? (
              '<div class="df-sec-label">Fuentes de datos</div>' +
              '<div class="df-acc-list">' + accordionsHtml + '</div>' +
              '<div class="df-sec-label" style="margin-top:4px;">Campos frecuentes <span style="font-weight:400;color:#64748b;font-size:10.5px;">(clic para insertar)</span></div>' +
              '<div class="df-freq-list">' +
                '<div class="df-freq-card" draggable="true" data-click="ptdInsertFieldFromSource" data-click-arg="cliente.nombre" data-click-arg2="Nombre del cliente" data-click-arg3="{{cliente.nombre}}">' +
                  '<span class="df-freq-left"><span class="df-freq-ico">Aa</span> Nombre del cliente</span><span class="df-freq-grip">⋮⋮</span>' +
                '</div>' +
                '<div class="df-freq-card" draggable="true" data-click="ptdInsertFieldFromSource" data-click-arg="operacion.folio" data-click-arg2="Folio" data-click-arg3="{{documento.folio}}">' +
                  '<span class="df-freq-left"><span class="df-freq-ico">#</span> Folio</span><span class="df-freq-grip">⋮⋮</span>' +
                '</div>' +
                '<div class="df-freq-card" draggable="true" style="border-color:#4f46e5;" data-click="ptdAddElement" data-click-arg="table_corte_ciego">' +
                  '<span class="df-freq-left"><span class="df-freq-ico" style="background:#3730a3;color:#c7d2fe;">🙈</span> Tabla Corte Ciego (Tómbola)</span><span class="df-freq-grip">+</span>' +
                '</div>' +
                '<div class="df-freq-card" draggable="true" style="border-color:#0891b2;" data-click="ptdAddElement" data-click-arg="table_corte_x">' +
                  '<span class="df-freq-left"><span class="df-freq-ico" style="background:#155e75;color:#a5f3fc;">📊</span> Tabla Corte X (Flujo Gaveta)</span><span class="df-freq-grip">+</span>' +
                '</div>' +
                '<div class="df-freq-card" draggable="true" style="border-color:#059669;" data-click="ptdAddElement" data-click-arg="table_corte_z">' +
                  '<span class="df-freq-left"><span class="df-freq-ico" style="background:#065f46;color:#6ee7b7;">🔒</span> Tabla Corte Z (Conciliación)</span><span class="df-freq-grip">+</span>' +
                '</div>' +
                '<div class="df-freq-card" draggable="true" style="border-color:#e11d48;" data-click="ptdInsertFieldFromSource" data-click-arg="profeco.leyenda_garantias" data-click-arg2="CLÁUSULA GARANTÍA PROFECO" data-click-arg3="{{profeco.leyenda_garantias}}">' +
                  '<span class="df-freq-left"><span class="df-freq-ico" style="background:#881337;color:#fecdd3;">⚖</span> Cláusula Oficial PROFECO</span><span class="df-freq-grip">+</span>' +
                '</div>' +
                '<div class="df-freq-card" draggable="true" style="border-color:#0284c7;" data-click="ptdInsertFieldFromSource" data-click-arg="importes.subtotal_sin_iva" data-click-arg2="SUBTOTAL SIN IVA" data-click-arg3="Subtotal SIN IVA: {{importes.subtotal_sin_iva}}">' +
                  '<span class="df-freq-left"><span class="df-freq-ico" style="background:#075985;color:#bae6fd;">S/I</span> Subtotal SIN IVA (Por separado)</span><span class="df-freq-grip">+</span>' +
                '</div>' +
                '<div class="df-freq-card" draggable="true" style="border-color:#0284c7;" data-click="ptdInsertFieldFromSource" data-click-arg="importes.impuesto_total" data-click-arg2="IMPUESTO TOTAL IVA 16%" data-click-arg3="Impuesto Total (IVA 16%): {{importes.impuesto_total}}">' +
                  '<span class="df-freq-left"><span class="df-freq-ico" style="background:#075985;color:#bae6fd;">%</span> Impuesto Total IVA (Por separado)</span><span class="df-freq-grip">+</span>' +
                '</div>' +
                '<div class="df-freq-card" draggable="true" style="border-color:#0284c7;" data-click="ptdInsertFieldFromSource" data-click-arg="importes.subtotal_con_iva" data-click-arg2="SUBTOTAL CON IVA" data-click-arg3="Subtotal CON IVA: {{importes.subtotal_con_iva}}">' +
                  '<span class="df-freq-left"><span class="df-freq-ico" style="background:#075985;color:#bae6fd;">C/I</span> Subtotal CON IVA (Por separado)</span><span class="df-freq-grip">+</span>' +
                '</div>' +
                '<div class="df-freq-card" draggable="true" style="border-color:#d97706;" data-click="ptdCycleTableTaxMode">' +
                  '<span class="df-freq-left"><span class="df-freq-ico" style="background:#78350f;color:#fde68a;">🧾</span> Artículos Tabla: CON IVA / SIN IVA</span><span class="df-freq-grip">⇄</span>' +
                '</div>' +
                '<div class="df-freq-card" draggable="true" style="border-color:#059669;" data-click="ptdInsertQrSealLayer">' +
                  '<span class="df-freq-left"><span class="df-freq-ico" style="background:#065f46;color:#6ee7b7;"><i class="fa-solid fa-qrcode" style="font-size:11px;"></i></span> Sello QR (Por separado)</span><span class="df-freq-grip">+</span>' +
                '</div>' +
                '<div class="df-freq-card" draggable="true" style="border-color:#059669;" data-click="ptdInsertFieldFromSource" data-click-arg="cfdi.serie_sello" data-click-arg2="SERIE DEL SELLO CSD" data-click-arg3="Serie Sello CSD: {{cfdi.serie_sello}}">' +
                  '<span class="df-freq-left"><span class="df-freq-ico" style="background:#065f46;color:#6ee7b7;"><i class="fa-solid fa-key" style="font-size:10px;"></i></span> Serie del Sello (Por separado)</span><span class="df-freq-grip">+</span>' +
                '</div>' +
                '<div class="df-freq-card" draggable="true" style="border-color:#4f46e5;" data-click="ptdInsertFieldFromSource" data-click-arg="credito.saldo_anterior" data-click-arg2="SALDO ANTERIOR" data-click-arg3="Saldo Anterior: {{credito.saldo_anterior}}">' +
                  '<span class="df-freq-left"><span class="df-freq-ico" style="background:#3730a3;color:#c7d2fe;"><i class="fa-solid fa-clock-rotate-left" style="font-size:10px;"></i></span> Saldo Anterior (Nota Crédito)</span><span class="df-freq-grip">+</span>' +
                '</div>' +
                '<div class="df-freq-card" draggable="true" style="border-color:#4f46e5;" data-click="ptdInsertFieldFromSource" data-click-arg="credito.saldo_actual" data-click-arg2="SALDO ACTUAL" data-click-arg3="Saldo Actual: {{credito.saldo_actual}}">' +
                  '<span class="df-freq-left"><span class="df-freq-ico" style="background:#3730a3;color:#c7d2fe;"><i class="fa-solid fa-scale-balanced" style="font-size:10px;"></i></span> Saldo Actual (Nota Crédito)</span><span class="df-freq-grip">+</span>' +
                '</div>' +
              '</div>'
            ) : _leftSegment === 'elementos' ? (
              '<div class="df-sec-label">Herramientas tipo Corel / Photoshop</div>' +
              '<div class="df-freq-list">' +
                '<div class="df-freq-card" data-click="ptdTriggerFreeImageUpload"><span class="df-freq-left"><span class="df-freq-ico">🖼</span> Subir Imagen / Logo Libre</span><span class="df-freq-grip">+</span></div>' +
                '<div class="df-freq-card" style="border-color:#4f46e5;" data-click="ptdAddElement" data-click-arg="table_corte_ciego"><span class="df-freq-left"><span class="df-freq-ico">🙈</span> Tabla Corte Ciego (Tómbola)</span><span class="df-freq-grip">+</span></div>' +
                '<div class="df-freq-card" style="border-color:#0891b2;" data-click="ptdAddElement" data-click-arg="table_corte_x"><span class="df-freq-left"><span class="df-freq-ico">📊</span> Tabla Corte X (Flujo Gaveta)</span><span class="df-freq-grip">+</span></div>' +
                '<div class="df-freq-card" style="border-color:#059669;" data-click="ptdAddElement" data-click-arg="table_corte_z"><span class="df-freq-left"><span class="df-freq-ico">🔒</span> Tabla Corte Z (Conciliación)</span><span class="df-freq-grip">+</span></div>' +
                '<div class="df-freq-card" style="border-color:#e11d48;" data-click="ptdInsertFieldFromSource" data-click-arg="profeco.leyenda_garantias" data-click-arg2="CLÁUSULA GARANTÍA PROFECO" data-click-arg3="{{profeco.leyenda_garantias}}"><span class="df-freq-left"><span class="df-freq-ico">⚖</span> Cláusula Oficial PROFECO</span><span class="df-freq-grip">+</span></div>' +
                '<div class="df-freq-card" style="border-color:#d97706;" data-click="ptdCycleTableTaxMode"><span class="df-freq-left"><span class="df-freq-ico">🧾</span> Cambiar Artículos: CON IVA / SIN IVA</span><span class="df-freq-grip">⇄</span></div>' +
                '<div class="df-freq-card" style="border-color:#0284c7;" data-click="ptdInsertFieldFromSource" data-click-arg="importes.subtotal_sin_iva" data-click-arg2="SUBTOTAL SIN IVA" data-click-arg3="Subtotal SIN IVA: {{importes.subtotal_sin_iva}}"><span class="df-freq-left"><span class="df-freq-ico">S/I</span> Campo Subtotal SIN IVA</span><span class="df-freq-grip">+</span></div>' +
                '<div class="df-freq-card" style="border-color:#0284c7;" data-click="ptdInsertFieldFromSource" data-click-arg="importes.impuesto_total" data-click-arg2="IMPUESTO TOTAL IVA 16%" data-click-arg3="Impuesto Total (IVA 16%): {{importes.impuesto_total}}"><span class="df-freq-left"><span class="df-freq-ico">%</span> Campo Impuesto Total (IVA)</span><span class="df-freq-grip">+</span></div>' +
                '<div class="df-freq-card" style="border-color:#0284c7;" data-click="ptdInsertFieldFromSource" data-click-arg="importes.subtotal_con_iva" data-click-arg2="SUBTOTAL CON IVA" data-click-arg3="Subtotal CON IVA: {{importes.subtotal_con_iva}}"><span class="df-freq-left"><span class="df-freq-ico">C/I</span> Campo Subtotal CON IVA</span><span class="df-freq-grip">+</span></div>' +
                '<div class="df-freq-card" style="border-color:#059669;" data-click="ptdInsertQrSealLayer"><span class="df-freq-left"><span class="df-freq-ico"><i class="fa-solid fa-qrcode"></i></span> Sello QR Independiente</span><span class="df-freq-grip">+</span></div>' +
                '<div class="df-freq-card" style="border-color:#059669;" data-click="ptdInsertFieldFromSource" data-click-arg="cfdi.serie_sello" data-click-arg2="SERIE DEL SELLO CSD" data-click-arg3="Serie Sello CSD: {{cfdi.serie_sello}}"><span class="df-freq-left"><span class="df-freq-ico"><i class="fa-solid fa-key"></i></span> Serie del Sello Independiente</span><span class="df-freq-grip">+</span></div>' +
                '<div class="df-freq-card" style="border-color:#4f46e5;" data-click="ptdInsertFieldFromSource" data-click-arg="credito.saldo_anterior" data-click-arg2="SALDO ANTERIOR" data-click-arg3="Saldo Anterior: {{credito.saldo_anterior}}"><span class="df-freq-left"><span class="df-freq-ico">⏪</span> Campo Saldo Anterior</span><span class="df-freq-grip">+</span></div>' +
                '<div class="df-freq-card" style="border-color:#4f46e5;" data-click="ptdInsertFieldFromSource" data-click-arg="credito.saldo_actual" data-click-arg2="SALDO ACTUAL" data-click-arg3="Saldo Actual: {{credito.saldo_actual}}"><span class="df-freq-left"><span class="df-freq-ico">💰</span> Campo Saldo Actual</span><span class="df-freq-grip">+</span></div>' +
                '<div class="df-freq-card" data-click="ptdAddElement" data-click-arg="text"><span class="df-freq-left"><span class="df-freq-ico">Aa</span> Texto Libre Encimable</span><span class="df-freq-grip">+</span></div>' +
                '<div class="df-freq-card" data-click="ptdAddElement" data-click-arg="combined"><span class="df-freq-left"><span class="df-freq-ico">{}</span> Texto Combinado {{...}}</span><span class="df-freq-grip">+</span></div>' +
                '<div class="df-freq-card" data-click="ptdAddElement" data-click-arg="rect"><span class="df-freq-left"><span class="df-freq-ico">▭</span> Rectángulo / Cinta de Color</span><span class="df-freq-grip">+</span></div>' +
                '<div class="df-freq-card" data-click="ptdAddElement" data-click-arg="line"><span class="df-freq-left"><span class="df-freq-ico">─</span> Línea Divisoria</span><span class="df-freq-grip">+</span></div>' +
                '<div class="df-freq-card" data-click="ptdAddElement" data-click-arg="table_products"><span class="df-freq-left"><span class="df-freq-ico">📋</span> Tabla de Productos</span><span class="df-freq-grip">+</span></div>' +
                '<div class="df-freq-card" data-click="ptdAddElement" data-click-arg="signature"><span class="df-freq-left"><span class="df-freq-ico">✒</span> Línea de Firma</span><span class="df-freq-grip">+</span></div>' +
              '</div>'
            ) : (
              '<div class="df-sec-label">Pila de Capas (Arriba = Frente · Abajo = Fondo)</div>' +
              '<div class="df-layers-list">' + layersListHtml + '</div>'
            )) +

            /* Widget Inferior: Plantillas de impresión (Miniatura Ticket Térmico + Selector Formato Térmico / Carta) */
            '<div class="df-thermal-box">' +
              '<div class="df-sec-label" style="margin-bottom:6px;">Plantillas de impresión (20 por formato)</div>' +
              '<div class="df-thermal-row">' +
                '<div class="df-mini-ticket" data-click="ptdQuickSwitchThermalFormat" data-click-arg="80mm" title="Clic para diseñar en Ticket 80 mm">' +
                  '<div style="text-align:center;font-weight:900;font-size:7.5px;color:' + esc(activePresetMeta.primary) + ';">MAGDALENO</div>' +
                  '<div style="text-align:center;font-size:5.5px;margin-bottom:3px;">MADERAS Y MATERIALES</div>' +
                  '<div style="text-align:center;font-weight:800;border-top:1px dashed #94a3b8;border-bottom:1px dashed #94a3b8;padding:1.5px 0;margin-bottom:3px;">ESTILO #' + _activePresetNumber + '</div>' +
                  '<div>Folio: T-000125</div>' +
                  '<div>Fecha: 26/04/2026</div>' +
                  '<div style="border-top:1px dotted #cbd5e1;margin:2px 0;padding-top:2px;display:flex;justify-content:space-between;"><span>Clavo 2 1/2"</span><b>$38.00</b></div>' +
                  '<div style="display:flex;justify-content:space-between;"><span>Tornillo 1"</span><b>$52.00</b></div>' +
                  '<div style="border-top:1px solid #0f172a;margin-top:3px;padding-top:2px;text-align:right;font-weight:900;font-size:7.5px;">Total: $90.00</div>' +
                '</div>' +
                '<div style="flex:1;min-width:0;">' +
                  '<label style="font-size:10.5px;color:#94a3b8;display:block;margin-bottom:4px;">Formato / Medida</label>' +
                  '<select class="df-sel" style="height:30px;font-size:11.5px;margin-bottom:6px;" data-change="ptdSwitchThermalDropdown">' +
                    '<option value="letter"' + (currentPaperKey === 'letter' ? ' selected' : '') + '>Carta (215.9 × 279.4 mm)</option>' +
                    '<option value="80mm"' + (currentPaperKey === '80mm' ? ' selected' : '') + '>Ticket 80 mm (20 estilos)</option>' +
                    '<option value="58mm"' + (currentPaperKey === '58mm' ? ' selected' : '') + '>Ticket 58 mm (20 estilos)</option>' +
                  '</select>' +
                  '<button type="button" class="df-btn" style="width:100%;height:28px;font-size:10.5px;padding:0 6px;" data-click="ptdSwitchInternalTab" data-click-arg="biblioteca">' +
                    '<i class="fa-solid fa-table-cells-large" style="color:#60a5fa;"></i> Ver los 20 Estilos' +
                  '</button>' +
                '</div>' +
              '</div>' +
            '</div>' +

          '</div>' +

          /* ── COLUMNA CENTRAL (Barra Rápida Photoshop/Corel + Reglas Milimétricas + Lienzo 100% Editable) ── */
          '<div class="df-center-col">' +

            '<div class="df-corel-toolbar">' +
              '<div class="df-corel-grp">' +
                '<button type="button" class="df-tool-btn" data-click="ptdTriggerFreeImageUpload" title="Subir una imagen y colocarla donde quieras"><i class="fa-regular fa-image" style="color:#60a5fa;"></i> + Imagen</button>' +
                '<button type="button" class="df-tool-btn" data-click="ptdAddElement" data-click-arg="text" title="Agregar cuadro de texto para encimar"><i class="fa-solid fa-font" style="color:#34d399;"></i> + Texto</button>' +
                '<button type="button" class="df-tool-btn" data-click="ptdAddElement" data-click-arg="rect" title="Agregar rectángulo o franja de color"><i class="fa-regular fa-square" style="color:#f59e0b;"></i> + Forma</button>' +
                '<button type="button" class="df-tool-btn" data-click="ptdAddElement" data-click-arg="table_corte_ciego" title="Insertar Tabla de Corte Ciego (Arqueo físico de billetes, monedas y vouchers sin saldo esperado)">🙈 + Corte Ciego</button>' +
                '<button type="button" class="df-tool-btn" data-click="ptdAddElement" data-click-arg="table_corte_x" title="Insertar Tabla de Corte X (Flujo de efectivo en gaveta y formas de pago en turno abierto)">📊 + Corte X</button>' +
                '<button type="button" class="df-tool-btn" data-click="ptdAddElement" data-click-arg="table_corte_z" title="Insertar Tabla de Corte Z (Conciliación Sistema Esperado vs Cajero Declarado vs Diferencia)">🔒 + Corte Z</button>' +
                '<button type="button" class="df-tool-btn" data-click="ptdInsertFieldFromSource" data-click-arg="profeco.leyenda_garantias" data-click-arg2="CLÁUSULA GARANTÍA PROFECO" data-click-arg3="{{profeco.leyenda_garantias}}" title="Insertar Cláusula Oficial de Garantía PROFECO (Art. 12 y 77 LFPC)">⚖ + PROFECO</button>' +
                '<button type="button" class="df-tool-btn" data-click="ptdCycleTableTaxMode" title="Cambiar si el Total del Artículo en la tabla es CON IVA, SIN IVA o DESGLOSADO"><i class="fa-solid fa-percent" style="color:#fbbf24;"></i> Artículos: CON/SIN IVA</button>' +
                '<button type="button" class="df-tool-btn" data-click="ptdInsertFieldFromSource" data-click-arg="importes.subtotal_sin_iva" data-click-arg2="SUBTOTAL SIN IVA" data-click-arg3="Subtotal SIN IVA: {{importes.subtotal_sin_iva}}" title="Insertar Subtotal SIN IVA por separado">+ Subt. s/IVA</button>' +
                '<button type="button" class="df-tool-btn" data-click="ptdInsertFieldFromSource" data-click-arg="importes.impuesto_total" data-click-arg2="IMPUESTO TOTAL IVA 16%" data-click-arg3="Impuesto Total (IVA 16%): {{importes.impuesto_total}}" title="Insertar Impuesto Total (IVA) por separado">+ Impuesto Total</button>' +
                '<button type="button" class="df-tool-btn" data-click="ptdInsertFieldFromSource" data-click-arg="importes.subtotal_con_iva" data-click-arg2="SUBTOTAL CON IVA" data-click-arg3="Subtotal CON IVA: {{importes.subtotal_con_iva}}" title="Insertar Subtotal CON IVA por separado">+ Subt. c/IVA</button>' +
                '<button type="button" class="df-tool-btn" data-click="ptdInsertQrSealLayer" title="Agregar Sello QR Fiscal como capa independiente"><i class="fa-solid fa-qrcode" style="color:#34d399;"></i> + Sello QR</button>' +
                '<button type="button" class="df-tool-btn" data-click="ptdInsertFieldFromSource" data-click-arg="cfdi.serie_sello" data-click-arg2="SERIE DEL SELLO CSD" data-click-arg3="Serie Sello CSD: {{cfdi.serie_sello}}" title="Agregar Serie del Sello por separado"><i class="fa-solid fa-key" style="color:#34d399;"></i> + Serie Sello</button>' +
                '<button type="button" class="df-tool-btn" data-click="ptdInsertFieldFromSource" data-click-arg="credito.saldo_anterior" data-click-arg2="SALDO ANTERIOR" data-click-arg3="Saldo Anterior: {{credito.saldo_anterior}}" title="Agregar Saldo Anterior (Nota de Crédito / Ticket)"><i class="fa-solid fa-clock-rotate-left" style="color:#a5b4fc;"></i> + Saldo Ant.</button>' +
                '<button type="button" class="df-tool-btn" data-click="ptdInsertFieldFromSource" data-click-arg="credito.saldo_actual" data-click-arg2="SALDO ACTUAL" data-click-arg3="Saldo Actual: {{credito.saldo_actual}}" title="Agregar Saldo Actual (Nota de Crédito / Ticket)"><i class="fa-solid fa-scale-balanced" style="color:#a5b4fc;"></i> + Saldo Act.</button>' +
              '</div>' +
              '<div class="df-corel-grp">' +
                '<span style="font-size:10px;color:#94a3b8;padding:0 4px;">Escala:</span>' +
                '<button type="button" class="df-tool-btn" data-click="ptdScaleSelectedByFactor" data-click-arg="0.88" title="Hacer más chico (-12%)"><i class="fa-solid fa-compress"></i> −Chico</button>' +
                '<button type="button" class="df-tool-btn" data-click="ptdScaleSelectedByFactor" data-click-arg="1.14" title="Hacer más grande (+14%)"><i class="fa-solid fa-expand"></i> +Grande</button>' +
              '</div>' +
              '<div class="df-corel-grp">' +
                '<span style="font-size:10px;color:#94a3b8;padding:0 4px;">Capas:</span>' +
                '<button type="button" class="df-tool-btn" data-click="ptdSelectedLayerOrder" data-click-arg="front" title="Traer hasta el frente (encima de todo)">⏫ Frente</button>' +
                '<button type="button" class="df-tool-btn" data-click="ptdSelectedLayerOrder" data-click-arg="up" title="Subir una capa">▲ Subir</button>' +
                '<button type="button" class="df-tool-btn" data-click="ptdSelectedLayerOrder" data-click-arg="down" title="Bajar una capa (poner debajo)">▼ Bajar</button>' +
                '<button type="button" class="df-tool-btn" data-click="ptdSelectedLayerOrder" data-click-arg="back" title="Enviar hasta el fondo (detrás de todo)">⏬ Fondo</button>' +
              '</div>' +
              '<div class="df-corel-grp">' +
                '<button type="button" class="df-tool-btn" data-click="ptdDuplicateSelectedElement" title="Duplicar elemento seleccionado"><i class="fa-regular fa-copy"></i></button>' +
                '<button type="button" class="df-tool-btn" data-click="ptdUndo" title="Deshacer"><i class="fa-solid fa-rotate-left"></i></button>' +
                '<button type="button" class="df-tool-btn" data-click="ptdRedo" title="Rehacer"><i class="fa-solid fa-rotate-right"></i></button>' +
                '<button type="button" class="df-tool-btn danger" data-click="ptdDeleteSelectedElement" title="Eliminar elemento seleccionado"><i class="fa-solid fa-trash"></i></button>' +
              '</div>' +
            '</div>' +

            '<div style="position:relative;flex:1;display:flex;flex-direction:column;overflow:hidden;">' +
              '<div class="df-ruler-corner"></div>' +
              '<div class="df-ruler-h">' + rulerHMarks + '</div>' +
              '<div class="df-stage-body">' +
                '<div class="df-ruler-v">' + rulerVMarks + '</div>' +
                '<div class="df-canvas-scroll" id="df-canvas-scroll">' +
                  '<div class="df-sheet" id="ptd-paper-sheet" style="width:' + sheetWpx + 'px;height:' + sheetHpx + 'px;">' +
                    sheetBackgroundHtml +
                    guidesHtml +
                    boxesHtml +
                  '</div>' +
                '</div>' +
              '</div>' +
            '</div>' +

            '<div class="df-bottom-bar">' +
              '<div style="display:flex;align-items:center;gap:14px;">' +
                '<span><i class="fa-regular fa-file-lines" style="margin-right:5px;"></i> <b style="color:#f8fafc;">Página ' + _activePageNum + ' de ' + (bgAsset ? bgAsset.page_count : 1) + '</b></span>' +
                '<span style="color:#334155;">|</span>' +
                '<span>' + (isTicketMode ? ('Ticket · ' + pwMm + ' mm') : ('Carta · ' + pwMm + ' × ' + phMm + ' mm')) + ' · <b>Plantilla #' + _activePresetNumber + '</b></span>' +
                '<span style="color:#334155;">|</span>' +
                '<span style="color:#60a5fa;font-size:11px;">✨ Todo es seleccionable: mueve, escala o cambia de capa cualquier elemento</span>' +
              '</div>' +
              '<div style="display:flex;align-items:center;gap:8px;">' +
                '<div class="df-zoom-group">' +
                  '<button type="button" class="df-zoom-btn" data-click="ptdStepZoom" data-click-arg="-0.1">−</button>' +
                  '<span class="df-zoom-val">' + Math.round(_zoom * 100) + '%</span>' +
                  '<button type="button" class="df-zoom-btn" data-click="ptdStepZoom" data-click-arg="0.1">+</button>' +
                '</div>' +
                '<button type="button" class="df-btn" style="height:28px;padding:0 9px;" data-click="ptdToggleFullscreen" title="Pantalla completa">' +
                  '<i class="fa-solid fa-expand"></i>' +
                '</button>' +
              '</div>' +
            '</div>' +
          '</div>' +

          /* ── COLUMNA DERECHA (Propiedades del campo/imagen + Escala + Capas + Fondo del documento) ── */
          '<div class="df-right-col">' +
            '<div class="df-prop-header">' +
              '<i class="fa-solid fa-layer-group"></i> <span>Propiedades del elemento</span>' +
            '</div>' +

            (selEl ? (
              '<div class="df-prop-group">' +
                '<label class="df-prop-label">Nombre de la capa / campo</label>' +
                '<input type="text" class="df-inp" style="text-transform:uppercase;" value="' + esc(selEl.label || '') + '" data-input="ptdUpdateSelectedLabel">' +
              '</div>' +

              '<div class="df-prop-group">' +
                '<label class="df-prop-label">Orden de Capa (Z-Index: ' + Number(selEl.z_index || 1) + ')</label>' +
                '<div style="display:grid;grid-template-columns:repeat(4,1fr);gap:4px;">' +
                  '<button type="button" class="df-btn" style="height:28px;padding:0;font-size:10.5px;" data-click="ptdSelectedLayerOrder" data-click-arg="front" title="Poner encima de todo">⏫ Frente</button>' +
                  '<button type="button" class="df-btn" style="height:28px;padding:0;font-size:10.5px;" data-click="ptdSelectedLayerOrder" data-click-arg="up" title="Subir una capa">▲ Subir</button>' +
                  '<button type="button" class="df-btn" style="height:28px;padding:0;font-size:10.5px;" data-click="ptdSelectedLayerOrder" data-click-arg="down" title="Bajar una capa (poner debajo)">▼ Bajar</button>' +
                  '<button type="button" class="df-btn" style="height:28px;padding:0;font-size:10.5px;" data-click="ptdSelectedLayerOrder" data-click-arg="back" title="Enviar atrás de todo">⏬ Fondo</button>' +
                '</div>' +
              '</div>' +

              '<div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;">' +
                '<div class="df-prop-group">' +
                  '<label class="df-prop-label">Escala rápida</label>' +
                  '<div style="display:flex;gap:4px;">' +
                    '<button type="button" class="df-btn" style="flex:1;height:30px;padding:0;font-size:11px;" data-click="ptdScaleSelectedByFactor" data-click-arg="0.9">−10%</button>' +
                    '<button type="button" class="df-btn" style="flex:1;height:30px;padding:0;font-size:11px;" data-click="ptdScaleSelectedByFactor" data-click-arg="1.1">+10%</button>' +
                  '</div>' +
                '</div>' +
                '<div class="df-prop-group">' +
                  '<label class="df-prop-label">Opacidad (' + curOpacityPct + '%)</label>' +
                  '<input type="range" min="10" max="100" step="5" value="' + curOpacityPct + '" style="width:100%;height:30px;accent-color:#2563eb;cursor:pointer;" data-input="ptdUpdateSelectedOpacity">' +
                '</div>' +
              '</div>' +

              (selEl.type === 'image' ? (
                '<div class="df-prop-group">' +
                  '<label class="df-prop-label">Archivo de esta imagen</label>' +
                  '<button type="button" class="df-btn" style="width:100%;height:32px;font-size:11.5px;" data-click="ptdReplaceSelectedImage">' +
                    '<i class="fa-solid fa-upload"></i> Cambiar imagen de esta capa' +
                  '</button>' +
                '</div>'
              ) : (
                '<div class="df-prop-group">' +
                  '<label class="df-prop-label">Vinculación de datos</label>' +
                  '<select class="df-sel" data-change="ptdUpdateSelectedBinding">' +
                    bindingOptsHtml +
                  '</select>' +
                '</div>' +
                '<div class="df-prop-group">' +
                  '<label class="df-prop-label">Texto / Contenido (Editable)</label>' +
                  '<textarea class="df-inp" rows="2" style="height:auto;padding:6px 8px;font-size:11.5px;" data-input="ptdUpdateSelectedTextContent">' + esc(selEl.text || '') + '</textarea>' +
                '</div>'
              )) +

              '<div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;">' +
                '<div class="df-prop-group">' +
                  '<label class="df-prop-label">X</label>' +
                  '<div class="df-mm-wrap">' +
                    '<input type="number" step="0.5" class="df-inp" value="' + esc(selEl.x_mm) + '" data-input="ptdUpdateSelectedCoord" data-click-arg="x_mm">' +
                    '<span class="df-mm-unit">mm</span>' +
                  '</div>' +
                '</div>' +
                '<div class="df-prop-group">' +
                  '<label class="df-prop-label">Y</label>' +
                  '<div class="df-mm-wrap">' +
                    '<input type="number" step="0.5" class="df-inp" value="' + esc(selEl.y_mm) + '" data-input="ptdUpdateSelectedCoord" data-click-arg="y_mm">' +
                    '<span class="df-mm-unit">mm</span>' +
                  '</div>' +
                '</div>' +
                '<div class="df-prop-group">' +
                  '<label class="df-prop-label">Ancho</label>' +
                  '<div class="df-mm-wrap">' +
                    '<input type="number" step="0.5" class="df-inp" value="' + esc(selEl.w_mm) + '" data-input="ptdUpdateSelectedCoord" data-click-arg="w_mm">' +
                    '<span class="df-mm-unit">mm</span>' +
                  '</div>' +
                '</div>' +
                '<div class="df-prop-group">' +
                  '<label class="df-prop-label">Alto</label>' +
                  '<div class="df-mm-wrap">' +
                    '<input type="number" step="0.5" class="df-inp" value="' + esc(selEl.h_mm) + '" data-input="ptdUpdateSelectedCoord" data-click-arg="h_mm">' +
                    '<span class="df-mm-unit">mm</span>' +
                  '</div>' +
                '</div>' +
              '</div>' +

              '<div class="df-prop-group">' +
                '<label class="df-prop-label">Fuente</label>' +
                '<select class="df-sel" data-change="ptdUpdateSelectedFontFamily">' +
                  '<option value="Arial"' + (selEl.font_family === 'Arial' ? ' selected' : '') + '>Arial</option>' +
                  '<option value="Inter"' + (selEl.font_family === 'Inter' ? ' selected' : '') + '>Inter</option>' +
                  '<option value="Montserrat"' + (selEl.font_family === 'Montserrat' ? ' selected' : '') + '>Montserrat</option>' +
                  '<option value="Courier New"' + (selEl.font_family === 'Courier New' ? ' selected' : '') + '>Courier New</option>' +
                '</select>' +
              '</div>' +

              '<div style="display:grid;grid-template-columns:1fr 1.25fr;gap:10px;">' +
                '<div class="df-prop-group">' +
                  '<label class="df-prop-label">Tamaño</label>' +
                  '<input type="number" min="6" max="48" class="df-inp" value="' + esc(selEl.font_size || 11) + '" data-input="ptdUpdateSelectedCoord" data-click-arg="font_size">' +
                '</div>' +
                '<div class="df-prop-group">' +
                  '<label class="df-prop-label">Estilo</label>' +
                  '<div class="df-style-btns">' +
                    '<button type="button" class="df-style-btn' + (selEl.bold ? ' active' : '') + '" data-click="ptdToggleTextStyle" data-click-arg="bold"><b>B</b></button>' +
                    '<button type="button" class="df-style-btn' + (selEl.italic ? ' active' : '') + '" data-click="ptdToggleTextStyle" data-click-arg="italic"><i>I</i></button>' +
                    '<button type="button" class="df-style-btn' + (selEl.underline ? ' active' : '') + '" data-click="ptdToggleTextStyle" data-click-arg="underline"><u>U</u></button>' +
                  '</div>' +
                '</div>' +
              '</div>' +

              '<div class="df-prop-group">' +
                '<label class="df-prop-label">Alineación</label>' +
                '<div class="df-style-btns">' +
                  '<button type="button" class="df-style-btn' + ((selEl.align || 'left') === 'left' ? ' active' : '') + '" data-click="ptdSetTextAlign" data-click-arg="left"><i class="fa-solid fa-align-left"></i></button>' +
                  '<button type="button" class="df-style-btn' + (selEl.align === 'center' ? ' active' : '') + '" data-click="ptdSetTextAlign" data-click-arg="center"><i class="fa-solid fa-align-center"></i></button>' +
                  '<button type="button" class="df-style-btn' + (selEl.align === 'right' ? ' active' : '') + '" data-click="ptdSetTextAlign" data-click-arg="right"><i class="fa-solid fa-align-right"></i></button>' +
                '</div>' +
              '</div>' +

              '<div class="df-prop-group">' +
                '<label class="df-prop-label">Color del texto / forma</label>' +
                '<div style="display:flex;align-items:center;gap:8px;background:#15223d;border:1px solid #26385e;border-radius:7px;padding:0 10px;height:34px;">' +
                  '<input type="color" value="' + esc(selEl.color || selEl.background_color || selEl.header_bg || '#000000') + '" style="width:24px;height:24px;border:none;background:transparent;cursor:pointer;" data-input="ptdUpdateSelectedColor">' +
                  '<span style="font-size:12px;font-weight:700;color:#f8fafc;">' + esc((selEl.color || selEl.background_color || selEl.header_bg || '#000000').toUpperCase()) + '</span>' +
                '</div>' +
              '</div>' +

              '<div class="df-switch-row">' +
                '<span class="df-prop-label">Ajustar texto <i class="fa-solid fa-circle-info" style="color:#64748b;font-size:10.5px;"></i></span>' +
                '<button type="button" class="df-toggle' + (selEl.wrap !== false ? ' on' : '') + '" data-click="ptdToggleWrapSelected"></button>' +
              '</div>'
            ) : '<div style="color:#94a3b8;font-size:12px;">Haz clic en cualquier elemento del lienzo para editarlo.</div>') +

            '<div style="border-top:1px solid #1e293b;padding-top:10px;">' +
              '<div class="df-prop-header" style="border-bottom:none;padding-bottom:4px;font-size:12.5px;">' +
                '<i class="fa-solid fa-percent" style="color:#fbbf24;"></i> <span>IVA de Artículos y Subtotales</span>' +
              '</div>' +
              '<div class="df-prop-group" style="margin-bottom:6px;">' +
                '<label class="df-prop-label">Total del artículo en la tabla</label>' +
                '<select class="df-sel" data-change="ptdSetTableTaxModeSelect">' +
                  '<option value="CON_IVA"' + (((els.filter(function (x) { return x.type === 'table_products'; })[0] || {}).tax_display_mode || 'CON_IVA') === 'CON_IVA' ? ' selected' : '') + '>Total Artículo CON IVA incluido</option>' +
                  '<option value="SIN_IVA"' + (((els.filter(function (x) { return x.type === 'table_products'; })[0] || {}).tax_display_mode) === 'SIN_IVA' ? ' selected' : '') + '>Total Artículo SIN IVA</option>' +
                  '<option value="DESGLOSADO"' + (((els.filter(function (x) { return x.type === 'table_products'; })[0] || {}).tax_display_mode) === 'DESGLOSADO' ? ' selected' : '') + '>Desglosado (Sin IVA + IVA 16% + Con IVA)</option>' +
                '</select>' +
              '</div>' +
              '<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:4px;">' +
                '<button type="button" class="df-btn" style="height:26px;padding:0;font-size:10px;" data-click="ptdInsertFieldFromSource" data-click-arg="importes.subtotal_sin_iva" data-click-arg2="SUBTOTAL SIN IVA" data-click-arg3="Subtotal SIN IVA: {{importes.subtotal_sin_iva}}" title="Insertar Subtotal SIN IVA">+Subt s/IVA</button>' +
                '<button type="button" class="df-btn" style="height:26px;padding:0;font-size:10px;" data-click="ptdInsertFieldFromSource" data-click-arg="importes.impuesto_total" data-click-arg2="IMPUESTO TOTAL IVA 16%" data-click-arg3="Impuesto Total (IVA 16%): {{importes.impuesto_total}}" title="Insertar Impuesto Total">+IVA Total</button>' +
                '<button type="button" class="df-btn" style="height:26px;padding:0;font-size:10px;" data-click="ptdInsertFieldFromSource" data-click-arg="importes.subtotal_con_iva" data-click-arg2="SUBTOTAL CON IVA" data-click-arg3="Subtotal CON IVA: {{importes.subtotal_con_iva}}" title="Insertar Subtotal CON IVA">+Subt c/IVA</button>' +
              '</div>' +
            '</div>' +

            '<div style="border-top:1px solid #1e293b;padding-top:12px;margin-top:auto;">' +
              '<div class="df-prop-header" style="border-bottom:none;padding-bottom:4px;font-size:13px;">' +
                '<i class="fa-regular fa-image"></i> <span>Fondo del documento</span>' +
              '</div>' +
              '<div class="df-switch-row" style="margin-bottom:6px;">' +
                '<span class="df-prop-label">Imprimir fondo</span>' +
                '<button type="button" class="df-toggle' + (printBgOn ? ' on' : '') + '" data-click="ptdTogglePrintBackgroundSwitch"></button>' +
              '</div>' +
              '<select class="df-sel" data-change="ptdUpdateBgPrintModeSelect">' +
                '<option value="fields_only"' + (!printBgOn ? ' selected' : '') + '>Solo campos · Papel preimpreso</option>' +
                '<option value="background_and_fields"' + (printBgOn ? ' selected' : '') + '>Fondo y campos · Hoja blanca</option>' +
              '</select>' +
            '</div>' +

          '</div>' +

        '</div>'
        )) +

      '</div>';

    bindCanvasPointerAndDropzone();
  }

  /* ═══════════════════════════════════════════════════════════════════════════
     MOTOR DE ARRASTRE Y ESCALADO DE 8 PUNTOS + DOBLE CLIC EN EL LIENZO
     ═══════════════════════════════════════════════════════════════════════════ */
  function bindCanvasPointerAndDropzone() {
    var sheet = document.getElementById('ptd-paper-sheet');
    if (sheet && !sheet._boundInteractions) {
      sheet._boundInteractions = true;

      sheet.addEventListener('pointerdown', function (e) {
        var handle = e.target.closest('[data-resize-el]');
        var box = e.target.closest('[data-el-id]');
        if (!box || !_workingVersion) return;

        var elId = box.getAttribute('data-el-id');
        _selectedElementId = elId;
        var els = ensureOverlayFields(_workingVersion);
        var targetEl = els.filter(function (x) { return x.id === elId; })[0];
        if (!targetEl) return;

        if (targetEl.locked) {
          showBannerToast('Esta capa está bloqueada (🔒). Desbloquéala en la pestaña Capas para moverla o escalarla.', true);
          renderDesignerStudioUI();
          return;
        }

        e.preventDefault();
        pushUndo();
        _dragState = {
          mode: handle ? 'resize' : 'move',
          dir: handle ? (handle.getAttribute('data-resize-dir') || 'br') : 'move',
          el: targetEl,
          node: box,
          startX: e.clientX,
          startY: e.clientY,
          origX: Number(targetEl.x_mm || 0),
          origY: Number(targetEl.y_mm || 0),
          origW: Number(targetEl.w_mm || 40),
          origH: Number(targetEl.h_mm || 10)
        };
      });

      sheet.addEventListener('dblclick', function (e) {
        var box = e.target.closest('[data-el-id]');
        if (!box || !_workingVersion) return;
        var elId = box.getAttribute('data-el-id');
        var els = ensureOverlayFields(_workingVersion);
        var targetEl = els.filter(function (x) { return x.id === elId; })[0];
        if (!targetEl || targetEl.locked) return;
        if (targetEl.type === 'image') {
          global.ptdReplaceSelectedImage();
          return;
        }
        var nuevoTxt = prompt('EDITAR TEXTO DE LA CAPA «' + (targetEl.label || '') + '»:', targetEl.text || '');
        if (nuevoTxt !== null) {
          pushUndo();
          targetEl.text = nuevoTxt;
          renderDesignerStudioUI();
        }
      });

      sheet.addEventListener('dragover', function (e) {
        e.preventDefault();
      });
      sheet.addEventListener('drop', function (e) {
        e.preventDefault();
        var file = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0];
        if (file) {
          var rect = sheet.getBoundingClientRect();
          var dropXmm = Math.max(2, pxToMm(e.clientX - rect.left) - 18);
          var dropYmm = Math.max(2, pxToMm(e.clientY - rect.top) - 10);
          insertImageFileAsMovableLayer(file, dropXmm, dropYmm);
        }
      });
    }

    if (!window._dfGlobalPointerBound) {
      window._dfGlobalPointerBound = true;
      window.addEventListener('pointermove', function (e) {
        if (!_dragState) return;
        var dxMm = pxToMm(e.clientX - _dragState.startX);
        var dyMm = pxToMm(e.clientY - _dragState.startY);
        var el = _dragState.el;
        var d = _dragState.dir;

        if (_dragState.mode === 'move') {
          el.x_mm = Math.max(0, Number((_dragState.origX + dxMm).toFixed(1)));
          el.y_mm = Math.max(0, Number((_dragState.origY + dyMm).toFixed(1)));
        } else {
          if (d.indexOf('r') >= 0) {
            el.w_mm = Math.max(6, Number((_dragState.origW + dxMm).toFixed(1)));
          }
          if (d.indexOf('b') >= 0) {
            el.h_mm = Math.max(3, Number((_dragState.origH + dyMm).toFixed(1)));
          }
          if (d.indexOf('l') >= 0) {
            var newW = Math.max(6, Number((_dragState.origW - dxMm).toFixed(1)));
            el.x_mm = Math.max(0, Number((_dragState.origX + (_dragState.origW - newW)).toFixed(1)));
            el.w_mm = newW;
          }
          if (d.indexOf('t') >= 0) {
            var newH = Math.max(3, Number((_dragState.origH - dyMm).toFixed(1)));
            el.y_mm = Math.max(0, Number((_dragState.origY + (_dragState.origH - newH)).toFixed(1)));
            el.h_mm = newH;
          }
        }

        _dragState.node.style.left = mmToPx(el.x_mm) + 'px';
        _dragState.node.style.top = mmToPx(el.y_mm) + 'px';
        _dragState.node.style.width = mmToPx(el.w_mm) + 'px';
        _dragState.node.style.height = mmToPx(el.h_mm) + 'px';
        _isDirty = true;
      });

      window.addEventListener('pointerup', function () {
        if (!_dragState) return;
        _dragState = null;
        renderDesignerStudioUI();
      });
    }

    var dz = document.getElementById('df-upload-dropzone');
    if (dz && !dz._boundDrop) {
      dz._boundDrop = true;
      dz.addEventListener('dragover', function (e) {
        e.preventDefault();
        dz.classList.add('dragover');
      });
      dz.addEventListener('dragleave', function () {
        dz.classList.remove('dragover');
      });
      dz.addEventListener('drop', function (e) {
        e.preventDefault();
        dz.classList.remove('dragover');
        var file = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0];
        if (file) handleUniversalFile(file, 'FREE_IMAGE');
      });
    }
  }

  /* ═══════════════════════════════════════════════════════════════════════════
     SUBIDA DE IMÁGENES LIBRES (CAPAS MOVIBLES Y ESCALABLES) O FONDOS PDF
     ═══════════════════════════════════════════════════════════════════════════ */
  function insertImageFileAsMovableLayer(file, xMm, yMm, replaceSelected) {
    var reader = new FileReader();
    reader.onload = function (evt) {
      var dataUrl = evt.target.result;
      var probeImg = new Image();
      probeImg.onload = function () {
        pushUndo();
        var els = ensureOverlayFields(_workingVersion);
        var ratio = (probeImg.width && probeImg.height) ? (probeImg.width / probeImg.height) : 1.5;
        var isTicket = (_workingVersion && _workingVersion.mode === 'TICKET');
        var defaultW = isTicket ? 42.0 : 65.0;
        var defaultH = Math.max(10.0, Math.min(110.0, Number((defaultW / ratio).toFixed(1))));

        if (replaceSelected && _selectedElementId) {
          var sel = els.filter(function (x) { return x.id === _selectedElementId; })[0];
          if (sel && sel.type === 'image') {
            sel.src = dataUrl;
            sel.label = 'IMAGEN: ' + String(file.name || 'CAPA').toUpperCase();
            showBannerToast('Imagen de la capa actualizada. Puedes moverla, escalarla o cambiar su orden de capa.', false);
            renderDesignerStudioUI();
            return;
          }
        }

        var maxZ = els.reduce(function (m, e) { return Math.max(m, Number(e.z_index || 1)); }, 1);
        var newId = 'img-layer-' + Date.now();
        els.push({
          id: newId,
          type: 'image',
          label: 'IMAGEN: ' + String(file.name || 'NUEVA').toUpperCase(),
          src: dataUrl,
          x_mm: xMm != null ? xMm : (isTicket ? 8.0 : 45.0),
          y_mm: yMm != null ? yMm : 35.0,
          w_mm: defaultW,
          h_mm: defaultH,
          scale_pct: 100,
          opacity: 1.0,
          rotation_deg: 0,
          page: _activePageNum,
          z_index: maxZ + 1
        });
        _selectedElementId = newId;
        showBannerToast('Imagen «' + file.name + '» insertada como capa independiente. Arrástrala, hazla más chica o grande y acomódala adelante o atrás de otras capas.', false);
        renderDesignerStudioUI();
      };
      probeImg.src = dataUrl;
    };
    reader.readAsDataURL(file);
  }

  function handleUniversalFile(file, mode) {
    if (!file) return;
    var isPdf = (file.type === 'application/pdf' || /\.pdf$/i.test(file.name || ''));
    if (!isPdf && mode === 'FREE_IMAGE') {
      insertImageFileAsMovableLayer(file, null, null, false);
      return;
    }
    if (!isPdf && mode === 'REPLACE_IMG') {
      insertImageFileAsMovableLayer(file, null, null, true);
      return;
    }
    var fd = new FormData();
    fd.append('file', file);
    fd.append('kind', 'BACKGROUND');
    var tok = localStorage.getItem('calebsys_token') || sessionStorage.getItem('calebsys_token') || '';
    fetch('/api/print-formats/assets/upload', {
      method: 'POST',
      headers: tok ? { 'Authorization': 'Bearer ' + tok } : {},
      body: fd
    }).then(function (r) {
      return r.json().then(function (d) {
        if (!r.ok) throw new Error((d.detail && d.detail.message) || d.detail || 'Error al subir archivo');
        return d;
      });
    }).then(function (asset) {
      pushUndo();
      if (mode === 'FREE_IMAGE') {
        var els = ensureOverlayFields(_workingVersion);
        var newId = 'pdf-layer-' + Date.now();
        els.push({
          id: newId,
          type: 'image',
          label: 'DISEÑO: ' + String(asset.original_filename).toUpperCase(),
          src: '/api/print-formats/assets/' + encodeURIComponent(asset.id) + '/page/1',
          asset_id: asset.id,
          x_mm: 0.0,
          y_mm: 0.0,
          w_mm: Number(_workingVersion.paper_width_mm || 215.9),
          h_mm: Number(_workingVersion.paper_height_mm || 279.4),
          scale_pct: 100,
          opacity: 1.0,
          page: 1,
          z_index: 1
        });
        _selectedElementId = newId;
        showBannerToast('Diseño «' + asset.original_filename + '» colocado en Capa 1. Puedes escalarlo, moverlo o encimarle textos e imágenes.', false);
      } else {
        _workingVersion.background_asset_id = asset.id;
        _activeBackendTpl.background_asset = asset;
        showBannerToast('Fondo de hoja «' + asset.original_filename + '» actualizado.', false);
      }
      renderDesignerStudioUI();
    }).catch(function (err) {
      showBannerToast(err.message, true);
    });
  }

  /* ═══════════════════════════════════════════════════════════════════════════
     ACCIONES DE LOS 20 ESTILOS PRECARGADOS (CARTA, TICKET 80 MM Y TICKET 58 MM)
     ═══════════════════════════════════════════════════════════════════════════ */
  global.ptdApplyPresetStyleNumber = function (numStr) {
    if (!_workingVersion) return;
    var num = Math.max(1, Math.min(20, parseInt(numStr || '1', 10)));
    pushUndo();
    _activePresetNumber = num;
    var isTicket = (_workingVersion.mode === 'TICKET');
    var pFmt = isTicket ? ((Number(_workingVersion.paper_width_mm || 80) < 70) ? '58mm' : '80mm') : 'letter';
    var dType = (_activeBackendTpl && _activeBackendTpl.doc_type) || _galleryDocType || 'cotizacion';
    _workingVersion.definition_json.preset_style_num = num;
    _workingVersion.definition_json.elements = generatePresetLayers(dType, pFmt, num, _activeBackendTpl && _activeBackendTpl.name);
    if (num === 20) {
      if (!_workingVersion.background_settings_json) _workingVersion.background_settings_json = {};
      _workingVersion.background_settings_json.print_mode = 'fields_only';
    }
    _selectedElementId = (_workingVersion.definition_json.elements[0] && _workingVersion.definition_json.elements[0].id) || 'f-cli-nombre';
    var stMeta = TEN_PRESET_STYLES[num - 1] || TEN_PRESET_STYLES[0];
    showBannerToast('Estilo Profesional #' + num + ' («' + stMeta.name + '») aplicado en ' + (pFmt === 'letter' ? 'Carta' : ('Ticket ' + pFmt)) + ' — ¡todas sus capas están listas para mover y modificar!', false);
    renderDesignerStudioUI();
  };

  global.ptdSwitchPresetSelect = function (e) {
    var val = e && e.target ? e.target.value : '1';
    global.ptdApplyPresetStyleNumber(val);
  };

  global.ptdSetGalleryDocType = function (docId) {
    _galleryDocType = docId || 'cotizacion';
    renderDesignerStudioUI();
  };

  global.ptdSetGalleryPaperFormat = function (fmt) {
    _galleryPaperFormat = (fmt === '80mm' || fmt === '58mm') ? fmt : 'letter';
    renderDesignerStudioUI();
  };

  global.ptdLoadPresetIntoCanvas = function (numStr, docTypeStr, paperFmtStr) {
    if (!_workingVersion) return;
    pushUndo();
    var num = Math.max(1, Math.min(20, parseInt(numStr || '1', 10)));
    var dType = docTypeStr || _galleryDocType || 'cotizacion';
    var pFmt = paperFmtStr || _galleryPaperFormat || 'letter';

    _activePresetNumber = num;
    _galleryDocType = dType;
    _galleryPaperFormat = pFmt;

    if (pFmt === 'letter') {
      _workingVersion.mode = 'CARTA';
      _workingVersion.paper_size = 'letter';
      _workingVersion.paper_width_mm = 215.9;
      _workingVersion.paper_height_mm = 279.4;
      _zoom = 0.85;
    } else if (pFmt === '58mm') {
      _workingVersion.mode = 'TICKET';
      _workingVersion.paper_size = '58mm';
      _workingVersion.paper_width_mm = 58.0;
      _workingVersion.paper_height_mm = 195.0;
      _zoom = 1.15;
    } else {
      _workingVersion.mode = 'TICKET';
      _workingVersion.paper_size = '80mm';
      _workingVersion.paper_width_mm = 80.0;
      _workingVersion.paper_height_mm = 210.0;
      _zoom = 1.05;
    }

    var docMeta = DOC_TYPES_LIST.filter(function (d) { return d.id === dType; })[0] || DOC_TYPES_LIST[0];
    if (_activeBackendTpl) {
      _activeBackendTpl.doc_type = dType;
    }
    _workingVersion.definition_json.preset_style_num = num;
    _workingVersion.definition_json.doc_title = docMeta.shortTitle;
    _workingVersion.definition_json.elements = generatePresetLayers(dType, pFmt, num, docMeta.shortTitle);
    _selectedElementId = (_workingVersion.definition_json.elements[0] && _workingVersion.definition_json.elements[0].id) || 'f-cli-nombre';
    _activeInternalTab = 'editor';

    var stMeta = TEN_PRESET_STYLES[num - 1] || TEN_PRESET_STYLES[0];
    showBannerToast('Cargado Estilo #' + num + ' («' + stMeta.name + '») para «' + docMeta.name + '» en ' + (pFmt === 'letter' ? 'Carta' : ('Ticket ' + pFmt)) + '. ¡100% libre de mover y editar!', false);
    renderDesignerStudioUI();
  };

  /* ═══════════════════════════════════════════════════════════════════════════
     ACCIONES DE ESCALA (%), CAPAS (FRENTE/SUBIR/BAJAR/FONDO), UNDO/REDO Y EDICIÓN
     ═══════════════════════════════════════════════════════════════════════════ */
  global.ptdTriggerFreeImageUpload = function () {
    _uploadTargetMode = 'FREE_IMAGE';
    var inp = document.getElementById('ptd-free-img-inp');
    if (inp) { inp.value = ''; inp.click(); }
  };

  global.ptdTriggerPageBgUpload = function () {
    _uploadTargetMode = 'PAGE_BG';
    var inp = document.getElementById('ptd-free-img-inp');
    if (inp) { inp.value = ''; inp.click(); }
  };

  global.ptdReplaceSelectedImage = function () {
    _uploadTargetMode = 'REPLACE_IMG';
    var inp = document.getElementById('ptd-free-img-inp');
    if (inp) { inp.value = ''; inp.click(); }
  };

  global.ptdHandleUniversalUpload = function (e) {
    var inp = e && e.target ? e.target : document.getElementById('ptd-free-img-inp');
    var file = inp && inp.files && inp.files[0];
    if (file) handleUniversalFile(file, _uploadTargetMode);
  };

  global.ptdScaleSelectedByFactor = function (factorStr) {
    if (!_workingVersion || !_selectedElementId) return;
    var factor = parseFloat(factorStr || '1.1');
    var els = ensureOverlayFields(_workingVersion);
    var sel = els.filter(function (x) { return x.id === _selectedElementId; })[0];
    if (!sel || sel.locked) return;
    pushUndo();
    var cx = Number(sel.x_mm || 0) + Number(sel.w_mm || 40) / 2;
    var cy = Number(sel.y_mm || 0) + Number(sel.h_mm || 10) / 2;
    var newW = Math.max(6, Number((Number(sel.w_mm || 40) * factor).toFixed(1)));
    var newH = Math.max(3, Number((Number(sel.h_mm || 10) * factor).toFixed(1)));
    sel.w_mm = newW;
    sel.h_mm = newH;
    sel.x_mm = Math.max(0, Number((cx - newW / 2).toFixed(1)));
    sel.y_mm = Math.max(0, Number((cy - newH / 2).toFixed(1)));
    if (sel.font_size) {
      sel.font_size = Math.max(6, Math.min(48, Math.round(Number(sel.font_size) * factor)));
    }
    sel.scale_pct = Math.round(Number(sel.scale_pct || 100) * factor);
    renderDesignerStudioUI();
  };

  global.ptdSelectedLayerOrder = function (dir) {
    if (!_workingVersion || !_selectedElementId) return;
    global.ptdMoveLayerOrder(_selectedElementId, dir);
  };

  global.ptdMoveLayerOrder = function (elId, dir) {
    if (!_workingVersion || !elId) return;
    var els = ensureOverlayFields(_workingVersion);
    var target = els.filter(function (x) { return x.id === elId; })[0];
    if (!target) return;
    pushUndo();
    var maxZ = els.reduce(function (m, e) { return Math.max(m, Number(e.z_index || 1)); }, 1);
    var minZ = els.reduce(function (m, e) { return Math.min(m, Number(e.z_index || 1)); }, 10);
    if (dir === 'front') target.z_index = maxZ + 1;
    else if (dir === 'back') target.z_index = Math.max(0, minZ - 1);
    else if (dir === 'up') target.z_index = Number(target.z_index || 1) + 1;
    else if (dir === 'down') target.z_index = Math.max(0, Number(target.z_index || 1) - 1);
    _selectedElementId = elId;
    renderDesignerStudioUI();
  };

  global.ptdSelectLayerById = function (elId) {
    _selectedElementId = elId;
    renderDesignerStudioUI();
  };

  global.ptdToggleLayerHidden = function (elId) {
    if (!_workingVersion) return;
    var els = ensureOverlayFields(_workingVersion);
    var target = els.filter(function (x) { return x.id === elId; })[0];
    if (!target) return;
    pushUndo();
    target.hidden = !target.hidden;
    renderDesignerStudioUI();
  };

  global.ptdToggleLayerLock = function (elId) {
    if (!_workingVersion) return;
    var els = ensureOverlayFields(_workingVersion);
    var target = els.filter(function (x) { return x.id === elId; })[0];
    if (!target) return;
    target.locked = !target.locked;
    renderDesignerStudioUI();
  };

  global.ptdDuplicateSelectedElement = function () {
    if (!_workingVersion || !_selectedElementId) return;
    var els = ensureOverlayFields(_workingVersion);
    var sel = els.filter(function (x) { return x.id === _selectedElementId; })[0];
    if (!sel) return;
    pushUndo();
    var clone = JSON.parse(JSON.stringify(sel));
    clone.id = 'dup-' + Date.now();
    clone.label = (sel.label || 'CAPA') + ' (COPIA)';
    clone.x_mm = Number((Number(sel.x_mm || 10) + 4).toFixed(1));
    clone.y_mm = Number((Number(sel.y_mm || 10) + 4).toFixed(1));
    clone.z_index = Number(sel.z_index || 3) + 1;
    els.push(clone);
    _selectedElementId = clone.id;
    renderDesignerStudioUI();
  };

  global.ptdResetMagdalenoLayers = function () {
    if (!_workingVersion) return;
    pushUndo();
    _workingVersion.definition_json.elements = createFullEditableLayersForDoc((_activeBackendTpl && _activeBackendTpl.name) || 'COTIZACIÓN');
    _selectedElementId = 'f-cli-nombre';
    showBannerToast('Todas las capas de la Plantilla #' + _activePresetNumber + ' fueron restauradas.', false);
    renderDesignerStudioUI();
  };

  global.ptdUndo = function () {
    if (!_undoStack.length || !_workingVersion) return;
    _redoStack.push(JSON.stringify(_workingVersion.definition_json.elements || []));
    _workingVersion.definition_json.elements = JSON.parse(_undoStack.pop());
    renderDesignerStudioUI();
  };

  global.ptdRedo = function () {
    if (!_redoStack.length || !_workingVersion) return;
    _undoStack.push(JSON.stringify(_workingVersion.definition_json.elements || []));
    _workingVersion.definition_json.elements = JSON.parse(_redoStack.pop());
    renderDesignerStudioUI();
  };

  global.ptdUpdateSelectedOpacity = function () {
    var inp = document.activeElement;
    if (!inp || !_workingVersion || !_selectedElementId) return;
    var els = ensureOverlayFields(_workingVersion);
    var sel = els.filter(function (x) { return x.id === _selectedElementId; })[0];
    if (!sel) return;
    sel.opacity = Number((parseFloat(inp.value || '100') / 100).toFixed(2));
    _isDirty = true;
    var box = document.querySelector('#ptd-paper-sheet [data-el-id="' + _selectedElementId + '"]');
    if (box) box.style.opacity = String(sel.opacity);
  };

  global.ptdUpdateSelectedTextContent = function () {
    var inp = document.activeElement;
    if (!inp || !_workingVersion || !_selectedElementId) return;
    var els = ensureOverlayFields(_workingVersion);
    var sel = els.filter(function (x) { return x.id === _selectedElementId; })[0];
    if (!sel) return;
    sel.text = inp.value;
    _isDirty = true;
    var box = document.querySelector('#ptd-paper-sheet [data-el-id="' + _selectedElementId + '"] > div');
    if (box) {
      box.innerHTML = String(sel.text || '').split('\n').map(function (ln) { return esc(ln); }).join('<br>');
    }
  };

  global.ptdSwitchInternalTab = function (tabName) {
    _activeInternalTab = tabName || 'editor';
    if (tabName === 'asignacion') {
      global.ptdSwitchSubTab('asignacion');
      var rCard = document.getElementById('card-print-rules');
      if (rCard) rCard.scrollIntoView({ behavior: 'smooth', block: 'start' });
    } else if (tabName === 'versiones') {
      global.ptdSwitchSubTab('historial');
      var hCard = document.getElementById('card-print-history');
      if (hCard) hCard.scrollIntoView({ behavior: 'smooth', block: 'start' });
    } else {
      global.ptdSwitchSubTab('todo');
      renderDesignerStudioUI();
    }
  };

  global.ptdSetLeftSegment = function (seg) {
    _leftSegment = (seg === 'elementos' || seg === 'capas') ? seg : 'campos';
    renderDesignerStudioUI();
  };

  global.ptdToggleSourceAcc = function (accId) {
    _openAccGroup = (_openAccGroup === accId) ? '' : accId;
    renderDesignerStudioUI();
  };

  global.ptdCycleTableTaxMode = function () {
    if (!_workingVersion) return;
    pushUndo();
    var els = ensureOverlayFields(_workingVersion);
    var tbl = els.filter(function (x) { return x.type === 'table_products'; })[0];
    if (!tbl) return;
    var cur = String(tbl.tax_display_mode || 'CON_IVA').toUpperCase();
    var nextMode = cur === 'CON_IVA' ? 'SIN_IVA' : (cur === 'SIN_IVA' ? 'DESGLOSADO' : 'CON_IVA');
    tbl.tax_display_mode = nextMode;
    _selectedElementId = tbl.id;
    var modeTxt = nextMode === 'SIN_IVA'
      ? 'Total del artículo SIN IVA (P.U. SIN IVA | Total Art. SIN IVA)'
      : (nextMode === 'DESGLOSADO' ? 'DESGLOSADO (Total Art. SIN IVA + IVA 16% + Total Art. CON IVA)' : 'Total del artículo CON IVA incluido (P.U. CON IVA | Total Art. CON IVA)');
    showBannerToast('Tabla configurada en: ' + modeTxt, false);
    renderDesignerStudioUI();
  };

  global.ptdSetTableTaxModeSelect = function (e) {
    if (!_workingVersion) return;
    var val = (e && e.target && e.target.value) ? e.target.value : 'CON_IVA';
    pushUndo();
    var els = ensureOverlayFields(_workingVersion);
    els.forEach(function (x) {
      if (x.type === 'table_products') {
        x.tax_display_mode = val;
        _selectedElementId = x.id;
      }
    });
    showBannerToast('Modo de IVA de los artículos actualizado a: ' + val, false);
    renderDesignerStudioUI();
  };

  global.ptdInsertQrSealLayer = function () {
    if (!_workingVersion) return;
    pushUndo();
    var els = ensureOverlayFields(_workingVersion);
    var maxZ = els.reduce(function (m, e) { return Math.max(m, Number(e.z_index || 1)); }, 1);
    var isTicket = (_workingVersion.mode === 'TICKET');
    var newId = 'qr-seal-' + Date.now();
    els.push({
      id: newId,
      type: 'image',
      label: 'SELLO QR FISCAL (POR SEPARADO)',
      src: SAMPLE_QR_SVG,
      field_key: 'cfdi.qr_sat',
      x_mm: isTicket ? 14.0 : 18.0,
      y_mm: isTicket ? 155.0 : 152.0,
      w_mm: isTicket ? 22.0 : 26.0,
      h_mm: isTicket ? 22.0 : 26.0,
      scale_pct: 100,
      opacity: 1.0,
      page: _activePageNum,
      z_index: maxZ + 1
    });
    _selectedElementId = newId;
    showBannerToast('Sello QR Fiscal insertado como capa independiente. Puedes moverlo y escalarlo por separado.', false);
    renderDesignerStudioUI();
  };

  global.ptdInsertFieldFromSource = function (fieldKey, fieldName, tokenStr) {
    if (!_workingVersion) return;
    if (fieldKey === 'cfdi.qr_sat') {
      global.ptdInsertQrSealLayer();
      return;
    }
    pushUndo();
    var els = ensureOverlayFields(_workingVersion);
    var maxZ = els.reduce(function (m, e) { return Math.max(m, Number(e.z_index || 1)); }, 1);
    var isTicket = (_workingVersion.mode === 'TICKET');
    var newId = 'f-' + Date.now();
    els.push({
      id: newId,
      type: 'field',
      label: String(fieldName || fieldKey).toUpperCase(),
      field_key: fieldKey,
      text: tokenStr || ('{{' + fieldKey + '}}'),
      x_mm: isTicket ? 4.0 : 35.0,
      y_mm: isTicket ? 62.0 : 88.0,
      w_mm: isTicket ? 48.0 : 86.0,
      h_mm: 7.5,
      font_family: (String(fieldKey).indexOf('cfdi.') === 0) ? 'Courier New' : 'Arial',
      font_size: isTicket ? 9.5 : 11,
      bold: true,
      align: 'left',
      color: '#000000',
      show_box: true,
      wrap: true,
      page: _activePageNum,
      z_index: maxZ + 1
    });
    _selectedElementId = newId;
    showBannerToast('Campo «' + (fieldName || fieldKey) + '» insertado como capa independiente.', false);
    renderDesignerStudioUI();
  };

  global.ptdUpdateSelectedLabel = function () {
    var inp = document.activeElement;
    if (!inp || !_workingVersion || !_selectedElementId) return;
    var els = ensureOverlayFields(_workingVersion);
    var sel = els.filter(function (x) { return x.id === _selectedElementId; })[0];
    if (!sel) return;
    sel.label = String(inp.value || '').toUpperCase();
    _isDirty = true;
  };

  global.ptdUpdateSelectedBinding = function (e) {
    var selNode = e && e.target ? e.target : null;
    if (!selNode || !_workingVersion || !_selectedElementId) return;
    var key = selNode.value;
    var meta = BINDING_OPTIONS.filter(function (b) { return b.key === key; })[0];
    var els = ensureOverlayFields(_workingVersion);
    var sel = els.filter(function (x) { return x.id === _selectedElementId; })[0];
    if (!sel) return;
    pushUndo();
    sel.field_key = key;
    if (key) {
      sel.text = meta && meta.token ? meta.token : ('{{' + key + '}}');
      if (meta) sel.label = meta.defaultName.toUpperCase();
    }
    renderDesignerStudioUI();
  };

  global.ptdUpdateSelectedCoord = function () {
    var inp = document.activeElement;
    if (!inp || !_workingVersion || !_selectedElementId) return;
    var prop = inp.getAttribute('data-click-arg');
    var els = ensureOverlayFields(_workingVersion);
    var sel = els.filter(function (x) { return x.id === _selectedElementId; })[0];
    if (!sel || !prop) return;
    sel[prop] = Number(parseFloat(inp.value || '0').toFixed(1));
    _isDirty = true;
    var box = document.querySelector('#ptd-paper-sheet [data-el-id="' + _selectedElementId + '"]');
    if (box) {
      if (prop === 'x_mm') box.style.left = mmToPx(sel.x_mm) + 'px';
      if (prop === 'y_mm') box.style.top = mmToPx(sel.y_mm) + 'px';
      if (prop === 'w_mm') box.style.width = mmToPx(sel.w_mm) + 'px';
      if (prop === 'h_mm') box.style.height = mmToPx(sel.h_mm) + 'px';
      if (prop === 'font_size') box.style.fontSize = Math.max(7, Math.round(Number(sel.font_size || 11) * _zoom)) + 'px';
    }
  };

  global.ptdUpdateSelectedFontFamily = function (e) {
    var v = e && e.target ? e.target.value : 'Arial';
    var els = ensureOverlayFields(_workingVersion);
    var sel = els.filter(function (x) { return x.id === _selectedElementId; })[0];
    if (!sel) return;
    sel.font_family = v;
    _isDirty = true;
    renderDesignerStudioUI();
  };

  global.ptdToggleTextStyle = function (prop) {
    var els = ensureOverlayFields(_workingVersion);
    var sel = els.filter(function (x) { return x.id === _selectedElementId; })[0];
    if (!sel || !prop) return;
    sel[prop] = !sel[prop];
    _isDirty = true;
    renderDesignerStudioUI();
  };

  global.ptdSetTextAlign = function (alignVal) {
    var els = ensureOverlayFields(_workingVersion);
    var sel = els.filter(function (x) { return x.id === _selectedElementId; })[0];
    if (!sel) return;
    sel.align = alignVal || 'left';
    _isDirty = true;
    renderDesignerStudioUI();
  };

  global.ptdUpdateSelectedColor = function (e) {
    var inp = (e && e.target) || document.activeElement;
    if (!inp) return;
    var col = inp.value || '#000000';
    var els = ensureOverlayFields(_workingVersion);
    var sel = els.filter(function (x) { return x.id === _selectedElementId; })[0];
    if (!sel) return;
    if (sel.type === 'rect') sel.background_color = col;
    else if (String(sel.type).indexOf('table_') === 0) sel.header_bg = col;
    else sel.color = col;
    _isDirty = true;
    renderDesignerStudioUI();
  };

  global.ptdToggleWrapSelected = function () {
    var els = ensureOverlayFields(_workingVersion);
    var sel = els.filter(function (x) { return x.id === _selectedElementId; })[0];
    if (!sel) return;
    sel.wrap = (sel.wrap === false);
    _isDirty = true;
    renderDesignerStudioUI();
  };

  global.ptdTogglePrintBackgroundSwitch = function () {
    if (!_workingVersion) return;
    if (!_workingVersion.background_settings_json) _workingVersion.background_settings_json = {};
    var cur = _workingVersion.background_settings_json.print_mode;
    _workingVersion.background_settings_json.print_mode = (cur === 'fields_only') ? 'background_and_fields' : 'fields_only';
    _isDirty = true;
    renderDesignerStudioUI();
  };

  global.ptdUpdateBgPrintModeSelect = function (e) {
    if (!_workingVersion) return;
    if (!_workingVersion.background_settings_json) _workingVersion.background_settings_json = {};
    _workingVersion.background_settings_json.print_mode = e && e.target ? e.target.value : 'background_and_fields';
    _isDirty = true;
    renderDesignerStudioUI();
  };

  global.ptdStepZoom = function (deltaStr) {
    var d = parseFloat(deltaStr || '0.1');
    _zoom = Math.max(0.55, Math.min(1.45, Number((_zoom + d).toFixed(2))));
    renderDesignerStudioUI();
  };

  global.ptdQuickSwitchThermalFormat = function (widthChoice) {
    if (!_workingVersion) return;
    pushUndo();
    var dType = (_activeBackendTpl && _activeBackendTpl.doc_type) || _galleryDocType || 'cotizacion';
    var pFmt = 'letter';
    if (widthChoice === 'letter') {
      _workingVersion.mode = 'CARTA';
      _workingVersion.paper_size = 'letter';
      _workingVersion.paper_width_mm = 215.9;
      _workingVersion.paper_height_mm = 279.4;
      _zoom = 0.85;
      pFmt = 'letter';
    } else if (widthChoice === '58mm') {
      _workingVersion.mode = 'TICKET';
      _workingVersion.paper_size = '58mm';
      _workingVersion.paper_width_mm = 58.0;
      _workingVersion.paper_height_mm = 195.0;
      _zoom = 1.15;
      pFmt = '58mm';
    } else {
      _workingVersion.mode = 'TICKET';
      _workingVersion.paper_size = '80mm';
      _workingVersion.paper_width_mm = 80.0;
      _workingVersion.paper_height_mm = 210.0;
      _zoom = 1.05;
      pFmt = '80mm';
    }
    _galleryPaperFormat = pFmt;
    // Regenerar las capas 100% movibles del estilo activo (#1..#20) adaptadas al ancho exacto (Carta / 80mm / 58mm)
    _workingVersion.definition_json.elements = generatePresetLayers(dType, pFmt, _activePresetNumber || 1, _activeBackendTpl && _activeBackendTpl.name);
    _selectedElementId = (_workingVersion.definition_json.elements[0] && _workingVersion.definition_json.elements[0].id) || 'f-cli-nombre';
    showBannerToast('Formato cambiado a ' + (pFmt === 'letter' ? 'Carta (215.9×279.4 mm)' : ('Ticket ' + pFmt)) + ' con el Estilo #' + _activePresetNumber + ' — todas sus capas son libres de mover y escalar.', false);
    renderDesignerStudioUI();
  };

  global.ptdSwitchThermalDropdown = function (e) {
    var val = e && e.target ? e.target.value : '80mm';
    global.ptdQuickSwitchThermalFormat(val);
  };

  global.ptdRemoveBgAsset = function () {
    if (!_workingVersion) return;
    pushUndo();
    _workingVersion.background_asset_id = null;
    if (_activeBackendTpl) _activeBackendTpl.background_asset = null;
    renderDesignerStudioUI();
  };

  global.ptdDeleteSelectedElement = function () {
    if (!_workingVersion || !_selectedElementId) return;
    pushUndo();
    var els = ensureOverlayFields(_workingVersion);
    _workingVersion.definition_json.elements = els.filter(function (x) { return x.id !== _selectedElementId; });
    _selectedElementId = _workingVersion.definition_json.elements[0] ? _workingVersion.definition_json.elements[0].id : null;
    renderDesignerStudioUI();
  };

  global.ptdAddElement = function (elType) {
    if (!_workingVersion) return;
    pushUndo();
    var els = ensureOverlayFields(_workingVersion);
    var maxZ = els.reduce(function (m, e) { return Math.max(m, Number(e.z_index || 1)); }, 1);
    var isTicket = (_workingVersion.mode === 'TICKET');
    var newId = 'el-' + Date.now();
    if (elType === 'rect') {
      els.push({
        id: newId,
        type: 'rect',
        label: 'RECTÁNGULO / CINTA DE COLOR',
        x_mm: isTicket ? 4.0 : 25.0,
        y_mm: isTicket ? 50.0 : 78.0,
        w_mm: isTicket ? 48.0 : 95.0,
        h_mm: 12.0,
        background_color: '#dbeafe',
        border_color: '#2563eb',
        opacity: 0.85,
        page: _activePageNum,
        z_index: maxZ + 1
      });
    } else if (elType === 'table_products' || elType === 'table_corte_ciego' || elType === 'table_corte_x' || elType === 'table_corte_z') {
      var tblLabels = {
        table_products: 'TABLA DE PRODUCTOS ADICIONAL',
        table_corte_ciego: 'TABLA ARQUEO CIEGO (BILLETES, MONEDAS Y VOUCHERS)',
        table_corte_x: 'TABLA CORTE X (FLUJO DE EFECTIVO EN GAVETA)',
        table_corte_z: 'TABLA CORTE Z (CONCILIACIÓN ESPERADO VS DECLARADO)'
      };
      var tblColors = {
        table_products: '#1e3a8a',
        table_corte_ciego: '#4f46e5',
        table_corte_x: '#0891b2',
        table_corte_z: '#065f46'
      };
      els.push({
        id: newId,
        type: elType,
        label: tblLabels[elType] || 'TABLA OPERATIVA',
        x_mm: isTicket ? 4.0 : 14.0,
        y_mm: isTicket ? 66.0 : 90.0,
        w_mm: isTicket ? (Number(_workingVersion.paper_width_mm || 80) < 70 ? 52.0 : 72.0) : 187.0,
        h_mm: isTicket ? 52.0 : 65.0,
        header_bg: tblColors[elType] || '#1e3a8a',
        page: _activePageNum,
        z_index: maxZ + 1
      });
    } else {
      els.push({
        id: newId,
        type: elType,
        label: elType === 'signature' ? 'FIRMA DE CONFORMIDAD' : 'TEXTO LIBRE ENCIMABLE',
        field_key: '',
        text: elType === 'combined' ? 'Recibimos de {{cliente.nombre}} la cantidad de {{totales.total}}' : (elType === 'signature' ? 'Atentamente\nFirma Autorizada' : 'TEXTO LIBRE EDITABLE (DOBLE CLIC)'),
        x_mm: isTicket ? 4.0 : 35.0,
        y_mm: isTicket ? 55.0 : 75.0,
        w_mm: isTicket ? 48.0 : 90.0,
        h_mm: 10.0,
        font_family: 'Arial',
        font_size: isTicket ? 9.5 : 12,
        bold: true,
        align: 'left',
        color: '#0f172a',
        page: _activePageNum,
        z_index: maxZ + 1
      });
    }
    _selectedElementId = newId;
    renderDesignerStudioUI();
  };

  global.ptdSwitchBackendTemplate = function (e) {
    var tid = e && e.target ? e.target.value : '';
    if (tid) loadBackendStudioData(tid);
  };

  global.ptdOpenDesignerWith = function (mode, shortDocId) {
    global.ptdSwitchSubTab('disenador');
    var mapDoc = {
      venta: 'ticket_venta_contado',
      ticket_venta_contado: 'ticket_venta_contado',
      orden_entrega: 'orden_entrega',
      cotizacion: 'cotizacion',
      credito: 'ticket_venta_credito',
      ticket_venta_credito: 'ticket_venta_credito',
      comprobante_pago: 'comprobante_pago',
      factura: 'cfdi_factura_ticket',
      cfdi_factura_ticket: 'cfdi_factura_ticket',
      devolucion: 'devolucion',
      cancelacion: 'comprobante_cancelacion',
      remision: 'remision',
      orden_compra: 'orden_compra',
      corte_ciego: 'corte_ciego',
      corte_x: 'corte_x',
      corte_z: 'corte_z',
      cierre: 'corte_z',
      apertura_caja: 'apertura_caja',
      estado_cuenta_cliente: 'estado_cuenta_cliente',
      estado_cuenta: 'estado_cuenta_cliente',
      documento_formal: 'documento_formal'
    };
    var bType = mapDoc[shortDocId] || shortDocId || 'cotizacion';
    var targetModeUpper = (String(mode || '').toLowerCase() === 'carta') ? 'CARTA' : 'TICKET';
    var targetPaperFmt = (targetModeUpper === 'CARTA') ? 'letter' : '80mm';

    _galleryDocType = bType;
    _galleryPaperFormat = targetPaperFmt;
    _activeInternalTab = 'editor';

    var match = _backendTemplates.filter(function (t) {
      return t.doc_type === bType && String(t.mode || '').toUpperCase() === targetModeUpper;
    })[0] || _backendTemplates.filter(function (t) { return t.doc_type === bType; })[0];

    var scrollStudio = function () {
      var card = document.getElementById('card-print-designer');
      if (card) card.scrollIntoView({ behavior: 'smooth', block: 'start' });
    };

    if (match) {
      loadBackendStudioData(match.id).then(function () {
        if (_workingVersion && String(_workingVersion.mode || '').toUpperCase() !== targetModeUpper) {
          global.ptdQuickSwitchThermalFormat(targetPaperFmt);
        }
        scrollStudio();
      });
    } else if (_workingVersion) {
      global.ptdLoadPresetIntoCanvas(String(_activePresetNumber || 1), bType, targetPaperFmt);
      scrollStudio();
    }
  };

  global.ptdCreateNewTemplatePrompt = function () {
    var name = (prompt('NOMBRE DE LA NUEVA PLANTILLA (EN MAYÚSCULAS):', 'PLANTILLA PERSONALIZADA #' + _activePresetNumber) || '').trim().toUpperCase();
    if (!name) return;
    var isTicket = (_workingVersion && _workingVersion.mode === 'TICKET');
    var pSize = isTicket ? (_workingVersion.paper_size || '80mm') : 'letter';
    apiCall('/api/print-formats/templates', {
      method: 'POST',
      body: JSON.stringify({
        name: name,
        doc_type: (_activeBackendTpl && _activeBackendTpl.doc_type) || _galleryDocType || 'cotizacion',
        mode: isTicket ? 'TICKET' : 'CARTA',
        paper_size: pSize
      })
    }).then(function (created) {
      showBannerToast('Plantilla «' + created.name + '» creada en borrador.', false);
      loadBackendStudioData(created.id);
    }).catch(function (err) {
      showBannerToast(err.message, true);
    });
  };

  global.ptdSaveBackendDraft = function () {
    if (!_activeBackendTpl || !_workingVersion) return Promise.resolve();
    return apiCall('/api/print-formats/templates/' + encodeURIComponent(_activeBackendTpl.id) + '/draft', {
      method: 'PUT',
      body: JSON.stringify({
        name: _activeBackendTpl.name,
        paper_size: _workingVersion.paper_size,
        orientation: _workingVersion.orientation,
        paper_width_mm: _workingVersion.paper_width_mm,
        paper_height_mm: _workingVersion.paper_height_mm,
        printable_width_mm: _workingVersion.printable_width_mm,
        background_asset_id: _workingVersion.background_asset_id,
        background_settings_json: _workingVersion.background_settings_json,
        definition_json: _workingVersion.definition_json,
        changelog: 'Guardado con Plantilla #' + _activePresetNumber + ' desde el Editor Visual 100% Editable por Capas.'
      })
    }).then(function (saved) {
      _isDirty = false;
      showBannerToast('Borrador v' + (saved.working_version ? saved.working_version.version_num : saved.current_version_num) + ' guardado con todas sus capas, imágenes y escalas.', false);
      return loadBackendStudioData(saved.id);
    }).catch(function (err) {
      showBannerToast(err.message, true);
    });
  };

  global.ptdPublishActiveTemplate = function () {
    if (!_activeBackendTpl) return;
    global.ptdSaveBackendDraft().then(function () {
      return apiCall('/api/print-formats/templates/' + encodeURIComponent(_activeBackendTpl.id) + '/publish', {
        method: 'POST',
        body: JSON.stringify({ changelog: 'Publicación oficial desde el Diseñador de Formatos.' })
      });
    }).then(function (pub) {
      showBannerToast('¡Formato «' + pub.name + '» (v' + pub.current_version_num + ') PUBLICADO con éxito!', false);
      loadBackendStudioData(pub.id);
    }).catch(function (err) {
      showBannerToast(err.message, true);
    });
  };

  global.ptdDownloadBackendPdf = function (includeBgStr) {
    if (!_activeBackendTpl || !_workingVersion) return;
    var incBg = (includeBgStr !== 'false' && includeBgStr !== false);
    var tok = localStorage.getItem('calebsys_token') || sessionStorage.getItem('calebsys_token') || '';
    global.ptdSaveBackendDraft().then(function () {
      return fetch('/api/print-formats/pdf', {
        method: 'POST',
        headers: Object.assign({ 'Content-Type': 'application/json' }, tok ? { 'Authorization': 'Bearer ' + tok } : {}),
        body: JSON.stringify({
          template_id: _activeBackendTpl.id,
          version_id: _workingVersion.id,
          include_background: incBg
        })
      });
    }).then(function (r) {
      if (!r.ok) throw new Error('Error al generar vista previa PDF');
      return r.blob();
    }).then(function (blob) {
      var url = URL.createObjectURL(blob);
      window.open(url, '_blank');
    }).catch(function (err) {
      showBannerToast(err.message, true);
    });
  };

  global.ptdSwitchSubTab = function (subTab) {
    var cardEq = document.getElementById('card-impresoras');
    var cardDes = document.getElementById('card-print-designer');
    var cardRules = document.getElementById('card-print-rules');
    var cardHist = document.getElementById('card-print-history');
    document.querySelectorAll('#prt-subnav .cfg-subbtn').forEach(function (b) {
      b.classList.toggle('active', b.getAttribute('data-prt-sub') === subTab);
    });
    if (cardEq) cardEq.style.display = (subTab === 'todo' || subTab === 'equipos') ? '' : 'none';
    if (cardDes) cardDes.style.display = (subTab === 'todo' || subTab === 'disenador') ? '' : 'none';
    if (cardRules) cardRules.style.display = (subTab === 'todo' || subTab === 'asignacion') ? '' : 'none';
    if (cardHist) cardHist.style.display = (subTab === 'todo' || subTab === 'historial') ? '' : 'none';
  };

  global.ptdToggleFullscreen = function () {
    var card = document.getElementById('card-print-designer');
    if (card) card.classList.toggle('ptd-fullscreen');
  };

  /* ═══════════════════════════════════════════════════════════════════════════
     SECCIÓN 3: ASIGNACIÓN Y REGLAS + SECCIÓN 4: HISTORIAL DE VERSIONES
     ═══════════════════════════════════════════════════════════════════════════ */
  function renderAssignmentsRulesSection() {
    var root = document.getElementById('prt-rules-section-root');
    if (!root) return;
    var publishedTpls = _backendTemplates.filter(function (t) { return t.status === 'PUBLISHED' || t.active_published_version_id; });
    var tplOpts = publishedTpls.map(function (t) {
      return '<option value="' + esc(t.id) + '">' + esc(t.name) + ' (' + esc(t.mode) + ' · v' + esc(t.current_version_num) + ')</option>';
    }).join('');
    var docOpts = ((_backendCatalog && _backendCatalog.doc_types) || []).map(function (d) {
      return '<option value="' + esc(d.doc_type) + '">' + esc(d.name) + '</option>';
    }).join('');
    var rowsHtml = _assignmentsList.length ? _assignmentsList.map(function (a) {
      var scopeBadge = a.terminal_id ? ('1° TERMINAL: ' + esc(a.terminal_id)) : a.sucursal_id ? ('2° SUCURSAL: ' + esc(a.sucursal_id)) : '3° EMPRESA GLOBAL';
      return '<tr>' +
        '<td><b>' + esc(a.doc_type_name || a.doc_type) + '</b></td>' +
        '<td><span class="cfg-chip">' + esc(a.role_target || 'CLIENTE') + '</span></td>' +
        '<td><b>' + esc(a.template_name) + '</b> (v' + esc(a.version_num) + ')</td>' +
        '<td>' + esc(scopeBadge) + '</td>' +
        '<td>' + (a.print_background ? 'Fondo + Campos' : 'Solo Campos · Papel preimpreso') + '</td>' +
        '<td><button type="button" class="btn btn-secondary btn-sm" data-click="ptdDeleteAssignmentRule" data-click-arg="' + esc(a.id) + '"><i class="fa-solid fa-trash"></i></button></td>' +
      '</tr>';
    }).join('') : '<tr><td colspan="6" style="text-align:center;color:var(--text-muted);padding:12px;">Sin reglas personalizadas; se aplica el formato predeterminado compatible.</td></tr>';

    root.innerHTML =
      '<div class="grid-2" style="grid-template-columns:repeat(3,1fr);gap:10px;margin-bottom:12px;">' +
        '<div class="form-group"><label class="form-label">Documento</label><select id="ptd-asig-doctype" class="form-control">' + docOpts + '</select></div>' +
        '<div class="form-group"><label class="form-label">Plantilla publicada</label><select id="ptd-asig-tpl" class="form-control">' + tplOpts + '</select></div>' +
        '<div class="form-group"><label class="form-label">Destino</label><select id="ptd-asig-target" class="form-control"><option value="CLIENTE">CLIENTE (Caja)</option><option value="ALMACEN">ALMACÉN (Orden Entrega)</option><option value="PDF_FORMAL">CARTA / PDF</option></select></div>' +
        '<div class="form-group"><label class="form-label">Sucursal (Vacío = Global)</label><input id="ptd-asig-sucursal" class="form-control" style="text-transform:uppercase;" placeholder="MATRIZ" data-input="toUpperCase"></div>' +
        '<div class="form-group"><label class="form-label">Terminal (Vacío = Todas)</label><input id="ptd-asig-terminal" class="form-control" style="text-transform:uppercase;" placeholder="CAJA-01" data-input="toUpperCase"></div>' +
        '<div class="form-group"><label class="form-label">Fondo al imprimir</label><div style="display:flex;gap:6px;"><select id="ptd-asig-bgmode" class="form-control"><option value="true">Fondo y campos</option><option value="false">Solo campos · Preimpreso</option></select><button type="button" class="btn btn-primary btn-sm" data-click="ptdCreateAssignmentRule">Asignar</button></div></div>' +
      '</div>' +
      '<table class="cfg-table"><thead><tr><th>Documento</th><th>Destino</th><th>Plantilla</th><th>Precedencia</th><th>Salida</th><th></th></tr></thead><tbody>' + rowsHtml + '</tbody></table>';
  }

  function renderVersionHistoryAndReprintsSection() {
    var root = document.getElementById('prt-history-section-root');
    if (!root) return;
    var versions = (_activeBackendTpl && _activeBackendTpl.versions) || [];
    var verRows = versions.map(function (v) {
      return '<tr>' +
        '<td><b>v' + esc(v.version_num) + '</b></td>' +
        '<td>' + esc(v.status) + '</td>' +
        '<td>' + esc(v.mode) + ' · ' + esc(v.paper_width_mm) + '×' + esc(v.paper_height_mm) + ' mm</td>' +
        '<td>' + esc(v.changelog || '—') + '</td>' +
        '<td><button type="button" class="btn btn-secondary btn-sm" data-click="ptdRestoreHistoricalVersion" data-click-arg="' + esc(v.id) + '">Restaurar en borrador</button></td>' +
      '</tr>';
    }).join('');
    root.innerHTML =
      '<table class="cfg-table"><thead><tr><th>Versión</th><th>Estado</th><th>Dimensiones</th><th>Detalle</th><th>Acción</th></tr></thead><tbody>' + verRows + '</tbody></table>';
  }

  global.ptdCreateAssignmentRule = function () {
    var docType = (document.getElementById('ptd-asig-doctype') || {}).value;
    var tplId = (document.getElementById('ptd-asig-tpl') || {}).value;
    var target = (document.getElementById('ptd-asig-target') || {}).value || 'CLIENTE';
    var suc = ((document.getElementById('ptd-asig-sucursal') || {}).value || '').trim().toUpperCase();
    var term = ((document.getElementById('ptd-asig-terminal') || {}).value || '').trim().toUpperCase();
    var bgMode = ((document.getElementById('ptd-asig-bgmode') || {}).value !== 'false');
    apiCall('/api/print-formats/assignments', {
      method: 'POST',
      body: JSON.stringify({ doc_type: docType, template_id: tplId, role_target: target, sucursal_id: suc || null, terminal_id: term || null, print_background: bgMode, copies: 1 })
    }).then(function () {
      showBannerToast('Regla de asignación guardada.', false);
      loadBackendStudioData(_activeBackendTpl && _activeBackendTpl.id);
    }).catch(function (err) {
      showBannerToast(err.message, true);
    });
  };

  global.ptdDeleteAssignmentRule = function (asigId) {
    apiCall('/api/print-formats/assignments/' + encodeURIComponent(asigId), { method: 'DELETE' }).then(function () {
      loadBackendStudioData(_activeBackendTpl && _activeBackendTpl.id);
    });
  };

  global.ptdRestoreHistoricalVersion = function (verId) {
    if (!_activeBackendTpl || !verId) return;
    apiCall('/api/print-formats/templates/' + encodeURIComponent(_activeBackendTpl.id) + '/versions/' + encodeURIComponent(verId) + '/restore', { method: 'POST' }).then(function (r) {
      showBannerToast('Versión restaurada en un nuevo borrador v' + r.current_version_num + '.', false);
      loadBackendStudioData(r.id);
    });
  };

  document.addEventListener('keydown', function (e) {
    var tag = (document.activeElement && document.activeElement.tagName) || '';
    if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;
    var sec = document.querySelector('section[data-cfg-sec="impresoras"]');
    if (!sec || !sec.classList.contains('on') || !_workingVersion) return;

    if (e.ctrlKey && e.key.toLowerCase() === 'z') {
      e.preventDefault();
      global.ptdUndo();
      return;
    }
    if (e.ctrlKey && e.key.toLowerCase() === 'y') {
      e.preventDefault();
      global.ptdRedo();
      return;
    }
    if (e.key === 'Delete' && _selectedElementId) {
      e.preventDefault();
      global.ptdDeleteSelectedElement();
      return;
    }
    if (['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight'].indexOf(e.key) >= 0 && _selectedElementId) {
      var els = ensureOverlayFields(_workingVersion);
      var sel = els.filter(function (x) { return x.id === _selectedElementId; })[0];
      if (!sel || sel.locked) return;
      e.preventDefault();
      var step = e.shiftKey ? 2.0 : 0.5;
      if (e.key === 'ArrowLeft') sel.x_mm = Math.max(0, Number((Number(sel.x_mm || 0) - step).toFixed(1)));
      if (e.key === 'ArrowRight') sel.x_mm = Number((Number(sel.x_mm || 0) + step).toFixed(1));
      if (e.key === 'ArrowUp') sel.y_mm = Math.max(0, Number((Number(sel.y_mm || 0) - step).toFixed(1)));
      if (e.key === 'ArrowDown') sel.y_mm = Number((Number(sel.y_mm || 0) + step).toFixed(1));
      _isDirty = true;
      renderDesignerStudioUI();
    }
  });

  function resolveDocTypeFromSale(sale, isQuote) {
    if (isQuote || (sale && sale.payment_method === 'COTIZACIÓN')) return 'cotizacion';
    if (!sale) return 'venta';
    if (sale.is_cfdi) return 'factura';
    if (sale.is_delivery_order || sale.is_safekept) return 'orden_entrega';
    if (sale.is_ar_payment) return 'comprobante_pago';
    if (sale.payment_method === '006') return 'credito';
    return 'venta';
  }

  global.CalebsysPrintTemplates = {
    initStudio: function () {
      loadBackendStudioData();
    },
    getStore: function () {
      try { return JSON.parse(localStorage.getItem(LS_TEMPLATES_KEY) || '{}'); } catch (e) { return {}; }
    },
    getTenPresets: function () {
      return TEN_PRESET_STYLES;
    },
    generatePresetLayers: generatePresetLayers,
    resolveDocTypeFromSale: resolveDocTypeFromSale
  };

})(window);
