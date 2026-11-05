# Gerenciador de Faturas — Itaú

Lê faturas do Itaú em PDF, extrai os lançamentos, normaliza os
estabelecimentos (Uber, 99, 99Food, iFood...) e mostra gráficos de gastos
por categoria, por estabelecimento, evolução mensal e assinaturas
recorrentes. Single-user, roda local.

## Stack

- **pdfplumber** — extração do PDF por coordenadas (o layout tem duas colunas
  cujos valores se sobrepõem em X; só coordenadas resolvem isso).
- **SQLite** — histórico mês a mês, zero setup.
- **Streamlit + Plotly** — interface de upload e gráficos.
- **pytest** — testes de regressão que travam a reconciliação e a
  normalização.

## Módulos

| Arquivo        | Responsabilidade |
|----------------|------------------|
| `extract.py`   | Parser do PDF → `ParsedInvoice` (vencimento + lançamentos datados). Reconcilia ao centavo com os totais da fatura. |
| `normalize.py` | Regras ordenadas que mapeiam nome bruto → merchant canônico; categoria do Itaú como desempate (99 transporte vs 99Food restaurante). |
| `models.py`    | `Transaction` e `ParsedInvoice`. |
| `storage.py`   | Persistência SQLite (idempotente por competência) e agregações. |
| `app.py`       | Interface Streamlit. |

## Uso

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt

# rodar a interface
streamlit run app.py

# ou inspecionar uma fatura pelo terminal
python extract.py /caminho/para/fatura.pdf

# rodar os testes
pytest -q
```

## Decisões de design

- **O Itaú já imprime a categoria** de cada lançamento (transporte,
  restaurante, educação...). Não construímos um classificador de categorias;
  elas vêm da própria fatura. A normalização resolve só o nível de
  *estabelecimento* dentro da categoria.
- **Mês/ano de competência vem da data de vencimento** do PDF. Datas de
  transação (dd/mm) são resolvidas para o ano completo relativo ao
  vencimento, tratando viradas de ano.
- **Re-upload é idempotente**: a fatura é chaveada pela competência
  (AAAA-MM), então reenviar o mesmo PDF substitui, não duplica.
- **Validação por reconciliação**: os testes garantem que a soma dos
  lançamentos bate com os totais impressos na fatura (nacional 1.631,11 +
  internacional 258,10).

## Regras de categoria

A categoria efetiva segue esta ordem: regra do estabelecimento (`normalize.py`),
depois a categoria impressa pelo Itaú, depois a de outra parcela da mesma
compra. A categoria original do Itaú fica guardada em `category_itau`.

- iFood e 99Food: sempre `restaurante`.
- iFood Clube (cobrança mensal "iFood Osasco"), Wellhub, Kiro, OVHcloud: `assinaturas`.
- Mercado Livre: mantém a do Itaú (marketplace).
- Parcela sem categoria herda a de outra parcela da mesma compra, em qualquer
  ordem de upload.
- Multa, juros e IOF de atraso: `encargos`, somados à parte do total de
  lançamentos, como na fatura.

## Limites conhecidos

- Parser calibrado para o layout de fatura de cartão **Platinum** testado. Um
  layout diferente (outro produto/banco) exige recalibrar as bandas X em
  `extract.py`.
- Detecção de assinatura é uma heurística (merchant que aparece em 2+
  competências); precisa de histórico para funcionar.
- Compras internacionais são registradas só em R$ (decisão do usuário).
