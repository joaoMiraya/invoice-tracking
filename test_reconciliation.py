"""Reconciliacao do parser contra os totais IMPRESSOS em cada fatura.

Os valores esperados foram lidos dos PDFs (linhas "Lançamentos no cartão",
"Lançamentos produtos e serviços", "Total lançamentos inter. em R$" e
"Total dos lançamentos atuais") e ficam fixos aqui, independentes do parser.
Uma fatura so esta correta se TODAS as secoes baterem ao centavo.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from extract import extract_invoice

PDF_DIR = Path(__file__).parent / "faturas_pdf"

D = Decimal
# periodo: (compras e saques, produtos e servicos, internacional, total atual)
EXPECTED = {
    "2026-01": (D("899.19"), None, None, D("899.19")),
    "2026-02": (D("1209.59"), D("-452.83"), None, D("756.76")),
    "2026-03": (D("885.72"), D("230.98"), None, D("1116.70")),
    "2026-04": (D("1730.08"), D("230.98"), None, D("1961.06")),
    "2026-05": (D("2008.24"), D("230.98"), None, D("2239.22")),
    "2026-06": (D("1566.75"), None, None, D("1566.75")),
    "2026-07": (D("1910.77"), None, None, D("1910.77")),
    "2026-08": (D("1826.44"), None, None, D("1826.44")),
    "2026-09": (D("2077.97"), None, None, D("2077.97")),
    "2026-10": (D("1753.00"), None, None, D("1753.00")),
    "2026-11": (D("1631.11"), None, D("267.13"), D("1898.24")),
}
# "Total de encargos em R$" (multa, juros, IOF de atraso), so onde existe.
FEES = {"2026-01": D("34.62")}


def _sum(txs, section):
    items = [t.amount for t in txs if t.section == section]
    return sum(items) if items else None


@pytest.mark.parametrize("period", sorted(EXPECTED))
def test_reconcilia_com_totais_impressos(period):
    pdf = PDF_DIR / f"{period}.pdf"
    if not pdf.exists():
        pytest.skip(f"{pdf.name} ausente")

    inv = extract_invoice(str(pdf))
    purchases, services, international, total = EXPECTED[period]

    assert inv.period == period
    assert _sum(inv.transactions, "purchases") == purchases
    assert _sum(inv.transactions, "services") == services
    assert _sum(inv.transactions, "international") == international
    assert _sum(inv.transactions, "fees") == FEES.get(period)
    assert sum(t.amount for t in inv.transactions if t.section != "fees") == total


@pytest.mark.parametrize("period", sorted(EXPECTED))
def test_parser_le_os_totais_impressos(period):
    """O parser tambem le os totais impressos, para o app alertar divergencia."""
    pdf = PDF_DIR / f"{period}.pdf"
    if not pdf.exists():
        pytest.skip(f"{pdf.name} ausente")

    inv = extract_invoice(str(pdf))
    assert inv.reconciliation_errors() == []
