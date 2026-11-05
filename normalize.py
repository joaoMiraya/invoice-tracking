"""Normalizacao de estabelecimento (merchant).

Os nomes impressos na fatura sao sujos e inconsistentes. O mesmo servico
aparece de varias formas:

    Uber:   "DL *UberRidesS", "DL*UberRidesSao PauloBR", "UBER *TRIP HELP..."
    99:     "99*SAO PAULOBR", "DL*99 RIDESAO PAULOBR"
    99Food: "99FOOD *VIVA...", "99Food *Deck 31 pending"
    iFood:  "IFOODCOM AGENCIA...", "IFD*MERLIM...", "IFD*iFoodOsascoBR"

Mapeamos cada nome bruto para um nome canonico usando uma lista ORDENADA de
regras. A primeira regra que casa vence, entao regras mais especificas vem
primeiro (99Food antes de 99). Cada regra pode exigir uma categoria do Itau
como desempate: "99" so vale se a categoria for "transporte"; senao o mesmo
texto poderia ser 99Food.

O que nao casar com nenhuma regra retorna um nome canonico derivado do texto
bruto e `matched=False`, para aparecer numa lista de "nao classificados".

Uma regra tambem pode FIXAR a categoria, por cima da impressa pelo Itau, que e
inconsistente para alguns servicos (iFood ja veio como transporte e
supermercado). Sem categoria fixada, vale a do Itau.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class MerchantRule:
    canonical: str
    pattern: re.Pattern[str]
    # Se definido, a regra so casa quando a categoria do Itau for uma destas.
    categories: frozenset[str] | None = None
    # Se definido, substitui a categoria impressa pelo Itau.
    category: str | None = None


def _rule(
    canonical: str,
    regex: str,
    categories: set[str] | None = None,
    category: str | None = None,
) -> MerchantRule:
    return MerchantRule(
        canonical=canonical,
        pattern=re.compile(regex, re.IGNORECASE),
        categories=frozenset(categories) if categories else None,
        category=category,
    )


SUBSCRIPTIONS = "assinaturas"
RESTAURANT = "restaurante"

# ORDEM IMPORTA: do mais especifico para o mais generico.
RULES: list[MerchantRule] = [
    # 99Food antes de 99 — senao "99" guloso capturaria "99FOOD".
    _rule("99Food", r"99\s*food", category=RESTAURANT),
    # iFood Clube (cobranca mensal "iFood Osasco") antes do iFood generico.
    _rule("iFood Clube", r"ifood\s*osasco", category=SUBSCRIPTIONS),
    _rule("iFood", r"ifood|\bifd\*", category=RESTAURANT),
    _rule("Uber", r"uber\s*rides|uber\s*\*|\buber\b"),
    # 99 (mobilidade): asterisco apos o 99, ou "99 ride". So transporte.
    _rule("99", r"\b99\*|\b99\s*ride", categories={"transporte"}),
    # Marketplace: mantem a categoria do Itau.
    _rule("Mercado Livre", r"mercado\s*livre|mercadolivre"),
    _rule("Wellhub", r"wellhub|gympass", category=SUBSCRIPTIONS),
    _rule("Kiro", r"kiro\s*pro|kiro\.dev", category=SUBSCRIPTIONS),
    _rule("OVHcloud", r"ovhcloud|ovh\b", category=SUBSCRIPTIONS),
]


@dataclass(frozen=True)
class NormalizedMerchant:
    canonical: str
    matched: bool
    # Categoria fixada pela regra (None = usar a do Itau).
    category: str | None = None

    def category_for(self, itau_category: str | None) -> str | None:
        """Categoria efetiva: a da regra, senao a impressa pelo Itau."""
        return self.category or itau_category


def _fallback_name(raw: str) -> str:
    """Nome legivel para merchant sem regra.

    So removemos prefixos de ADQUIRENTE conhecidos que aparecem antes de um
    "*" (ex. "DL*", "IFD*"). Nao removemos letras arbitrarias, senao cortamos
    o inicio de nomes legitimos (UNIMAR -> MAR, SPAZIO -> ZIO).
    """
    # "DL*Foo" / "DL *Foo" / "IFD*Foo" -> remove o prefixo adquirente + "*"
    cleaned = re.sub(r"^[A-Z]{2,4}\s*\*\s*", "", raw).strip()
    return cleaned or raw


def normalize_merchant(raw: str, category: str | None = None) -> NormalizedMerchant:
    """Mapeia um nome bruto para o nome canonico do servico.

    A categoria do Itau (quando disponivel) desempata regras ambiguas.
    """
    for rule in RULES:
        if rule.categories is not None:
            if category is None or category.lower() not in rule.categories:
                continue
        if rule.pattern.search(raw):
            return NormalizedMerchant(
                canonical=rule.canonical, matched=True, category=rule.category
            )
    return NormalizedMerchant(canonical=_fallback_name(raw), matched=False)
