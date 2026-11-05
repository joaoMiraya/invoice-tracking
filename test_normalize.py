"""Testes da normalizacao de merchant.

Foco no bug que o usuario apontou: "99*" nao pode engolir "99FOOD", e
"99FOOD" nao pode cair em "99". Usamos os nomes brutos reais da fatura.
"""

from __future__ import annotations

import pytest

from normalize import normalize_merchant


@pytest.mark.parametrize("raw,category,expected", [
    # --- o bug central: 99 vs 99Food ---
    ("99FOOD *VIVA A AITERIAC", "restaurante", "99Food"),
    ("99Food *Deck 31 pending", "restaurante", "99Food"),
    ("99FOOD *MARMITEX TOP BC", "restaurante", "99Food"),
    ("99*SAO PAULOBR", "transporte", "99"),
    ("DL*99 RIDESAO PAULOBR", "transporte", "99"),
    # --- Uber nas varias formas ---
    ("DL *UberRidesS", "transporte", "Uber"),
    ("DL*UberRidesSao PauloBR", "transporte", "Uber"),
    ("UBER *TRIP HELP.UBER.CO", "transporte", "Uber"),
    # --- iFood ---
    ("IFOODCOM AGENCIA DE RIN", "restaurante", "iFood"),
    ("IFD*MERLIM DA CRUZ RES", "restaurante", "iFood"),
    ("IFD*iFoodOsascoBR", "outros", "iFood Clube"),
    # --- outros servicos ---
    ("MERCADOLIVRE*M 01/03", "supermercado", "Mercado Livre"),
    ("Wellhub Joao MirayaSao", "outros", "Wellhub"),
    ("KIRO PROKIRO.DEVUS", None, "Kiro"),
    ("OVHcloudLisboaPT", None, "OVHcloud"),
])
def test_normalizacao_conhecida(raw, category, expected):
    result = normalize_merchant(raw, category)
    assert result.matched is True
    assert result.canonical == expected


def test_99food_nunca_vira_99():
    for raw in ("99FOOD *VIVA", "99Food *Deck"):
        assert normalize_merchant(raw, "restaurante").canonical == "99Food"


def test_99_transporte_nunca_vira_99food():
    assert normalize_merchant("99*SAO PAULOBR", "transporte").canonical == "99"


def test_99_sem_categoria_transporte_nao_casa_regra_99():
    # "99*" sem categoria transporte nao deve virar "99" (desempate exige)
    result = normalize_merchant("99*ALGO ESTRANHO", category=None)
    assert result.canonical != "99" or result.matched is False


def test_desconhecido_retorna_fallback_nao_casado():
    result = normalize_merchant("TABACARIA E CONVENIENCI", "outros")
    assert result.matched is False
    assert result.canonical  # algum nome legivel
