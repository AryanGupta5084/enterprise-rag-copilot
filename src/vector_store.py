import redis
import json
import os
from dotenv import load_dotenv
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, SparseVectorParams, SparseVector
from langchain_huggingface import HuggingFaceEmbeddings
from sentence_transformers import CrossEncoder
from fastembed import SparseTextEmbedding
from qdrant_client.http.exceptions import UnexpectedResponse
from qdrant_client import models

load_dotenv()

try:
    qdrant_url = os.getenv("QDRANT_URL", "http://qdrant:6333")
    qdrant = QdrantClient(url=qdrant_url)
    print("✅ Qdrant connection established.")
except Exception as e:
    print(f"❌ Qdrant connection failed: {e}")

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

try:
    embedding_model = HuggingFaceEmbeddings(model_name="BAAI/bge-base-en-v1.5")
    print("✅ High-Performance BGE Dense Embedding model loaded.")
except Exception as e:
    print(f"❌ Failed to load HuggingFace Embeddings. Error: {e}")

try:
    reranker_model = CrossEncoder('BAAI/bge-reranker-base')
    print("✅ High-Performance BGE Cross-Encoder Reranker loaded.")
except Exception as e:
    print(f"❌ Failed to load BGE Reranker. Error: {e}")

try:
    sparse_embedding_model = SparseTextEmbedding(model_name="Qdrant/bm25")
    print("✅ High-Performance BM25 Sparse Embedding model loaded.")
except Exception as e:
    print(f"❌ Failed to load BM25 Sparse Embeddings. Error: {e}")

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
    """Creates the 768-dim Qdrant collection, gracefully ignoring if it already exists."""
    try:
        print(f"📦 Attempting to create Qdrant collection: '{COLLECTION_NAME}'...")
        qdrant.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config={"default": VectorParams(size=768, distance=Distance.COSINE)},
            sparse_vectors_config={"bm25": SparseVectorParams()}
        )
        print("✅ Collection created successfully.")
        
    except UnexpectedResponse as e:
        if getattr(e, 'status_code', None) == 409 or "already exists" in str(e):
            print(f"✅ Qdrant collection '{COLLECTION_NAME}' already exists and is ready.")
        else:
            raise e

init_qdrant_collection()

def get_sparse_embedding(text: str):
    """Generates a real BM25 sparse vector (indices and values) for exact keyword matching."""
    sparse_result = list(sparse_embedding_model.embed([text]))
    return sparse_result


def calculate_rrf(dense_ranked_docs: list, sparse_ranked_docs: list, k: int = 60) -> list:
    """ Reciprocal Rank Fusion (RRF) with k=60. Mathematically merges the results of Dense and Sparse retrievals. """
    print(f"🧮 [RAG Pipeline] Fusing Dense and Sparse results using RRF (k={k})...")
    rrf_scores = {}
    doc_store = {}
    
    for rank, doc in enumerate(dense_ranked_docs):
        doc_id = doc.id
        doc_store[doc_id] = doc
        rrf_scores[doc_id] = rrf_scores.get(doc_id, 0) + 1 / (k + rank + 1)
        
    for rank, doc in enumerate(sparse_ranked_docs):
        doc_id = doc.id
        doc_store[doc_id] = doc
        rrf_scores[doc_id] = rrf_scores.get(doc_id, 0) + 1 / (k + rank + 1)
    sorted_docs = sorted(rrf_scores.items(), key=lambda x: x[1], reverse=True)
    
    return [doc_store[doc_id] for doc_id, score in sorted_docs]


def search_qdrant(queries: list[str], limit: int = 3) -> list[dict]:
    """ Executes TRUE Hybrid Retrieval using Qdrant's modern query_points API. """
    print(f"\n🔍 [RAG Pipeline] Executing True Hybrid Retrieval (Dense + Sparse/BM25) for {len(queries)} queries...")
    
    all_fused_results = {}
    
    for query in queries:
        dense_embedding = get_embedding_with_cache(query)
        sparse_embedding_list = get_sparse_embedding(query)
        
        sparse_vector = sparse_embedding_list[0]
        
        dense_response = qdrant.query_points(
            collection_name=COLLECTION_NAME,
            query=dense_embedding, 
            using="default",
            limit=limit
        )

        sparse_response = qdrant.query_points(
            collection_name=COLLECTION_NAME,
            query=models.SparseVector(
                indices=sparse_vector.indices,
                values=sparse_vector.values
            ),
            using="bm25",
            limit=limit
        )
        
        fused = calculate_rrf(dense_response.points, sparse_response.points)
        
        for doc in fused:
            all_fused_results[doc.id] = doc
            
    return list(all_fused_results.values())

def rerank_documents(query: str, retrieved_docs: list) -> list[dict]:
    """ Scores and re-orders the retrieved documents using the BGE Cross-Encoder, 
        and converts them into standard dictionaries for LangGraph state serialization. """
    print("\n⚖️ [RAG Pipeline] Reranking documents with BGE Cross-Encoder...")
    
    if not retrieved_docs:
        return []
        
    pairs = [[query, doc.payload.get("text", "")] for doc in retrieved_docs]
    scores = reranker_model.predict(pairs)
    
    final_docs = []
    for doc, score in zip(retrieved_docs, scores):
        final_docs.append({
            "id": str(doc.id),
            "text": doc.payload.get("text", ""),
            "source": doc.payload.get("source", {}),
            "score": float(score)
        })
        
    final_docs.sort(key=lambda x: x["score"], reverse=True)
    return final_docs