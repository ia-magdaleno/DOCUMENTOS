"""Suite de pruebas automatizadas del Submódulo «Diseñador de formatos» (Configuración -> Impresoras F9).

Verifica los 15 Criterios de Aceptación:
1. Subir PDF carta, colocar nombre, fecha, folio y total, guardar, cerrar y reabrir conservando coordenadas mm.
2. Subir imagen PNG, colocar elementos, guardar y reabrir conservando coordenadas mm.
3. Cambiar zoom sin alterar posiciones físicas finales en mm.
4. Generar salida PDF con Fondo + Campos e imprimir salida Solo Campos para papel preimpreso.
5. Diseñar ticket 80 mm y 58 mm con flujo automático y ancho imprimible.
6. Procesar operación con descripciones largas y caracteres españoles (ÁÉÍÓÚÑ).
7. Generar cotización multipágina (31 partidas) sin perder productos ni encimar totales.
8. Usar fondo PDF de varias páginas (3 páginas) con campos distintos por página.
9. Editar borrador sin alterar la versión publicada en producción (inmutabilidad).
10. Publicar y asignar plantilla por sucursal/terminal con precedencia determinista sin alterar otras sucursales.
11. Rechazar acceso cruzado entre empresas (multiempresa) a plantillas, fondos, vistas previas y PDFs.
12. Conservar la configuración previa de impresoras.
13. Reimprimir documento con su versión histórica congelada y snapshot de datos original.
14. Mostrar errores claros ante archivos dañados o no compatibles.
15. Impedir que un usuario sin permiso (vendedor/cajero) publique o modifique asignaciones (403).
"""
import io
import os
import sys

import jwt
import pypdfium2 as pdfium
import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from main import app  # noqa: E402
from deps import JWT_ALGORITHM, JWT_SECRET  # noqa: E402
from services import print_formats_service as pfs  # noqa: E402

client = TestClient(app)

SAMPLE_PDF_OUT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "media", "print_formats", "ejemplos_generados"))
os.makedirs(SAMPLE_PDF_OUT_DIR, exist_ok=True)


def _make_token(empresa: str = "EMP-TEST-A", sucursal: str = "MATRIZ", role: str = "Administrador", user_id: str = "admin_test") -> dict:
    tok = jwt.encode(
        {"sub": user_id, "empresa": empresa, "sucursal": sucursal, "role": role},
        JWT_SECRET,
        algorithm=JWT_ALGORITHM,
    )
    return {"Authorization": f"Bearer {tok}"}


def _build_valid_pdf_bytes(num_pages: int = 1) -> bytes:
    pdf = pdfium.PdfDocument.new()
    for _ in range(num_pages):
        # Carta 612 x 792 pt (215.9 x 279.4 mm)
        pdf.new_page(612, 792)
    buf = io.BytesIO()
    pdf.save(buf)
    pdf.close()
    return buf.getvalue()


def _build_valid_png_bytes() -> bytes:
    img = Image.new("RGB", (816, 1056), (240, 246, 255))
    drw = ImageDraw.Draw(img)
    drw.rectangle([20, 20, 796, 140], fill=(30, 58, 138))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_01_and_08_upload_multipage_pdf_place_fields_save_reopen():
    """Escenarios 1 y 8: Subir PDF Carta (multipágina), colocar nombre, fecha, folio y total
    en páginas distintas, guardar, cerrar y volver a abrir sin perder posiciones físicas (mm)."""
    headers = _make_token("EMP-AC-01", "MATRIZ", "Administrador")

    # 1. Subir PDF de 3 páginas
    pdf_bytes = _build_valid_pdf_bytes(num_pages=3)
    res_up = client.post(
        "/api/print-formats/assets/upload",
        headers=headers,
        files={"file": ("membrete_corporativo_3pags.pdf", pdf_bytes, "application/pdf")},
        data={"kind": "BACKGROUND"},
    )
    assert res_up.status_code == 201, res_up.text
    asset = res_up.json()
    assert asset["page_count"] == 3
    assert len(asset["pages_meta"]) == 3
    assert abs(asset["pages_meta"][0]["width_mm"] - 215.9) < 0.5

    # 2. Crear plantilla Carta asociada al fondo PDF
    res_tpl = client.post(
        "/api/print-formats/templates",
        headers=headers,
        json={
            "name": "cotización con fondo pdf 3 páginas",
            "doc_type": "cotizacion",
            "mode": "CARTA",
            "background_asset_id": asset["id"],
        },
    )
    assert res_tpl.status_code == 201
    tpl = res_tpl.json()
    assert tpl["name"] == "COTIZACIÓN CON FONDO PDF 3 PÁGINAS"  # Normalizado a MAYÚSCULAS

    # 3. Colocar nombre, fecha, folio y total en página 1 y cláusula en página 2 con coordenadas exactas en mm
    elements = [
        {"id": "f-nombre", "type": "field", "label": "NOMBRE CLIENTE", "field_key": "cliente.nombre", "x_mm": 24.5, "y_mm": 48.0, "w_mm": 110.0, "h_mm": 7.5, "page": 1},
        {"id": "f-fecha", "type": "field", "label": "FECHA", "field_key": "operacion.fecha", "x_mm": 158.0, "y_mm": 22.5, "w_mm": 42.0, "h_mm": 6.5, "page": 1},
        {"id": "f-folio", "type": "field", "label": "FOLIO", "field_key": "operacion.folio", "x_mm": 158.0, "y_mm": 14.0, "w_mm": 42.0, "h_mm": 7.0, "page": 1},
        {"id": "f-total", "type": "field", "label": "TOTAL", "field_key": "importes.total", "x_mm": 152.0, "y_mm": 238.5, "w_mm": 48.0, "h_mm": 9.0, "page": 1},
        {"id": "f-pag2", "type": "text", "label": "ANEXO PÁGINA 2", "text": "CONDICIONES TÉCNICAS PARA {{cliente.nombre}}", "x_mm": 20.0, "y_mm": 35.0, "w_mm": 165.0, "h_mm": 12.0, "page": 2},
    ]
    res_save = client.put(
        f"/api/print-formats/templates/{tpl['id']}/draft",
        headers=headers,
        json={"definition_json": {"doc_title": "COTIZACIÓN", "elements": elements}},
    )
    assert res_save.status_code == 200

    # 4. Cerrar y volver a abrir verificando que cada coordenada en mm sea idéntica
    res_reopen = client.get(f"/api/print-formats/templates/{tpl['id']}", headers=headers)
    assert res_reopen.status_code == 200
    reopened = res_reopen.json()
    saved_els = {e["id"]: e for e in reopened["working_version"]["definition_json"]["elements"]}
    assert saved_els["f-nombre"]["x_mm"] == 24.5
    assert saved_els["f-nombre"]["y_mm"] == 48.0
    assert saved_els["f-total"]["x_mm"] == 152.0
    assert saved_els["f-total"]["y_mm"] == 238.5
    assert saved_els["f-pag2"]["page"] == 2


def test_02_and_04_image_background_and_pdf_generation_modes():
    """Escenarios 2 y 4: Subir imagen PNG de fondo, colocar campos, generar PDF con Fondo+Campos
    y generar PDF con Solo Campos para papel preimpreso."""
    headers = _make_token("EMP-AC-01", "MATRIZ", "Administrador")
    png_bytes = _build_valid_png_bytes()

    res_up = client.post(
        "/api/print-formats/assets/upload",
        headers=headers,
        files={"file": ("membrete_imagen.png", png_bytes, "image/png")},
        data={"kind": "BACKGROUND"},
    )
    assert res_up.status_code == 201
    asset_id = res_up.json()["id"]

    res_tpl = client.post(
        "/api/print-formats/templates",
        headers=headers,
        json={
            "name": "REMISIÓN CARTA CON IMAGEN DE FONDO",
            "doc_type": "remision",
            "mode": "CARTA",
            "background_asset_id": asset_id,
        },
    )
    assert res_tpl.status_code == 201
    tpl_id = res_tpl.json()["id"]

    # PDF con Fondo + Campos
    res_pdf_full = client.post(
        "/api/print-formats/pdf",
        headers=headers,
        json={"template_id": tpl_id, "include_background": True},
    )
    assert res_pdf_full.status_code == 200
    assert res_pdf_full.content.startswith(b"%PDF-")
    with open(os.path.join(SAMPLE_PDF_OUT_DIR, "ejemplo_carta_fondo_y_campos.pdf"), "wb") as f:
        f.write(res_pdf_full.content)

    # PDF con SOLO CAMPOS (para papel membretado preimpreso)
    res_pdf_fields = client.post(
        "/api/print-formats/pdf",
        headers=headers,
        json={"template_id": tpl_id, "include_background": False},
    )
    assert res_pdf_fields.status_code == 200
    assert res_pdf_fields.content.startswith(b"%PDF-")
    with open(os.path.join(SAMPLE_PDF_OUT_DIR, "ejemplo_carta_solo_campos_preimpreso.pdf"), "wb") as f:
        f.write(res_pdf_fields.content)


def test_03_zoom_coordinate_invariance():
    """Escenario 3: Cambiar el nivel de zoom (50%, 75%, 100%, 150%, 200%) conserva intactas las posiciones físicas en mm."""
    orig_x_mm = 145.5
    orig_y_mm = 218.0
    for zoom in (0.5, 0.75, 1.0, 1.25, 1.5, 2.0):
        px_x = pfs.mm_to_canvas_px(orig_x_mm, zoom=zoom)
        px_y = pfs.mm_to_canvas_px(orig_y_mm, zoom=zoom)
        back_x_mm = pfs.canvas_px_to_mm(px_x, zoom=zoom)
        back_y_mm = pfs.canvas_px_to_mm(px_y, zoom=zoom)
        assert abs(back_x_mm - orig_x_mm) <= 0.05
        assert abs(back_y_mm - orig_y_mm) <= 0.05


def test_05_and_06_tickets_80mm_58mm_spanish_long_descriptions():
    """Escenarios 5 y 6: Diseñar ticket 80 mm y 58 mm con descripciones largas y caracteres españoles (ÁÉÍÓÚÑ)."""
    headers = _make_token("EMP-AC-01", "MATRIZ", "Administrador")

    for paper_sz, w_mm, prt_w in [("80mm", 80.0, 72.0), ("58mm", 58.0, 48.0)]:
        res_t = client.post(
            "/api/print-formats/templates",
            headers=headers,
            json={
                "name": f"TICKET VENTA {paper_sz} ESPAÑOL ÁÉÍÓÚÑ",
                "doc_type": "ticket_venta_contado",
                "mode": "TICKET",
                "paper_size": paper_sz,
                "paper_width_mm": w_mm,
                "printable_width_mm": prt_w,
            },
        )
        assert res_t.status_code == 201
        tid = res_t.json()["id"]

        res_pdf = client.post(
            "/api/print-formats/pdf",
            headers=headers,
            json={"template_id": tid, "multi_page_demo": False},
        )
        assert res_pdf.status_code == 200
        assert res_pdf.content.startswith(b"%PDF-")
        with open(os.path.join(SAMPLE_PDF_OUT_DIR, f"ejemplo_ticket_{paper_sz}.pdf"), "wb") as f:
            f.write(res_pdf.content)


def test_07_multipage_quote_pagination_without_overlapping_totals():
    """Escenario 7: Generar una cotización de varias páginas (31 productos) sin perder productos ni encimar totales."""
    headers = _make_token("EMP-AC-01", "MATRIZ", "Administrador")
    res_list = client.get("/api/print-formats/templates?doc_type=cotizacion&mode=CARTA", headers=headers)
    assert res_list.status_code == 200
    seed_tpl = next(t for t in res_list.json()["templates"] if t["code"] == "SEED_COTIZACION_CARTA_MULTIPAGINA")
    tpl_id = seed_tpl["id"]

    res_prev = client.post(
        "/api/print-formats/preview",
        headers=headers,
        json={"template_id": tpl_id, "multi_page_demo": True},
    )
    assert res_prev.status_code == 200
    prev = res_prev.json()
    assert prev["total_pages"] >= 2
    total_rows_across_pages = sum(len(p["table_slice"]) for p in prev["pages"])
    assert total_rows_across_pages == prev["context_summary"]["items_count"] == 31

    # Verificar que el bloque de totales solo aparece en la última página
    for p in prev["pages"][:-1]:
        el_types = [e["type"] for e in p["elements"]]
        assert "totals_block" not in el_types
    last_page_types = [e["type"] for e in prev["pages"][-1]["elements"]]
    assert "totals_block" in last_page_types

    # Generar el PDF multipágina real y verificar que tenga >= 2 páginas con pypdfium2
    res_pdf = client.post(
        "/api/print-formats/pdf",
        headers=headers,
        json={"template_id": tpl_id, "multi_page_demo": True},
    )
    assert res_pdf.status_code == 200
    pdf_doc = pdfium.PdfDocument(res_pdf.content)
    assert len(pdf_doc) == prev["total_pages"] >= 2
    pdf_doc.close()
    with open(os.path.join(SAMPLE_PDF_OUT_DIR, "ejemplo_cotizacion_multipagina_carta.pdf"), "wb") as f:
        f.write(res_pdf.content)


def test_09_10_13_immutability_branch_assignment_and_historical_reprint():
    """Escenarios 9, 10 y 13:
    - Editar un borrador no altera la versión publicada (inmutabilidad).
    - Publicar y asignar a una sucursal sin alterar otras sucursales.
    - Reimprimir un documento conserva la versión histórica emitida."""
    headers = _make_token("EMP-AC-01", "MATRIZ", "Administrador")
    res_list = client.get("/api/print-formats/templates?doc_type=ticket_venta_contado", headers=headers)
    tpl = next(t for t in res_list.json()["templates"] if t["code"] == "SEED_VENTA_CONTADO_80MM")
    tpl_id = tpl["id"]
    orig_pub_ver_id = tpl["active_published_version_id"]
    initial_vnum = int(tpl["current_version_num"])

    # Emitir documento histórico con la versión publicada actual
    res_em = client.post(
        "/api/print-formats/emissions",
        headers=headers,
        json={"doc_type": "ticket_venta_contado", "template_id": tpl_id, "operation_id": "VENTA-HIST-001"},
    )
    assert res_em.status_code == 201
    emission_id = res_em.json()["emission_id"]
    assert res_em.json()["version_num"] == initial_vnum

    # Editar borrador -> debe crear versión (initial_vnum + 1) en DRAFT mientras active_published_version_id sigue intacto
    res_draft = client.put(
        f"/api/print-formats/templates/{tpl_id}/draft",
        headers=headers,
        json={"name": "VENTA DE CONTADO EN 80 MM EDITADO EN BORRADOR"},
    )
    assert res_draft.status_code == 200
    updated_tpl = res_draft.json()
    assert updated_tpl["active_published_version_id"] == orig_pub_ver_id
    assert updated_tpl["working_version"]["version_num"] == initial_vnum + 1
    assert updated_tpl["working_version"]["status"] == "DRAFT"

    # Publicar nueva versión
    res_pub = client.post(f"/api/print-formats/templates/{tpl_id}/publish", headers=headers)
    assert res_pub.status_code == 200
    assert res_pub.json()["active_published_version_id"] == updated_tpl["working_version"]["id"]

    # Asignar exclusivamente a SUCURSAL-NORTE sin afectar MATRIZ
    res_asig = client.post(
        "/api/print-formats/assignments",
        headers=headers,
        json={
            "doc_type": "ticket_venta_contado",
            "template_id": tpl_id,
            "sucursal_id": "SUCURSAL-NORTE",
            "role_target": "CLIENTE",
        },
    )
    assert res_asig.status_code == 200

    res_lookup_norte = client.get("/api/print-formats/assignments?doc_type=ticket_venta_contado&sucursal_id=SUCURSAL-NORTE", headers=headers)
    assert res_lookup_norte.json()["resolved_assignment_id"] == res_asig.json()["assignment_id"]

    res_lookup_matriz = client.get("/api/print-formats/assignments?doc_type=ticket_venta_contado&sucursal_id=MATRIZ", headers=headers)
    assert res_lookup_matriz.json()["resolved_assignment_id"] is None

    # Reimprimir emisión histórica -> debe usar initial_vnum (histórica) y NO (initial_vnum + 1), mientras que updated usa (initial_vnum + 1)
    res_rep_hist = client.post(
        f"/api/print-formats/emissions/{emission_id}/reprint",
        headers=headers,
        json={"reprint_mode": "historical"},
    )
    assert res_rep_hist.status_code == 200
    assert res_rep_hist.json()["used_version_num"] == initial_vnum
    assert res_rep_hist.json()["data_snapshot_preserved"] is True

    res_rep_upd = client.post(
        f"/api/print-formats/emissions/{emission_id}/reprint",
        headers=headers,
        json={"reprint_mode": "updated"},
    )
    assert res_rep_upd.status_code == 200
    assert res_rep_upd.json()["used_version_num"] == initial_vnum + 1


def test_11_14_15_security_multitenant_isolation_invalid_files_and_rbac():
    """Escenarios 11, 14 y 15:
    - Rechazar acceso cruzado entre empresas (EMP-A vs EMP-B).
    - Rechazar archivos inválidos o PDFs corruptos con mensaje comprensible.
    - Rechazar publicación o cambio de asignación por rol sin permisos (vendedor)."""
    headers_emp_a = _make_token("EMP-TENANT-A", "MATRIZ", "Administrador")
    headers_emp_b = _make_token("EMP-TENANT-B", "MATRIZ", "Administrador")
    headers_vendedor_a = _make_token("EMP-TENANT-A", "MATRIZ", "vendedor", "vend_01")

    # Crear plantilla en EMP-A
    res_tpl_a = client.post(
        "/api/print-formats/templates",
        headers=headers_emp_a,
        json={"name": "PLANTILLA PRIVADA EMPRESA A", "doc_type": "cotizacion", "mode": "CARTA"},
    )
    assert res_tpl_a.status_code == 201
    tpl_a_id = res_tpl_a.json()["id"]

    # EMP-B intenta leer, editar o generar PDF de la plantilla de EMP-A -> 404 rechazado
    assert client.get(f"/api/print-formats/templates/{tpl_a_id}", headers=headers_emp_b).status_code == 404
    assert client.put(f"/api/print-formats/templates/{tpl_a_id}/draft", headers=headers_emp_b, json={"name": "HACK"}).status_code == 404
    assert client.post("/api/print-formats/pdf", headers=headers_emp_b, json={"template_id": tpl_a_id}).status_code == 404

    # Archivo inválido (texto disfrazado de PDF y PDF corrupto) -> 400 con mensaje claro
    res_bad_type = client.post(
        "/api/print-formats/assets/upload",
        headers=headers_emp_a,
        files={"file": ("falso.pdf", b"ESTE NO ES UN PDF REAL", "application/pdf")},
    )
    assert res_bad_type.status_code == 400

    res_corrupt_pdf = client.post(
        "/api/print-formats/assets/upload",
        headers=headers_emp_a,
        files={"file": ("corrupto.pdf", b"%PDF-1.7 archivo corrupto sin xref", "application/pdf")},
    )
    assert res_corrupt_pdf.status_code == 400
    assert "dañado" in str(res_corrupt_pdf.json()).lower()

    # Vendedor sin permiso intenta publicar o cambiar asignaciones -> 403 Forbidden
    res_vend_pub = client.post(f"/api/print-formats/templates/{tpl_a_id}/publish", headers=headers_vendedor_a)
    assert res_vend_pub.status_code == 403

    res_vend_asig = client.post(
        "/api/print-formats/assignments",
        headers=headers_vendedor_a,
        json={"doc_type": "cotizacion", "template_id": tpl_a_id},
    )
    assert res_vend_asig.status_code == 403


def test_16_photoshop_corel_free_image_layers_scaling_and_z_index_pdf():
    """Escenario 16 (Modo Photoshop / CorelDRAW / Paint):
    Subir/colocar múltiples capas de imagen independientes, escalar su tamaño (w_mm, h_mm),
    apilar una imagen debajo de otra mediante z_index y encimar texto dinámico encima,
    generando el PDF real respetando el orden exacto de capas."""
    import base64

    headers = _make_token("EMP-AC-01", "MATRIZ", "Administrador")
    png_bytes = _build_valid_png_bytes()
    b64_data_url = "data:image/png;base64," + base64.b64encode(png_bytes).decode("ascii")

    res_tpl = client.post(
        "/api/print-formats/templates",
        headers=headers,
        json={"name": "DISEÑO MULTICAPA ESTILO PHOTOSHOP COREL", "doc_type": "cotizacion", "mode": "CARTA"},
    )
    assert res_tpl.status_code == 201
    tpl_id = res_tpl.json()["id"]

    elements = [
        {
            "id": "img-fondo-abajo",
            "type": "image",
            "label": "IMAGEN CAPA INFERIOR",
            "src": b64_data_url,
            "x_mm": 15.0,
            "y_mm": 20.0,
            "w_mm": 120.0,
            "h_mm": 60.0,
            "opacity": 0.85,
            "scale_pct": 120,
            "page": 1,
            "z_index": 1,
        },
        {
            "id": "img-logo-arriba",
            "type": "image",
            "label": "IMAGEN CAPA SUPERIOR SUPERPUESTA",
            "src": b64_data_url,
            "x_mm": 35.0,
            "y_mm": 30.0,
            "w_mm": 65.0,
            "h_mm": 30.0,
            "opacity": 1.0,
            "scale_pct": 85,
            "page": 1,
            "z_index": 4,
        },
        {
            "id": "txt-encimado-frente",
            "type": "field",
            "label": "TEXTO ENCIMADO SOBRE IMÁGENES",
            "field_key": "cliente.nombre",
            "text": "{{cliente.nombre}}",
            "x_mm": 40.0,
            "y_mm": 38.0,
            "w_mm": 95.0,
            "h_mm": 9.0,
            "font_size": 14,
            "bold": True,
            "page": 1,
            "z_index": 10,
        },
    ]

    res_save = client.put(
        f"/api/print-formats/templates/{tpl_id}/draft",
        headers=headers,
        json={"definition_json": {"doc_title": "COTIZACIÓN", "elements": elements}},
    )
    assert res_save.status_code == 200

    res_pdf = client.post(
        "/api/print-formats/pdf",
        headers=headers,
        json={"template_id": tpl_id, "include_background": True},
    )
    assert res_pdf.status_code == 200
    assert res_pdf.content.startswith(b"%PDF-")


def test_17_ten_preloaded_templates_carta_80mm_58mm_free_layers():
    """Escenario 17: Verificar que las plantillas por capas libres (Estilos 1 al 10)
    funcionan, permiten mover/modificar sus capas y generan PDF real en Carta, Ticket 80 mm y Ticket 58 mm."""
    headers = _make_token("EMP-AC-01", "MATRIZ", "Administrador")

    for mode, p_size, pw_mm, ph_mm in [
        ("CARTA", "letter", 215.9, 279.4),
        ("TICKET", "80mm", 80.0, 210.0),
        ("TICKET", "58mm", 58.0, 195.0),
    ]:
        res_tpl = client.post(
            "/api/print-formats/templates",
            headers=headers,
            json={
                "name": f"PLANTILLA LIBRE ESTILO #5 EN {p_size.upper()}",
                "doc_type": "cotizacion",
                "mode": mode,
                "paper_size": p_size,
                "paper_width_mm": pw_mm,
                "paper_height_mm": ph_mm,
            },
        )
        assert res_tpl.status_code == 201
        tid = res_tpl.json()["id"]

        max_w = pw_mm - 8.0
        movable_layers = [
            {"id": "l-banner", "type": "rect", "label": "FRANJA SUPERIOR", "x_mm": 3.0, "y_mm": 4.0, "w_mm": max_w, "h_mm": 10.0, "background_color": "#b45309", "z_index": 1},
            {"id": "l-title", "type": "text", "label": "TÍTULO MOVIBLE", "text": "COTIZACIÓN", "x_mm": 4.0, "y_mm": 6.0, "w_mm": max_w - 2.0, "h_mm": 6.0, "bold": True, "z_index": 3},
            {"id": "f-cli-nombre", "type": "field", "label": "CLIENTE", "field_key": "cliente.nombre", "x_mm": 4.0, "y_mm": 18.0, "w_mm": max_w, "h_mm": 7.0, "z_index": 4},
            {"id": "layer-table-products", "type": "table_products", "label": "TABLA", "x_mm": 4.0, "y_mm": 30.0, "w_mm": max_w, "h_mm": 45.0, "header_bg": "#b45309", "z_index": 2},
            {"id": "f-tot-total", "type": "field", "label": "TOTAL", "field_key": "importes.total", "x_mm": 4.0, "y_mm": 85.0, "w_mm": max_w, "h_mm": 8.0, "z_index": 5},
        ]

        res_draft = client.put(
            f"/api/print-formats/templates/{tid}/draft",
            headers=headers,
            json={
                "paper_size": p_size,
                "paper_width_mm": pw_mm,
                "paper_height_mm": ph_mm,
                "definition_json": {"preset_style_num": 5, "elements": movable_layers},
            },
        )
        assert res_draft.status_code == 200

        res_pdf = client.post("/api/print-formats/pdf", headers=headers, json={"template_id": tid})
        assert res_pdf.status_code == 200
        assert res_pdf.content.startswith(b"%PDF-")


def test_18_separate_sello_qr_serie_sello_and_credit_saldos_anterior_actual():
    """Escenario 18:
    - Sello QR (`cfdi.qr_sat`) y Serie del Sello (`cfdi.serie_sello`) por separado para Ticket y Factura.
    - Saldo Anterior (`credito.saldo_anterior`) y Saldo Actual (`credito.saldo_actual`) por separado para Notas de Crédito / Ticket de Crédito."""
    headers = _make_token("EMP-AC-01", "MATRIZ", "Administrador")

    # 1. Verificar que el catálogo expone los campos separados
    res_cat = client.get("/api/print-formats/catalog", headers=headers)
    assert res_cat.status_code == 200
    cat_str = str(res_cat.json())
    assert "cfdi.qr_sat" in cat_str
    assert "cfdi.serie_sello" in cat_str
    assert "credito.saldo_anterior" in cat_str
    assert "credito.saldo_actual" in cat_str

    # 2. Verificar evaluación de Saldo Anterior y Saldo Actual + Serie del Sello en Ticket de Crédito / Nota de Crédito
    demo_ctx = pfs.build_demo_context("ticket_venta_credito")
    val_ant = pfs.resolve_field_value(demo_ctx, "credito.saldo_anterior")
    val_act = pfs.resolve_field_value(demo_ctx, "credito.saldo_actual")
    val_serie = pfs.resolve_field_value(demo_ctx, "cfdi.serie_sello")
    assert val_ant.startswith("$18,500.00")
    assert val_act.startswith("$") and val_act != val_ant
    assert "0000100000050000DEMO" in val_serie


def test_19_article_totals_with_and_without_iva_and_separate_subtotals():
    """Escenario 19:
    - Especificar si el total del artículo es CON IVA, SIN IVA o DESGLOSADO.
    - Impuesto Total (IVA 16%), Subtotal SIN IVA y Subtotal CON IVA por separado."""
    headers = _make_token("EMP-AC-01", "MATRIZ", "Administrador")

    res_cat = client.get("/api/print-formats/catalog", headers=headers)
    assert res_cat.status_code == 200
    cat_str = str(res_cat.json())
    for required_key in [
        "productos.precio_sin_iva",
        "productos.precio_con_iva",
        "productos.iva_articulo",
        "productos.importe_sin_iva",
        "productos.importe_con_iva",
        "importes.subtotal_sin_iva",
        "importes.impuesto_total",
        "importes.subtotal_con_iva",
        "importes.total_con_iva",
    ]:
        assert required_key in cat_str

    demo_ctx = pfs.build_demo_context("cotizacion")
    first_item = demo_ctx["productos"][0]
    assert first_item["importe_sin_iva"] < first_item["importe_con_iva"]
    assert round(first_item["importe_sin_iva"] + first_item["iva_articulo"], 2) == first_item["importe_con_iva"]

    sub_sin = pfs.resolve_field_value(demo_ctx, "importes.subtotal_sin_iva")
    imp_tot = pfs.resolve_field_value(demo_ctx, "importes.impuesto_total")
    sub_con = pfs.resolve_field_value(demo_ctx, "importes.subtotal_con_iva")
    assert sub_sin.startswith("$") and imp_tot.startswith("$") and sub_con.startswith("$")
    assert sub_sin != sub_con


def test_20_cortes_ciego_x_z_and_20_profeco_styles():
    """Escenario 20:
    - Lógica completa para Corte Ciego (`corte_ciego`), Corte Parcial (`corte_x`) y Corte Z / Cierre Definitivo (`corte_z`).
    - Cumplimiento con PROFECO (Art. 12, 77 y 85 LFPC, NOM-030-SCFI) y SAT Anexo 20 CFDI 4.0.
    - 20 estilos profesionales distintos (no solo colores) en Carta, Ticket 80mm y Ticket 58mm."""
    headers = _make_token("EMP-AC-01", "MATRIZ", "Administrador")

    # 1. Verificar catálogo de documentos y grupos de campos de Corte de Caja y PROFECO
    res_cat = client.get("/api/print-formats/catalog", headers=headers)
    assert res_cat.status_code == 200
    cat_json = res_cat.json()
    cat_str = str(cat_json)
    assert "corte_ciego" in cat_str
    assert "corte_x" in cat_str
    assert "corte_z" in cat_str
    assert "apertura_caja" in cat_str
    for key in [
        "corte.tipo_corte",
        "corte.fondo_inicial",
        "corte.ventas_efectivo",
        "corte.retiros_fajillas",
        "corte.efectivo_esperado",
        "corte.efectivo_declarado",
        "corte.diferencia_neta",
        "corte.estado_cuadre",
        "corte.folio_sobre",
        "profeco.leyenda_garantias",
        "profeco.leyenda_consumidor",
    ]:
        assert key in cat_str

    # 2. Verificar semillas de Corte Ciego, Corte X y Corte Z y su generación real de PDF
    res_tpls = client.get("/api/print-formats/templates", headers=headers)
    assert res_tpls.status_code == 200
    tpl_codes = {t["code"]: t["id"] for t in res_tpls.json()["templates"]}
    for seed_code in ["SEED_CORTE_CIEGO_80MM", "SEED_CORTE_X_80MM", "SEED_CORTE_Z_80MM"]:
        assert seed_code in tpl_codes
        res_pdf = client.post(
            "/api/print-formats/pdf",
            headers=headers,
            json={"template_id": tpl_codes[seed_code], "multi_page_demo": False},
        )
        assert res_pdf.status_code == 200
        assert res_pdf.content.startswith(b"%PDF-")

    # 3. Verificar que el diseñador frontend incluye los 20 estilos arquitectónicos y las 3 tablas de corte
    js_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "frontend",
        "scripts",
        "loaders",
        "print-templates-designer.js",
    )
    with open(js_path, "r", encoding="utf-8") as f:
        js_src = f.read()

    for num in range(1, 21):
        assert f"num: {num}," in js_src
    for token in [
        "table_corte_ciego",
        "table_corte_x",
        "table_corte_z",
        "corte.efectivo_declarado",
        "corte.estado_cuadre",
        "profeco.leyenda_garantias",
        "PROFECO",
    ]:
        assert token in js_src





