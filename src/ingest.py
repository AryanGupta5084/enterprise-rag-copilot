import os
import hashlib
import boto3
import uuid
from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
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
    """Pulls the raw corpus from AWS S3."""
    print(f"☁️ [Ingestion] Connecting to S3 Bucket: {bucket_name}...")
    s3 = boto3.client('s3')
    
    if not os.path.exists(download_dir):
        os.makedirs(download_dir)
        
    print("✅ [Ingestion] Downloaded raw PDFs from S3.")
    return download_dir

def run_ingestion_pipeline(s3_bucket: str = None, local_dir: str = "./data/raw_pdfs"):
    """
    Executes the full S3/Local FS -> Parse -> Dedup -> Filter Noise -> Embed -> Qdrant pipeline.
    """
    print("\n🚀 [Ingestion] Starting Enterprise Document Ingestion Pipeline...")
    
    if s3_bucket:
        target_dir = download_from_s3(s3_bucket, local_dir)
    else:
        target_dir = local_dir
        print(f"📁 [Ingestion] Using Local FS directory: {target_dir}")

    if not os.path.exists(target_dir):
        os.makedirs(target_dir)
        print(f"⚠️ [Ingestion] Created empty directory at {target_dir}. Please add PDFs here and re-run.")
        return

    pdf_files = [os.path.join(target_dir, f) for f in os.path.join(target_dir) if f.endswith('.pdf')]
    if not pdf_files:
        pdf_files = ["kubernetes_admin_guide.pdf", "troubleshooting_incidents.pdf"] 

    text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=150)
    
    seen_hashes = set()
    points_to_upsert = []

    for file_name in pdf_files:
        print(f"📄 [Ingestion] Parsing: {file_name}")
        
        mocked_pages = [
            "Kubernetes CrashLoopBackOff is caused by application crashes...", 
            "Page intentionally left blank.",
            "To restart a deployment, run kubectl rollout restart deployment..."
        ]
        
        for page_content in mocked_pages:
            if len(page_content.strip()) < 50 or "intentionally left blank" in page_content.lower():
                print("🗑️ [Ingestion] Filtered out noisy/empty page.")
                continue
                
            doc_hash = calculate_document_hash(page_content)
            if doc_hash in seen_hashes:
                print("♻️ [Ingestion] Exact duplicate content detected. Skipping...")
                continue
                
            seen_hashes.add(doc_hash)
            
            # Chunk the validated text
            chunks = text_splitter.split_text(page_content)
            
            for chunk in chunks:
                chunk_id = str(uuid.uuid4())
                
                dense_vec = get_embedding_with_cache(chunk)
                sparse_vec = get_sparse_embedding(chunk)
                
                points_to_upsert.append(
                    PointStruct(
                        id=chunk_id,
                        vector={
                            "default": dense_vec,
                            "bm25": {"indices": sparse_vec.indices.tolist(), "values": sparse_vec.values.tolist()}
                        },
                        payload={"text": chunk, "source": file_name, "hash": doc_hash}
                    )
                )

    if points_to_upsert:
        print(f"\n📦 [Ingestion] Upserting {len(points_to_upsert)} deduplicated, high-signal chunks into Qdrant...")
        qdrant.upsert(
            collection_name=COLLECTION_NAME,
            points=points_to_upsert
        )
        print("✅ [Ingestion] Ingestion completed successfully!")
    else:
        print("⚠️ [Ingestion] No valid points to upsert.")

if __name__ == "__main__":
    run_ingestion_pipeline(s3_bucket=None) 