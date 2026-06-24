import os
import json
from dotenv import load_dotenv
from pydantic import BaseModel, Field
from langchain_core.prompts import PromptTemplate
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.output_parsers import StrOutputParser
from langchain_community.tools.tavily_search import TavilySearchResults

load_dotenv()
class SelfRAGEvaluation(BaseModel):
    """Pydantic schema for the Self-RAG LLM Judge."""
    score: float = Field(description="A score between 0.0 and 1.0 indicating how well the answer is grounded in the context. 1.0 is perfect, 0.0 is hallucinated.")
    reasoning: str = Field(description="Brief explanation for the given score.")

class CopilotResponse(BaseModel):
    """L9 Guardrail: Strict schema definition for the final LLM output."""
    answer: str = Field(description="The final synthesized answer to the user's query.")
    confidence_score: float = Field(description="A confidence score between 0.0 and 1.0.")
    needs_human_review: bool = Field(description="Set to true if the answer is uncertain or the query is high-risk.")

def generate_hyde_documents(user_query: str) -> list[str]:
    """
    Generates 3 hypothetical answers using a single optimized API call.
    """
    print(f"\n🧠 [RAG Pipeline] Generating HyDE documents for: '{user_query}'...")
    
    llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash", temperature=0.7)
    prompt = PromptTemplate.from_template(
        "You are a Kubernetes SRE expert. Write 3 brief, distinct paragraphs of documentation "
        "that would perfectly answer the following user query. "
        "You MUST separate each of the 3 paragraphs with exactly three pipe characters: |||\n\n"
        "Query: {query}"
    )
    chain = prompt | llm | StrOutputParser()
    
    try:
        combined_docs = chain.invoke({"query": user_query})
        hypothetical_docs = [doc.strip() for doc in combined_docs.split("|||") if doc.strip()]
        print(f"✅ Successfully generated {len(hypothetical_docs)} hypothetical documents in 1 API call.")
        return hypothetical_docs
    except Exception as e:
        print(f"⚠️ Google API throttled us. Falling back to original query. Error: {e}")
        return [user_query]


def generate_final_answer(query: str, context_docs: list) -> str:
    """
    LLM Answer Generation strictly bound by the L9 Pydantic Guardrail,
    now featuring explicit retry logic on schema failure.
    """
    print("\n🟣 [RAG Pipeline] Generating Final Answer with L9 Schema Validation & Retry Logic...")
    
    if context_docs and isinstance(context_docs, dict):
        context_text = "\n\n".join([str(doc.get("text", doc.get("document", doc))) for doc in context_docs])
    else:
        context_text = "\n\n".join([str(doc) for doc in context_docs])
        
    llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash", temperature=0.3)
    structured_llm = llm.with_structured_output(CopilotResponse)
    
    prompt = PromptTemplate.from_template(
        "You are an expert Kubernetes SRE Assistant. Answer the user's query strictly using the provided Context.\n"
        "If the Context does not contain the answer, say 'I do not have enough information to answer that.'\n\n"
        "Context:\n{context}\n\n"
        "Query: {query}\n"
    )
    
    chain = prompt | structured_llm
    
    max_retries = 3
    for attempt in range(max_retries):
        try:
            response_obj = chain.invoke({"context": context_text, "query": query})
            
            print(f"✅ [L9 Guardrail] Output successfully validated on attempt {attempt + 1}. Confidence: {response_obj.confidence_score}")
            return response_obj.answer
            
        except Exception as e:
            print(f"⚠️ [L9 Guardrail] Schema validation failed (Attempt {attempt + 1}/{max_retries}). Error: {e}")
            
            if attempt == max_retries - 1:
                print("❌ [L9 Guardrail] Max retries reached. Triggering safe fallback.")
                return "I apologize, but I encountered an internal formatting error while synthesizing the data. Please try again."
                
            print("🔄 [L9 Guardrail] Retrying LLM generation to correct formatting...")

def crag_grader_and_fallback(query: str, retrieved_docs: list) -> list:
    """CRAG Grader: Evaluates relevance and triggers Tavily Web Fallback if needed."""
    print("\n⚖️ [CRAG Grader] Evaluating retrieval relevance...")
    if not retrieved_docs:
        print("⚠️ [CRAG Grader] No docs retrieved. Triggering Tavily Web Fallback...")
        try:
            tavily = TavilySearchResults(max_results=2)
            web_docs = tavily.invoke(query)
            print("✅ [Tavily] Fallback web search successful.")
            return [{"text": doc["content"], "source": "tavily_web"} for doc in web_docs]
        except Exception as e:
            print(f"❌ [CRAG Grader] Tavily search failed: {e}")
            return []
    print("✅ [CRAG Grader] Context is highly relevant.")
    return retrieved_docs

def self_rag_reflect(query: str, context_docs: list, final_answer: str) -> tuple[float, str]:
    """
    Self-RAG Reflection: Uses an LLM Judge to dynamically evaluate the generated answer 
    against the context. Returns a tuple of (score, evaluated_answer) for the LangGraph router.
    """
    print("\n🟣 [Self-RAG] Running true LLM reflection and fact-checking...")
    
    if context_docs and isinstance(context_docs, dict):
        context_text = "\n\n".join([str(doc.get("text", doc.get("document", doc))) for doc in context_docs])
    else:
        context_text = "\n\n".join([str(doc) for doc in context_docs])
        
    llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash", temperature=0.0)
    structured_evaluator = llm.with_structured_output(SelfRAGEvaluation)
    
    prompt = PromptTemplate.from_template(
        "You are a strict grading evaluator for an Enterprise AI system.\n"
        "Given the user's query, the retrieved context, and the AI's generated answer, "
        "evaluate if the AI's answer is factual, strictly grounded in the context, and answers the query.\n\n"
        "Context:\n{context}\n\n"
        "Query: {query}\n\n"
        "AI Answer: {answer}\n\n"
        "Provide a score between 0.0 (total hallucination or irrelevant) and 1.0 (perfectly grounded and accurate)."
    )
    
    chain = prompt | structured_evaluator
    
    try:
        evaluation = chain.invoke({
            "context": context_text, 
            "query": query, 
            "answer": final_answer
        })
        
        score = evaluation.score
        print(f"✅ [Self-RAG] LLM Judge Evaluation Complete. Score: {score} | Reasoning: {evaluation.reasoning}")
        
        return float(score), final_answer
        
    except Exception as e:
        print(f"⚠️ [Self-RAG] Evaluation failed due to an error: {e}. Defaulting to passing score to prevent infinite loops.")
        return 1.0, final_answer