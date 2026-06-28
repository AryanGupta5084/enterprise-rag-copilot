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
    """Pulls the raw corpus from AWS S3 using boto3."""
    print(f"☁️ [Ingestion] Connecting to S3 Bucket: {bucket_name}...")
    s3 = boto3.client('s3')
    
    if not os.path.exists(download_dir):
        os.makedirs(download_dir)
        
    try:
        objects = s3.list_objects_v2(Bucket=bucket_name)
        if 'Contents' not in objects:
            print(f"⚠️ [Ingestion] S3 Bucket '{bucket_name}' is empty.")
            return download_dir
            
        for obj in objects['Contents']:
            file_key = obj['Key']
            if file_key.lower().endswith('.pdf'):
                download_path = os.path.join(download_dir, file_key)
                print(f"⬇️ Downloading {file_key} from S3...")
                s3.download_file(bucket_name, file_key, download_path)
                
        print("✅ [Ingestion] Successfully downloaded raw PDFs from S3.")
    except Exception as e:
        print(f"❌ [Ingestion] Failed to fetch from S3: {e}")
        raise

    return download_dir

def ingest_data(s3_bucket: str = None, local_dir: str = "./data/raw_pdfs"):
    """
    Converts S3/Local PDFs into Dense + Sparse vectors, applies dedup/noise filtering, 
    and uploads them to Qdrant.
    """
    print(f"\n📥 Starting Enterprise ingestion into Qdrant collection: '{COLLECTION_NAME}'")
    
    target_dir = download_from_s3(s3_bucket, local_dir) if s3_bucket else local_dir
    
    if not os.path.exists(target_dir):
        os.makedirs(target_dir)

    pdf_files = [os.path.join(target_dir, f) for f in os.listdir(target_dir) if f.endswith('.pdf')]
    
    if not pdf_files:
        print("❌ [Ingestion] No PDFs found in S3 or local directory. Aborting ingestion.")
        return

    text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=150)
    
    seen_hashes = set()
    points = []

    for file_name in pdf_files:
        print(f"📄 [Ingestion] Parsing real PDF: {file_name}")
        
        try:
            loader = PyPDFLoader(file_name)
            pages = loader.load()
        except Exception as e:
            print(f"⚠️ [Ingestion] Failed to parse {file_name}: {e}. Skipping...")
            continue
        
        for page in pages:
            page_content = page.page_content
            
            if len(page_content.strip()) < 50 or "intentionally left blank" in page_content.lower():
                continue
                
            doc_hash = calculate_document_hash(page_content)
            if doc_hash in seen_hashes:
                continue
                
            seen_hashes.add(doc_hash)
            
            chunks = text_splitter.split_text(page_content)
            for i, chunk in enumerate(chunks):
                chunk_id = str(uuid.uuid4())
                
                dense_vec = get_embedding_with_cache(chunk)
                sparse_vec = get_sparse_embedding(chunk)
                
                points.append(
                    PointStruct(
                        id=chunk_id,
                        vector={
                            "default": dense_vec, 
                            "bm25": {"indices": sparse_vec[0].indices.tolist(), "values": sparse_vec[0].values.tolist()}
                        },
                        payload={
                            "text": chunk, 
                            "source": os.path.basename(file_name), 
                            "chunk_id": i,
                            "hash": doc_hash
                        }
                    )
                )

    if points:
        print(f"\n📦 [Ingestion] Upserting {len(points)} deduplicated, dual-vector chunks into Qdrant...")
        qdrant.upsert(
            collection_name=COLLECTION_NAME,
            points=points
        )
        print("\n✅ Ingestion complete! Your Qdrant database is now populated with true S3 data.")
    else:
        print("\n⚠️ [Ingestion] No valid points to upsert.")

if __name__ == "__main__":
    ingest_data(s3_bucket=None)