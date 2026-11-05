"""Extrai transacoes de uma fatura Itau (PDF com texto selecionavel).

Estrategia (guiada pelo conteudo, nao por coordenadas fixas):

1. Cada pagina tem duas colunas. O ponto de corte e calculado por pagina a
   partir da posicao das datas da coluna direita (varia entre faturas:
   x~350 em uma, x~360 em outras).
2. As palavras de cada coluna sao agrupadas em linhas visuais e lidas em ordem
   de leitura: coluna esquerda, depois direita, pagina a pagina.
3. Uma maquina de estados acompanha a SECAO corrente pelos cabecalhos
   ("Lançamentos: compras e saques", "produtos e serviços", "internacionais",
   "Pagamentos efetuados", "Compras parceladas - próximas faturas"...). So as
   secoes que compoem o total da fatura geram transacoes.
4. Os cabecalhos e totais sao comparados SEM espacos e sem acento, porque
   varias faturas nao tem caracteres de espaco no PDF ("Lançamentos:compras
   esaques", "supermercadoTEODOROSAMPA").
5. Os totais impressos sao lidos junto, e `ParsedInvoice.reconciliation_errors`
   aponta qualquer divergencia.

Uso:
    python extract.py /caminho/para/fatura.pdf
"""

from __future__ import annotations

import re
import sys
import unicodedata
from datetime import date
from decimal import Decimal

import pdfplumber

from models import ParsedInvoice, Transaction

LINE_TOLERANCE = 3.0  # palavras com `top` ate esta distancia = mesma linha
DEFAULT_SPLIT_X = 345.0  # corte entre colunas quando a direita nao tem datas
RIGHT_DATE_X = (330.0, 380.0)  # faixa onde ficam as datas da coluna direita

DATE_RE = re.compile(r"^\d{2}/\d{2}")
MONEY_RE = re.compile(r"^-?[\d.]+,\d{2}$")
TX_LINE_RE = re.compile(r"^(\d{2}/\d{2})\s*(.*?)\s+(-?[\d.]+,\d{2})$")
DUE_DATE_RE = re.compile(r"Vencimento[:\s]*?(\d{2})/(\d{2})/(\d{4})")

# Encargos cobrados como lancamento (bucket proprio, decisao do usuario).
FEE_RE = re.compile(r"^(MULTA|JUROS|ENCARGO|IOF|REPASSEDEIOF)", re.IGNORECASE)
FEE_CATEGORY = "encargos"
REFINANCING_CATEGORY = "parcelamento de fatura"

KNOWN_CATEGORIES = [
    "transporte", "restaurante", "supermercado", "educação", "saúde",
    "outros", "lazer", "vestuário", "serviços", "viagem", "eletrônicos",
]


def _key(text: str) -> str:
    """Forma comparavel: sem acento, sem espacos, minuscula."""
    no_accents = "".join(
        c for c in unicodedata.normalize("NFD", text)
        if unicodedata.category(c) != "Mn"
    )
    return re.sub(r"\s+", "", no_accents).lower()


# Do prefixo mais longo ao mais curto.
_CATEGORY_LOOKUP = sorted(
    ((_key(c), c) for c in KNOWN_CATEGORIES), key=lambda p: len(p[0]), reverse=True
)


def _split_category(first_word: str) -> tuple[str, str] | None:
    """Separa categoria conhecida do inicio da palavra.

    "supermercadoTEODOROSAMPA" -> ("supermercado", "TEODOROSAMPA")
    """
    key = _key(first_word)
    for prefix, canonical in _CATEGORY_LOOKUP:
        if key.startswith(prefix):
            # o prefixo sem acento tem o mesmo tamanho do original com acento
            return canonical, first_word[len(prefix):]
    return None


# Totais impressos: (chave normalizada, destino). Testados ANTES dos cabecalhos.
# "Total transações inter." (sem IOF) e ignorado: o total da secao e o
# "Total lançamentos inter.", que inclui o repasse de IOF.
_TOTAL_LINES = [
    ("lancamentosnocartao", "purchases"),
    ("lancamentosprodutoseservicos", "services"),
    ("totallancamentosinter", "international"),
    ("totaldoslancamentosatuais", "total"),
    ("totaldeencargosemr$", "fees"),
]

# Cabecalhos de secao: (trecho da chave, secao | None para "fora de secao").
_HEADERS = [
    ("pagamentosefetuados", None),
    ("lancamentos:comprasesaques", "purchases"),
    ("lancamentos:produtoseservicos", "services"),
    ("lancamentosinternacionais", "international"),
    ("proximasfaturas", None),  # compras parceladas - proximas faturas
    ("encargoscobrados", None),
    ("limitesdecredito", None),
]


def _parse_money(text: str) -> Decimal:
    return Decimal(text.replace(".", "").replace(",", "."))


def _extract_due_date(pdf) -> date:
    text = pdf.pages[0].extract_text() or ""
    m = DUE_DATE_RE.search(text)
    if not m:
        raise ValueError("data de vencimento nao encontrada na fatura")
    day, month, year = (int(g) for g in m.groups())
    return date(year, month, day)


def _resolve_year(day_month: str, due: date) -> date:
    """'dd/mm' -> data completa. Compra com mes maior que o do vencimento e do
    ano anterior (fatura de janeiro traz compras de dezembro)."""
    day, month = (int(x) for x in day_month.split("/"))
    year = due.year - 1 if month > due.month else due.year
    return date(year, month, day)


def _split_x(words: list[dict]) -> float:
    right_dates = [
        w["x0"] for w in words
        if DATE_RE.match(w["text"]) and RIGHT_DATE_X[0] <= w["x0"] <= RIGHT_DATE_X[1]
    ]
    return min(right_dates) - 3 if right_dates else DEFAULT_SPLIT_X


def _column_lines(words: list[dict]) -> list[list[str]]:
    """Linhas da pagina em ordem de leitura (esquerda, depois direita)."""
    split = _split_x(words)
    lines: list[list[str]] = []
    for column in (
        [w for w in words if w["x0"] < split],
        [w for w in words if w["x0"] >= split],
    ):
        column.sort(key=lambda w: (w["top"], w["x0"]))
        current: list[dict] = []
        for w in column:
            if current and w["top"] - current[0]["top"] > LINE_TOLERANCE:
                lines.append([x["text"] for x in sorted(current, key=lambda x: x["x0"])])
                current = []
            current.append(w)
        if current:
            lines.append([x["text"] for x in sorted(current, key=lambda x: x["x0"])])
    return lines


def _category_for(section: str, merchant: str) -> str | None:
    if FEE_RE.match(_key(merchant)):
        return FEE_CATEGORY
    if section == "services":
        return REFINANCING_CATEGORY
    return None


def extract_invoice(pdf_path: str) -> ParsedInvoice:
    with pdfplumber.open(pdf_path) as pdf:
        due = _extract_due_date(pdf)
        lines: list[list[str]] = []
        for page in pdf.pages:
            lines.extend(_column_lines(page.extract_words()))

    txs: list[Transaction] = []
    printed: dict[str, Decimal] = {}
    section: str | None = None
    last_tx: Transaction | None = None

    for tokens in lines:
        text = " ".join(tokens)
        key = _key(text)
        previous, last_tx = last_tx, None

        # 1) Totais impressos (terminam com valor) encerram a secao.
        total = next((dest for k, dest in _TOTAL_LINES if k in key), None)
        if total and MONEY_RE.match(tokens[-1]) and ":" not in text:
            printed[total] = _parse_money(tokens[-1])
            section = None
            continue

        # 2) Cabecalhos mudam a secao corrente.
        header = next((h for h in _HEADERS if h[0] in key), None)
        if header:
            section = header[1]
            continue

        # 3) Repasse de IOF internacional: lancamento sem data.
        if section == "international" and key.startswith("repassedeiof"):
            txs.append(Transaction(
                day_month=f"{due.day:02d}/{due.month:02d}",
                merchant_raw="Repasse de IOF",
                category=FEE_CATEGORY, city=None,
                amount=_parse_money(tokens[-1]),
                kind="international", section="international",
            ))
            continue

        if section is None:
            continue

        # 4) Linha de lancamento: data ... valor.
        m = TX_LINE_RE.match(text)
        if m:
            day_month, merchant, value = m.groups()
            category = _category_for(section, merchant)
            # Encargo no meio das compras: a fatura soma a parte (fees).
            tx_section = (
                "fees" if section == "purchases" and category == FEE_CATEGORY
                else section
            )
            tx = Transaction(
                day_month=day_month,
                merchant_raw=merchant.strip(),
                category=category,
                city=None,
                amount=_parse_money(value),
                kind="international" if section == "international" else "national",
                section=tx_section,
            )
            txs.append(tx)
            last_tx = tx
            continue

        # 5) Linha logo abaixo de uma compra: "categoria Cidade".
        if previous and previous.section == "purchases" and previous.category is None:
            split = _split_category(tokens[0])
            if split:
                previous.category, glued_city = split
                city = " ".join(([glued_city] if glued_city else []) + tokens[1:])
                previous.city = city.strip() or None

    for t in txs:
        t.date = _resolve_year(t.day_month, due)
    return ParsedInvoice(due_date=due, transactions=txs, printed=printed)


def extract_transactions(pdf_path: str) -> list[Transaction]:
    """Compat: so a lista de transacoes (com data resolvida)."""
    return extract_invoice(pdf_path).transactions


def main() -> None:
    if len(sys.argv) != 2:
        print(f"uso: python {sys.argv[0]} <fatura.pdf>", file=sys.stderr)
        raise SystemExit(1)

    invoice = extract_invoice(sys.argv[1])
    print(f"vencimento: {invoice.due_date}   competencia: {invoice.period}\n")
    for t in invoice.transactions:
        cat = t.category or "-"
        print(f"{t.section[:5]:<5} {t.date}  {t.amount:>9}  [{cat:<22}]  {t.merchant_raw}")

    errors = invoice.reconciliation_errors()
    print(f"\n{len(invoice.transactions)} transacoes")
    print("reconciliacao: OK" if not errors else "DIVERGENCIAS:\n  " + "\n  ".join(errors))


if __name__ == "__main__":
    main()
