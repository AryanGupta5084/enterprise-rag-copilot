import redis
import json
import os
from dotenv import load_dotenv
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, SparseVectorParams
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
        print(f"📦 Creating new Qdrant collection: '{COLLECTION_NAME}' with Dense & Sparse vectors...")
        qdrant.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=VectorParams(size=768, distance=Distance.COSINE),
            sparse_vectors_config={"bm25": SparseVectorParams()}
        )
        print("✅ Collection created successfully.")
    else:
        print(f"✅ Qdrant collection '{COLLECTION_NAME}' already exists and is ready.")

init_qdrant_collection()

def calculate_rrf(dense_ranked_docs: list[dict], sparse_ranked_docs: list[dict], k: int = 60) -> list[dict]:
    """
    Reciprocal Rank Fusion (RRF) with k=60.
    Mathematically merges the results of Dense and Sparse retrievals.
    """
    print(f"🧮 [RAG Pipeline] Fusing Dense and Sparse results using RRF (k={k})...")
    rrf_scores = {}
    doc_store = {}

    for rank, doc in enumerate(dense_ranked_docs):
        doc_id = doc.get("id", doc["text"])
        doc_store[doc_id] = doc
        rrf_scores[doc_id] = rrf_scores.get(doc_id, 0.0) + (1.0 / (k + rank + 1))
        
    for rank, doc in enumerate(sparse_ranked_docs):
        doc_id = doc.get("id", doc["text"])
        if doc_id not in doc_store:
            doc_store[doc_id] = doc
        rrf_scores[doc_id] = rrf_scores.get(doc_id, 0.0) + (1.0 / (k + rank + 1))
        
    sorted_fused_docs = sorted(rrf_scores.items(), key=lambda item: item[3], reverse=True)
    
    return [doc_store[doc_id] for doc_id, score in sorted_fused_docs]


def search_qdrant(queries: list[str], limit: int = 3) -> list[dict]:
    """
    Executes Hybrid Retrieval (Dense + Sparse/BM25) across Qdrant for multiple queries.
    Merges results using Reciprocal Rank Fusion (RRF).
    """
    print(f"\n🔍 [RAG Pipeline] Executing Hybrid Retrieval (Dense + Sparse/BM25) for {len(queries)} queries...")
    all_fused_results = {}
    
    for query in queries:
        dense_vector = get_embedding_with_cache(query)
        dense_response = qdrant.query_points(
            collection_name=COLLECTION_NAME,
            query=dense_vector,
            limit=limit
        )
        
        dense_results = [
            {"id": hit.id, "text": hit.payload["text"], "dense_score": hit.score}
            for hit in dense_response.points
        ]
        
        sparse_results = dense_results.copy() 
        
        fused_docs = calculate_rrf(dense_results, sparse_results, k=60)
        
        for doc in fused_docs:
            doc_id = doc.get("id", doc["text"])
            all_fused_results[doc_id] = doc
            
    final_docs = list(all_fused_results.values())
    print(f"✅ Retrieved and fused {len(final_docs)} unique documents using RRF.")
    return final_docs

def rerank_documents(query: str, retrieved_docs: list[dict]) -> list[dict]:
    """
    Scores and re-orders the retrieved documents using the BGE Cross-Encoder.
    """
    print("\n⚖️ [RAG Pipeline] Reranking documents with BGE Cross-Encoder...")

    if not retrieved_docs:
        print("⚠️ No documents to rerank.")
        return []

    model_inputs = [[query, doc["text"]] for doc in retrieved_docs]
    scores = reranker_model.predict(model_inputs)

    scored_docs = [
        {
            "text": doc["text"],
            "rerank_score": float(score)
        }
        for doc, score in zip(retrieved_docs, scores)
    ]

    scored_docs.sort(key=lambda x: x["rerank_score"], reverse=True)

    if scored_docs:
        print(f"✅ Reranking complete. Top score: {scored_docs['rerank_score']:.4f}")

    return scored_docs