"""Análise Fundamentalista — app local (Streamlit). Rode com: streamlit run app.py"""
import streamlit as st

import ui
from telas import comparador, favoritas, individual, screener

st.set_page_config(page_title="Análise Fundamentalista", page_icon="📊", layout="wide")

ui.PAGINAS.update(
    screener=st.Page(screener.render, title="Screener", icon="🔎", url_path="screener", default=True),
    individual=st.Page(individual.render, title="Análise individual", icon="🏢", url_path="individual"),
    comparador=st.Page(comparador.render, title="Comparador", icon="⚖️", url_path="comparador"),
    favoritas=st.Page(favoritas.render, title="Favoritas", icon="⭐", url_path="favoritas"),
)

with st.sidebar:
    st.header("📊 Sócio de Empresas")
    st.caption("Buy and hold, com mentalidade de sócio.")

    st.subheader("Dados")
    ultima = ui.quando("indicadores_em")
    st.caption(f"Última atualização: **{ultima}**" if ultima else "Nunca atualizado.")
    completo = st.checkbox("Atualizar também setor e dívida de todas as ações",
                           help="Normalmente só ações sem dados ou com mais de "
                                f"{ui.DIAS_DETALHES} dias são re-baixadas.")
    if st.button("🔄 Atualizar dados", type="primary", width="stretch"):
        try:
            ui.atualizar_dados(forcar_detalhes=completo)
        except Exception as e:  # rede fora do ar, site mudou etc.
            st.error(f"Não consegui atualizar: {e}")

    with st.expander("Histórico de 10 anos (CVM)"):
        hist = ui.quando("historico_em")
        st.caption(f"Baixado em: {hist}" if hist else "Ainda não baixado. Necessário para os gráficos "
                   "de lucro, receita e endividamento.")
        if st.button("⬇️ Baixar/atualizar histórico", width="stretch"):
            try:
                ui.atualizar_historico()
            except Exception as e:
                st.error(f"Não consegui baixar: {e}")

    st.caption("Fonte: fundamentus.com.br e dados abertos da CVM. "
               "Ferramenta de estudo — não é recomendação de investimento.")

st.navigation(list(ui.PAGINAS.values())).run()
