import streamlit as st
import requests

st.set_page_config(page_title="Enterprise RAG Copilot")
st.title("Enterprise RAG Copilot")
st.markdown("Your highly secure Kubernetes IT Operations Assistant.")

if "jwt_token" not in st.session_state:
    st.session_state.jwt_token = None
if "messages" not in st.session_state:
    st.session_state.messages = []

if st.session_state.jwt_token is None:
    st.subheader("Login to Access the Copilot")
    st.markdown("Please authenticate to access the secure RAG pipeline.")
    
    with st.form("login_form"):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        submit_button = st.form_submit_button("Login")
        
        if submit_button:
            try:
                response = requests.post(
                    "http://localhost:8000/login",
                    data={"username": username, "password": password}
                )
                
                if response.status_code == 200:
                    st.session_state.jwt_token = response.json().get("access_token")
                    st.success("Login successful! Loading Copilot...")
                    st.rerun()
                else:
                    st.error("Invalid username or password.")
            except requests.exceptions.ConnectionError:
                st.error("Failed to connect to the backend. Is FastAPI running?")

else:
    st.sidebar.header("Account")
    if st.sidebar.button("Logout"):
        st.session_state.jwt_token = None
        st.session_state.messages = []
        st.rerun()

    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    if prompt := st.chat_input("E.g., How do I restart a crashlooping pod?"):
        
        st.chat_message("user").markdown(prompt)
        st.session_state.messages.append({"role": "user", "content": prompt})

        with st.chat_message("assistant"):
            with st.spinner("Analyzing intent and routing through security pipeline..."):
                try:
                    headers = {
                        "Authorization": f"Bearer {st.session_state.jwt_token}",
                        "Content-Type": "application/json"
                    }
                    
                    response = requests.post(
                        "http://localhost:8000/ask",
                        json={"query": prompt},
                        headers=headers
                    )
                    
                    if response.status_code == 200:
                        data = response.json()
                        if "⚠️" in data.get("status", ""):
                            st.warning(data["final_answer"])
                            st.code(data.get("generated_sql", ""), language="sql")
                        else:
                            answer = data.get("final_answer", "")
                            st.markdown(answer)
                            st.session_state.messages.append({"role": "assistant", "content": answer})
                    
                    elif response.status_code == 401:
                        st.error("Your session has expired. Please log out and log back in.")
                    else:
                        st.error(f"Security/System Guardrail Triggered (Status {response.status_code}):\n {response.text}")
                        
                except requests.exceptions.ConnectionError:
                    st.error("Failed to connect to the FastAPI backend.")