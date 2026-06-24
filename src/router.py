import os
import redis
from dotenv import load_dotenv
from langchain_core.prompts import PromptTemplate
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.output_parsers import StrOutputParser

load_dotenv()

try:
    # ☁️ Connecting to Upstash Serverless Redis (Aligns with Enterprise Diagram)
    redis_client = redis.Redis(
        host=os.getenv("UPSTASH_REDIS_HOST"),
        port=int(os.getenv("UPSTASH_REDIS_PORT", 6379)),
        password=os.getenv("UPSTASH_REDIS_PASSWORD"),
        ssl=True, # Required for Upstash Serverless
        decode_responses=True
    )
    INTENT_CACHE_TTL = 86400 # 24 hours (Matches Tier 2 Cache in Architecture)
except Exception as e:
    print(f"❌ Failed to connect to Upstash Redis: {e}")

def route_user_query(user_query: str) -> str:
    """
    Intent Router: Dynamically routes the query to 'rag', 'sql', or 'hybrid'
    based on semantic intent, wrapped in a 24-hour Redis cache.
    """
    cache_key = f"intent:{user_query.lower().strip()}"
    
    cached_intent = redis_client.get(cache_key)
    if cached_intent:
        print(f"🔥 [Intent Router] Cache hit! Returning intent '{cached_intent.upper()}' directly from Upstash Redis.")
        return cached_intent

    print("🥶 [Intent Router] Cache miss. Analyzing semantic intent with LLM...")
    
    llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash", temperature=0.0)
    
    prompt = PromptTemplate.from_template(
        "You are an expert intent router for an Enterprise Kubernetes SRE Copilot.\n"
        "Classify the user's query into one of three distinct routing paths:\n\n"
        "1. 'sql' - If the query asks for structured live metrics, counts, database rows, or specific incident status.\n"
        "2. 'rag' - If the query asks for documentation, troubleshooting steps, logs, or conceptual explanations.\n"
        "3. 'hybrid' - If the query requires BOTH live database metrics AND conceptual troubleshooting documentation.\n\n"
        "Return ONLY the exact word: 'rag', 'sql', or 'hybrid'. Do not return any other text.\n\n"
        "Query: {query}\n"
        "Route:"
    )
    
    chain = prompt | llm | StrOutputParser()
    
    try:
        intent = chain.invoke({"query": user_query}).strip().lower()
        
        if intent not in ["rag", "sql", "hybrid"]:
            print(f"⚠️ [Intent Router] Unrecognized output '{intent}', defaulting to 'rag'.")
            intent = "rag" 
            
    except Exception as e:
        print(f"❌ [Intent Router] Routing failed, defaulting to 'rag'. Error: {e}")
        intent = "rag"
        
    print(f"✅ [Intent Router] Query intelligently routed to: {intent.upper()}")
    
    redis_client.setex(cache_key, INTENT_CACHE_TTL, intent)
    
    return intent