from fastapi import FastAPI, Request, Depends, HTTPException, OAuth2PasswordRequestForm
from pydantic import BaseModel
from src.router import route_user_query
from src.rag_pipeline import generate_hyde_documents, crag_grader_and_fallback, generate_final_answer, self_rag_reflect
from src.vector_store import get_embedding_with_cache, search_qdrant, rerank_documents
from src.text2sql_pipeline import generate_sql, validate_sql, execute_sql, format_sql_results
from src.orchestrator import app_graph
import uuid
from src.security import SecureQueryRequest, truncate_input, scan_input_llm_guard, post_process_output, redact_pii, verify_jwt_token, check_token_budget
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
import datetime
from fastapi.security import OAuth2PasswordRequestForm
import jwt
from langchain_core.prompts import PromptTemplate
from langchain_google_genai import ChatGoogleGenerativeAI

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
    
def apply_l9_guardrail(query: str, routed_to: str, message: str, status: str, generated_sql: str, final_answer: str) -> CopilotResponse:
    """
    L9 Guardrail: Final Middleware API Formatter.
    Applies Pydantic schema validation to ALL graph outputs with an LLM retry loop.
    """
    print("\n🛡️ [L9 Guardrail] Enforcing Final Pydantic Schema across all outputs...")
    
    llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash", temperature=0.0)
    structured_llm = llm.with_structured_output(CopilotResponse)
    
    prompt = PromptTemplate.from_template(
        "You are the final API gateway formatting agent. Your strict requirement is to take the provided raw system outputs "
        "and map them perfectly into the required JSON schema. Do not change the final answer text.\n\n"
        "Query: {query}\n"
        "Routed To: {routed_to}\n"
        "Message: {message}\n"
        "Status: {status}\n"
        "Generated SQL: {generated_sql}\n"
        "Final Answer: {final_answer}\n"
    )
    
    chain = prompt | structured_llm
    
    max_retries = 3
    for attempt in range(max_retries):
        try:
            response_obj = chain.invoke({
                "query": query,
                "routed_to": routed_to,
                "message": message,
                "status": status,
                "generated_sql": generated_sql,
                "final_answer": final_answer
            })
            print(f"✅ [L9 Guardrail] Output successfully validated on attempt {attempt + 1}.")
            return response_obj
        except Exception as e:
            print(f"⚠️ [L9 Guardrail] Schema validation failed (Attempt {attempt + 1}/{max_retries}). Error: {e}")
            if attempt == max_retries - 1:
                print("❌ [L9 Guardrail] Max retries reached. Engaging hardcoded fallback schema.")
                return CopilotResponse(
                    query=query, routed_to=routed_to, message=message, 
                    status="error", generated_sql=generated_sql, final_answer=final_answer
                )
            
@app.post("/ask", response_model=CopilotResponse)
@limiter.limit("20/minute")
async def ask_copilot(request: Request, payload: SecureQueryRequest, token: dict = Depends(verify_jwt_token)):
    """
    Accepts a user query, routes it via the Intent Router, 
    and caches the decision in Redis.
    """
    query_text = payload.query
    username = token.get("sub", "unknown_user") if isinstance(token, dict) else token

    try:
        estimated_cost = len(query_text) // 4
        check_token_budget(username=username, estimated_tokens=estimated_cost)
    except ValueError as e:
        raise HTTPException(status_code=429, detail=str(e))
        
    query_text = truncate_input(query_text, max_tokens=1000)
    
    try:
        query_text = scan_input_llm_guard(query_text)
    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e))

    query_text = redact_pii(query_text)
    destination = route_user_query(query_text)
    
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
    
    if state_snapshot.next and "sql_execution_node" in state_snapshot.next:
        print(f"⚠️ [HITL] Graph execution paused. Waiting for human approval on Thread: {thread_id}")
        
        return apply_l9_guardrail(
            query=query_text,
            routed_to=destination,
            message=f"Query generated successfully but requires admin approval. Please use /approve with thread_id: {thread_id}",
            status="pending_approval",
            generated_sql=final_state.get("generated_sql", ""),
            final_answer="[Execution Paused] Awaiting human approval."
        )
        
    raw_final_answer = final_state.get("final_answer", "")

    print("\n🛡️ [Security L7b] Scanning generated LLM response for Moderation & PII leaks...")
    safe_final_answer = post_process_output(raw_final_answer)
    
    return apply_l9_guardrail(
        query=query_text,
        routed_to=destination,
        message=f"Query successfully processed via the {destination.upper()} pipeline.",
        status="success",
        generated_sql=final_state.get("generated_sql", ""),
        final_answer=safe_final_answer
    )

class ApprovalRequest(BaseModel):
    thread_id: str
    is_approved: bool

@app.post("/approve", response_model=CopilotResponse)
async def approve_sql(
    request: Request, 
    payload: ApprovalRequest,
    token: dict = Depends(verify_jwt_token)
):
    """
    HITL Endpoint: Resumes the LangGraph state machine after a human 
    has reviewed and approved the pending SQL query via the specific thread_id.
    """
    username = token.get("sub", "unknown_user") if isinstance(token, dict) else token
    
    config = {"configurable": {"thread_id": payload.thread_id}}
    
    state_snapshot = app_graph.get_state(config)
    if not state_snapshot.next or "sql_execution_node" not in state_snapshot.next:
        raise HTTPException(status_code=400, detail=f"No pending SQL queries awaiting approval for thread: {payload.thread_id}")
        
    if not payload.is_approved:
        print(f"🚫 [HITL] Admin '{username}' REJECTED SQL execution for thread {payload.thread_id}.")
        raise HTTPException(status_code=400, detail="SQL execution was rejected by the administrator.")

    print(f"👍 [HITL] Admin '{username}' approved SQL execution. Resuming LangGraph thread {payload.thread_id}...")
    
    try:
        result = app_graph.invoke(None, config=config)
        
        safe_answer = post_process_output(result.get("final_answer", ""))
        
        return apply_l9_guardrail(
            query=result.get("query", ""),
            routed_to=result.get("destination", "sql"),
            message="SQL execution approved and completed.",
            status="success",
            generated_sql=result.get("generated_sql", ""),
            final_answer=safe_answer
        )
        
    except Exception as e:
        print(f"❌ [API] Error resuming graph: {e}")
        raise HTTPException(status_code=500, detail="Failed to execute approved SQL.")