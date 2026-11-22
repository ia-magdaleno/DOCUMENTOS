# DOCUMENTACIÓN TÉCNICA Y ARQUITECTÓNICA — SUBMÓDULO «DISEÑADOR DE FORMATOS» (`FORMAS`)
**Documento de Ingeniería preparado para:** Don Isael (Programador y Arquitecto Principal de CALEBSYS)  
**Repositorio GitHub:** `https://github.com/ia-magdaleno/FORMAS`  
**Sistema:** CALEBSYS ERP · POS · CRM · Facturación CFDI 4.0  
**Ubicación en el Sistema:** `Configuración → Impresoras (F9)` (`/admin#configuracion`)  
**Stack Tecnológico:** Backend FastAPI + SQLAlchemy + Pillow + `pypdfium2` (`backend/`) · Frontend Vanilla ES6+ Modular compatible con CSP (`frontend/scripts/loaders/print-templates-designer.js`, `frontend/pages/admin/configuracion.html`)

---

## Índice General para Ingeniería
1. [Resumen Ejecutivo y Alcance del Módulo `FORMAS`](#1-resumen-ejecutivo-y-alcance-del-módulo-formas)
2. [Inventario Completo de Archivos Entregados](#2-inventario-completo-de-archivos-entregados)
3. [Arquitectura de Base de Datos (5 Modelos SQLAlchemy + Migración Alembic)](#3-arquitectura-de-base-de-datos-5-modelos-sqlalchemy--migración-alembic)
4. [Todo en Ticket (`80 mm` / `58 mm`) y Tamaño Carta (`215.9 × 279.4 mm`)](#4-todo-en-ticket-80-mm--58-mm-y-tamaño-carta-2159--2794-mm)
5. [Motor Visual Multicapa Estilo Photoshop / CorelDRAW (100% Movible y Escalable)](#5-motor-visual-multicapa-estilo-photoshop--coreldraw-100-movible-y-escalable)
6. [Lógica Financiera y Operativa de Cortes de Caja (`Corte Ciego`, `Corte X` y `Corte Z`)](#6-lógica-financiera-y-operativa-de-cortes-de-caja-corte-ciego-corte-x-y-corte-z)
7. [Desglose Fiscal de IVA (Artículos y Subtotales), Sellos CFDI y Saldos de Crédito](#7-desglose-fiscal-de-iva-artículos-y-subtotales-sellos-cfdi-y-saldos-de-crédito)
8. [Catálogo de los 20 Estilos Profesionales Precargados (PROFECO / SAT / Grandes Cadenas)](#8-catálogo-de-los-20-estilos-profesionales-precargados-profeco--sat--grandes-cadenas)
9. [Contratos de API REST (`/api/print-formats/*`)](#9-contratos-de-api-rest-apiprint-formats)
10. [Conversión Física Exacta (`mm` ↔ `pt` ↔ `px`), Paginación Multipágina e Inmutabilidad](#10-conversión-física-exacta-mm--pt--px-paginación-multipágina-e-inmutabilidad)
11. [Seguridad, Multitenancy (`empresa_id`), RBAC, CSP y Regla Global de `MAYÚSCULAS`](#11-seguridad-multitenancy-empresa_id-rbac-csp-y-regla-global-de-mayúsculas)
12. [Guía de Pruebas Automatizadas (`12/12 PASSED`) y Verificación para Don Isael](#12-guía-de-pruebas-automatizadas-1212-passed-y-verificación-para-don-isael)

---

## 1. Resumen Ejecutivo y Alcance del Módulo `FORMAS`

Se diseñó e implementó de punta a punta el submódulo profesional **«Diseñador de formatos»** dentro de **`Configuración → Impresoras (F9)`**, integrado al flujo real del Punto de Venta (POS) y del Admin Shell de CALEBSYS, conservando intactas las impresoras configuradas y las reglas de negocio existentes.

### Capacidades Principales Entregadas
1. **Todo en Ticket Térmico (`80 mm` y `58 mm`) y Tamaño Carta (`215.9 × 279.4 mm`):**
   - Los **17 tipos de documentos** del sistema cuentan con plantillas precargadas y editables tanto en **Ticket (`80 mm` / `58 mm`)** como en **Tamaño Carta**, con botones de acceso directo **`🧾 Diseñar Ticket`** y **`📄 Diseñar Carta`** en el panel `🔗 ASIGNACIÓN POR TIPO DE DOCUMENTO Y ACCESO RÁPIDO A DISEÑO`.
2. **Lienzo Multicapa 100% Libre (Estilo Photoshop / CorelDRAW / Paint):**
   - Cada elemento del documento (logotipo, imágenes subidas por el usuario, textos, campos dinámicos `{{grupo.campo}}`, tablas de productos, tablas de cortes de caja, cuadros de totales, líneas, rectángulos, sello QR, serie del sello y firmas) es una **capa independiente** con coordenadas físicas en milímetros (`x_mm, y_mm, w_mm, h_mm`).
   - Soporta arrastre libre con puntero, **8 nodos de redimensionamiento** (`tl, tm, tr, mr, br, bm, bl, ml`), **escala proporcional** (`−10% / +10%`), **orden de capas (`z_index`)** (`⏫ Frente`, `▲ Subir`, `▼ Bajar`, `⏬ Fondo`), opacidad (`10%–100%`), bloqueo/ocultamiento de capas y historial `Deshacer / Rehacer (Undo/Redo)`.
   - Permite subir **imágenes libres (`PNG, JPG, SVG`)** para colocarlas en cualquier posición o capa, así como subir un **PDF o imagen membretada como fondo de hoja** con selector **`Fondo y campos · Hoja blanca`** vs. **`Solo campos · Papel preimpreso`**.
3. **Cortes de Caja con Lógica Completa del Sistema (`Corte Ciego`, `Corte X`, `Corte Z / Cierre` y `Apertura de Caja`):**
   - **`Corte Ciego` (`corte_ciego` / `table_corte_ciego`):** Conteo físico de efectivo por denominaciones (billetes de `$1,000` a `$20` y monedas) y vouchers **ocultando los saldos esperados del sistema** hasta cerrar el sobre de tómbola.
   - **`Corte X` (`corte_x` / `table_corte_x`):** Supervisión parcial en turno abierto (**no reinicia acumuladores Z**), calculando el flujo de efectivo en gaveta: `(+) Fondo Inicial + Ventas Efectivo + Abonos CxC + Entradas - Retiros/Fajillas - Gastos - Devoluciones = Efectivo Esperado`.
   - **`Corte Z` (`corte_z` / `table_corte_z`):** Cierre definitivo de turno/día con **tabla comparativa de conciliación (`Esperado Sistema vs. Declarado Cajero vs. Diferencia Sobrante/Faltante`)**, dictamen de cuadre (`CUADRADO EXACTO / SOBRANTE / FALTANTE`), resumen fiscal de IVA del turno y 3 firmas (`Cajero`, `Supervisor`, `Auditoría`).
4. **20 Estilos Profesionales Distintos (`#1` al `#20`) con Cumplimiento PROFECO y SAT:**
   - 20 arquitecturas visuales distintas inspiradas en modelos reales de grandes cadenas comerciales (*Home Depot Pro, Costco/Sam's, Walmart, Liverpool, OXXO/7-Eleven, Cemex/Construrama, Coppel/Elektra, SAT CFDI 4.0 Anexo 20, Amazon/MercadoLibre, Apple Store/Suizo, AutoZone, Sears/Sanborns, Office Depot, Truper, BBVA/Santander, Corte Ciego Tómbola, Corte X Supervisión, Corte Z Conciliación, Notarial Legal y Papel Preimpreso*), cumpliendo con **PROFECO (`LFPC Art. 12, 66, 77 y 85`, `NOM-030-SCFI`)** y **SAT (`Anexo 20 CFDI 4.0`)**.

---

## 2. Inventario Completo de Archivos Entregados

| Archivo | Tipo | Responsabilidad Técnica |
| :--- | :---: | :--- |
| `backend/models.py` | Backend ORM | Define las 5 tablas SQLAlchemy del submódulo: `PrintFormatTemplate`, `PrintFormatVersion`, `PrintTemplateAsset`, `PrintFormatAssignment` y `PrintDocumentEmission`. |
| `backend/alembic/versions/20261117_0001_print_formats_designer.py` | Migración BD | Migración Alembic idempotente para crear las 5 tablas e índices compuestos multiempresa en SQLite / PostgreSQL. |
| `backend/services/print_formats_service.py` | Motor Backend | Catálogo de 17 tipos de documentos y 11 grupos de campos (incluyendo `corte` y `profeco`), evaluador seguro de tokens `{{grupo.campo}}`, procesador de fondos PDF (`pypdfium2`) e imágenes (`Pillow`), motor de paginación multipágina, generador real de PDFs (`generate_pdf_bytes`) y sembrador idempotente (`ensure_seed_templates`) de **30 plantillas base (Ticket + Carta para cada documento)**. |
| `backend/routers/print_formats.py` | API REST | Router FastAPI montado en `/api/print-formats` con 17 endpoints protegidos por JWT y RBAC. |
| `backend/main.py` | Bootstrap | Registra `print_formats.router` y ejecuta `ensure_print_formats_schema` al iniciar la aplicación. |
| `frontend/pages/admin/configuracion.html` | Vista HTML / CSS | Incorpora las 4 secciones en `Configuración → Impresoras (F9)`: 1. Impresoras y equipos (con botones `🧾 Diseñar Ticket` y `📄 Diseñar Carta` por cada documento), 2. Diseñador de formatos, 3. Asignación y reglas, 4. Historial de versiones. |
| `frontend/scripts/loaders/print-templates-designer.js` | Motor Frontend | Estudio visual completo tipo Photoshop/CorelDRAW: lienzo interactivo con reglas en `mm`, Drag & Drop, 8 nodos de escalado, pila de capas (`z_index`), subida de imágenes libres/fondos PDF, generador de los **20 estilos profesionales** en Carta, Ticket `80 mm` y Ticket `58 mm`, tablas de `Corte Ciego`, `Corte X` y `Corte Z`, y conexión con la API REST. |
| `frontend/scripts/loaders/config-hub.js` | Integración Admin | Conecta el catálogo de impresoras y las 16 asignaciones por tipo de documento con el estudio del Diseñador de formatos. |
| `frontend/scripts/app/02-shortcuts.js` y `06-pos-checkout.js` | Integración POS | Sincroniza la emisión de tickets térmicos y documentos tamaño carta desde el POS con las plantillas configuradas. |
| `backend/tests/test_print_formats_designer.py` | Suite QA (`pytest`) | **12 pruebas automatizadas de extremo a extremo (`12/12 PASSED`)** que validan PDFs multipágina, tickets `80mm`/`58mm`, imágenes por capas, los 20 estilos PROFECO/SAT, Cortes Ciego/X/Z, Sello QR, Serie del Sello, Saldos de Crédito, desglose de IVA, inmutabilidad de versiones, precedencia de asignación y aislamiento multiempresa. |

---

## 3. Arquitectura de Base de Datos (5 Modelos SQLAlchemy + Migración Alembic)

Definidos en `backend/models.py` y respaldados por `backend/alembic/versions/20261117_0001_print_formats_designer.py`:

1. **`print_format_templates` (`PrintFormatTemplate`):**
   - Cabecera de plantilla aislada por `empresa_id` (y opcionalmente `sucursal_id`).
   - Campos clave: `id`, `empresa_id`, `sucursal_id`, `code`, `name`, `doc_type`, `mode` (`TICKET` | `CARTA`), `paper_size` (`80mm` | `58mm` | `letter` | `a4`), `status` (`DRAFT` | `PUBLISHED` | `ARCHIVED`), `active_published_version_id`, `latest_draft_version_id`, `current_version_num`, `is_system_seed`, `integration_status` (`OPERATIVO` | `SOLO_PLANTILLA`).
2. **`print_format_versions` (`PrintFormatVersion`):**
   - Versiones **inmutables** de cada plantilla (`version_num = 1, 2, 3...`).
   - Cuando una versión está en estado `PUBLISHED`, jamás se sobrescribe: al editar una plantilla publicada, el backend clona automáticamente un nuevo borrador `DRAFT` (`version_num + 1`) mientras las operaciones en vivo siguen usando `active_published_version_id` hasta que el administrador publique el nuevo borrador.
   - Campos clave: `paper_width_mm`, `paper_height_mm`, `printable_width_mm`, `margins_mm_json`, `background_asset_id`, `background_settings_json` (`fit_mode`, `page_rule`, `print_mode`: `background_and_fields` | `fields_only`), `definition_json` (arreglo completo de capas `elements`, `preset_style_num`, `flow_blocks`), `changelog`.
3. **`print_template_assets` (`PrintTemplateAsset`):**
   - Almacena metadatos verificados de los archivos PDF o imágenes (`PNG/JPG`) cargados como fondo o logotipo (`sha256_hash`, `mime_type`, `size_bytes`, `page_count`, `width_px`, `height_px`, `width_mm`, `height_mm`, `storage_rel_path`).
4. **`print_format_assignments` (`PrintFormatAssignment`):**
   - Reglas de asignación deterministas con orden de precedencia estricto:
     $$\text{1. Terminal Específica} \longrightarrow \text{2. Sucursal Específica} \longrightarrow \text{3. Empresa Global} \longrightarrow \text{4. Plantilla Predeterminada}$$
   - Soporta además `role_target` (`CLIENTE`, `CAJA`, `ALMACEN`, `AUDITORIA`) y `printer_name`.
5. **`print_document_emissions` (`PrintDocumentEmission`):**
   - Bitácora histórica de cada documento impreso: guarda `template_id`, `version_id`, `version_num` y un `rendered_snapshot_json` con los importes y datos exactos del momento de la operación.
   - Permite reimprimir cualquier documento en dos modalidades:
     - **`historical` (Copia fiel):** usa la versión exacta de la plantilla con la que se emitió originalmente.
     - **`updated` (Diseño actual):** conserva intactos los datos históricos (`rendered_snapshot_json`), pero los proyecta sobre la versión publicada actual.

---

## 4. Todo en Ticket (`80 mm` / `58 mm`) y Tamaño Carta (`215.9 × 279.4 mm`)

Todos los tipos de documentos cuentan con soporte nativo y semillas precargadas en ambas modalidades (`TICKET` y `CARTA`):

| # | Código `doc_type` | Nombre del Documento | Semilla Ticket (`80 mm` / `58 mm`) | Semilla Tamaño Carta (`215.9 × 279.4 mm`) | Estado Integración |
| :-: | :--- | :--- | :--- | :--- | :---: |
| 1 | `ticket_venta_contado` | Venta de Contado | `SEED_VENTA_CONTADO_80MM` | `SEED_VENTA_CONTADO_CARTA` | `OPERATIVO` |
| 2 | `ticket_venta_credito` | Venta a Crédito y Pagaré | `SEED_VENTA_CREDITO_80MM` | `SEED_VENTA_CREDITO_CARTA` | `OPERATIVO` |
| 3 | `orden_entrega` | Orden de Entrega (Almacén / Patio) | `SEED_ORDEN_ENTREGA_80MM` | `SEED_ORDEN_ENTREGA_CARTA` | `OPERATIVO` |
| 4 | `cotizacion` | Cotización Comercial | `SEED_COTIZACION_80MM` | `SEED_COTIZACION_CARTA_MULTIPAGINA` | `OPERATIVO` |
| 5 | `comprobante_pago` | Comprobante de Pago o Abono CxC | `SEED_COMPROBANTE_ABONO_80MM` | `SEED_COMPROBANTE_ABONO_CARTA` | `OPERATIVO` |
| 6 | `cfdi_factura_ticket` | Factura CFDI 4.0 SAT | `SEED_CFDI_FACTURA_80MM` | `SEED_CFDI_FACTURA_CARTA` | `OPERATIVO` |
| 7 | `devolucion` | Nota de Crédito / Devolución | `SEED_DEVOLUCION_80MM` | `SEED_DEVOLUCION_CARTA` | `OPERATIVO` |
| 8 | `remision` | Remisión de Salida | `SEED_REMISION_80MM` | `SEED_CARTA_FONDO_PDF_IMG` | `OPERATIVO` |
| 9 | `orden_compra` | Orden de Compra a Proveedor | `SEED_ORDEN_COMPRA_80MM` | `SEED_ORDEN_COMPRA_CARTA` | `OPERATIVO` |
| 10 | `corte_ciego` | Corte Ciego de Caja / Tómbola | `SEED_CORTE_CIEGO_80MM` | `SEED_CORTE_CIEGO_CARTA` | `OPERATIVO` |
| 11 | `corte_x` | Corte Parcial de Caja (Corte X) | `SEED_CORTE_X_80MM` | `SEED_CORTE_X_CARTA` | `OPERATIVO` |
| 12 | `corte_z` | Corte Z / Cierre Definitivo de Caja | `SEED_CORTE_Z_80MM` | `SEED_CORTE_Z_CARTA` | `OPERATIVO` |
| 13 | `apertura_caja` | Apertura de Caja y Fondo Inicial | `SEED_APERTURA_CAJA_80MM` | `SEED_APERTURA_CAJA_CARTA` | `OPERATIVO` |
| 14 | `estado_cuenta_cliente` | Estado de Cuenta de Cliente | `SEED_ESTADO_CUENTA_80MM` | `SEED_ESTADO_CUENTA_CARTA` | `OPERATIVO` |
| 15 | `documento_formal` | Documentos Formales / Contratos | `SEED_DOCUMENTO_FORMAL_80MM` | `SEED_DOCUMENTO_FORMAL_CARTA` | `SOLO_PLANTILLA` |

---

## 5. Motor Visual Multicapa Estilo Photoshop / CorelDRAW (100% Movible y Escalable)

En `frontend/scripts/loaders/print-templates-designer.js`, cada elemento dentro de `definition_json.elements` se modela como una capa independiente:

```json
{
  "id": "layer-logo-magdaleno",
  "type": "image",
  "label": "LOGO MAGDALENO (IMAGEN)",
  "src": "data:image/svg+xml;utf8,...",
  "x_mm": 14.0,
  "y_mm": 12.0,
  "w_mm": 86.0,
  "h_mm": 21.0,
  "z_index": 2,
  "opacity": 1.0,
  "scale_pct": 100,
  "locked": false,
  "hidden": false,
  "page": 1
}
```

### Tipos de Capa Soportados por el Lienzo y por el Renderizador PDF (`generate_pdf_bytes`)
- `image`: Logotipos, imágenes subidas libremente (`data:image/png;base64,...` o `asset_id`) y `Sello QR Fiscal ({{cfdi.qr_sat}})`.
- `field`: Campo dinámico vinculado al catálogo oficial (`field_key`, ej. `cliente.nombre`, `operacion.folio`, `importes.subtotal_sin_iva`, `cfdi.serie_sello`, `credito.saldo_anterior`, `corte.estado_cuadre`, `profeco.leyenda_garantias`).
- `text` / `combined`: Cuadro de texto libre o texto combinado con múltiples tokens `{{grupo.campo}}` para encimar sobre cualquier imagen o forma.
- `rect` y `line`: Rectángulos, cintillos decorativos, marcos perimetrales y líneas divisorias con color de fondo, borde y opacidad configurables.
- `table_products`: Tabla dinámica de artículos con 3 modos de visualización de IVA (`CON_IVA`, `SIN_IVA`, `DESGLOSADO`) y paginación automática multipágina.
- `table_corte_ciego`, `table_corte_x`, `table_corte_z`: Tablas operativas especializadas para los 3 tipos de corte de caja.
- `totals_block`: Cuadro estructurado de `Subtotal SIN IVA`, `Impuesto Total (IVA 16%)`, `Subtotal CON IVA` y `Total CON IVA`.
- `signature`: Línea y bloque de firma autorizada (Cajero, Cliente, Almacén/Chofer, Supervisor, Auditoría).

---

## 6. Lógica Financiera y Operativa de Cortes de Caja (`Corte Ciego`, `Corte X` y `Corte Z`)

El grupo de datos `FIELD_GROUPS_CATALOG["corte"]` en `backend/services/print_formats_service.py` provee 27 campos operativos reales y 3 tablas especializadas:

### 6.1 Arqueo / Corte Ciego (`corte_ciego` · Tabla `table_corte_ciego` · Estilo `#16`)
- **Regla de Seguridad Ciega:** Oculta deliberadamente `corte.efectivo_esperado`, `corte.total_esperado_general` y `corte.diferencia_neta` para que el cajero realice el conteo físico sin conocer la cifra que espera el sistema.
- **Campos y Tabla:**
  - Conteo físico de denominaciones (`Billetes de $1,000`, `$500`, `$200`, `$100`, `$50/$20 y Morralla`).
  - Vouchers físicos declarados (`Tarjetas Débito/Crédito`, `Transferencias SPEI`, `Fajillas depositadas en Tómbola`).
  - `Folio Sobre de Valores / Tómbola ({{corte.folio_sobre}})`, `Efectivo Físico Declarado ({{corte.efectivo_declarado}})`, `Total Declarado a Ciegas ({{corte.total_declarado_general}})` y firmas de entrega/recepción.

### 6.2 Corte Parcial de Supervisión (`corte_x` · Tabla `table_corte_x` · Estilo `#17`)
- **Regla Operativa:** Consulta el estado del turno abierto **sin cerrar la caja ni reiniciar los acumuladores Z**.
- **Ecuación de Flujo de Efectivo en Gaveta:**
  $$\text{Efectivo Esperado en Gaveta} = (+\text{Fondo Inicial}) + (+\text{Ventas Efectivo}) + (+\text{Abonos CxC Efectivo}) + (+\text{Entradas}) - (-\text{Retiros/Fajillas}) - (-\text{Gastos}) - (-\text{Devoluciones Efectivo})$$
- **Desglose Adicional:** Rango de folios (`{{corte.folio_inicial}}` al `{{corte.folio_final}}`), número de operaciones (`{{corte.num_operaciones}}`), cobros en `Tarjeta Débito`, `Tarjeta Crédito`, `Transferencia SPEI` y `Ventas a Crédito Otorgado (CxC)`.

### 6.3 Corte Z / Cierre Definitivo de Turno (`corte_z` · Tabla `table_corte_z` · Estilo `#18`)
- **Regla de Conciliación y Auditoría:** Compara rubro por rubro lo registrado por el sistema contra lo declarado por el cajero:
  - Columnas de `table_corte_z`: `Concepto Conciliación | Esperado Sistema | Declarado Cajero | Diferencia`.
  - Rubros conciliados: `Efectivo Físico en Gaveta`, `Fajillas Retiradas a Tómbola`, `Tarjetas Débito y Crédito`, `Transferencias SPEI` y `Ventas a Crédito Otorgado (CxC)`.
- **Dictamen y Resumen Fiscal del Turno:**
  - `{{corte.diferencia_neta}}` y `{{corte.estado_cuadre}}` (`CUADRADO EXACTO (DIFERENCIA $0.00 MXN)` / `SOBRANTE` / `FALTANTE`).
  - Resumen de impuestos del turno: `Ventas Subtotal SIN IVA ({{importes.subtotal_sin_iva}})`, `Impuesto IVA 16% Trasladado ({{importes.impuesto_total}})` y `Ventas Netas CON IVA ({{importes.total_con_iva}})`.
  - **3 Firmas Oficiales:** `Cajero Responsable`, `Supervisor / Gerente` y `Auditoría / Tesorería`.

---

## 7. Desglose Fiscal de IVA (Artículos y Subtotales), Sellos CFDI y Saldos de Crédito

### 7.1 Especificación de IVA por Artículo y Subtotales Separados
- **En la Tabla de Artículos (`table_products.tax_display_mode`):**
  1. `CON_IVA`: Muestra `P. Unitario (CON IVA)` y `Total Artículo (CON IVA)`.
  2. `SIN_IVA`: Muestra `P. Unitario (SIN IVA)` y `Total Artículo (SIN IVA)`.
  3. `DESGLOSADO`: Muestra simultáneamente `P.U. SIN IVA`, `Total Art. SIN IVA`, `IVA (16%)` y `Total Art. CON IVA`.
- **Campos Individuales de Artículo:** `{{productos.precio_sin_iva}}`, `{{productos.precio_con_iva}}`, `{{productos.iva_articulo}}`, `{{productos.importe_sin_iva}}`, `{{productos.importe_con_iva}}`.
- **Subtotales e Impuestos por Separado:**
  - `{{importes.subtotal_sin_iva}}` — **Subtotal SIN IVA** (capa independiente)
  - `{{importes.impuesto_total}}` — **Impuesto Total (IVA 16%)** (capa independiente)
  - `{{importes.subtotal_con_iva}}` — **Subtotal CON IVA** (capa independiente)
  - `{{importes.total_con_iva}}` — **Total CON IVA (Neto)** (capa independiente)

### 7.2 Sello QR y Serie del Sello por Separado (Ticket y Factura)
- `{{cfdi.qr_sat}}`: **Sello QR Fiscal SAT** como capa de imagen independiente (`layer-qr-sat` / `t-qr`), libre de mover y escalar en cualquier parte del Ticket o de la Hoja Carta.
- `{{cfdi.serie_sello}}`: **Serie del Sello CSD del Emisor** (`0000100000050000...`) como campo independiente (`f-cfdi-serie-sello`).
- `{{cfdi.no_cert_sat}}`: **Serie del Sello SAT** como campo independiente (`f-cfdi-cert-sat`).

### 7.3 Saldo Anterior y Saldo Actual por Separado (Notas de Crédito, Tickets de Crédito y CxC)
- `{{credito.saldo_anterior}}`: **Saldo Anterior** del cliente antes de la operación (`f-cred-saldo-anterior`).
- `{{credito.importe_abono}}`: **Cargo / Abono** aplicado en la operación (`f-cred-importe-abono`).
- `{{credito.saldo_actual}}`: **Saldo Actual** resultante después de la operación (`f-cred-saldo-actual`).

---

## 8. Catálogo de los 20 Estilos Profesionales Precargados (PROFECO / SAT / Grandes Cadenas)

Cada uno de los **20 estilos (`#1` al `#20`)** modifica la **arquitectura y distribución espacial de las capas** (no solo los colores) tanto en **Tamaño Carta** como en **Ticket `80 mm`** y **Ticket `58 mm`**:

1. **`01 · Home Depot Pro Constructor`:** Cabezal técnico industrial con bloque de obra/contratista, cintillo naranja/carbón y garantía PROFECO.
2. **`02 · Costco / Sam's Club Mayorista`:** Banda superior azul real a todo el ancho, cajas separadas de Socio/Cliente y Folio, y auditoría de partidas NOM-030-SCFI.
3. **`03 · Walmart Supercenter Comercial`:** Cabezal comercial con cinta ámbar y precios claros con IVA incluido (Art. 12 LFPC PROFECO).
4. **`04 · Liverpool / Palacio Marco Editorial`:** Marco perimetral completo alrededor del documento, tipografía serif centrada y póliza departamental Art. 77 LFPC.
5. **`05 · OXXO / 7-Eleven Express`:** Encabezado estructurado en cuadrícula compacta de 4 celdas con bordes definidos para lectura rápida en mostrador.
6. **`06 · Cemex / Construrama Patio y Báscula`:** Doble franja superior carbón/ámbar, caja de control de salida de patio/báscula y 3 firmas operativas.
7. **`07 · Coppel / Elektra Estado de Cuenta y Pagaré`:** Tres bloques separados para `Saldo Anterior`, `Cargo/Abono` y `Saldo Actual`, más marco de Pagaré Mercantil (Art. 66 LFPC).
8. **`08 · SAT CFDI 4.0 Anexo 20 Doble Panel Fiscal`:** Panel izquierdo Emisor Fiscal + Panel derecho Timbre UUID SAT + Tabla en modo `DESGLOSADO` (`Sin IVA + IVA 16% + Con IVA`).
9. **`09 · Amazon / MercadoLibre Guía Logística`:** Sello QR en esquina superior izquierda + Caja de Guía de Despacho y prioridad de ruta.
10. **`10 · Apple Store / Suizo Minimalista`:** Diseño asimétrico con línea fina negra pura y tabla en modalidad `SIN_IVA` + desglose fiscal inferior.
11. **`11 · AutoZone / Refaccionaria Header Invertido`:** Cabezal oscuro invertido de alto contraste con franja naranja y sello de póliza de garantía PROFECO.
12. **`12 · Sears / Sanborns Columna Vertical`:** Barra vertical lateral izquierda a todo lo alto de la hoja/ticket (`279.4 mm` / `205 mm`) + tarjeta superior de Folio.
13. **`13 · Office Depot / Lumen Corporativo`:** Encabezado dividido en 3 bloques superiores con recuadro de Autofacturación Web SAT CFDI 4.0.
14. **`14 · Truper / Ferretera Industrial`:** Doble cinta industrial acero/naranja con tabla comparativa de precios unitarios e importes SIN IVA vs. CON IVA.
15. **`15 · BBVA / Santander Ficha de Bóveda`:** Cabezal bancario de tesorería con certificación electrónica de caja, serie de sello y control de valores.
16. **`16 · Corte Ciego Oficial · Conteo de Tómbola`:** Formato oficial de arqueo físico por denominaciones y sobre ciego sin mostrar saldos esperados del sistema.
17. **`17 · Corte X Supervisión · Flujo de Gaveta`:** Formato de auditoría parcial en turno abierto con flujo `(+) Fondo (+) Ventas (-) Retiros = Efectivo en Gaveta`.
18. **`18 · Corte Z Cierre Definitivo · Conciliación`:** Formato de cierre definitivo con tabla `Esperado vs. Declarado vs. Diferencia`, dictamen de cuadre y 3 firmas.
19. **`19 · Notarial / Contrato Marco Legal`:** Diseño simétrico centrado con marco legal y cláusulas de adhesión PROFECO (Art. 85 LFPC).
20. **`20 · Papel Preimpreso (Solo Campos Dinámicos)`:** Sin fondos ni logotipos (`print_mode = "fields_only"`) para imprimir únicamente los campos dinámicos sobre papelería membretada física.

---

## 9. Contratos de API REST (`/api/print-formats/*`)

Implementados en `backend/routers/print_formats.py`:

| Método | Ruta | Descripción |
| :---: | :--- | :--- |
| `GET` | `/api/print-formats/catalog` | Devuelve los 17 tipos de documentos (`DOC_TYPES_CATALOG`), los 11 grupos de campos (`FIELD_GROUPS_CATALOG`), tamaños de papel y conversión física (`MM_TO_PT`). |
| `GET` | `/api/print-formats/templates` | Lista todas las plantillas del tenant (`empresa_id`), sembrando automáticamente las 30 plantillas base (Ticket + Carta) si aún no existen. |
| `POST` | `/api/print-formats/templates` | Crea una nueva plantilla en estado `DRAFT` o duplica una existente (`duplicate_from_id`). |
| `GET` | `/api/print-formats/templates/{id}` | Obtiene el detalle completo de la plantilla, su `working_version` (`definition_json.elements`), su `background_asset` y su historial de versiones. |
| `PUT` | `/api/print-formats/templates/{id}/draft` | Guarda cambios en el borrador. Si la versión activa estaba `PUBLISHED`, clona automáticamente la versión `N+1` en `DRAFT` preservando intacta la versión publicada. |
| `POST` | `/api/print-formats/templates/{id}/publish` | Valida campos obligatorios (`validate_template_for_publish`) y publica la versión actual como `PUBLISHED` inmutable. |
| `POST` | `/api/print-formats/templates/{id}/restore/{ver_id}` | Restaura cualquier versión histórica como un nuevo borrador editable. |
| `POST` | `/api/print-formats/assets/upload` | Sube y valida un archivo PDF (hasta 25 páginas vía `pypdfium2`) o imagen (`PNG/JPG` vía `Pillow`, máx. 15 MB) para usarlo como fondo o capa. |
| `GET` | `/api/print-formats/assets/{asset_id}/page/{page_num}` | Renderiza en `PNG` de alta definición la página solicitada del PDF o imagen de fondo para el lienzo del diseñador. |
| `POST` | `/api/print-formats/preview` | Evalúa todas las capas, condiciones visuales y paginación multipágina (`multi_page_demo: true/false` o `operation_id` real) y devuelve las páginas calculadas en JSON. |
| `POST` | `/api/print-formats/pdf` | Genera y devuelve el binario `%PDF-1.4` real a escala milimétrica exacta (`include_background: true/false` para hoja blanca vs. papel preimpreso). |
| `GET/POST/DELETE` | `/api/print-formats/assignments` | Consulta, crea o elimina reglas de asignación con precedencia `Terminal → Sucursal → Empresa`. |
| `GET/POST` | `/api/print-formats/emissions` | Registra y consulta emisiones históricas con snapshot inmutable de datos. |
| `POST` | `/api/print-formats/emissions/{id}/reprint` | Reimprime una emisión histórica en modo `historical` (versión original) o `updated` (versión actual con datos históricos intactos). |

---

## 10. Conversión Física Exacta (`mm` ↔ `pt` ↔ `px`), Paginación Multipágina e Inmutabilidad

1. **Invarianza de Coordenadas ante el Zoom:**
   - Todas las coordenadas en base de datos se almacenan exclusivamente en **milímetros reales (`mm`)**:
     $$\text{Puntos PDF (pt)} = \text{mm} \times \frac{72}{25.4} \approx \text{mm} \times 2.83464567$$
     $$\text{Píxeles en Lienzo (px)} = \text{round}(\text{mm} \times \text{PX\_PER\_MM\_BASE} \times \text{zoom})$$
   - Cambiar el zoom del diseñador (`55%` a `145%`) solo escala la proyección visual en pantalla y jamás altera `x_mm, y_mm, w_mm, h_mm` guardados en `definition_json`.
2. **Paginación Multipágina de Tablas (`paginate_document_pages`):**
   - Calcula cuántas filas caben en las páginas intermedias (`bottom_limit_y_mm = 212.0 mm`) y cuántas en la última página reservando el espacio del bloque de totales, sellos y firmas (`last_page_reserved_mm = 58.0 mm`).
   - Si una cotización o factura tiene 31 productos, divide automáticamente las filas en `N` páginas, repite el encabezado de tabla en cada página y coloca el bloque de totales y firmas exclusivamente en la última página (`page_scope = "last_only"`), evitando cualquier traslape.

---

## 11. Seguridad, Multitenancy (`empresa_id`), RBAC, CSP y Regla Global de `MAYÚSCULAS`

- **Aislamiento Multiempresa (`empresa_id`):** Todos los endpoints extraen `empresa_id` del token JWT. Ningún tenant puede leer, editar, publicar o usar plantillas ni assets de otra empresa (`HTTP 404`).
- **Control de Permisos (RBAC):** Solo roles administrativos (`Administrador`, `Admin`, `SuperAdmin`, `Gerente`, `Configuracion`) pueden crear, editar, subir fondos, publicar plantillas o modificar asignaciones (`require_admin_permission`). Los roles operativos (`Vendedor`, `Cajero`) pueden consultar la vista previa y emitir documentos pero reciben `HTTP 403` si intentan alterar plantillas.
- **Evaluador Seguro de Plantillas:** El motor de tokens `{{grupo.campo}}` y condiciones visuales (`evaluate_element_condition`) utiliza expresiones regulares y tablas de búsqueda cerradas; jamás usa `eval()` ni `exec()`.
- **Cumplimiento CSP (`Content-Security-Policy`):** Todo el HTML dinámico de `print-templates-designer.js` utiliza delegación declarativa (`data-click`, `data-click-arg`, `data-change`, `data-input`) procesada por `frontend/scripts/click-delegate.js`, sin `onclick` inline.
- **Normalización a `MAYÚSCULAS` (`AGENTS.md`):** Todos los nombres de plantillas, etiquetas de capas y campos de negocio capturados por el usuario se normalizan automáticamente a `MAYÚSCULAS`.

---

## 12. Guía de Pruebas Automatizadas (`12/12 PASSED`) y Verificación para Don Isael

Para ejecutar la suite completa de pruebas automatizadas del submódulo:

```powershell
cd backend
..\.venv\Scripts\python.exe -m pytest tests/test_print_formats_designer.py -v
```

### Resultado de los 12 Escenarios Validados en `test_print_formats_designer.py`
1. `test_01_and_08_upload_multipage_pdf_place_fields_save_reopen` — **PASSED** (Subida de PDF multipágina, posicionamiento de campos en `mm`, guardado y reapertura sin pérdida de coordenadas).
2. `test_02_and_04_image_background_and_pdf_generation_modes` — **PASSED** (Fondo PNG/JPG y generación de PDF real en modo `background_and_fields` y `fields_only` para papel preimpreso).
3. `test_03_zoom_coordinate_invariance` — **PASSED** (Invarianza matemática de `mm <-> pt <-> px` en cualquier nivel de zoom).
4. `test_05_and_06_tickets_80mm_58mm_spanish_long_descriptions` — **PASSED** (Generación de tickets térmicos en `80 mm` y `58 mm` con caracteres en español `ÁÉÍÓÚÑ$` y descripciones largas sin desbordamiento).
5. `test_07_multipage_quote_pagination_without_overlapping_totals` — **PASSED** (Cotización de 31 artículos paginada automáticamente en múltiples hojas Carta sin encimar totales ni firmas).
6. `test_09_10_13_immutability_branch_assignment_and_historical_reprint` — **PASSED** (Inmutabilidad de versión publicada al editar borrador, asignación por sucursal sin afectar otras sedes y reimpresión histórica fiel).
7. `test_11_14_15_security_multitenant_isolation_invalid_files_and_rbac` — **PASSED** (Aislamiento cruzado entre empresas `EMP-A` vs `EMP-B`, rechazo de PDFs corruptos y bloqueo RBAC a rol `vendedor`).
8. `test_16_photoshop_corel_free_image_layers_scaling_and_z_index_pdf` — **PASSED** (Capas de imagen libres en Base64, escalado `%`, apilamiento `z_index` con texto encimado y renderizado en PDF).
9. `test_17_ten_preloaded_templates_carta_80mm_58mm_free_layers` — **PASSED** (Plantillas precargadas editables en Carta, Ticket `80 mm` y Ticket `58 mm`).
10. `test_18_separate_sello_qr_serie_sello_and_credit_saldos_anterior_actual` — **PASSED** (`Sello QR` y `Serie del Sello CSD` por separado + `Saldo Anterior` y `Saldo Actual` por separado).
11. `test_19_article_totals_with_and_without_iva_and_separate_subtotals` — **PASSED** (Total de artículo `CON_IVA`, `SIN_IVA` y `DESGLOSADO` + `Subtotal SIN IVA`, `Impuesto Total IVA 16%` y `Subtotal CON IVA` por separado).
12. `test_20_cortes_ciego_x_z_and_20_profeco_styles` — **PASSED** (Lógica completa y generación PDF de `Corte Ciego`, `Corte X` y `Corte Z`, cláusulas oficiales `PROFECO` y los 20 estilos profesionales).
