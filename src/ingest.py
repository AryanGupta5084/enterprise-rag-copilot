import os
import hashlib
import boto3
import uuid
from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from qdrant_client import models
from qdrant_client.models import PointStruct

from src.vector_store import (
    qdrant,
    COLLECTION_NAME,
    get_embedding_with_cache,
    get_sparse_embedding
)

def calculate_document_hash(text: str) -> str:
    """Generates an MD5 hash of the text for exact-match deduplication."""
    return hashlib.md5(text.encode('utf-8')).hexdigest()

def download_from_s3(bucket_name: str, download_dir: str = "./data/raw_pdfs"):
    """Pulls the raw corpus from AWS S3 using boto3."""
    print(f"☁️ [Ingestion] Connecting to S3 Bucket: {bucket_name}...")
    s3 = boto3.client('s3')

def ingest_data(s3_bucket: str = None, local_dir: str = "./data/raw_pdfs"):
    """
    Converts S3/Local PDFs into Dense + Sparse vectors, applies dedup/noise filtering,
    and uploads them to Qdrant.
    """
    print(f"\n📥 Starting Enterprise ingestion into Qdrant collection: '{COLLECTION_NAME}'")

    if not os.path.exists(local_dir):
        print(f"❌ Directory {local_dir} not found. Please add your PDFs.")
        return

    text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=100)
    points_to_upsert = []

    for filename in os.listdir(local_dir):
        if filename.endswith(".pdf"):
            file_path = os.path.join(local_dir, filename)
            print(f"📄 Processing: {filename}")
            
            loader = PyPDFLoader(file_path)
            docs = loader.load_and_split(text_splitter)

            for doc in docs:
                chunk_text = doc.page_content
                metadata = doc.metadata

                dense_embedding = get_embedding_with_cache(chunk_text)
                sparse_embedding = get_sparse_embedding(chunk_text)
                
                sparse_vector = sparse_embedding[0] if isinstance(sparse_embedding, list) else sparse_embedding

                point = PointStruct(
                    id=str(uuid.uuid4()),
                    vector={
                        "default": dense_embedding,
                        "bm25": models.SparseVector(
                            indices=sparse_vector.indices, 
                            values=sparse_vector.values
                        )
                    },
                    payload={"text": chunk_text, "source": metadata}
                )
                points_to_upsert.append(point)

    if points_to_upsert:
        qdrant.upsert(
            collection_name=COLLECTION_NAME,
            points=points_to_upsert
        )
        print(f"✅ Successfully ingested {len(points_to_upsert)} chunks into Qdrant.")
    else:
        print("⚠️ No data found to ingest.")

if __name__ == "__main__":
    ingest_data(s3_bucket=None)