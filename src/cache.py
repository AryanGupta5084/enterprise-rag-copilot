import os
import redis
import json
import hashlib
try:
    redis_client = redis.Redis(
        host=os.getenv("UPSTASH_REDIS_HOST"),
        port=int(os.getenv("UPSTASH_REDIS_PORT", 6379)),
        password=os.getenv("UPSTASH_REDIS_PASSWORD"),
        ssl=True,
        decode_responses=True
    )
    print("✅ Successfully connected to Serverless Upstash Redis!")
except Exception as e:
    print(f"❌ Failed to connect to Upstash Redis: {e}")

TTL_SQL_GEN    = 24 * 60 * 60
TTL_SQL_RESULT = 15 * 60
TTL_RAG_ANSWER = 60 * 60

def _generate_key(prefix: str, text: str) -> str:
    """Generates a secure SHA-256 hash for the Redis key."""
    text_hash = hashlib.sha256(text.strip().lower().encode('utf-8')).hexdigest()
    return f"{prefix}:{text_hash}"

def get_cached_sql_gen(query: str):
    key = _generate_key("sql_gen", query)
    cached = redis_client.get(key)
    if cached:
        print("🔥 [Redis Cache] HIT! (Tier 3: SQL Gen) - Bypassing Text2SQL LLM.")
        return cached
    return None

def set_cached_sql_gen(query: str, sql_query: str):
    key = _generate_key("sql_gen", query)
    redis_client.setex(key, TTL_SQL_GEN, sql_query)

def get_cached_sql_result(sql_query: str):
    key = _generate_key("sql_res", sql_query)
    cached = redis_client.get(key)
    if cached:
        print("🔥 [Redis Cache] HIT! (Tier 4: SQL Result) - Bypassing Postgres DB.")
        return json.loads(cached)
    return None

def set_cached_sql_result(sql_query: str, result_rows: list):
    key = _generate_key("sql_res", sql_query)
    redis_client.setex(key, TTL_SQL_RESULT, json.dumps(result_rows))

def get_cached_rag_answer(query: str):
    key = _generate_key("rag_ans", query)
    cached = redis_client.get(key)
    if cached:
        print("🔥 [Redis Cache] HIT! (Tier 5: RAG Answer) - Bypassing entire LangGraph RAG pipeline.")
        return cached
    return None

def set_cached_rag_answer(query: str, final_answer: str):
    key = _generate_key("rag_ans", query)
    redis_client.setex(key, TTL_RAG_ANSWER, final_answer)