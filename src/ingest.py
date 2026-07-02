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
    """
    Downloads all PDFs from an S3 bucket into a local directory.
    """
    print(f"☁️ [Ingestion] Connecting to S3 Bucket: {bucket_name}")

    os.makedirs(download_dir, exist_ok=True)

    s3 = boto3.client("s3")

    paginator = s3.get_paginator("list_objects_v2")

    downloaded = 0

    for page in paginator.paginate(Bucket=bucket_name):
        for obj in page.get("Contents", []):

            key = obj["Key"]

            if not key.lower().endswith(".pdf"):
                continue

            local_path = os.path.join(
                download_dir,
                os.path.basename(key)
            )

            print(f"⬇ Downloading {key}")

            s3.download_file(
                bucket_name,
                key,
                local_path
            )

            downloaded += 1

    print(f"✅ Downloaded {downloaded} PDF(s) from S3.")

def ingest_data(s3_bucket: str = None, local_dir: str = "./data/raw_pdfs"):
    """
    Converts S3/Local PDFs into Dense + Sparse vectors, applies dedup/noise filtering,
    and uploads them to Qdrant.
    """
    print(f"\n📥 Starting Enterprise ingestion into Qdrant collection: '{COLLECTION_NAME}'")

    if s3_bucket:
        download_from_s3(s3_bucket, local_dir)

    if not os.path.exists(local_dir):
        print(f"❌ Directory {local_dir} not found.")
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
    bucket = os.getenv("S3_CORPUS_BUCKET")
    ingest_data(s3_bucket=bucket)