"""Presentation helpers; no retrieval or conversation state is kept here."""
from datetime import datetime, timedelta, timezone
from html import escape
from pathlib import Path

import streamlit as st

LOGO = '<span class="desk-logo" aria-hidden="true">M<i></i></span>'
STARTERS = (
    ("과전류 차단 · E.OC1", "E.OC1의 원인과 대처 방법", "error_outline"),
    ("모터 시동 불가", "모터 시동이 걸리지 않습니다. 주회로 점검 항목은?", "troubleshoot"),
    ("과부하 · E.THT", "E.THT의 가감속 시간 관련 점검 항목은?", "manage_search"),
    ("냉각팬 교환 후 소음", "냉각팬 교환 후 인버터 소음 점검 항목은?", "checklist"),
)


def apply_styles():
    css = (Path(__file__).parent/"assets/styles.css").read_text(encoding="utf-8")
    st.html(f"<style>{css}</style>")


def header(title=None):
    st.html("""<header class="workspace-header">
        <div class="workspace-name"><strong>설비 알람 분석</strong>
        <span>설비보전 / 매뉴얼 기반 점검</span></div>
    </header>""")
    if title:
        st.html(f'<div class="conversation-title"><span>조회 내용</span><h1>{escape(title)}</h1></div>')


def sidebar_brand():
    st.html(f"""<div class="sidebar-brand"><span class="brand-mark">{LOGO}</span>
        <div><strong>설비보전 지원</strong><span>유지보수 기술자료 조회</span></div></div>""")


def source_card():
    st.html("""<div class="source-card"><span class="source-label">참조 문서</span>
        <div class="source-name"><span class="pdf-icon">PDF</span><div><strong>FR-E800 취급설명서</strong>
        <span>미쓰비시전기 · 보수편</span></div></div></div>""")


def saved_time(value):
    """Stored timestamps are UTC; the operator workspace uses Korea time."""
    return datetime.fromisoformat(value).astimezone(timezone(timedelta(hours=9))).strftime("%m.%d %H:%M")


def welcome(on_prompt):
    st.html("""<section class="welcome-panel"><span class="eyebrow">유지보수 조회</span>
        <h1>알람·증상 조회</h1>
        <p>표시 코드와 발생 조건을 입력하여 점검 항목과 대처 방법을 조회합니다.</p></section>
        <div class="query-guide">
            <div><span>알람 표시</span><strong>코드 또는 구체적인 증상</strong></div>
            <div><span>운전 구간</span><strong>가속 · 정속 · 감속 / 정지</strong></div>
            <div><span>최근 작업</span><strong>배선 변경 · 부품 교환 등</strong></div>
        </div>
        <div class="section-heading"><h2>빠른 조회</h2><span>점검 대상 선택</span></div>""")
    with st.container(key="starter_questions"):
        for offset in (0, 2):
            columns = st.columns(2, gap="small")
            for column, (title, question, icon) in zip(columns, STARTERS[offset:offset+2]):
                with column:
                    st.button(f"**{title}**\n\n{question}", key=f"starter_{offset}_{icon}",
                              icon=f":material/{icon}:", width="stretch", on_click=on_prompt, args=(question,))
