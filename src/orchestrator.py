from typing import TypedDict, List, Dict, Any
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver

from src.text2sql_pipeline import generate_sql, validate_sql, execute_sql, format_sql_results
from src.rag_pipeline import generate_final_answer, crag_grader_and_fallback, self_rag_reflect

class GraphState(TypedDict):
    query: str
    destination: str
    context_docs: List[Dict]
    generated_sql: str
    is_sql_safe: bool
    final_answer: str

def sql_generation_node(state: GraphState):
    """Handles the green Text2SQL generation and validation block."""
    print("\n🟢 [LangGraph Node] Entering SQL Generation...")
    sql = generate_sql(state["query"])
    is_safe = validate_sql(sql)
    return {"generated_sql": sql, "is_sql_safe": is_safe}

def sql_execution_node(state: GraphState):
    """Handles the database execution and formatting."""
    print("\n🟢 [LangGraph Node] Entering SQL Execution...")
    db_results = execute_sql(state["generated_sql"])
    formatted_context = format_sql_results(db_results)
    return {"context_docs": formatted_context}

def blocked_sql_node(state: GraphState):
    """Handles SQL queries that fail the security blocklist."""
    print("\n🔴 [LangGraph Node] SQL Blocked by Guardrails!")
    return {"final_answer": "I cannot execute that query because it failed security validation."}

def generate_answer_node(state: GraphState):
    """Handles the purple LLM Answer Generation block."""
    print("\n🟣 [LangGraph Node] Entering LLM Answer Generation...")
    answer = generate_final_answer(state["query"], state["context_docs"])
    return {"final_answer": answer}

def rag_retrieval_node(state: GraphState):
    """Handles the blue RAG Pipeline block (Retrieval + CRAG)."""
    print("\n🔵 [LangGraph Node] Entering RAG Retrieval...")
    
    mock_retrieved_docs = [
        {
            "document": "Kubernetes pods can be restarted using kubectl delete pod.", 
            "vector_score": 0.9, 
            "rerank_score": 0.95
        }
    ]
    
    crag_results = crag_grader_and_fallback(state["query"], mock_retrieved_docs)
    
    return {"context_docs": crag_results["documents"]}

def self_rag_node(state: GraphState):
    """Handles the purple Self-RAG reflection loop."""
    print("\n🟣 [LangGraph Node] Entering Self-RAG Reflection...")
    
    final_evaluated_answer = self_rag_reflect(state["query"], state["context_docs"], state["final_answer"])
    
    return {"final_answer": final_evaluated_answer}

def route_intent(state: GraphState):
    """The Intent Router: Decides whether to go down the RAG or SQL path."""
    print(f"\n🔀 [LangGraph Router] Routing query down the '{state['destination']}' pipeline...")
    if state["destination"] == "sql":
        return "sql"
    return "rag"

def route_sql_safety(state: GraphState):
    """Routes the graph based on whether the SQL passed the blocklist."""
    if state["is_sql_safe"]:
        return "execute"
    return "blocked"

workflow = StateGraph(GraphState)

workflow.add_node("generate_sql", sql_generation_node)
workflow.add_node("execute_sql", sql_execution_node)
workflow.add_node("blocked_sql", blocked_sql_node)
workflow.add_node("rag_retrieval", rag_retrieval_node)
workflow.add_node("generate_answer", generate_answer_node)
workflow.add_node("self_rag", self_rag_node)

workflow.set_conditional_entry_point(
    route_intent,
    {
        "sql": "generate_sql",
        "rag": "rag_retrieval"
    }
)

workflow.add_conditional_edges("generate_sql", route_sql_safety, {"execute": "execute_sql", "blocked": "blocked_sql"})
workflow.add_edge("execute_sql", "generate_answer")
workflow.add_edge("blocked_sql", END)

workflow.add_edge("rag_retrieval", "generate_answer")

workflow.add_edge("generate_answer", "self_rag")
workflow.add_edge("self_rag", END)

memory = MemorySaver()
app_graph = workflow.compile(
    checkpointer=memory,
    interrupt_before=["execute_sql"] 
)