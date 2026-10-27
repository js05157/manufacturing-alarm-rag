"""Streamlit chat. Retrieval happens against prebuilt stores, never the PDF."""
import sqlite3

import streamlit as st

from config import Settings
from rag.chat_store import ChatStore
from rag.pipeline import RAGService

st.set_page_config(page_title="Manufacturing Alarm RAG", page_icon="⚙️", layout="centered")
st.title("Manufacturing Alarm RAG")
st.caption("FR-E800 인버터 · 제조사 보수 매뉴얼에 근거한 알람·증상 확인")


@st.cache_resource
def service():
    return RAGService(Settings())


settings = Settings()
evidence_only = settings.llm_backend == "evidence_only" or (settings.llm_backend == "openai" and not (settings.llm_model and settings.llm_api_key))

try:
    if settings.chat_db.resolve() == settings.sqlite.resolve():
        raise ValueError("CHAT_DB_PATH는 매뉴얼 SQLITE_PATH와 다른 파일이어야 합니다.")
    chats = ChatStore(settings.chat_db)
    rooms = chats.rooms()
    # Preserve conversations already displayed by the previous app version.
    if "active_chat_id" not in st.session_state and st.session_state.get("messages"):
        migrated = chats.create_room()
        for message in st.session_state.messages:
            chats.append(migrated, message["role"], message["content"], message.get("metadata"))
        st.session_state.active_chat_id = migrated
        rooms = chats.rooms()
    room_ids = {room["id"] for room in rooms}
    if st.session_state.get("active_chat_id") not in room_ids:
        requested = st.query_params.get("chat")
        st.session_state.active_chat_id = requested if requested in room_ids else rooms[0]["id"] if rooms else chats.create_room()
        rooms = chats.rooms()
    active_id = st.session_state.active_chat_id
    st.query_params["chat"] = active_id
    messages = chats.messages(active_id)
except (OSError, sqlite3.Error, ValueError):
    st.error("대화 저장소를 열 수 없습니다. CHAT_DB_PATH가 매뉴얼 DB와 분리되어 있고 쓰기 가능한 경로인지 확인해 주세요.")
    st.stop()


def select_chat(room_id):
    st.session_state.active_chat_id = room_id
    st.query_params["chat"] = room_id


def new_chat():
    select_chat(chats.create_room())


def display_message(message):
    metadata = message.get("metadata", {})
    with st.chat_message(message["role"]):
        if metadata.get("error"):
            st.error(message["content"])
        else:
            st.markdown(message["content"])
        if metadata.get("context_used"):
            st.caption("이 채팅방의 이전 질문 맥락을 반영했습니다.")
        if "elapsed_seconds" in metadata:
            st.caption(f"응답 시간 {metadata['elapsed_seconds']:.2f}초")
        if metadata.get("local_llm", {}).get("batch_count"):
            st.caption(f"로컬 모델 생성 {metadata['local_llm']['inference_seconds']:.2f}초")


with st.sidebar:
    st.subheader("채팅")
    st.button("＋ 새 채팅", key="new_chat", on_click=new_chat, use_container_width=True)
    for room in rooms:
        st.button(room["title"], key=f"chat_{room['id']}",
                  type="primary" if room["id"] == active_id else "secondary",
                  on_click=select_chat, args=(room["id"],), use_container_width=True)
    st.caption("대화는 이 PC에 저장됩니다. 맥락은 채팅방별로 분리됩니다.")
    st.divider()
    st.subheader("매뉴얼 안내")
    st.write("미쓰비시전기 FR-E800 시리즈 취급설명서(보수편)")
    st.write("조작 패널의 표시 코드를 입력하거나, 발생한 증상을 설명해 주세요.")
    st.caption("PDF 쪽수는 파일의 실제 페이지입니다. 문서 쪽수는 하단에 인쇄된 번호입니다.")
    if evidence_only:
        st.info("원문 검색 모드: LLM을 사용하지 않고 매뉴얼 근거를 정리합니다.")
    elif settings.llm_backend == "local":
        st.info("로컬 Qwen3 답변 생성 · 외부 LLM API 전송 없음")
    st.caption("실제 조작·점검은 설비의 안전 절차와 제조사 매뉴얼을 따라 주세요.")

st.session_state.messages = messages
for message in messages:
    display_message(message)

question = st.chat_input("예: E.OC1의 원인과 대처 방법 / 모터 시동이 걸리지 않아요")
if question:
    try:
        chats.append(active_id, "user", question)
    except (OSError, sqlite3.Error, ValueError):
        st.error("질문을 저장하지 못했습니다. 대화 저장소의 경로와 쓰기 권한을 확인해 주세요.")
        st.stop()
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
