"""Presentation helpers; no retrieval or conversation state is kept here."""
from html import escape
from pathlib import Path

import streamlit as st

LOGO = '<span class="desk-logo" aria-hidden="true">M<i></i></span>'
STARTERS = (
    ("알람 코드 확인", "E.OC1의 원인과 대처 방법", "error_outline"),
    ("증상으로 찾기", "모터 시동이 걸리지 않아요", "troubleshoot"),
    ("원인 함께 살펴보기", "E.THT가 가감속 시간 때문일 수 있어?", "manage_search"),
    ("점검 항목 확인", "냉각팬 교환 후 소음이 나요", "checklist"),
)


def apply_styles():
    css = (Path(__file__).parent/"assets/styles.css").read_text(encoding="utf-8")
    st.html(f"<style>{css}</style>")


def header(title=None):
    st.html(f"""<header class="workspace-header">
        <div class="workspace-name"><span class="workspace-mark">{LOGO}</span>
        <div><strong>Manufacturing Alarm RAG</strong><span>매뉴얼에서 찾는 설비의 답</span></div></div>
        <span class="manual-pill">FR-E800 <i></i> 보수편</span>
    </header>""")
    if title:
        st.html(f'<div class="conversation-title"><span>CONVERSATION</span><h1>{escape(title)}</h1></div>')


def sidebar_brand():
    st.html(f"""<div class="sidebar-brand"><span class="brand-mark">{LOGO}</span>
        <div><strong>ALARM DESK</strong><span>Manufacturing assistant</span></div></div>""")


def source_card():
    st.html("""<div class="source-card"><span class="source-label">KNOWLEDGE SOURCE</span>
        <div class="source-name"><span class="pdf-icon">PDF</span><div><strong>FR-E800 보수편</strong>
        <span>미쓰비시전기 · 한국어</span></div></div></div>""")


def welcome(on_prompt):
    st.html(f"""<section class="welcome-panel"><div class="welcome-mark">{LOGO}</div>
        <span class="eyebrow">FR-E800 MANUAL ASSISTANT</span>
        <h1>어떤 알람을 확인할까요?</h1>
        <p>알람 코드부터 막연한 증상까지.<br>제조사 매뉴얼에서 원인과 점검 방법을 찾아드립니다.</p>
        </section>""")
    with st.container(key="starter_questions"):
        for offset in (0, 2):
            columns = st.columns(2, gap="small")
            for column, (title, question, icon) in zip(columns, STARTERS[offset:offset+2]):
                with column:
                    st.button(f"**{title}**\n\n{question}", key=f"starter_{offset}_{icon}",
                              icon=f":material/{icon}:", width="stretch", on_click=on_prompt, args=(question,))
    st.html("""<div class="welcome-features"><span>원문 근거 확인</span><i></i><span>페이지 출처 제공</span>
        <i></i><span>대화 맥락 연결</span></div>""")
