"""Persistencia em SQLite.

Guarda faturas e seus lancamentos para montar o historico mes a mes. Uma
fatura e identificada pela competencia (AAAA-MM, derivada do vencimento), o
que torna o re-upload do mesmo PDF idempotente: regravar a mesma competencia
substitui os lancamentos daquela fatura, sem duplicar.

O merchant normalizado e persistido junto (snapshot), mas guardamos tambem o
merchant bruto para reprocessar se as regras mudarem.
"""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Iterable
from datetime import date
from decimal import Decimal
from pathlib import Path

from models import ParsedInvoice, Transaction
from normalize import normalize_merchant

DEFAULT_DB = Path(__file__).parent / "faturas.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS invoices (
    period      TEXT PRIMARY KEY,          -- AAAA-MM (competencia)
    due_date    TEXT NOT NULL,             -- ISO date
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS transactions (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    period         TEXT NOT NULL REFERENCES invoices(period) ON DELETE CASCADE,
    tx_date        TEXT NOT NULL,          -- ISO date
    merchant_raw   TEXT NOT NULL,
    merchant       TEXT NOT NULL,          -- normalizado (snapshot)
    merchant_known INTEGER NOT NULL,       -- 1 se casou uma regra
    category       TEXT,                   -- categoria efetiva (regra > Itau > parcela)
    category_itau  TEXT,                   -- categoria impressa pelo Itau
    city           TEXT,
    amount         TEXT NOT NULL,          -- Decimal como string
    kind           TEXT NOT NULL,          -- national | international
    section        TEXT NOT NULL DEFAULT 'purchases'  -- purchases|services|international|fees
);

CREATE INDEX IF NOT EXISTS ix_tx_period   ON transactions(period);
CREATE INDEX IF NOT EXISTS ix_tx_date     ON transactions(tx_date);
CREATE INDEX IF NOT EXISTS ix_tx_merchant ON transactions(merchant);
"""


def connect(db_path: str | Path = DEFAULT_DB) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    _migrate(conn)
    return conn


def _migrate(conn: sqlite3.Connection) -> None:
    """Adiciona colunas que bancos antigos nao tem."""
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(transactions)")}
    if "section" not in cols:
        conn.execute(
            "ALTER TABLE transactions ADD COLUMN section TEXT NOT NULL DEFAULT 'purchases'"
        )
    if "category_itau" not in cols:
        conn.execute("ALTER TABLE transactions ADD COLUMN category_itau TEXT")
    conn.commit()


def save_invoice(conn: sqlite3.Connection, invoice: ParsedInvoice) -> int:
    """Grava (ou regrava) uma fatura. Idempotente por competencia.

    Retorna a quantidade de lancamentos gravados.
    """
    period = invoice.period
    with conn:  # transacao
        # re-upload da mesma competencia: limpa e regrava
        conn.execute("DELETE FROM transactions WHERE period = ?", (period,))
        conn.execute(
            "INSERT OR REPLACE INTO invoices(period, due_date) VALUES (?, ?)",
            (period, invoice.due_date.isoformat()),
        )
        rows = [_tx_row(period, t) for t in invoice.transactions]
        conn.executemany(
            """INSERT INTO transactions
               (period, tx_date, merchant_raw, merchant, merchant_known,
                category, category_itau, city, amount, kind, section)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            rows,
        )
        _inherit_installment_categories(conn)
    return len(rows)


def _tx_row(period: str, t: Transaction) -> tuple:
    n = normalize_merchant(t.merchant_raw, t.category)
    assert t.date is not None, "transacao sem data resolvida"
    return (
        period,
        t.date.isoformat(),
        t.merchant_raw,
        n.canonical,
        1 if n.matched else 0,
        n.category_for(t.category),
        t.category,
        t.city,
        str(t.amount),
        t.kind,
        t.section,
    )


# Sufixo de parcela no fim do nome: "MLP*Netshoes 03/06", "ClickbusSaoPa02/03".
_INSTALLMENT_RE = re.compile(r"(\d{2})/(\d{2})$")


def _installment_key(merchant_raw: str, tx_date: str) -> tuple[str, str, str] | None:
    """Identifica a compra parcelada: (nome sem parcela, dia/mes da compra, nº de parcelas).

    Todas as parcelas repetem a data da compra original. Espacos sao ignorados
    porque variam entre faturas.
    """
    compact = re.sub(r"\s+", "", merchant_raw).lower()
    m = _INSTALLMENT_RE.search(compact)
    if not m:
        return None
    return compact[: m.start()], tx_date[5:], m.group(2)


def _inherit_installment_categories(conn: sqlite3.Connection) -> None:
    """Parcela sem categoria herda a de outra parcela da mesma compra.

    Roda sobre o banco inteiro, entao a ordem de upload das faturas nao importa.
    """
    known: dict[tuple[str, str, str], str] = {}
    missing: list[tuple[int, tuple[str, str, str]]] = []
    for r in conn.execute("SELECT id, merchant_raw, tx_date, category FROM transactions"):
        key = _installment_key(r["merchant_raw"], r["tx_date"])
        if key is None:
            continue
        if r["category"] is None:
            missing.append((r["id"], key))
        else:
            known.setdefault(key, r["category"])
    conn.executemany(
        "UPDATE transactions SET category = ? WHERE id = ?",
        [(known[key], tx_id) for tx_id, key in missing if key in known],
    )


def list_periods(conn: sqlite3.Connection) -> list[str]:
    cur = conn.execute("SELECT period FROM invoices ORDER BY period")
    return [r["period"] for r in cur]


def total_by_category(conn: sqlite3.Connection, period: str) -> dict[str, Decimal]:
    cur = conn.execute(
        """SELECT COALESCE(category, 'sem categoria') AS cat,
                  SUM(CAST(amount AS REAL)) AS total
           FROM transactions WHERE period = ? GROUP BY cat
           ORDER BY total DESC""",
        (period,),
    )
    return {r["cat"]: Decimal(str(round(r["total"], 2))) for r in cur}


def total_by_merchant(conn: sqlite3.Connection, period: str) -> dict[str, Decimal]:
    cur = conn.execute(
        """SELECT merchant, SUM(CAST(amount AS REAL)) AS total
           FROM transactions WHERE period = ? GROUP BY merchant
           ORDER BY total DESC""",
        (period,),
    )
    return {r["merchant"]: Decimal(str(round(r["total"], 2))) for r in cur}


def monthly_by_category(conn: sqlite3.Connection) -> list[dict]:
    """Serie historica: total por (competencia, categoria)."""
    cur = conn.execute(
        """SELECT period,
                  COALESCE(category, 'sem categoria') AS category,
                  SUM(CAST(amount AS REAL)) AS total
           FROM transactions
           GROUP BY period, category
           ORDER BY period, category"""
    )
    return [dict(r) for r in cur]


def recurring_merchants(conn: sqlite3.Connection, min_periods: int = 2) -> list[dict]:
    """Candidatos a assinatura: merchant que aparece em >= N competencias.

    Heuristica simples de recorrencia. Com uma unica fatura nada aparece, mas
    conforme o historico cresce, assinaturas (Kiro, OVHcloud, Wellhub...)
    emergem por recorrerem mes a mes.
    """
    cur = conn.execute(
        """SELECT merchant,
                  COUNT(DISTINCT period) AS meses,
                  AVG(CAST(amount AS REAL)) AS media
           FROM transactions
           GROUP BY merchant
           HAVING meses >= ?
           ORDER BY meses DESC, media DESC""",
        (min_periods,),
    )
    return [
        {"merchant": r["merchant"], "meses": r["meses"],
         "media": Decimal(str(round(r["media"], 2)))}
        for r in cur
    ]
