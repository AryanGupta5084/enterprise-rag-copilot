import redis
import json
import os
from dotenv import load_dotenv
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams
from langchain_huggingface import HuggingFaceEmbeddings
from sentence_transformers import CrossEncoder

load_dotenv()

try:
    qdrant = QdrantClient(host="localhost", port=6333)
    print("✅ Qdrant connection established.")
except Exception as e:
    print(f"❌ Qdrant connection failed: {e}")

redis_client = redis.Redis(host='localhost', port=6379, db=0, decode_responses=True)

try:
    embedding_model = HuggingFaceEmbeddings(model_name="BAAI/bge-base-en-v1.5")
    print("✅ High-Performance BGE Embedding model loaded.")
except Exception as e:
    print(f"❌ Failed to load HuggingFace Embeddings. Error: {e}")

try:
    reranker_model = CrossEncoder('BAAI/bge-reranker-base')
    print("✅ High-Performance BGE Cross-Encoder Reranker loaded.")
except Exception as e:
    print(f"❌ Failed to load BGE Reranker. Error: {e}")


EMBEDDING_CACHE_TTL = 7 * 24 * 60 * 60

def get_embedding_with_cache(text: str) -> list[float]:
    """Embeds text using HuggingFace with a 7-Day Redis Cache."""
    cache_key = f"embed_bge768:{text.strip()}"
    cached_vector = redis_client.get(cache_key)
    
    if cached_vector:
        return json.loads(cached_vector)
        
    vector = embedding_model.embed_query(text)
    redis_client.setex(cache_key, EMBEDDING_CACHE_TTL, json.dumps(vector))
    return vector

COLLECTION_NAME = "kubernetes_kb"

def init_qdrant_collection():
    """Creates the 768-dim Qdrant collection only if it doesn't exist."""
    collections_response = qdrant.get_collections()
    collection_names = [collection.name for collection in collections_response.collections]
    
    if COLLECTION_NAME not in collection_names:
        print(f"📦 Creating new Qdrant collection: '{COLLECTION_NAME}' with 768 dimensions...")
        qdrant.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=VectorParams(size=768, distance=Distance.COSINE),
        )
        print("✅ Collection created successfully.")
    else:
        print(f"✅ Qdrant collection '{COLLECTION_NAME}' already exists and is ready.")

init_qdrant_collection()

def search_qdrant(query_vector: list[float], limit: int = 3) -> list[dict]:
    """
    Searches the Qdrant database for the closest matching documents.
    Returns both the text and the original vector similarity score.
    """
    print(f"🔍 Searching Qdrant collection '{COLLECTION_NAME}'...")
    
    response = qdrant.query_points(
        collection_name=COLLECTION_NAME,
        query=query_vector,
        limit=limit
    )
    
    retrieved_docs = [
        {
            "text": hit.payload["text"],
            "vector_score": hit.score
        }
        for hit in response.points
    ]
    
    print(f"✅ Retrieved {len(retrieved_docs)} relevant documents.")
    return retrieved_docs

def rerank_documents(query: str, retrieved_docs: list[dict]) -> list[dict]:
    """
    Scores and re-orders the retrieved documents using the BGE Cross-Encoder.
    """
    print("⚖️ Reranking documents with BGE Cross-Encoder...")

    if not retrieved_docs:
        print("⚠️ No documents to rerank.")
        return []

    model_inputs = [[query, doc["text"]] for doc in retrieved_docs]

    scores = reranker_model.predict(model_inputs)

    scored_docs = [
        {
            "document": doc["text"],
            "vector_score": doc["vector_score"],
            "rerank_score": float(score)
        }
        for doc, score in zip(retrieved_docs, scores)
    ]

    scored_docs.sort(key=lambda x: x["rerank_score"], reverse=True)

    if scored_docs:
        print(f"✅ Reranking complete. Top score: {scored_docs[0]['rerank_score']:.4f}")

    return scored_docs