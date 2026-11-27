# 📊 Análise Fundamentalista — mentalidade de sócio

App local (Python + Streamlit) para analisar ações brasileiras no estilo do
[Fundamentus](https://www.fundamentus.com.br), focado em buy and hold.

## Como rodar

Requer Python 3.10+.

```bash
cd analise_fundamentalista
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

Abra <http://localhost:8501> no navegador. Na **primeira vez**:

1. Clique em **🔄 Atualizar dados** (barra lateral). Baixa os indicadores de todas as ações e o
   setor/dívida de cada uma — cerca de 1 minuto.
2. Abra **Histórico de 10 anos (CVM)** e clique em **⬇️ Baixar/atualizar histórico** (≈130 MB, ~20 s).
   Só é necessário para os gráficos de lucro, receita e endividamento. Refaça 1x por ano.

Depois disso o app funciona offline com o que está salvo. Para rodar os testes:
`python -m unittest discover -s tests`.

## Telas

| Tela | O que faz |
|---|---|
| 🔎 **Screener** | Tabela com busca, filtro por setor e faixas mín/máx de cada indicador; ordenação clicando no cabeçalho; exporta CSV. Selecione linhas para analisar, favoritar ou comparar. Botão **🤝 Filtro Sócio** (veja abaixo). |
| 🏢 **Análise individual** | **Resumo** (o que a empresa faz, diferenciais, pontos fortes e fracos), todos os indicadores (cada um comparado com a **mediana do setor**), checklist do Filtro Sócio, histórico de receita/lucro/ROE/margem (até 10 anos), endividamento e posição no setor. |
| ⚖️ **Comparador** | 2 a 5 ações lado a lado; melhor valor de cada linha em destaque; gráficos por grupo de indicadores e evolução histórica. |
| ⭐ **Favoritas** | Ações agrupadas por setor, com notas pessoais. Salvas em SQLite local. |

### Resumo da empresa (aba 🧭 Resumo)

- **📊 Pontos fortes e fracos pelos números:** sempre disponíveis, calculados localmente com regras fixas
  (ex.: ROE ≥ 15% é forte; Dív.Líq/EBITDA > 3 é fraco; classe da ação ON/Novo Mercado vs. PN) e comparados com a
  mediana do setor. Com o histórico CVM baixado, entram também consistência de lucro e ROE.
- **🧠 O que faz, diferenciais e pontos do negócio:** não existem nos dados do Fundamentus/CVM, então vêm do Claude
  (`claude-opus-5-5`) quando você clica em **Gerar resumo com IA**. Para isso defina a chave antes de rodar:

  ```bash
  export ANTHROPIC_API_KEY="sk-ant-..."
  streamlit run app.py
  ```

  Só são enviados nome, ticker, tipo e setor da empresa. O resultado fica salvo em `dados/analise.db` (sem custo ao
  reabrir; "Gerar de novo" refaz). O texto vem do conhecimento geral do modelo: pode estar desatualizado ou impreciso —
  confirme no Formulário de Referência da empresa. Sem chave, o resto do app funciona normalmente.

### Consistência ao longo dos anos (selo ◆ 0–5)

Uma empresa boa não é a que teve um ano bom. Com o histórico da CVM (até 10 exercícios) o app avalia 5 testes
(`consistencia.py`; os limites são constantes no topo do arquivo):

| Teste | Regra |
|---|---|
| Lucro quase sempre | lucro positivo em todos os anos, com no máximo 1 prejuízo (mín. 8 anos de histórico) |
| Lucro crescente | mediana do lucro dos 3 últimos anos > a dos 3 primeiros |
| ROE alto | ROE ≥ 15% em ao menos 4 dos últimos 5 anos |
| Dívida controlada | Dív.Líq/EBITDA < 3 (ou caixa líquido) em ao menos 4 dos últimos 5 anos |
| Caixa operacional | caixa gerado pelas operações positivo em ao menos 4 dos últimos 5 anos |

Bancos e seguradoras não passam pelos dois últimos (selo de 0 a 3). O selo aparece como coluna no Screener (com
*Anos c/ lucro*, *Cresc. lucro* e *ROE mín. 5a*), pode ser usado como filtro e, no Filtro Sócio, como critério opcional
(**Exigir consistência**, desligado por padrão). Na aba **Histórico** da ação há também EBITDA, Dív.Líq/EBITDA, caixa
das operações vs. lucro, fluxo de caixa livre, dividendos pagos e payout. Dividendos e capex vêm do fluxo de caixa e
podem faltar em algumas empresas. Depois de atualizar o app, baixe o histórico de novo (barra lateral): ele agora
também relaciona cada ação à sua empresa na CVM.

### App no celular (PWA no GitHub Pages)

A prévia mobile também é publicada como **PWA** (instalável, abre offline), como um app de tela inicial:
**https://mauroagcs.github.io/analise-fundamentalista/**. No celular, abra o link e use *Adicionar à Tela de
Início*. O site fica na pasta `docs/` (Pages: branch `main`, pasta `/docs`) e é um retrato dos dados da última
publicação (a página mostra a data). Favoritas e notas ficam no navegador do aparelho.

Para atualizar o site com dados novos, um comando (precisa de `git` autenticado):

```bash
./publicar_site.sh      # atualizar.py -> gerar_mobile.py --site docs -> commit -> push
```

`python atualizar.py` atualiza o banco sem abrir o Streamlit (só baixa o que está velho; `--forcar` baixa tudo).
`python gerar_mobile.py --site PASTA` gera o site completo (HTML + manifest + service worker + ícones).

### Prévia para celular (HTML)

```bash
python gerar_mobile.py                          # gera dados/app_mobile.html (um arquivo só, ~650 KB)
python -m http.server 8000 --directory dados    # opcional: serve na rede local
```

Abra `http://IP-DO-COMPUTADOR:8000/app_mobile.html` no celular (mesmo Wi-Fi), ou envie o arquivo para o celular.
Tem Screener (com Filtro Sócio), detalhe da ação (resumo, números vs. setor, histórico, setor), comparador e favoritas
com notas. É um **retrato** dos dados do banco no momento da geração: atualize no app e gere de novo. Funciona sem
internet, mas não busca cotações nem gera resumo de IA (mostra os já salvos). Favoritas, notas e comparador ficam
guardados só no navegador do celular. Se o celular abrir o arquivo numa visualização que bloqueia
armazenamento, a página avisa na aba Favoritas; servir por `http.server` resolve.

### Filtro Sócio (padrão, ajustável na tela)

- Somente ações **ON com final 3** (exclui PN, units e BDRs)
- Liquidez média ≥ **R$ 1 milhão/dia**
- **ROE > 15%** (**> 10%** em utilities: energia elétrica, água e saneamento, gás)
- **Margem líquida > 0**
- **Dív.Líq/EBITDA < 3**

### Bancos e seguradoras

Setores *Intermediários Financeiros* e *Previdência e Seguros* ficam marcados como
**"Analisar à parte"**. Dív.Líq/EBITDA e demais indicadores de dívida não são calculados nem
exigidos para eles. Como o Fundamentus não informa margem líquida de bancos/seguradoras, nesse
critério vale **lucro líquido 12m > 0**.

## De onde vêm os dados

- **Fundamentus** (`resultado.php` e `detalhes.php`): cotação, múltiplos, ROE/ROIC, margens, liquidez,
  setor/subsetor, dívida bruta/líquida, EBIT. O cache fica em `dados/analise.db` (SQLite) com a data da
  última atualização. Setor e dívida só são re-baixados se tiverem mais de 15 dias
  (ou marcando a opção na barra lateral).
- **CVM** (dados abertos, DFP anual): histórico de 10 anos de receita, lucro, patrimônio e dívida.
  O Fundamentus só publica esse histórico como imagem, por isso a CVM.

## Notas e limitações

- **Dív.Líq/EBITDA** não vem pronta: é calculada como `Dív.Líq × (EV/EBITDA) / (EBIT × EV/EBIT)`
  (EBITDA = EV ÷ EV/EBITDA). Fica vazia se o EBITDA for ≤ 0 — e, nesse caso, a ação não passa no Filtro Sócio.
- A coluna de dívida do `resultado.php` hoje é **Dív.Líq/Patrimônio**; a **Dív.Bruta/PL** é calculada
  a partir da dívida bruta de `detalhes.php`.
- No Fundamentus, `0,00` significa "sem dado": o app trata como vazio. Ações sem negociação
  (liquidez 0) são ignoradas. Valores ausentes aparecem como `None` na tabela do screener.
- A mediana do setor exige ao menos 3 ações líquidas e conta cada ticker (PETR3 e PETR4 contam duas vezes).
- Histórico CVM: valores nominais, lucro dos controladores, dívida = empréstimos + debêntures.
  Exercícios fiscais fora do ano-calendário aparecem no ano em que terminam.
- Ferramenta de estudo, **não é recomendação de investimento**. Os dados podem ter erros ou atrasos.
  Seja gentil com o Fundamentus: não atualize em loop.

## Estrutura

```
app.py           navegação + barra lateral
fundamentus.py   scraping (resultado.php, detalhes.php)
cvm.py           histórico anual (DFP) da CVM
db.py            SQLite (cache, favoritas, histórico)
resumo.py        pontos fortes/fracos pelos números + perfil via Claude
regras.py        indicadores derivados, Filtro Sócio, medianas, formatação
ui.py            dados em cache, atualização, gráficos
telas/           screener, individual, comparador, favoritas
tests/           parsers (HTML real salvo) e regras
```
