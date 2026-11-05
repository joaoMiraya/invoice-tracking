"""Regras de categoria por cima da categoria impressa pelo Itau.

Decisoes do usuario:
1. iFood e 99Food sempre "restaurante"; a cobranca iFood Clube vira "assinaturas".
2. Mercado Livre mantem a categoria do Itau (marketplace).
3. Kiro, OVHcloud e Wellhub sao "assinaturas".
4. Parcela sem categoria herda a categoria de outra parcela da mesma compra.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from extract import extract_invoice
from normalize import normalize_merchant
from storage import connect, save_invoice


@pytest.mark.parametrize("raw,itau,merchant,category", [
    ("IFD*55.386.344GABRIEL", "transporte", "iFood", "restaurante"),
    ("IFD*60118671MARIADASP", "supermercado", "iFood", "restaurante"),
    ("IFOODCOM AGENCIA DE RIN", "restaurante", "iFood", "restaurante"),
    ("99FOOD*AMERICANBURGUC", "transporte", "99Food", "restaurante"),
    ("99FOOD*POINTDABATATC", "supermercado", "99Food", "restaurante"),
    ("IFD*iFoodOsascoBR", "outros", "iFood Clube", "assinaturas"),
    ("iFoodOsascoBR", "outros", "iFood Clube", "assinaturas"),
    ("KIRO PROKIRO.DEVUS", None, "Kiro", "assinaturas"),
    ("OVHcloudLisboaPT", None, "OVHcloud", "assinaturas"),
    ("WellhubJoaoMirayaSao", "outros", "Wellhub", "assinaturas"),
    # Mercado Livre: mantem a do Itau
    ("MERCADOLIVRE*M 01/03", "supermercado", "Mercado Livre", "supermercado"),
    ("MERCADOLIVRE*2 02/02", "eletrônicos", "Mercado Livre", "eletrônicos"),
    # sem regra de categoria: mantem a do Itau
    ("DL*UberRidesSaoPauloBR", "transporte", "Uber", "transporte"),
    ("TABACARIA E CONVENIENCI", "outros", "TABACARIA E CONVENIENCI", "outros"),
])
def test_categoria_efetiva(raw, itau, merchant, category):
    n = normalize_merchant(raw, itau)
    assert (n.canonical, n.category_for(itau)) == (merchant, category)


PDF_DIR = Path(__file__).parent / "faturas_pdf"


@pytest.mark.skipif(not (PDF_DIR / "2026-05.pdf").exists(), reason="faturas ausentes")
def test_parcela_sem_categoria_herda_de_outra_parcela_em_qualquer_ordem():
    conn = connect(":memory:")
    # ordem invertida de proposito: a parcela com categoria (jan) entra por ultimo
    for period in ("2026-05", "2026-02", "2026-01"):
        save_invoice(conn, extract_invoice(str(PDF_DIR / f"{period}.pdf")))

    rows = conn.execute(
        "SELECT period, category, category_itau FROM transactions "
        "WHERE merchant_raw LIKE 'MLP*Netshoes%' ORDER BY period"
    ).fetchall()
    assert [r["period"] for r in rows] == ["2026-01", "2026-02", "2026-05"]
    assert [r["category"] for r in rows] == ["vestuário"] * 3
    # a categoria original do Itau continua guardada
    assert [r["category_itau"] for r in rows] == ["vestuário", None, None]
