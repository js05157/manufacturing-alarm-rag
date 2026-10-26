"""Streamlit chat. Retrieval happens against prebuilt stores, never the PDF."""
import streamlit as st

from config import Settings
from rag.pipeline import RAGService

st.set_page_config(page_title="Manufacturing Alarm RAG", page_icon="⚙️", layout="centered")
st.title("Manufacturing Alarm RAG")
st.caption("FR-E800 인버터 · 제조사 보수 매뉴얼에 근거한 알람·증상 확인")


@st.cache_resource
def service():
    return RAGService(Settings())


settings = Settings()
evidence_only = not (settings.llm_model and settings.llm_api_key)
with st.sidebar:
    st.subheader("매뉴얼 안내")
    st.write("미쓰비시전기 FR-E800 시리즈 취급설명서(보수편)")
    st.write("조작 패널의 표시 코드를 입력하거나, 발생한 증상을 설명해 주세요.")
    st.caption("PDF 쪽수는 파일의 실제 페이지입니다. 문서 쪽수는 하단에 인쇄된 번호입니다.")
    if evidence_only:
        st.info("원문 검색 모드: LLM을 사용하지 않고 매뉴얼 근거를 정리합니다.")
    st.caption("실제 조작·점검은 설비의 안전 절차와 제조사 매뉴얼을 따라 주세요.")

if "messages" not in st.session_state:
    st.session_state.messages = []
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

question = st.chat_input("예: E.OC1의 원인과 대처 방법 / 모터 시동이 걸리지 않아요")
if question:
    st.session_state.messages.append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.write(question)
    with st.chat_message("assistant"):
        try:
            with st.spinner("매뉴얼 근거를 확인하고 있습니다…"):
                answer = service().answer(question, evidence_only=evidence_only)
            st.markdown(answer["text"])
            st.caption(f"응답 시간 {answer['elapsed_seconds']:.2f}초")
            st.session_state.messages.append({"role": "assistant", "content": answer["text"]})
        except (ValueError, FileNotFoundError, RuntimeError) as exc:
            text = str(exc)
            st.error(text)
            st.session_state.messages.append({"role": "assistant", "content": text})
        except Exception as exc:
            # Unexpected errors stay visible and retain their type without leaking
            # credentials or HTTP request details into the UI.
            st.error(f"검색 처리 실패({type(exc).__name__}). 데이터 구축 상태와 로컬 로그를 확인해 주세요.")
