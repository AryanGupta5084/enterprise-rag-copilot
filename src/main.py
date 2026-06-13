from fastapi import FastAPI
import uvicorn
import os
from dotenv import load_dotenv

load_dotenv()

# Initialize the FastAPI Service
app = FastAPI(
    title="Enterprise RAG Copilot",
    description="Kubernetes SRE copilot with LangGraph, Qdrant, Postgres, and Redis",
    version="1.0.0"
)

@app.get("/")
async def root():
    return {"status": "online", "message": "Enterprise RAG Copilot API is running!"}

@app.get("/health")
async def health_check():
    # checks to verify Qdrant, Postgres, and Redis connections
    return {
        "postgres": "pending configuration",
        "qdrant": "pending configuration",
        "redis": "pending configuration",
        "langgraph_state": "initialized"
    }

if __name__ == "__main__":
    print("Starting FastAPI server...")
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)