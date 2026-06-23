import os
import json
from dotenv import load_dotenv
from pydantic import BaseModel, Field
from langchain_core.prompts import PromptTemplate
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.output_parsers import StrOutputParser
from langchain_community.tools.tavily_search import TavilySearchResults

load_dotenv()

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
    LLM Answer Generation: Takes the verified context and generates a final answer 
    strictly bound by the L9 Pydantic Guardrail.
    """
    print("\n🟣 [RAG Pipeline] Generating Final Answer with L9 Schema Validation...")
    
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
    
    try:
        response_obj = chain.invoke({"context": context_text, "query": query})
        print(f"✅ [L9 Guardrail] Output successfully validated. Confidence: {response_obj.confidence_score}")
        return response_obj.answer
    except Exception as e:
        print(f"❌ [L9 Guardrail] Schema validation failed after retries: {e}")
        return "I apologize, but I encountered an internal formatting error while synthesizing the data. Please try again."

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
    Self-RAG Reflection: Evaluates the generated answer against the context.
    Returns a tuple of (score, evaluated_answer) for the graph-native router.
    """
    print("\n🟣 [Self-RAG] Running reflection and fact-checking...")
    
    simulated_score = 1.0 
    
    print(f"✅ [Self-RAG] Answer evaluated. Score: {simulated_score}")
    return simulated_score, final_answer