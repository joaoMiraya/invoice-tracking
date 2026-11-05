"""Testes de comportamento do parser na fatura de 2026-11.

A reconciliacao das 11 faturas fica em test_reconciliation.py; aqui ficam
propriedades especificas que a soma nao pega.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from extract import extract_transactions

FATURA = Path(__file__).parent / "faturas_pdf" / "2026-11.pdf"

pytestmark = pytest.mark.skipif(not FATURA.exists(), reason="fatura ausente")


@pytest.fixture(scope="module")
def txs():
    return extract_transactions(str(FATURA))


def test_sem_pagamentos(txs):
    assert all(t.amount > 0 for t in txs)


def test_compras_nacionais_tem_categoria(txs):
    sem = [t for t in txs if t.section == "purchases" and t.category is None]
    assert sem == []


def test_internacionais_incluem_repasse_de_iof(txs):
    inter = [t for t in txs if t.section == "international"]
    assert [t.merchant_raw for t in inter if t.category == "encargos"] == ["Repasse de IOF"]
    assert len(inter) == 4  # 3 compras + repasse de IOF


def test_parcela_futura_nao_entra(txs):
    assert not any("02/03" in t.merchant_raw for t in txs)
