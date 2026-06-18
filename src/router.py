import redis

try:
    redis_client = redis.Redis(host='localhost', port=6379, db=0, decode_responses=True)
    INTENT_CACHE_TTL = 86400
except Exception as e:
    print(f"Failed to connect to Redis: {e}")

def route_user_query(user_query: str) -> str:
    """
    Acts as the entry point for our LangGraph State Machine.
    Decides if the query goes to the 'RAG' or 'Text2SQL' pipeline.
    """
    cache_key = f"intent:{user_query.lower().strip()}"
    
    cached_intent = redis_client.get(cache_key)
    if cached_intent:
        print("🔥 Cache hit! Returning the intent directly from Redis.")
        return cached_intent

    print("🥶 Cache miss. Analyzing intent...")
    
    sql_keywords = ["database", "table", "count", "sql", "rows", "select", "how many"]
    
    if any(keyword in user_query.lower() for keyword in sql_keywords):
        intent = "sql"
    else:
        intent = "rag"
        
    redis_client.setex(cache_key, INTENT_CACHE_TTL, intent)
    
    return intent