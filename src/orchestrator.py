from typing import TypedDict, List, Dict, Any, Annotated
import operator
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.postgres import PostgresSaver
from psycopg_pool import ConnectionPool
from src.text2sql_pipeline import generate_sql, validate_sql, execute_sql, format_sql_results
from src.rag_pipeline import generate_final_answer, self_rag_reflect, crag_grader_and_fallback, generate_hyde_documents
from src.vector_store import search_qdrant, rerank_documents
from src.security import spotlight_context
from src.cache import (
    get_cached_sql_gen, set_cached_sql_gen,
    get_cached_sql_result, set_cached_sql_result,
    get_cached_rag_answer, set_cached_rag_answer
)

class GraphState(TypedDict):
    query: str
    destination: str
    context_docs: Annotated[list, operator.add] 
    generated_sql: str
    is_sql_safe: bool
    final_answer: str
    self_rag_score: float
    generation_attempts: int
    metadata: Dict[str, Any]

def sql_generation_node(state: GraphState):
    print("\n🟢 [LangGraph Node] Entering SQL Generation...")
    query = state["query"]
    
    cached_sql = get_cached_sql_gen(query)
    if cached_sql:
        return {"generated_sql": cached_sql, "is_sql_safe": validate_sql(cached_sql)}
        
    sql = generate_sql(query)
    set_cached_sql_gen(query, sql)
    return {"generated_sql": sql, "is_sql_safe": validate_sql(sql)}

def sql_execution_node(state: GraphState):
    print("\n🟢 [LangGraph Node] Entering SQL Execution (HITL Approved!)...")
    generated_sql = state["generated_sql"]
    
    cached_results = get_cached_sql_result(generated_sql)
    if cached_results:
        return {"context_docs": format_sql_results(cached_results)}
        
    db_results = execute_sql(generated_sql)
    set_cached_sql_result(generated_sql, db_results)
    return {"context_docs": format_sql_results(db_results)}

def blocked_sql_node(state: GraphState):
    print("\n🔴 [LangGraph Node] SQL Blocked by Guardrails!")
    return {"final_answer": "I cannot execute that query because it failed security validation."}

def rag_retrieval_node(state: GraphState):
    print("\n🔵 [LangGraph Node] Entering Advanced RAG Retrieval...")
    query = state["query"]
    
    hyde_docs = generate_hyde_documents(query)
    search_queries = [query] + hyde_docs
    
    raw_retrieved_docs = search_qdrant(search_queries)
    final_ranked_docs = rerank_documents(query, raw_retrieved_docs)
    crag_verified_docs = crag_grader_and_fallback(query, final_ranked_docs)
    
    safe_xml_context = spotlight_context(crag_verified_docs)
    
    return {"context_docs": [safe_xml_context]}

def finalize_node(state: GraphState):
    print("\n🏁 [LangGraph Node] Entering Finalize - Attaching Metadata...")
    
    metadata = {
        "routing_destination": state.get("destination", "unknown"),
        "generation_attempts": state.get("generation_attempts", 1),
        "self_rag_score": state.get("self_rag_score", 1.0),
        "sql_executed": bool(state.get("generated_sql")),
        "sql_safe": state.get("is_sql_safe", True),
        "status": "completed"
    }
    
    print(f"✅ [Finalize] Attached metadata: {metadata}")
    return {"metadata": metadata}

def generate_answer_node(state: GraphState):
    print("\n🟣 [LangGraph Node] Entering LLM Answer Generation...")
    
    current_attempts = state.get("generation_attempts", 0) + 1
    
    if current_attempts == 1:
        cached_answer = get_cached_rag_answer(state["query"])
        if cached_answer:
            return {"final_answer": cached_answer, "generation_attempts": current_attempts}
            
    answer = generate_final_answer(state["query"], state["context_docs"])
    return {"final_answer": answer, "generation_attempts": current_attempts}

def self_rag_node(state: GraphState):
    print("\n🟣 [LangGraph Node] Entering Self-RAG Reflection...")
    
    score, evaluated_answer = self_rag_reflect(state["query"], state["context_docs"], state["final_answer"])
    
    return {"final_answer": evaluated_answer, "self_rag_score": score}

def intent_router_node(state: GraphState):
    from src.router import route_user_query
    intent = route_user_query(state["query"])
    return {"destination": intent}

def route_intent(state: GraphState):
    """Fans out to RAG, SQL, or Parallel Hybrid execution."""
    intent = state.get("destination", "rag")
    if intent == "hybrid":
        return ["rag_retrieval_node", "sql_generation_node"]
    elif intent == "sql":
        return ["sql_generation_node"]
    return ["rag_retrieval_node"]

def route_sql_safety(state: GraphState):
    if state["is_sql_safe"]:
        return "execute"
    return "blocked"

def route_self_rag(state: GraphState):
    """Graph-native loop tracking attempts and scores."""
    score = state.get("self_rag_score", 1.0)
    attempts = state.get("generation_attempts", 1)
    
    if score < 0.8 and attempts <= 2:
        print(f"🔄 [LangGraph Edge] Self-RAG Score {score:.2f} < 0.8. Rerouting (Attempt {attempts}/2)...")
        return "generate_answer_node"
        
    print(f"✅ [LangGraph Edge] Final answer accepted (Score: {score:.2f}).")
    set_cached_rag_answer(state["query"], state["final_answer"])
    return "finalize_node"

workflow = StateGraph(GraphState)

workflow.add_node("intent_router_node", intent_router_node)
workflow.add_node("sql_generation_node", sql_generation_node)
workflow.add_node("sql_execution_node", sql_execution_node)
workflow.add_node("blocked_sql_node", blocked_sql_node)
workflow.add_node("rag_retrieval_node", rag_retrieval_node)
workflow.add_node("generate_answer_node", generate_answer_node)
workflow.add_node("self_rag_node", self_rag_node)
workflow.add_node("finalize_node", finalize_node)

workflow.set_entry_point("intent_router_node")

workflow.add_conditional_edges(
    "intent_router_node",
    route_intent,
    {"rag_retrieval_node": "rag_retrieval_node", "sql_generation_node": "sql_generation_node"}
)

workflow.add_conditional_edges(
    "sql_generation_node",
    route_sql_safety,
    {"execute": "sql_execution_node", "blocked": "blocked_sql_node"}
)

workflow.add_edge("rag_retrieval_node", "generate_answer_node")
workflow.add_edge("sql_execution_node", "generate_answer_node")
workflow.add_edge("blocked_sql_node", "finalize_node")

workflow.add_edge("generate_answer_node", "self_rag_node")

workflow.add_conditional_edges(
    "self_rag_node",
    route_self_rag,
    {"generate_answer_node": "generate_answer_node", "finalize_node": "finalize_node"}
)
workflow.add_edge("finalize_node", END)
DB_URI = "postgresql://postgres:postgres@localhost:5432/postgres"
pool = ConnectionPool(conninfo=DB_URI, max_size=5)

def get_compiled_graph():
    """Returns the graph with Checkpointing and HITL Interrupt."""
    with pool.connection() as conn:
        checkpointer = PostgresSaver(conn)
        checkpointer.setup() 
        
    return workflow.compile(
        checkpointer=checkpointer,
        interrupt_before=["sql_execution_node"]
    )

app = get_compiled_graph()