from fastapi import FastAPI
from pydantic import BaseModel
from src.router import route_user_query
from src.rag_pipeline import generate_hyde_documents, crag_grader_and_fallback, generate_final_answer, self_rag_reflect
from src.vector_store import get_embedding_with_cache, search_qdrant, rerank_documents

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
    
    if destination == "rag":
        hypothetical_answers = generate_hyde_documents(request.query)
        response_data["hyde_documents"] = hypothetical_answers
        
        query_vector = get_embedding_with_cache(request.query)
        response_data["query_embedding_dimensions"] = len(query_vector)
        
        retrieved_context = search_qdrant(query_vector, limit=3)
        
        reranked_context = rerank_documents(request.query, retrieved_context)
        
        crag_results = crag_grader_and_fallback(request.query, reranked_context)
        
        response_data["crag_routing_decision"] = crag_results["source"]
        response_data["final_context"] = crag_results["documents"]
        
        initial_answer = generate_final_answer(request.query, crag_results["documents"])
        
        final_answer = self_rag_reflect(request.query, crag_results["documents"], initial_answer)
        
        response_data["final_answer"] = final_answer
        
    return response_data