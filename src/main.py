from fastapi import FastAPI, Request, Depends, HTTPException, OAuth2PasswordRequestForm
from pydantic import BaseModel
from src.router import route_user_query
from src.rag_pipeline import generate_hyde_documents, crag_grader_and_fallback, generate_final_answer, self_rag_reflect
from src.vector_store import get_embedding_with_cache, search_qdrant, rerank_documents
from src.text2sql_pipeline import generate_sql, validate_sql, execute_sql, format_sql_results
from src.orchestrator import app_graph
import uuid
from src.security import SecureQueryRequest, truncate_input, scan_input_llm_guard, redact_pii, verify_jwt_token, check_token_budget
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
import datetime
from fastapi.security import OAuth2PasswordRequestForm
import jwt

class CopilotResponse(BaseModel):
    """
    L9 Guardrail: Pydantic Schema Validation.
    Forces the final API output into a strict, predictable JSON schema.
    """
    query: str
    routed_to: str
    message: str
    status: str
    generated_sql: str
    final_answer: str

app = FastAPI(
    title="Enterprise RAG Copilot API",
    description="Production-grade Kubernetes SRE copilot using LangGraph, Qdrant, Postgres, and Redis.",
    version="1.0.0"
)

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

class QueryRequest(BaseModel):
    query: str

@app.get("/")
async def root():
    """Root endpoint to verify the API is online."""
    return {"status": "online", "message": "Enterprise RAG Copilot API is running!"}

@app.get("/health")
async def health_check():
    """
    Health check endpoint. 
    In the industry, load balancers (like AWS ALB or Kubernetes probes) 
    ping this endpoint to ensure the container is healthy.
    """
    return {
        "api_status": "healthy",
        "postgres_connection": "pending configuration",
        "qdrant_connection": "pending configuration",
        "redis_cache": "pending configuration"
    }

MOCK_USERS = {
    "admin_user": "securepassword123",
    "sre_engineer": "k8s_rocks!"
}

SECRET_KEY = "enterprise-rag-super-secret-key"

@app.post("/login")
async def login(form_data: OAuth2PasswordRequestForm = Depends()):
    """
    Authenticates a user and returns a signed JWT Bearer token.
    """
    username = form_data.username
    password = form_data.password
    
    if username in MOCK_USERS and MOCK_USERS[username] == password:
        expiration = datetime.datetime.utcnow() + datetime.timedelta(hours=1)
        token_payload = {"sub": username, "exp": expiration}
        
        access_token = jwt.encode(token_payload, SECRET_KEY, algorithm="HS256")
        
        print(f"[Auth] Issued new JWT token for user: {username}")
        return {"access_token": access_token, "token_type": "bearer"}
    else:
        print(f"[Auth] Failed login attempt for user: {username}")
        raise HTTPException(status_code=401, detail="Invalid username or password")

@app.post("/ask", response_model=CopilotResponse)
@limiter.limit("20/minute")
async def ask_copilot(request: Request, payload: SecureQueryRequest, user: str = Depends(verify_jwt_token)):
    """
    Accepts a user query, routes it via the Intent Router, 
    and caches the decision in Redis.
    """
    query_text = payload.query
    try:
        estimated_cost = len(query_text) // 4
        check_token_budget(username=user, estimated_tokens=estimated_cost)
    except ValueError as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=429, detail=str(e))
    query_text = truncate_input(query_text, max_tokens=1000)
    try:
        query_text = scan_input_llm_guard(query_text)
    except ValueError as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=403, detail=str(e))
    query_text = redact_pii(query_text)
    destination = route_user_query(query_text)
    
    response_data = {
        "query": query_text,
        "routed_to": destination,
        "message": f"Query routed to the {destination.upper()} pipeline."
    }
    
    print(f"\n⚡ Triggering Unified LangGraph State Machine for '{destination}' Intent...")
    
    thread_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}
    
    initial_state = {
        "query": query_text,
        "destination": destination,
        "context_docs": [],
        "generated_sql": "",
        "is_sql_safe": False,
        "final_answer": ""
    }
    
    final_state = app_graph.invoke(initial_state, config=config)
    
    state_snapshot = app_graph.get_state(config)
    if state_snapshot.next and "execute_sql" in state_snapshot.next:
        print(f"⚠️ [HITL] Graph execution paused. Waiting for human approval on Thread: {thread_id}")
        response_data["status"] = "⚠️ Pending Human-in-the-Loop (HITL) Approval"
        response_data["thread_id"] = thread_id
        response_data["generated_sql"] = final_state.get("generated_sql", "")
        response_data["final_answer"] = f"Your query is ready. Please review it and use the /approve endpoint with thread_id: {thread_id}"
        return response_data
        
    raw_final_answer = final_state.get("final_answer", "")

    print("\n🛡️ [Security L7b] Scanning generated LLM response for PII leaks...")
    safe_final_answer = redact_pii(raw_final_answer)
    
    response_data["status"] = "Executed via Unified LangGraph State Machine"
    response_data["generated_sql"] = final_state.get("generated_sql", "")
    response_data["final_answer"] = safe_final_answer
    
    return response_data

class ApprovalRequest(BaseModel):
    thread_id: str
    is_approved: bool

@app.post("/approve")
async def approve_sql_execution(request: ApprovalRequest):
    """
    HITL Endpoint: Allows a human to approve or reject a paused Text2SQL query.
    """
    config = {"configurable": {"thread_id": request.thread_id}}
    state_snapshot = app_graph.get_state(config)
    
    if not state_snapshot.next or "execute_sql" not in state_snapshot.next:
        return {"status": "Error", "message": "No pending execution found for this thread."}
        
    if request.is_approved:
        print("\n✅ [HITL] Human Approved! Resuming execution...")
        final_state = app_graph.invoke(None, config=config)
        
        return {
            "status": "Executed Successfully",
            "database_records": final_state.get("context_docs", []),
            "final_answer": final_state.get("final_answer", "")
        }
    else:
        print("\n❌ [HITL] Human Rejected. Aborting.")
        return {"status": "Rejected", "final_answer": "The database query was rejected by an administrator."}