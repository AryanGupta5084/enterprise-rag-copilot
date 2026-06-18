import uuid
from src.vector_store import qdrant, get_embedding_with_cache, COLLECTION_NAME
from qdrant_client.models import PointStruct

kubernetes_kb = [
    "To restart a crashlooping pod, delete it with `kubectl delete pod <pod-name>`. Its managing controller (Deployment, StatefulSet, or ReplicaSet) will automatically create a new replacement pod.",
    "A Kubernetes Service is an abstraction which defines a logical set of Pods and a policy by which to access them. Types include ClusterIP, NodePort, and LoadBalancer.",
    "Horizontal Pod Autoscaler (HPA) automatically updates a workload resource with the aim of automatically scaling the workload to match demand based on CPU or memory usage.",
    "To update a Kubernetes deployment, use the 'kubectl set image' command or apply a new YAML file. Kubernetes will perform a rolling update by default to ensure zero downtime.",
    "A ConfigMap is an API object used to store non-confidential data in key-value pairs. Pods can consume ConfigMaps as environment variables, command-line arguments, or as configuration files."
]

def ingest_data():
    """Converts text into vectors and uploads them to Qdrant."""
    print(f"\n📥 Starting ingestion into Qdrant collection: '{COLLECTION_NAME}'")
    
    points = []
    for i, doc in enumerate(kubernetes_kb):
        print(f"Processing document {i+1}/{len(kubernetes_kb)}...")
        
        vector = get_embedding_with_cache(doc)
        
        point = PointStruct(
            id=str(uuid.uuid4()),
            vector=vector,
            payload={
                "text": doc, 
                "source": "dummy_k8s_docs",
                "chunk_id": i
            }
        )
        points.append(point)
        
    qdrant.upsert(
        collection_name=COLLECTION_NAME,
        points=points
    )
    print("\n✅ Ingestion complete! Your Qdrant database is now populated.")

if __name__ == "__main__":
    ingest_data()