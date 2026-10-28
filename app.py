"""Streamlit chat. Retrieval happens against prebuilt stores, never the PDF."""
import sqlite3

import streamlit as st

from config import Settings
from rag.chat_store import ChatStore
from rag.pipeline import RAGService
from ui import apply_styles, header, sidebar_brand, source_card, welcome, saved_time

st.set_page_config(page_title="설비 알람 분석", page_icon="⚙️", layout="wide", initial_sidebar_state="auto")
apply_styles()


@st.cache_resource
def service():
    return RAGService(Settings())


settings = Settings()
evidence_only = settings.llm_backend == "evidence_only" or (settings.llm_backend == "openai" and not (settings.llm_model and settings.llm_api_key))

try:
    if settings.chat_db.resolve() == settings.sqlite.resolve():
        raise ValueError("CHAT_DB_PATH는 매뉴얼 SQLITE_PATH와 다른 파일이어야 합니다.")
    chats = ChatStore(settings.chat_db)
    rooms = chats.rooms(include_empty=False)
    # Preserve conversations already displayed by the previous app version.
    if "active_chat_id" not in st.session_state and st.session_state.get("messages"):
        migrated = chats.create_room()
        for message in st.session_state.messages:
            chats.append(migrated, message["role"], message["content"], message.get("metadata"))
        st.session_state.active_chat_id = migrated
        rooms = chats.rooms(include_empty=False)
    room_ids = {room["id"] for room in rooms}
    if "active_chat_id" not in st.session_state:
        requested = st.query_params.get("chat")
        st.session_state.active_chat_id = requested if requested in room_ids else None
    elif st.session_state.active_chat_id not in room_ids:
        st.session_state.active_chat_id = None
    active_id = st.session_state.active_chat_id
    if active_id:
        st.query_params["chat"] = active_id
    elif "chat" in st.query_params:
        del st.query_params["chat"]
    messages = chats.messages(active_id) if active_id else []
    st.session_state.setdefault("draft_nonce", 0)
except (OSError, sqlite3.Error, ValueError):
    st.error("대화 저장소를 열 수 없습니다. CHAT_DB_PATH가 매뉴얼 DB와 분리되어 있고 쓰기 가능한 경로인지 확인해 주세요.")
    st.stop()


def select_chat(room_id):
    st.session_state.active_chat_id = room_id
    st.query_params["chat"] = room_id


def new_chat():
    # A draft is a screen, not a saved room. Persist only on the first send.
    st.session_state.active_chat_id = None
    st.session_state.messages = []
    st.session_state.draft_nonce += 1
    st.session_state.pop("pending_prompt", None)
    if "chat" in st.query_params:
        del st.query_params["chat"]


def queue_prompt(question):
    st.session_state.pending_prompt = question


def display_message(message):
    metadata = message.get("metadata", {})
    avatar = ":material/hub:" if message["role"] == "assistant" else None
    with st.chat_message(message["role"], avatar=avatar):
        if metadata.get("error"):
            st.error(message["content"])
        else:
            st.markdown(message["content"])
        if metadata.get("context_used"):
            st.caption("이 채팅방의 이전 질문 맥락을 반영했습니다.")
        if "elapsed_seconds" in metadata:
            st.caption(f"응답 시간 {metadata['elapsed_seconds']:.2f}초")


question = st.chat_input("알람 코드나 설비 증상을 입력하세요", key=f"prompt_{active_id or 'draft'}_{st.session_state.draft_nonce}")
question = question or st.session_state.pop("pending_prompt", None)
if question:
    try:
        if not active_id:
            active_id = chats.create_room()
            st.session_state.active_chat_id = active_id
            st.query_params["chat"] = active_id
        chats.append(active_id, "user", question)
        rooms = chats.rooms(include_empty=False)
    except (OSError, sqlite3.Error, ValueError):
        st.error("질문을 저장하지 못했습니다. 대화 저장소의 경로와 쓰기 권한을 확인해 주세요.")
        st.stop()

with st.sidebar:
    sidebar_brand()
    st.button("새 조회", icon=":material/add:", key="new_chat", on_click=new_chat, width="stretch")
    st.html(f'<div class="recent-label">최근 대화<span>{len(rooms):02d}</span></div>')
    with st.container(key="chat_history"):
        for room in rooms:
            with st.container(key=f"history_row_{room['id']}"):
                st.button(room["title"], key=f"chat_{room['id']}", icon=":material/chat_bubble_outline:",
                          type="primary" if room["id"] == active_id else "secondary",
                          on_click=select_chat, args=(room["id"],), width="stretch")
                st.caption(saved_time(room["updated_at"]))
        if not rooms:
            st.caption("저장된 조회가 없습니다.")
    with st.container(key="sidebar_footer"):
        source_card()
        with st.expander("자료·보관 안내"):
            st.caption("FR-E800 시리즈 취급설명서(보수편)에 근거합니다. PDF 쪽수는 파일의 실제 페이지, 문서 쪽수는 인쇄된 번호입니다.")
            st.caption("대화는 이 PC에 저장되며, 채팅방별로 맥락이 분리됩니다.")
            if evidence_only:
                st.caption("원문 검색 모드 · LLM 생성 없이 매뉴얼 근거를 정리합니다.")
            st.caption("실제 점검·조작은 설비의 안전 절차와 제조사 매뉴얼에 따라 수행하세요.")

title = next((room["title"] for room in rooms if room["id"] == active_id), None)
header(title)
st.session_state.messages = messages
if not messages and not question:
    welcome(queue_prompt)
else:
    for message in messages:
        display_message(message)

if question:
    display_message({"role": "user", "content": question})
    with st.chat_message("assistant"):
        try:
            with st.spinner("매뉴얼 근거를 검색하고 답변을 생성하고 있습니다…"):
                answer = service().answer(question, evidence_only=evidence_only, history=messages)
            text = answer["text"]
            metadata = {key: answer[key] for key in ("conversation_context", "context_used", "elapsed_seconds", "local_llm") if key in answer}
        except (ValueError, FileNotFoundError, RuntimeError) as exc:
            text = str(exc)
            metadata = {"error": True}
        except Exception as exc:
            # Unexpected errors stay visible and retain their type without leaking
            # credentials or HTTP request details into the UI.
            text = f"검색 처리 실패({type(exc).__name__}). 데이터 구축 상태와 로컬 로그를 확인해 주세요."
            metadata = {"error": True}
    try:
        chats.append(active_id, "assistant", text, metadata)
    except (OSError, sqlite3.Error, ValueError):
        display_message({"role": "assistant", "content": text, "metadata": metadata})
        st.error("답변을 대화 기록에 저장하지 못했습니다. 대화 저장소의 쓰기 권한을 확인해 주세요.")
        st.stop()
    st.rerun()
