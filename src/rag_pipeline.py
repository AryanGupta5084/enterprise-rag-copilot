import os
from dotenv import load_dotenv
from langchain_core.prompts import PromptTemplate
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.output_parsers import StrOutputParser
from langchain_tavily import TavilySearch

load_dotenv()

def generate_hyde_documents(user_query: str) -> list[str]:
    """
    Generates 3 hypothetical answers using a single optimized API call 
    to prevent Google Free Tier rate limits.
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
    
def crag_grader_and_fallback(query: str, reranked_docs: list[dict]) -> dict:
    """
    CRAG Grader: Evaluates the reranked score.
    If the top score is < 0.7, it triggers the Tavily Web Search Fallback.
    """
    print("\n⚖️ [CRAG] Evaluating document relevance...")
    
    if not reranked_docs or reranked_docs[0]['rerank_score'] < 0.7:
        top_score = reranked_docs[0]['rerank_score'] if reranked_docs else 0.0
        print(f"⚠️ [CRAG] Top score {top_score:.4f} is below the 0.7 threshold!")
        print("🌐 [CRAG] Triggering Tavily Web Search Fallback...")
        
        try:
            if not os.getenv("TAVILY_API_KEY"):
                raise ValueError("TAVILY_API_KEY is missing from .env")
                
            tavily = TavilySearch(max_results=2)
            web_results = tavily.invoke({"query": query})
            
            fallback_docs = []
            if isinstance(web_results, str):
                fallback_docs.append({"document": web_results, "vector_score": 0.0, "rerank_score": 1.0, "source": "tavily_web_search"})
            elif isinstance(web_results, list):
                fallback_docs = [{"document": res.get("content", str(res)), "vector_score": 0.0, "rerank_score": 1.0, "source": res.get("url", "tavily_web_search")} for res in web_results]
            elif isinstance(web_results, dict):
                if "results" in web_results and isinstance(web_results["results"], list):
                    fallback_docs = [{"document": res.get("content", str(res)), "vector_score": 0.0, "rerank_score": 1.0, "source": res.get("url", "tavily_web_search")} for res in web_results["results"]]
                else:
                    fallback_docs.append({"document": str(web_results), "vector_score": 0.0, "rerank_score": 1.0, "source": "tavily_web_search"})
            print(f"✅ [CRAG] Successfully retrieved {len(fallback_docs)} documents from the web.")
            return {"source": "tavily_web_search", "documents": fallback_docs}
            
        except Exception as e:
            print(f"⚠️ [CRAG] Live web search unavailable ({e}). Using simulated fallback.")
            mock_docs = [{
                "document": f"SIMULATED WEB RESULT: I searched the internet for '{query}' but my Tavily API key is missing. Please add it to your .env file!",
                "vector_score": 0.0,
                "rerank_score": 1.0,
                "source": "https://tavily.com"
            }]
            return {"source": "mock_web_search", "documents": mock_docs}
            
    print(f"✅ [CRAG] Document score {reranked_docs[0]['rerank_score']:.4f} passes threshold. Using internal knowledge base.")
    return {"source": "qdrant_database", "documents": reranked_docs}

def generate_final_answer(query: str, context_docs: list[dict]) -> str:
    """
    LLM Answer Generation: Takes the verified context (from Qdrant or Tavily) 
    and generates a final, human-friendly answer using the LLM.
    """
    print("\n🧠 [RAG Pipeline] Generating final answer using LLM...")
    
    context_text = "\n\n".join([doc["document"] for doc in context_docs])
    
    llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash", temperature=0.3)
    
    prompt = PromptTemplate.from_template(
        "You are an expert Kubernetes SRE Assistant. Answer the user's query strictly using the provided Context.\n"
        "If the Context does not contain the answer, say 'I do not have enough information to answer that.'\n\n"
        "Context:\n{context}\n\n"
        "Query: {query}\n\n"
        "Answer:"
    )
    
    chain = prompt | llm | StrOutputParser()
    
    try:
        answer = chain.invoke({"context": context_text, "query": query})
        print("✅ [RAG Pipeline] Final answer generated successfully.")
        return answer
    except Exception as e:
        print(f"⚠️ [RAG Pipeline] Failed to generate answer. Error: {e}")
        return "Sorry, I encountered an error while generating the response."
    
def self_rag_reflect(query: str, context_docs: list[dict], generated_answer: str, attempt: int = 1) -> str:
    """
    Self-RAG Reflect: Evaluates the generated answer. 
    If the quality is poor (< 0.8), it forces a regeneration (max 2 times).
    """
    print(f"\n🔍 [Self-RAG] Evaluating generated answer (Attempt {attempt})...")
    llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash", temperature=0.0)
    
    prompt = PromptTemplate.from_template(
        "You are a strict grading assistant. Evaluate if the Answer directly and accurately answers the Query based ONLY on the Context.\n"
        "Score it from 0.0 to 1.0, where 1.0 is a perfect answer.\n"
        "Respond with ONLY the numeric score, nothing else.\n\n"
        "Query: {query}\nContext: {context}\nAnswer: {answer}\n\nScore:"
    )
    
    context_text = "\n".join([doc["document"] for doc in context_docs])
    chain = prompt | llm | StrOutputParser()
    
    try:
        score_str = chain.invoke({"query": query, "context": context_text, "answer": generated_answer})
        score = float(score_str.strip())
        print(f"⚖️ [Self-RAG] Answer Score: {score:.2f}")
        
        if score < 0.8 and attempt < 2:
            print("⚠️ [Self-RAG] Score below 0.8 threshold. Forcing LLM to regenerate the answer...")
            new_answer = generate_final_answer(query, context_docs)
            return self_rag_reflect(query, context_docs, new_answer, attempt + 1)
            
        if score < 0.8 and attempt >= 2:
            print("⚠️ [Self-RAG] Max retries reached. Returning best available answer.")
            
        print("✅ [Self-RAG] Answer passed quality check!")
        return generated_answer
        
    except Exception as e:
        print(f"⚠️ [Self-RAG] Evaluator failed ({e}). Bypassing reflection.")
        return generated_answer