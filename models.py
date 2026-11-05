"""Modelo de dominio das transacoes extraidas de uma fatura."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from decimal import Decimal

# Secoes que compoem o "Total dos lançamentos atuais".
SECTIONS = ("purchases", "services", "international")
# Encargos (multa, juros, IOF de atraso) listados junto das compras, mas que a
# fatura soma a parte: "Total de encargos em R$". Bucket proprio.
FEES_SECTION = "fees"


@dataclass
class Transaction:
    """Uma linha de lancamento da fatura.

    day_month:    dia/mes como aparece na fatura (ex. "08/10").
    merchant_raw: nome do estabelecimento exatamente como impresso (sujo).
    category:     categoria impressa pelo Itau, "encargos" para multa/juros/IOF,
                  "parcelamento de fatura" para refinanciamento, ou None.
    city:         cidade impressa na 2a linha, ou None.
    amount:       valor em R$ (positivo = debito; negativo = credito).
    kind:         "national" | "international".
    section:      "purchases" (compras e saques) | "services" (produtos e
                  servicos) | "international".
    date:         data completa resolvida a partir do vencimento.
    """

    day_month: str
    merchant_raw: str
    category: str | None
    city: str | None
    amount: Decimal
    kind: str = "national"
    section: str = "purchases"
    date: date | None = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["amount"] = str(self.amount)
        d["date"] = self.date.isoformat() if self.date else None
        return d


@dataclass
class ParsedInvoice:
    """Resultado de parsear um PDF de fatura.

    due_date:     data de vencimento (define o mes/ano de competencia).
    transactions: lancamentos com data completa.
    printed:      totais impressos na fatura, por secao, mais "total".
    """

    due_date: date
    transactions: list[Transaction] = field(default_factory=list)
    printed: dict[str, Decimal] = field(default_factory=dict)

    @property
    def period(self) -> str:
        return f"{self.due_date.year:04d}-{self.due_date.month:02d}"

    def reconciliation_errors(self) -> list[str]:
        """Divergencias entre a soma extraida e os totais impressos.

        Lista vazia = a extracao bate ao centavo com a fatura.
        """
        errors: list[str] = []
        for section in (*SECTIONS, FEES_SECTION):
            parsed = [t.amount for t in self.transactions if t.section == section]
            got = sum(parsed) if parsed else None
            want = self.printed.get(section)
            if got != want:
                errors.append(f"{section}: extraido {got}, impresso {want}")
        got_total = sum(t.amount for t in self.transactions if t.section in SECTIONS)
        want_total = self.printed.get("total")
        if want_total is None:
            errors.append("total impresso nao encontrado")
        elif got_total != want_total:
            errors.append(f"total: extraido {got_total}, impresso {want_total}")
        return errors
