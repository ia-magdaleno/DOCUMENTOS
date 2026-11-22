"""Suite integral de pruebas automatizadas del Módulo «Centro de Documentos» (Documentos · Consulta e impresión).

Ejecuta sobre una base SQLite temporal aislada (no altera `calebsys_local.db`) y verifica los bloques A–F:
- A. Regresión (NC-PMM-00-0003 por $130.02 + folios reales de venta, salidas Carta/Ticket/CSV/XLSX y protección CSV).
- B. Mostrador (venta -> entrega vinculada -> evidencia adjunta validada -> Carta/Ticket -> Solicitud de impresión).
- C. Aislamiento (2 empresas, 2 sucursales, folios visibles repetidos sin colisión, regla de Cortes Z, protección de importes, RRHH y rotación de sede).
- D. Históricos (multipágina >= 2 hojas, reconstrucción sin original e inmutabilidad de original conservado tras publicar nueva versión de plantilla).
- E. Envíos (preview exacto, idempotencia doble clic, lote con fallo parcial, reintento seguro conservando éxitos, distinción prueba vs entrega real y enlace revocable).
- F. Integridad (cero alteraciones en ventas, caja, saldos de clientes/cartera ni existencias de inventario).
"""
from __future__ import annotations

import datetime as _dt
import io
import os
import sys
import tempfile
import uuid
from decimal import Decimal

import jwt
import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import models  # noqa: E402
from database import Base, get_db  # noqa: E402
from deps import JWT_ALGORITHM, JWT_SECRET  # noqa: E402
from main import app  # noqa: E402


@pytest.fixture()
def isolated_env(tmp_path):
    db_file = tmp_path / "test_doc_center_suite.sqlite"
    eng = sa.create_engine(f"sqlite:///{db_file}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=eng)
    TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=eng)

    def _override_get_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override_get_db
    client = TestClient(app)
    try:
        yield client, TestingSession
    finally:
        app.dependency_overrides.pop(get_db, None)
        eng.dispose()


def _tok(empresa: str, sucursal: str = "MATRIZ", role: str = "Administrador", sub: str = "AMAGDALENO", user_id: str = "u-admin") -> dict:
    token = jwt.encode(
        {"sub": sub, "user_id": user_id, "empresa": empresa, "sucursal": sucursal, "role": role},
        JWT_SECRET,
        algorithm=JWT_ALGORITHM,
    )
    return {"Authorization": f"Bearer {token}"}


def _make_png_bytes() -> bytes:
    img = Image.new("RGB", (320, 200), (245, 248, 255))
    d = ImageDraw.Draw(img)
    d.rectangle([10, 10, 310, 190], outline=(26, 86, 219), width=3)
    d.text((24, 80), "EVIDENCIA DE ENTREGA PATIO", fill=(15, 23, 42))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _mk_sale(
    *,
    id: str,
    empresa_id: str,
    sucursal_id: str = "MATRIZ",
    folio: str = "1",
    client_id: str = "PUBLICO-GENERAL",
    total: Decimal = Decimal("100.00"),
    payment_method: str = "001",
    seller_id: str | None = "JUAN",
    status: str = "completed",
) -> models.Sale:
    return models.Sale(
        id=id,
        empresa_id=empresa_id,
        sucursal_id=sucursal_id,
        folio=folio,
        client_id=client_id,
        total=total,
        payment_method=payment_method,
        amount_paid=total,
        change_returned=Decimal("0.00"),
        is_cfdi=False,
        discount=Decimal("0.00"),
        advance=Decimal("0.00"),
        is_safekept=False,
        status=status,
        seller_id=seller_id,
        canal_venta="mostrador",
        saldo_favor_applied=Decimal("0.00"),
    )


def test_case_a_and_f_regression_nc_130_02_exports_and_operational_integrity(isolated_env):
    """Casos A y F: Verifica NC-PMM-00-0003 ($130.02, APLICADA) distinguida de CFDI Egreso,
    venta real folio '1' ($150.00), exportación CSV protegida contra fórmulas, XLSX e integridad total."""
    client, SessionCls = isolated_env
    emp = "EMP-REG-01"

    with SessionCls() as db:
        db.add(models.Company(id=emp, name="MADERAS Y MATERIALES MAGDALENO", rfc="GMM2106218A1", status="ACTIVE"))
        db.add(models.Branch(empresa_id=emp, id="br-m1", name="MATRIZ", address="COLOSIO 256", status="ACTIVE", is_main=True))
        cli_elvia = models.Client(
            id="cli-elvia", empresa_id=emp, sucursal_id="MATRIZ",
            name="=ELVIA PEREA VERDUGO",  # Prefijo '=' intencional para verificar protección CSV anti-fórmulas
            rfc="PEVE850101AB1", saldo_actual=Decimal("400.00"), saldo_favor=Decimal("130.02"),
        )
        db.add(cli_elvia)
        db.add(models.Product(
            id="prod-1", empresa_id=emp, sucursal_id="MATRIZ", sku="TAB-PINO-01",
            name="TABLÓN DE PINO", description="TABLÓN DE PINO 1RA", price=Decimal("150.00"),
        ))
        db.add(models.Warehouse(id="wh-1", empresa_id=emp, sucursal_id="MATRIZ", name="BODEGA MATRIZ"))
        db.add(models.WarehouseStock(empresa_id=emp, warehouse_id="wh-1", product_id="prod-1", quantity=Decimal("24.0000")))

        sale = _mk_sale(
            id="sale-real-1", empresa_id=emp, sucursal_id="MATRIZ", folio="1",
            client_id="cli-elvia", total=Decimal("150.00"), payment_method="001", seller_id="JUAN",
        )
        db.add(sale)
        db.add(models.SaleItem(
            id="si-1", empresa_id=emp, sucursal_id="MATRIZ", sale_id="sale-real-1",
            product_id="prod-1", product_sku="TAB-PINO-01", quantity=Decimal("1"), price=Decimal("150.00"), subtotal=Decimal("150.00"),
        ))

        # Nota de crédito interna NC-PMM-00-0003 por $130.02 (distinta de CFDI Egreso)
        db.add(models.CustomerCreditLedger(
            id="nc-internal-0003", empresa_id=emp, sucursal_id="MATRIZ", client_id="cli-elvia",
            amount=Decimal("130.02"), transaction_type="NOTA_CREDITO_INTERNA", sale_id="sale-real-1",
            description="NC-PMM-00-0003 | BONIFICACIÓN APLICADA EN MOSTRADOR",
        ))
        # CFDI de Egreso fiscal separado
        db.add(models.CfdiDocument(
            id="cfdi-egreso-1", empresa_id=emp, sucursal_id="MATRIZ", sale_id="sale-real-1",
            tipo="E", serie="NCE", folio="0045", uuid_fiscal="11111111-2222-3333-4444-555555555555",
            status="TIMBRADO", total=Decimal("130.02"), receptor_rfc="PEVE850101AB1", receptor_nombre="ELVIA PEREA VERDUGO",
            xml='<?xml version="1.0" encoding="UTF-8"?><cfdi:Comprobante Version="4.0" TipoDeComprobante="E" SubTotal="112.09" Total="130.02"/>',
        ))
        db.add(models.CashShift(
            id="shift-open-1", empresa_id=emp, sucursal_id="MATRIZ",
            opened_by_id="JUAN", opening_amount=Decimal("1000.00"), expected_amount=Decimal("1150.00"), status="OPEN",
        ))
        db.commit()

        # Snapshot ANTES para prueba F de Integridad
        snap_before = {
            "sale_total": float(db.query(models.Sale).filter_by(id="sale-real-1").one().total),
            "cli_saldo": float(db.query(models.Client).filter_by(id="cli-elvia").one().saldo_actual),
            "cli_favor": float(db.query(models.Client).filter_by(id="cli-elvia").one().saldo_favor),
            "stock_qty": float(db.query(models.WarehouseStock).filter_by(product_id="prod-1").one().quantity),
            "shift_exp": float(db.query(models.CashShift).filter_by(id="shift-open-1").one().expected_amount),
        }

    hdr = _tok(emp)
    r_boot = client.get("/api/documents/bootstrap", headers=hdr)
    assert r_boot.status_code == 200
    assert r_boot.json()["session"]["company_profile"]["nombre_comercial"] == "MADERAS Y MATERIALES MAGDALENO"

    # Buscar NC-PMM-00-0003 y verificar importe exacto $130.02 y distinción frente a CFDI Egreso
    r_nc = client.get("/api/documents?q=NC-PMM-00-0003", headers=hdr)
    assert r_nc.status_code == 200
    items_nc = r_nc.json()["items"]
    assert len(items_nc) == 1
    nc_doc = items_nc[0]
    assert nc_doc["folio_visible"] == "NC-PMM-00-0003"
    assert nc_doc["doc_subtype"] == "nota_credito_interna"
    assert nc_doc["total_amount"] == 130.02
    assert nc_doc["doc_status"] == "APLICADA"
    assert nc_doc["fiscal_status"] == "INTERNO_NO_FISCAL"

    # Verificar que el CFDI de Egreso tiene identidad propia bajo Facturación
    r_ce = client.get("/api/documents?doc_subtype=cfdi_egreso", headers=hdr)
    assert r_ce.status_code == 200
    assert len(r_ce.json()["items"]) == 1
    assert r_ce.json()["items"][0]["doc_key"] != nc_doc["doc_key"]

    # Descargar PDF Carta, Ticket y exportar CSV + XLSX
    r_pdf = client.get(f"/api/documents/item/{nc_doc['id']}/file?format=CARTA", headers=hdr)
    assert r_pdf.status_code == 200
    assert r_pdf.content.startswith(b"%PDF-")

    r_csv = client.get("/api/documents/export?format=csv&scope=all_results", headers=hdr)
    assert r_csv.status_code == 200
    csv_text = r_csv.content.decode("utf-8-sig")
    # Celda que empezaba con '=' debe quedar sanitizada con comilla simple anti-fórmula
    assert "'=ELVIA PEREA VERDUGO" in csv_text

    r_xlsx = client.get("/api/documents/export?format=xlsx&scope=current_page", headers=hdr)
    assert r_xlsx.status_code == 200
    assert len(r_xlsx.content) > 500

    # Caso F: Comprobar integridad intacta después de consultar, previsualizar, descargar y exportar
    with SessionCls() as db:
        snap_after = {
            "sale_total": float(db.query(models.Sale).filter_by(id="sale-real-1").one().total),
            "cli_saldo": float(db.query(models.Client).filter_by(id="cli-elvia").one().saldo_actual),
            "cli_favor": float(db.query(models.Client).filter_by(id="cli-elvia").one().saldo_favor),
            "stock_qty": float(db.query(models.WarehouseStock).filter_by(product_id="prod-1").one().quantity),
            "shift_exp": float(db.query(models.CashShift).filter_by(id="shift-open-1").one().expected_amount),
        }
    assert snap_after == snap_before


def test_case_b_mostrador_sale_linked_delivery_evidence_formats_and_print_honesty(isolated_env):
    """Caso B: Localiza venta -> abre entrega vinculada -> sube/descarga evidencia -> Carta/Ticket -> Solicitud de impresión."""
    client, SessionCls = isolated_env
    emp = "EMP-MOST-01"

    with SessionCls() as db:
        db.add(models.Branch(empresa_id=emp, id="b1", name="MATRIZ", status="ACTIVE", is_main=True))
        db.add(models.Client(id="c-desierto", empresa_id=emp, sucursal_id="MATRIZ", name="CONSTRUCTORA DEL DESIERTO", rfc="CDE200101AA1"))
        db.add(_mk_sale(
            id="s-vta-1284", empresa_id=emp, sucursal_id="MATRIZ", folio="VTA-001284",
            client_id="c-desierto", total=Decimal("2450.00"), payment_method="001", status="completed",
        ))
        db.add(models.SafekeptItem(
            id="sk-1284", empresa_id=emp, sucursal_id="MATRIZ", sale_id="s-vta-1284",
            product_sku="TAB-PINO", quantity_ordered=Decimal("6"), quantity_delivered=Decimal("6"), status="ENTREGADO",
        ))
        db.add(models.KardexDelivery(
            id="ent-0874", empresa_id=emp, sucursal_id="MATRIZ", safekept_item_id="sk-1284",
            quantity_delivered=Decimal("6"), notes="ENTREGADO EN OBRA",
        ))
        # Traslado sin importe monetario para verificar distinción importe cero vs no aplicable
        db.add(models.Transfer(
            id="tr-0071", empresa_id=emp, folio="TRA-000071", status="RECIBIDO",
            sucursal_origen_id="MATRIZ", sucursal_destino_id="SUCURSAL NORTE",
            warehouse_origin_id="WH-MATRIZ", warehouse_dest_id="WH-NORTE", requested_by="ALM-01",
        ))
        db.commit()

    hdr = _tok(emp)
    r_list = client.get("/api/documents?q=VTA-001284", headers=hdr)
    assert r_list.status_code == 200
    sale_row = r_list.json()["items"][0]
    assert sale_row["folio_visible"] == "VTA-001284"

    # Abrir expediente de la venta y seguir su entrega vinculada
    r_exp = client.get(f"/api/documents/item/{sale_row['id']}", headers=hdr)
    assert r_exp.status_code == 200
    rels = r_exp.json()["related"]
    assert any(r["doc_subtype"] == "orden_entrega" and r["authorized"] for r in rels)
    ent_key = next(r["doc_key"] for r in rels if r["doc_subtype"] == "orden_entrega")

    # Subir evidencia PNG válida a la entrega y verificar rechazo de archivo ejecutable falso
    bad_upload = client.post(
        f"/api/documents/item/{ent_key}/attachments",
        headers=hdr,
        files={"file": ("virus.pdf", b"MZ-FAKE-EXE-BYTES", "application/pdf")},
    )
    assert bad_upload.status_code == 400

    ok_upload = client.post(
        f"/api/documents/item/{ent_key}/attachments",
        headers=hdr,
        files={"file": ("evidencia_patio.png", _make_png_bytes(), "image/png")},
        data={"kind": "EVIDENCIA_ENTREGA", "contains_amounts": "false", "notes": "firma chofer"},
    )
    assert ok_upload.status_code == 201
    att_id = ok_upload.json()["id"]
    assert ok_upload.json()["notes"] == "FIRMA CHOFER"  # Regla MAYÚSCULAS

    r_att = client.get(f"/api/documents/item/{ent_key}/file?format=ATTACHMENT&attachment_id={att_id}", headers=hdr)
    assert r_att.status_code == 200
    assert r_att.content[:8] == b"\x89PNG\r\n\x1a\n"

    # Cambiar Carta <-> Ticket en la venta y comprobar correspondencia exacta de folio
    p_carta = client.get(f"/api/documents/item/{sale_row['id']}/preview-page?mode=CARTA", headers=hdr).json()
    p_ticket = client.get(f"/api/documents/item/{sale_row['id']}/preview-page?mode=TICKET", headers=hdr).json()
    assert p_carta["folio_visible"] == "VTA-001284"
    assert p_ticket["folio_visible"] == "VTA-001284"
    assert p_carta["representation_meta"]["mode"] == "CARTA"
    assert p_ticket["representation_meta"]["mode"] == "TICKET"

    dl_carta = client.get(f"/api/documents/item/{sale_row['id']}/file?format=CARTA", headers=hdr)
    assert "VTA-001284_MATRIZ_CARTA.pdf" in dl_carta.headers.get("content-disposition", "")

    # Diálogo del navegador registra honestamente "Solicitud de impresión", NO "Impreso"
    pr_log = client.post(
        f"/api/documents/item/{sale_row['id']}/print-log",
        headers=hdr,
        json={"channel": "BROWSER_DIALOG", "format": "TICKET", "copies": 1},
    )
    assert pr_log.status_code == 200
    assert pr_log.json()["registered_status"] == "Solicitud de impresión"
    assert pr_log.json()["confirmed_physical_print"] is False

    # Verificar que Traslado reporta amount_state == NOT_APPLICABLE (distinto de $0.00)
    r_tr = client.get("/api/documents?q=TRA-000071", headers=hdr).json()["items"][0]
    assert r_tr["amount_applicable"] is False
    assert r_tr["amount_state"] == "NOT_APPLICABLE"
    assert r_tr["total_amount"] is None


def test_case_c_isolation_duplicate_folio_corte_z_rule_amount_redaction_and_branch_rotation(isolated_env):
    """Caso C: 2 empresas, 2 sucursales, folios visibles idénticos, regla de Cortes Z,
    protección integral de importes (almacenista) y conservación de sucursal al rotar empleado."""
    client, SessionCls = isolated_env

    with SessionCls() as db:
        db.add(models.Branch(empresa_id="EMP-A", id="ba-1", name="MATRIZ", status="ACTIVE", is_main=True))
        db.add(models.Branch(empresa_id="EMP-A", id="ba-2", name="SUCURSAL BOULEVARD", status="ACTIVE", is_main=False))
        db.add(models.Branch(empresa_id="EMP-B", id="bb-1", name="MATRIZ", status="ACTIVE", is_main=True))

        # Dos ventas con el MISMO folio visible "A-500" en dos sucursales distintas de EMP-A y otra en EMP-B
        db.add(_mk_sale(id="sa-matriz", empresa_id="EMP-A", sucursal_id="MATRIZ", folio="A-500", total=Decimal("310.00"), seller_id="emp-rot"))
        db.add(_mk_sale(id="sa-blvd", empresa_id="EMP-A", sucursal_id="SUCURSAL BOULEVARD", folio="A-500", total=Decimal("890.00"), seller_id="emp-2"))
        db.add(_mk_sale(id="sb-other", empresa_id="EMP-B", sucursal_id="MATRIZ", folio="A-500", total=Decimal("9999.00")))

        # Orden de entrega en MATRIZ (EMP-A) para probar rol almacenista sin permiso de importes
        db.add(models.SafekeptItem(id="sk-alm-1", empresa_id="EMP-A", sucursal_id="MATRIZ", sale_id="sa-matriz", product_sku="CEM-50KG", quantity_ordered=Decimal("10"), status="PENDIENTE"))

        # Dos Cortes Z en cajas/sucursales distintas de EMP-A
        db.add(models.CashShift(id="cz-1", empresa_id="EMP-A", sucursal_id="MATRIZ", opened_by_id="caj1", closed_by_id="caj1", opening_amount=Decimal("500"), expected_amount=Decimal("1500"), reported_amount=Decimal("1500"), difference=Decimal("0"), status="CLOSED"))
        db.add(models.CashShift(id="cz-2", empresa_id="EMP-A", sucursal_id="SUCURSAL BOULEVARD", opened_by_id="caj2", closed_by_id="caj2", opening_amount=Decimal("500"), expected_amount=Decimal("2100"), reported_amount=Decimal("2100"), difference=Decimal("0"), status="CLOSED"))

        # Documento RRHH
        now_utc = _dt.datetime.utcnow()
        db.add(models.Employee(id="emp-rot", empresa_id="EMP-A", sucursal_id="MATRIZ", user_id="emp-rot", full_name="PEDRO ROTACIÓN"))
        db.add(models.AttendanceAuthorization(
            user_id="emp-rot", empresa_id="EMP-A", sucursal_id="MATRIZ", event_date="2026-11-20",
            entrada_ts=now_utc, intento_ts=now_utc, status="AUTORIZADO", horas_transcurridas=6.5,
        ))
        db.commit()

    hdr_admin_a = _tok("EMP-A", "MATRIZ", "Administrador", "ADMIN_A")
    hdr_cajero_blvd = _tok("EMP-A", "SUCURSAL BOULEVARD", "Cajero", "CAJ_BLVD")
    hdr_almacen_a = _tok("EMP-A", "MATRIZ", "Almacenista", "ALM_MATRIZ")
    hdr_admin_b = _tok("EMP-B", "MATRIZ", "Administrador", "ADMIN_B")

    # 1. Admin A ve sus dos "A-500" (Matriz $310 y Boulevard $890) y NUNCA ve el $9999 de EMP-B
    res_a = client.get("/api/documents?q=A-500", headers=hdr_admin_a).json()["items"]
    assert len(res_a) == 2
    totals_by_key = {r["doc_key"]: r["total_amount"] for r in res_a}
    assert totals_by_key["EMP-A::sales::sa-matriz"] == 310.0
    assert totals_by_key["EMP-A::sales::sa-blvd"] == 890.0

    # Admin B no puede abrir el doc_key de EMP-A
    cross = client.get("/api/documents/item/EMP-A::sales::sa-matriz", headers=hdr_admin_b)
    assert cross.status_code == 404

    # 2. Cajero de SUCURSAL BOULEVARD solo ve su sede y recibe 403 si intenta consultar MATRIZ
    res_blvd = client.get("/api/documents?q=A-500", headers=hdr_cajero_blvd).json()["items"]
    assert len(res_blvd) == 1
    assert res_blvd[0]["sucursal_id"] == "SUCURSAL BOULEVARD"
    assert client.get("/api/documents?sucursal_id=MATRIZ", headers=hdr_cajero_blvd).status_code == 403
    assert client.get("/api/documents/item/EMP-A::sales::sa-matriz", headers=hdr_cajero_blvd).status_code == 403

    # 3. Rotar al empleado a SUCURSAL BOULEVARD y verificar que la venta sa-matriz conserva sucursal MATRIZ
    with SessionCls() as db:
        emp_obj = db.query(models.Employee).filter_by(id="emp-rot").one()
        emp_obj.sucursal_id = "SUCURSAL BOULEVARD"
        db.commit()
    client.post("/api/documents/sync", headers=hdr_admin_a, json={})
    exp_rot = client.get("/api/documents/item/EMP-A::sales::sa-matriz", headers=hdr_admin_a).json()
    assert exp_rot["document"]["sucursal_id"] == "MATRIZ"

    # 4. Regla de Cortes Z: consolidado en pantalla SOLO para Admin General; prohibido exportar, imprimir reporte o lote ZIP consolidado
    cz_admin = client.get("/api/documents?doc_subtype=corte_z", headers=hdr_admin_a).json()
    assert cz_admin["corte_z_consolidado_screen"] is not None
    assert cz_admin["corte_z_consolidado_screen"]["grand_total"] == 3600.0

    cz_cajero = client.get("/api/documents?doc_subtype=corte_z", headers=hdr_cajero_blvd).json()
    assert cz_cajero["corte_z_consolidado_screen"] is None

    assert client.get("/api/documents/export?doc_subtype=corte_z&sucursal_id=ALL", headers=hdr_admin_a).status_code == 403
    assert client.get("/api/documents/report-print?doc_subtype=corte_z&sucursal_id=ALL", headers=hdr_admin_a).status_code == 403
    assert client.post("/api/documents/download-batch", headers=hdr_admin_a, json={"doc_keys": ["EMP-A::cash_shifts::cz-1", "EMP-A::cash_shifts::cz-2"]}).status_code == 403

    # Pero el comprobante individual de una caja sí está disponible
    assert client.get("/api/documents/item/EMP-A::cash_shifts::cz-1/file?format=TICKET", headers=hdr_admin_a).status_code == 200

    # 5. Protección de importes (Almacenista: view_amounts == False) y protección RRHH
    alm_list = client.get("/api/documents", headers=hdr_almacen_a).json()["items"]
    sale_for_alm = next(x for x in alm_list if x["doc_key"] == "EMP-A::sales::sa-matriz")
    assert sale_for_alm["amount_state"] == "REDACTED"
    assert sale_for_alm["total_amount"] is None
    # Bloquea filtro por rango de importes y descarga de PDF de venta monetaria
    assert client.get("/api/documents?importe_min=100", headers=hdr_almacen_a).status_code == 403
    assert client.get("/api/documents/item/EMP-A::sales::sa-matriz/file?format=CARTA", headers=hdr_almacen_a).status_code == 403
    # Permite generar orden de entrega sanitizada sin importes
    assert client.get("/api/documents/item/EMP-A::safekept_items::sk-alm-1/file?format=CARTA", headers=hdr_almacen_a).status_code == 200
    # Bloquea acceso de Almacenista a RRHH
    assert client.get("/api/documents?category=rrhh", headers=hdr_almacen_a).status_code == 403


def test_case_d_historical_multipage_missing_original_and_conserved_immutability(isolated_env):
    """Caso D: Cotización multipágina (>= 2 hojas), histórico reconstruido sin original,
    y cambio de plantilla verificando que el original conservado permanece byte a byte idéntico."""
    client, SessionCls = isolated_env
    emp = "EMP-HIST-01"

    with SessionCls() as db:
        db.add(models.Branch(empresa_id=emp, id="bh-1", name="MATRIZ", status="ACTIVE", is_main=True))
        q = models.Quote(
            id="qt-multi-32", empresa_id=emp, sucursal_id="MATRIZ", folio="COT-MULTI-01",
            client_id="cli-luis", client_name="LUIS ESCÁRCEGA", total=Decimal("32000.00"), status="VIGENTE",
        )
        db.add(q)
        for idx in range(1, 33):
            db.add(models.QuoteItem(
                id=f"qi-{idx}", empresa_id=emp, sucursal_id="MATRIZ", quote_id="qt-multi-32",
                product_sku=f"SKU-{idx:03d}", description=f"PARTIDA ESTRUCTURAL NÚMERO {idx}",
                quantity=Decimal("2"), price=Decimal("500.00"), subtotal=Decimal("1000.00"),
            ))
        db.add(_mk_sale(id="sale-conserved-1", empresa_id=emp, sucursal_id="MATRIZ", folio="VTA-CONS-01", total=Decimal("580.00")))
        db.commit()

    hdr = _tok(emp)
    client.get("/api/documents/bootstrap", headers=hdr)

    # 1. Documento multipágina en modo reconstrucción explícita -> indica qué se reconstruyó y pagina >= 2 hojas
    prev_mp = client.get("/api/documents/item/EMP-HIST-01::quotes::qt-multi-32/preview-page?mode=CARTA&representation=reconstructed&page=1", headers=hdr).json()
    assert prev_mp["total_pages"] >= 2
    assert prev_mp["representation_meta"]["kind"] == "RECONSTRUCCION_HISTORICA"
    assert len(prev_mp["representation_meta"]["reconstructed_elements"]) >= 3

    # Al solicitar representation=original emite y conserva automáticamente el documento original
    prev_auto_orig = client.get("/api/documents/item/EMP-HIST-01::quotes::qt-multi-32/preview-page?mode=CARTA&representation=original&page=1", headers=hdr).json()
    assert prev_auto_orig["representation_meta"]["kind"] == "ORIGINAL_CONSERVADO"
    assert prev_auto_orig["representation_meta"]["is_conserved_original"] is True

    # 2. Emitir representación original conservada para VTA-CONS-01
    tpls = client.get("/api/print-formats/templates?doc_type=ticket_venta_contado&mode=CARTA", headers=hdr).json()["templates"]
    carta_tpl = tpls[0]
    em_res = client.post("/api/print-formats/emissions", headers=hdr, json={
        "doc_type": "ticket_venta_contado",
        "operation_id": "sale-conserved-1",
        "template_id": carta_tpl["id"],
    })
    assert em_res.status_code == 201

    client.post("/api/documents/sync", headers=hdr, json={})
    orig_before = client.get("/api/documents/item/EMP-HIST-01::sales::sale-conserved-1/preview-page?mode=CARTA&representation=original", headers=hdr).json()
    assert orig_before["representation_meta"]["kind"] == "ORIGINAL_CONSERVADO"
    sha_before = orig_before["representation_meta"]["sha256"]

    # 3. Modificar y publicar una nueva versión (v2) de esa plantilla en el entorno de prueba
    tpl_detail = client.get(f"/api/print-formats/templates/{carta_tpl['id']}", headers=hdr).json()
    new_def = dict(tpl_detail["working_version"]["definition_json"])
    new_els = list(new_def.get("elements") or [])
    new_els.append({
        "id": "el-banner-v2", "type": "text", "label": "CAMBIO V2", "text": "NUEVO ENCABEZADO PLANTILLA V2",
        "x_mm": 15.0, "y_mm": 255.0, "w_mm": 160.0, "h_mm": 10.0, "font_size": 14, "bold": True, "color": "#dc2626", "page": 1,
    })
    new_def["elements"] = new_els
    r_draft = client.put(f"/api/print-formats/templates/{carta_tpl['id']}/draft", headers=hdr, json={"definition_json": new_def, "changelog": "PRUEBA V2"})
    assert r_draft.status_code == 200
    r_pub = client.post(f"/api/print-formats/templates/{carta_tpl['id']}/publish", headers=hdr, json={})
    assert r_pub.status_code == 200
    assert r_pub.json()["current_version_num"] == 2
    assert r_pub.json()["working_version"]["status"] == "PUBLISHED"

    # 4. Confirmar que el original conservado (v1) sigue IDÉNTICO mientras updated usa v2
    orig_after = client.get("/api/documents/item/EMP-HIST-01::sales::sale-conserved-1/preview-page?mode=CARTA&representation=original", headers=hdr).json()
    assert orig_after["representation_meta"]["version_num"] == 1
    assert orig_after["representation_meta"]["sha256"] == sha_before

    upd_after = client.get("/api/documents/item/EMP-HIST-01::sales::sale-conserved-1/preview-page?mode=CARTA&representation=updated", headers=hdr).json()
    assert upd_after["representation_meta"]["kind"] == "NUEVA_REPRESENTACION"
    assert upd_after["representation_meta"]["version_num"] == 2
    assert upd_after["representation_meta"]["sha256"] != sha_before


def test_case_e_dispatch_preview_idempotency_partial_batch_retry_and_share_link_revocation(isolated_env):
    """Caso E: Preview antes de confirmar, envío individual + lote con fallo parcial en canal de prueba,
    idempotencia ante doble clic, reintento seguro conservando éxitos y revocación de enlace."""
    client, SessionCls = isolated_env
    emp = "EMP-SEND-01"

    with SessionCls() as db:
        db.add(models.Branch(empresa_id=emp, id="bs-1", name="MATRIZ", status="ACTIVE", is_main=True))
        db.add(_mk_sale(id="sd-1", empresa_id=emp, sucursal_id="MATRIZ", folio="VTA-S01", total=Decimal("420.00")))
        db.add(_mk_sale(id="sd-2", empresa_id=emp, sucursal_id="MATRIZ", folio="VTA-S02", total=Decimal("780.00")))
        db.commit()

    hdr = _tok(emp)
    client.get("/api/documents/bootstrap", headers=hdr)

    batch_items = [
        {"doc_key": "EMP-SEND-01::sales::sd-1", "recipient": "cliente.ok@pruebas.dev", "formats": ["CARTA"]},
        {"doc_key": "EMP-SEND-01::sales::sd-2", "recipient": "cliente.fail@pruebas.dev", "formats": ["CARTA"]},
    ]

    # 1. Previsualización exacta antes de confirmar
    prev = client.post("/api/documents/dispatch/preview", headers=hdr, json={
        "channel": "EMAIL",
        "message": "envio de comprobantes de prueba",
        "items": batch_items,
    })
    assert prev.status_code == 200
    assert prev.json()["message_normalized"] == "ENVIO DE COMPROBANTES DE PRUEBA"
    assert len(prev.json()["recipients_summary"]) == 2
    assert "VTA-S01_MATRIZ_CARTA.pdf" in prev.json()["recipients_summary"][0]["exact_files"]

    # 2. Ejecutar lote con fallo parcial e idempotencia por operation_key
    op_key = f"OP-TEST-{uuid.uuid4().hex[:10]}"
    disp1 = client.post("/api/documents/dispatch", headers=hdr, json={
        "operation_key": op_key,
        "channel": "EMAIL",
        "message": "envio de comprobantes de prueba",
        "is_test_mode": True,
        "items": batch_items,
    })
    assert disp1.status_code == 200
    d1 = disp1.json()
    assert d1["status"] == "PARTIAL_FAILURE"
    assert d1["delivery_scope"] == "INTEGRATION_TEST"
    assert d1["succeeded_items"] == 1
    assert d1["failed_items"] == 1
    # Honesto: nunca marcar "Entregado" sin confirmación real del proveedor
    ok_item = next(i for i in d1["items"] if i["folio_visible"] == "VTA-S01")
    fail_item = next(i for i in d1["items"] if i["folio_visible"] == "VTA-S02")
    assert ok_item["provider_delivery_confirmed"] is False
    assert "Entregado" not in ok_item["ui_status_label"]
    assert fail_item["safe_to_retry"] is True

    # Doble clic con mismo operation_key -> replay idempotente sin reenviar
    disp_dup = client.post("/api/documents/dispatch", headers=hdr, json={
        "operation_key": op_key,
        "channel": "EMAIL",
        "message": "envio de comprobantes de prueba",
        "is_test_mode": True,
        "items": batch_items,
    })
    assert disp_dup.status_code == 200
    assert disp_dup.json()["idempotent_replay"] is True

    # 3. Reintentar corrigiendo destinatario fallido: el éxito previo conserva attempt_count == 1
    retry_res = client.post(
        f"/api/documents/dispatch/{d1['operation_id']}/retry",
        headers=hdr,
        json={"override_recipients": {fail_item["id"]: "cliente.recuperado@pruebas.dev"}},
    )
    assert retry_res.status_code == 200
    dr = retry_res.json()
    assert dr["status"] == "COMPLETED"
    assert dr["succeeded_items"] == 2
    ok_after = next(i for i in dr["items"] if i["folio_visible"] == "VTA-S01")
    rec_after = next(i for i in dr["items"] if i["folio_visible"] == "VTA-S02")
    assert ok_after["attempt_count"] == 1  # Conservó el éxito intacto sin reenviarlo
    assert rec_after["attempt_count"] == 2

    # 4. Enlace seguro limitado al archivo con vencimiento y revocación inmediata
    sh = client.post("/api/documents/share-links", headers=hdr, json={
        "doc_key": "EMP-SEND-01::sales::sd-1",
        "format_code": "CARTA",
        "expires_in_hours": 24,
        "max_downloads": 2,
    })
    assert sh.status_code == 201
    share_path = sh.json()["share_path"]
    link_id = sh.json()["id"]

    r_dl_pub = client.get(share_path)
    assert r_dl_pub.status_code == 200
    assert r_dl_pub.content.startswith(b"%PDF-")

    r_rev = client.post(f"/api/documents/share-links/{link_id}/revoke", headers=hdr)
    assert r_rev.status_code == 200
    assert client.get(share_path).status_code == 410
