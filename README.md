# 🛡️ Enterprise RAG Copilot

> **A Production-Grade, Security-First Multi-Agent Orchestrator for Kubernetes Site Reliability Engineering (SRE)**

---

# 🎯 Platform Overview

**Enterprise RAG Copilot** is a **security-hardened, production-grade multi-agent AI platform** purpose-built to streamline **Kubernetes operations** and automate **infrastructure diagnostics** for Site Reliability Engineering (SRE) teams.

The platform combines **high-precision Retrieval-Augmented Generation (RAG)** with **dynamic, schema-aware relational querying**, enabling engineers to receive deterministic, evidence-backed answers sourced directly from:

- 📚 Internal enterprise documentation
- 🗄️ Live relational databases
- ☸️ Kubernetes cluster state
- ⚙️ Infrastructure telemetry

Unlike conventional RAG systems that rely solely on semantic retrieval and often produce inconsistent reasoning, **Enterprise RAG Copilot** employs a **deterministic state-machine architecture** that orchestrates specialized AI agents through controlled execution paths.

To ensure enterprise-grade reliability and security, the platform incorporates:

- 🔒 A Zero-Trust security architecture
- 🧠 Multi-agent orchestration with deterministic workflows
- 🔍 Real-time response self-reflection and validation
- 🛡️ Administrative verification loops for destructive operations
- 📈 Production-ready observability and monitoring
- ✅ Evidence-grounded responses to minimize hallucinations

The result is an enterprise AI copilot capable of delivering **accurate, explainable, secure, and production-ready operational intelligence** for modern Kubernetes environments.

# 🚀 Key Technological Advancements

### ⚡ State-Machine Execution
**`src/orchestrator.py`**

Replaces traditional chain-of-thought sequencing with an **asynchronous, graph-based execution architecture** powered by **LangGraph**. Workflow state is persistently managed using pooled PostgreSQL transaction checkpointers (`PostgresSaver`), enabling deterministic execution, fault tolerance, and resumable workflows.

---

### 🔍 Hybrid Structural Retrieval
**`src/vector_store.py`**

Performs **parallel hybrid retrieval** by combining:

- **Dense semantic embeddings**
  - **768-dimensional cosine similarity vectors**
  - Model: **`BAAI/bge-base-en-v1.5`**
- **Sparse lexical retrieval**
  - **BM25 term-frequency indexing**
  - Powered by **Qdrant BM25**

Both retrieval strategies operate within a **single unified Qdrant collection**, maximizing retrieval accuracy across both semantic and keyword-based queries.

---

### 🎯 Rank Fusion & Context Optimization
**`src/vector_store.py`**

Candidate documents from dense and sparse retrieval are merged using the **Reciprocal Rank Fusion (RRF)** algorithm (`k = 60`).

The fused candidates are subsequently re-ranked using a **BGE Cross-Encoder** model, significantly improving context relevance before downstream inference.

---

### 🧠 Corrective RAG Grader
**`src/rag_pipeline.py`**

Implements an automated relevance evaluation layer for retrieved context.

If the internal document retrieval score falls below the **0.70 confidence threshold**, the pipeline automatically invokes **Tavily Web Search** to supplement missing external knowledge, improving answer completeness and reducing retrieval failures.

---

### 🔄 Self-RAG Grounding Reflex
**`src/rag_pipeline.py`**

Every generated response is evaluated against its supporting source documents.

If grounding confidence falls below the **0.80 threshold**, indicating a potential hallucination, the orchestrator automatically:

1. Resets the execution graph
2. Re-runs the retrieval pipeline
3. Retries generation (up to **2 attempts**) before returning the final response

This self-reflection mechanism enhances factual consistency and minimizes unsupported outputs.

---

### 🗄️ Dynamic Database Discovery
**`src/text2sql_pipeline.py`**

Instead of relying on predefined schemas, the platform dynamically discovers database structure by querying PostgreSQL's **`information_schema`** at runtime.

This enables the Text-to-SQL pipeline to:

- Automatically identify available databases and tables
- Generate schema-aware SQL queries
- Adapt seamlessly to evolving database structures without code modifications

---

### 👨‍💻 Human-in-the-Loop Interception
**`src/orchestrator.py`**, **`src/main.py`**

Sensitive SQL execution is protected through **LangGraph's native breakpoint mechanism**:

```python
interrupt_before=["sql_execution_node"]
```

Before executing generated SQL, workflow execution is paused and the graph state is preserved until an administrator explicitly approves the operation.

This verification layer provides an additional safeguard against unintended or destructive database actions.

# 📸 Platform Interface

### 🔐 Multi-Tenant Identity Verification Gate

The platform enforces **tenant-level access isolation** by restricting all application functionality until users are successfully authenticated against authorized identity profiles.
<img src="images/Screenshot 2026-07-01 100142.png" width="700">

---

### 🚨 Human-in-the-Loop SQL Intercept Card

For database analytics requests, the orchestration engine temporarily **pauses workflow execution** before any SQL statement is executed.
<img src="images/Screenshot 2026-07-01 095400.png" width="700">
This approval workflow prevents unintended or destructive database operations while maintaining complete execution traceability.

---

### 🔌 OpenAPI Core API Specifications

The backend is built with **FastAPI**, exposing a fully self-documenting OpenAPI interface for secure service interaction.
<img src="images/Screenshot 2026-07-01 100325.png" width="700">

---

### 📐 Systems & Component Architecture Blueprint

The platform follows a defense-in-depth architecture that isolates every stage of the request lifecycle.
<img src="images/enterprise_rag_architecture.png" width="700">
Together, these architectural components provide a scalable, secure, and resilient foundation for production Kubernetes operations.

---

## Security Pipeline Overview

| Layer | Component | Architectural Method | Primary Purpose |
|:------:|-----------|----------------------|-----------------|
| **L1** | **Regex Injection Guard** | Compile-time pattern validation using **Pydantic** models and regular expressions. | Detects and blocks prompt injection patterns and malicious input sequences before processing. |
| **L2** | **LLM Guard Scanner** | Real-time payload inspection using the **llm-guard** framework. | Identifies obfuscated jailbreak attempts, prompt attacks, and malicious payloads before they reach the language model. |
| **L4a** | **JWT Authorization** | Stateless authentication using **PyJWT (HS256)** token verification. | Validates cryptographic signatures, user claims, and token expiration before granting API access. |
| **L4b** | **Distributed Rate Limiting** | Token-bucket rate limiting implemented through **SlowAPI**. | Restricts requests to **20 requests per minute** per client IP to mitigate abuse and denial-of-service attacks. |
| **L5** | **Tiktoken Buffer Truncation** | Token counting using the **`cl100k_base`** tokenizer. | Truncates oversized inputs to **1,000 tokens**, protecting the system from excessive context windows and resource exhaustion. |
| **L6** | **Resource Budget Tracker** | Thread-safe usage accounting and compute monitoring. | Enforces a maximum daily budget of **100,000 tokens per user** to prevent excessive resource consumption. |
| **L7a** | **Inbound Data Sanitization** | Multi-pattern sanitization and redaction filters. | Removes or masks sensitive information such as credentials, API keys, email addresses, and tracking identifiers before processing. |
| **L7b** | **Outbound Leak Filter** | Post-generation content inspection. | Detects and redacts accidental exposure of infrastructure details, database credentials, secrets, or sensitive configuration data. |
| **L8** | **XML Context Spotlighting** | Strict XML encapsulation of retrieved knowledge. | Isolates contextual documents from system instructions, mitigating indirect prompt injection through retrieved content. |
| **L9** | **Deterministic Blueprint Sync** | Structured response validation using **Pydantic** models. | Ensures all responses conform to predefined JSON schemas, automatically retrying generation up to **3 times** if validation fails. |

Together, these nine security layers provide a comprehensive defense framework that enables **Enterprise RAG Copilot** to operate securely in production-grade Kubernetes and enterprise environments.

# ⚡ Multi-Tier Caching Network

To reduce latency, minimize infrastructure costs, and improve throughput, **Enterprise RAG Copilot** employs a **5-tier caching architecture** powered by **Upstash Serverless Redis**. Each cache layer targets a different stage of the request lifecycle, eliminating redundant computation and accelerating repeated operations.

---

## 🗂️ Cache Architecture

| Tier | Cache Layer | Retention | Purpose |
|:----:|-------------|:--------:|---------|
| **Tier 1** | **Embedding Vector Cache** | **7 Days** | Eliminates redundant embedding generation by caching SHA-256 hashed query vectors. |
| **Tier 2** | **Intent Classification Cache** | **24 Hours** | Stores previously classified user intents to bypass repeated routing computations. |
| **Tier 3** | **SQL Statement Cache** | **24 Hours** | Reuses validated Text-to-SQL translations, avoiding unnecessary LLM inference. |
| **Tier 4** | **Transactional Database Cache** | **15 Minutes** | Caches database query results to reduce repeated access to production databases. |
| **Tier 5** | **Answer Synthesis Cache** | **1 Hour** | Stores complete AI-generated responses, allowing identical requests to bypass the orchestration engine entirely. |

---

# 🛠️ Infrastructure Technology Matrix

The platform is built on a modern cloud-native technology stack optimized for security, scalability, and production reliability.

---

## 🏗️ Core Application Layer

| Component | Technology |
|-----------|------------|
| **State & Workflow Orchestration** | LangGraph Framework, LangChain |
| **API Infrastructure** | FastAPI, Uvicorn, SlowAPI |
| **Frontend Interface** | Streamlit |

---

## 🤖 AI & Retrieval Stack

| Component | Technology |
|-----------|------------|
| **Primary Language Model** | Google Gemini (`gemini-2.5-flash`) |
| **Dense Embedding Model** | `BAAI/bge-base-en-v1.5` (Hugging Face) |
| **Cross-Encoder Re-Ranker** | `BAAI/bge-reranker-base` |
| **Sparse Retrieval Engine** | FastEmbed BM25 |

---

## 💾 Data & Persistence Layer

| Component | Technology |
|-----------|------------|
| **Vector Database** | Qdrant |
| **Relational Database** | PostgreSQL 16 |
| **Connection Pooling** | Psycopg 3 |
| **Workflow Checkpointing** | PostgreSQL (`PostgresSaver`) |
| **Distributed Cache** | Upstash Serverless Redis |

---

## 🔐 Security & Runtime Utilities

| Component | Technology |
|-----------|------------|
| **Prompt & Payload Security** | LLM-Guard |
| **Token Management** | Tiktoken |
| **Authentication** | JWT (PyJWT) |
| **Input Validation** | Pydantic |
| **Rate Limiting** | SlowAPI |

---

## 📊 Technology Stack Summary

| Category | Technologies |
|----------|--------------|
| **Frontend** | Streamlit |
| **Backend** | FastAPI, Uvicorn |
| **Workflow Engine** | LangGraph, LangChain |
| **LLM** | Google Gemini 2.5 Flash |
| **Embeddings** | BAAI BGE Base |
| **Reranking** | BAAI BGE Reranker |
| **Hybrid Search** | Dense + BM25 |
| **Vector Store** | Qdrant |
| **Database** | PostgreSQL 16 |
| **Caching** | Upstash Redis |
| **Security** | JWT, LLM-Guard, Pydantic, SlowAPI, Tiktoken |
| **Deployment** | Docker, Kubernetes, AWS |

# 📁 Repository Architecture

```text
enterprise-rag-copilot/
├── Dockerfile                        # Python multi-port container build definition
├── docker-compose.yml                # Multi-engine local infrastructure composition map
├── requirements.txt                  # Locked production dependencies file
├── app.py                            # Streamlit UI managing token verification and approval panels
├── enterprise_rag_architecture.jpg   # Complete structural systems layout map
└── src/
    ├── main.py                       # Primary REST application framework providing endpoint schemas
    ├── orchestrator.py               # State-graph compilation, routing, and persistence mapping
    ├── security.py                   # 9-layer data isolation and thread safety engine
    ├── router.py                     # LLM query intent routing with Upstash cache tracking
    ├── rag_pipeline.py               # Advanced RAG logic (HyDE expansion, CRAG grading, and Self-RAG)
    ├── text2sql_pipeline.py          # Schema synchronization and text-to-SQL validation logic
    ├── vector_store.py               # Dual dense/sparse embedding generators, RRF, and collection setup
    ├── cache.py                      # Core Redis connection configuration and lifecycle hooks
    ├── ingest.py                     # Asynchronous document parser and vector ingestion pipeline
    └── init_db.py                    # SQL telemetry table creation and mock data seeding
```

# 💻 Local Developer Setup

Follow the steps below to set up and run **Enterprise RAG Copilot** in your local development environment.

---

## 1️⃣ Clone the Repository

```bash
git clone https://github.com/aryangupta5084/enterprise-rag-copilot.git

cd enterprise-rag-copilot
```

---

## 2️⃣ Configure Environment Variables

Create a **`.env`** file in the project root and populate it with your credentials and service configuration.

> **Note:** Replace the placeholder values below with your own API keys and connection details.

```env
# Google Gemini
GOOGLE_API_KEY=your_google_gemini_api_key

# Tavily Web Search
TAVILY_API_KEY=your_tavily_api_key

# Upstash Redis
UPSTASH_REDIS_HOST=your-upstash-host.upstash.io
UPSTASH_REDIS_PORT=6379
UPSTASH_REDIS_PASSWORD=your_upstash_password

# PostgreSQL
DB_URI=postgresql://postgres:postgres@postgres:5432/postgres

# Qdrant
QDRANT_URL=http://qdrant:6333
```

---

## 3️⃣ Build & Start the Application

Build all Docker images and launch the complete multi-container stack in detached mode.

```bash
docker compose up --build -d
```

---

## 4️⃣ Verify Running Services

After all containers report a **healthy** status, access the platform using the following endpoints.

| Service | URL |
|----------|-----|
| 🖥️ **Streamlit Admin Dashboard** | <http://localhost:8501> |
| 📚 **FastAPI Interactive API Docs** | <http://localhost:8000/docs> |

---

## Default User Accounts

| Role | Username | Password | Permissions |
|------|----------|----------|-------------|
| **Platform SRE Engineer** | `sre_engineer` | `k8s_rocks!` | Read-only access to the platform. Can perform document retrieval, submit infrastructure queries, and view operational insights. |
| **System Infrastructure Administrator** | `admin_user` | `securepassword123` | Full administrative access, including Human-in-the-Loop (HITL) approval for SQL execution, workflow management, and privileged platform operations. |

---

## Role-Based Access Control (RBAC)

### 👨‍💻 Platform SRE Engineer

**Capabilities**

- 📄 Perform document and knowledge retrieval
- 🔍 Query Kubernetes operational data
- 🤖 Interact with the AI copilot
- 📊 View generated responses and system insights
- 📝 Generate audit logs for submitted requests

**Restrictions**

- ❌ Cannot approve SQL execution
- ❌ Cannot perform administrative actions
- ❌ Cannot modify system configuration

---

# ☁️ AWS Fargate Enterprise Deployment

The repository includes **Terraform Infrastructure as Code (IaC)** modules for provisioning a production-ready AWS environment. The deployment architecture follows cloud-native best practices, emphasizing security, scalability, and operational reliability.

---

## 🌐 Infrastructure Overview

The Terraform configuration automatically provisions:

- Amazon ECS Fargate cluster
- Application Load Balancer (ALB)
- Amazon RDS for PostgreSQL
- Amazon EC2 instance hosting Qdrant
- AWS Secrets Manager
- VPC networking and security groups
- IAM roles and task execution policies

---

# ⭐ Support the Project

If you find **Enterprise RAG Copilot** useful for your research, infrastructure, or production projects, consider giving the repository a ⭐ on GitHub.

---

> **Enterprise RAG Copilot**  
> *Building secure, trustworthy, and deterministic AI systems for modern cloud infrastructure and Kubernetes operations.*