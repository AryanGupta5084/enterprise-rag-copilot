from fastapi import FastAPI
from pydantic import BaseModel
from src.router import route_user_query
from src.rag_pipeline import generate_hyde_documents, crag_grader_and_fallback, generate_final_answer, self_rag_reflect
from src.vector_store import get_embedding_with_cache, search_qdrant, rerank_documents
from src.text2sql_pipeline import generate_sql, validate_sql, execute_sql, format_sql_results
from src.orchestrator import app_graph
import uuid

app = FastAPI(
    title="Enterprise RAG Copilot API",
    description="Production-grade Kubernetes SRE copilot using LangGraph, Qdrant, Postgres, and Redis.",
    version="1.0.0"
)

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

@app.post("/ask")
async def ask_copilot(request: QueryRequest):
    """
    Accepts a user query, routes it via the Intent Router, 
    and caches the decision in Redis.
    """
    destination = route_user_query(request.query)
    
    response_data = {
        "query": request.query,
        "routed_to": destination,
        "message": f"Query routed to the {destination.upper()} pipeline."
    }
    
    print(f"\n⚡ Triggering Unified LangGraph State Machine for '{destination}' Intent...")
    
    # Generate a unique thread ID so LangGraph can remember this specific conversation
    thread_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}
    
    initial_state = {
        "query": request.query,
        "destination": destination,
        "context_docs": [],
        "generated_sql": "",
        "is_sql_safe": False,
        "final_answer": ""
    }
    
    # Run the unified graph! It will automatically route to RAG or SQL.
    final_state = app_graph.invoke(initial_state, config=config)
    
    # Check if the graph hit our SQL interrupt() breakpoint
    state_snapshot = app_graph.get_state(config)
    if state_snapshot.next and "execute_sql" in state_snapshot.next:
        print(f"⚠️ [HITL] Graph execution paused. Waiting for human approval on Thread: {thread_id}")
        response_data["status"] = "⚠️ Pending Human-in-the-Loop (HITL) Approval"
        response_data["thread_id"] = thread_id
        response_data["generated_sql"] = final_state.get("generated_sql", "")
        response_data["final_answer"] = f"Your query is ready. Please review it and use the /approve endpoint with thread_id: {thread_id}"
        return response_data
        
    # Populate the final successful response
    response_data["status"] = "Executed via Unified LangGraph State Machine"
    response_data["generated_sql"] = final_state.get("generated_sql", "")
    response_data["final_answer"] = final_state.get("final_answer", "")
    
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
    
    # Verify the graph is actually paused
    if not state_snapshot.next or "execute_sql" not in state_snapshot.next:
        return {"status": "Error", "message": "No pending execution found for this thread."}
        
    if request.is_approved:
        print("\n✅ [HITL] Human Approved! Resuming execution...")
        # Resume the graph by passing None (meaning: continue with no changes to state)
        final_state = app_graph.invoke(None, config=config)
        
        return {
            "status": "Executed Successfully",
            "database_records": final_state.get("context_docs", []),
            "final_answer": final_state.get("final_answer", "")
        }
    else:
        print("\n❌ [HITL] Human Rejected. Aborting.")
        return {"status": "Rejected", "final_answer": "The database query was rejected by an administrator."}