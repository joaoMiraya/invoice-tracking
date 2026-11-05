"""Interface web (Streamlit) para faturas do Itau.

Fluxo:
    1. Upload de um ou mais PDFs de fatura.
    2. Cada PDF e parseado, datado pela competencia (vencimento) e persistido
       de forma idempotente no SQLite.
    3. Graficos: gasto por categoria, por merchant normalizado (Uber vs 99 vs
       iFood vs 99Food), evolucao mensal e assinaturas recorrentes.

Rodar:
    streamlit run app.py
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

from extract import extract_invoice
from storage import (
    connect,
    save_invoice,
    list_periods,
    total_by_category,
    total_by_merchant,
    monthly_by_category,
    recurring_merchants,
)

st.set_page_config(page_title="Faturas Itau", page_icon="💳", layout="wide")


@st.cache_resource
def get_conn():
    return connect()


conn = get_conn()

st.title("💳 Gerenciador de Faturas — Itau")

# --- Upload ---------------------------------------------------------------
with st.sidebar:
    st.header("Upload")
    files = st.file_uploader(
        "PDFs de fatura", type="pdf", accept_multiple_files=True
    )
    if files and st.button("Processar", type="primary"):
        for f in files:
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                tmp.write(f.getvalue())
                tmp_path = tmp.name
            try:
                invoice = extract_invoice(tmp_path)
                n = save_invoice(conn, invoice)
                errors = invoice.reconciliation_errors()
                if errors:
                    st.warning(
                        f"{f.name}: {n} lancamentos (competencia {invoice.period}), "
                        "mas NAO bate com os totais da fatura: " + "; ".join(errors)
                    )
                else:
                    st.success(f"{f.name}: {n} lancamentos (competencia {invoice.period})")
            except Exception as e:  # noqa: BLE001
                st.error(f"{f.name}: falhou — {e}")
            finally:
                Path(tmp_path).unlink(missing_ok=True)

periods = list_periods(conn)
if not periods:
    st.info("Envie uma fatura em PDF pela barra lateral para comecar.")
    st.stop()

# --- Selecao de competencia ----------------------------------------------
period = st.selectbox("Competencia", periods, index=len(periods) - 1)

cat = total_by_category(conn, period)
merch = total_by_merchant(conn, period)
total_mes = sum(cat.values())

c1, c2, c3 = st.columns(3)
c1.metric("Total da competencia", f"R$ {total_mes:,.2f}")
c2.metric("Categorias", len(cat))
c3.metric("Estabelecimentos", len(merch))

# --- Gasto por categoria --------------------------------------------------
left, right = st.columns(2)
with left:
    st.subheader("Gasto por categoria")
    df_cat = pd.DataFrame(
        {"categoria": list(cat.keys()), "valor": [float(v) for v in cat.values()]}
    )
    fig = px.pie(df_cat, names="categoria", values="valor", hole=0.4)
    st.plotly_chart(fig, use_container_width=True)

with right:
    st.subheader("Gasto por estabelecimento")
    df_m = pd.DataFrame(
        {"merchant": list(merch.keys()), "valor": [float(v) for v in merch.values()]}
    )
    fig = px.bar(df_m, x="valor", y="merchant", orientation="h")
    fig.update_layout(yaxis={"categoryorder": "total ascending"})
    st.plotly_chart(fig, use_container_width=True)

# --- Evolucao mensal por categoria ----------------------------------------
st.subheader("Evolucao mensal por categoria")
rows = monthly_by_category(conn)
if rows:
    df_hist = pd.DataFrame(rows)
    df_hist["total"] = df_hist["total"].astype(float)
    fig = px.line(df_hist, x="period", y="total", color="category", markers=True)
    st.plotly_chart(fig, use_container_width=True)

# --- Assinaturas recorrentes ----------------------------------------------
st.subheader("Assinaturas recorrentes (aparecem em 2+ competencias)")
rec = recurring_merchants(conn, min_periods=2)
if rec:
    df_rec = pd.DataFrame(rec)
    df_rec["media"] = df_rec["media"].astype(float)
    st.dataframe(df_rec, use_container_width=True, hide_index=True)
else:
    st.caption(
        "Nenhuma ainda — envie faturas de mais meses para detectar assinaturas."
    )
