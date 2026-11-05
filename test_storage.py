"""Testes da persistencia SQLite."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from extract import extract_invoice
from storage import (
    connect,
    list_periods,
    save_invoice,
    total_by_category,
    total_by_merchant,
)

FATURA = Path(__file__).parent / "faturas_pdf" / "2026-11.pdf"

pytestmark = pytest.mark.skipif(not FATURA.exists(), reason="fatura ausente")


@pytest.fixture
def conn():
    c = connect(":memory:")
    yield c
    c.close()


@pytest.fixture
def invoice():
    return extract_invoice(str(FATURA))


def test_salva_e_lista_competencia(conn, invoice):
    assert save_invoice(conn, invoice) == len(invoice.transactions)
    assert list_periods(conn) == ["2026-11"]


def test_reupload_e_idempotente(conn, invoice):
    save_invoice(conn, invoice)
    save_invoice(conn, invoice)
    count = conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
    assert count == len(invoice.transactions)


def test_total_por_categoria_bate_com_fatura(conn, invoice):
    save_invoice(conn, invoice)
    cats = total_by_category(conn, "2026-11")
    assert {"transporte", "restaurante", "encargos"} <= set(cats)
    assert sum(cats.values()) == Decimal("1898.24")


def test_total_por_merchant_separa_99_de_99food(conn, invoice):
    save_invoice(conn, invoice)
    merchants = total_by_merchant(conn, "2026-11")
    assert merchants["Uber"] == Decimal("332.00")
    assert merchants["99"] == Decimal("69.35")
    assert merchants["99Food"] == Decimal("92.43")


def test_secao_e_persistida(conn, invoice):
    save_invoice(conn, invoice)
    sections = {r[0] for r in conn.execute("SELECT DISTINCT section FROM transactions")}
    assert sections == {"purchases", "international"}
