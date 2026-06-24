import streamlit as st
import requests
import re

API_BASE_URL = "http://localhost:8000"

st.title("Enterprise RAG Copilot 🛡️")
st.markdown("Kubernetes SRE copilot using LangGraph, Qdrant, Postgres, and Redis.")

if "messages" not in st.session_state:
    st.session_state.messages = []
if "pending_thread_id" not in st.session_state:
    st.session_state.pending_thread_id = None
if "pending_sql" not in st.session_state:
    st.session_state.pending_sql = None

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        if "sql" in msg:
            st.code(msg["sql"], language="sql")

if st.session_state.pending_thread_id:
    with st.chat_message("assistant"):
        st.warning("⚠️ **Human-in-the-Loop Approval Required**")
        st.write("The AI generated the following SQL query. Do you approve its execution?")
        st.code(st.session_state.pending_sql, language="sql")
        
        col1, col2 = st.columns(2)
        
        if col1.button("✅ Approve Execution", use_container_width=True):
            with st.spinner("Executing approved query..."):
                headers = {"Authorization": f"Bearer {st.session_state.get('token', 'your_jwt_here')}"}
                payload = {
                    "thread_id": st.session_state.pending_thread_id,
                    "is_approved": True
                }
                
                try:
                    response = requests.post(f"{API_BASE_URL}/approve", json=payload, headers=headers)
                    data = response.json()
                    
                    st.session_state.pending_thread_id = None
                    st.session_state.pending_sql = None
                    
                    st.session_state.messages.append({"role": "assistant", "content": data.get("final_answer", "")})
                    st.rerun()
                except Exception as e:
                    st.error(f"Error communicating with backend: {e}")
                    
        if col2.button("❌ Reject Query", type="primary", use_container_width=True):
            st.session_state.pending_thread_id = None
            st.session_state.pending_sql = None
            st.session_state.messages.append({"role": "assistant", "content": "SQL execution was rejected by the administrator."})
            st.rerun()

elif prompt := st.chat_input("Ask about Kubernetes or live metrics..."):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        with st.spinner("Processing through 9-Layer Security Pipeline..."):
            headers = {"Authorization": f"Bearer {st.session_state.get('token', 'your_jwt_here')}"}
            payload = {"query": prompt}
            
            try:
                response = requests.post(f"{API_BASE_URL}/ask", json=payload, headers=headers)
                data = response.json()
                
                if data.get("status") == "pending_approval":
                    match = re.search(r"thread_id:\s*([a-f0-9\-]+)", data.get("message", ""))
                    if match:
                        st.session_state.pending_thread_id = match.group(1)
                        st.session_state.pending_sql = data.get("generated_sql", "")
                        st.rerun()
                    else:
                        st.error("Failed to parse Thread ID for approval.")
                else:
                    final_answer = data.get("final_answer", "")
                    st.markdown(final_answer)
                    if data.get("generated_sql"):
                        st.code(data.get("generated_sql"), language="sql")
                        
                    msg_obj = {"role": "assistant", "content": final_answer}
                    if data.get("generated_sql"):
                        msg_obj["sql"] = data.get("generated_sql")
                    st.session_state.messages.append(msg_obj)
                    
            except Exception as e:
                st.error(f"Failed to connect to backend: {e}")