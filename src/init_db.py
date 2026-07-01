import psycopg2
import os
from psycopg_pool import ConnectionPool

DB_URI = os.getenv("DB_URI", "postgresql://postgres:postgres@postgres:5432/postgres")
pool = ConnectionPool(conninfo=DB_URI, max_size=5, kwargs={"autocommit": True})

def init_postgres_db():
    print("🐘 [Postgres Init] Connecting to PostgreSQL...")
    try:
        conn = psycopg2.connect(DB_URI)
        cursor = conn.cursor()

        table_queries = [
            """CREATE TABLE IF NOT EXISTS clusters (
                cluster_id SERIAL PRIMARY KEY, name VARCHAR(100), region VARCHAR(50), status VARCHAR(20)
            );""",
            """CREATE TABLE IF NOT EXISTS nodes (
                node_id SERIAL PRIMARY KEY, cluster_id INT, name VARCHAR(100), instance_type VARCHAR(50), status VARCHAR(20)
            );""",
            """CREATE TABLE IF NOT EXISTS pods (
                pod_id SERIAL PRIMARY KEY, namespace VARCHAR(50), name VARCHAR(100), status VARCHAR(20), restart_count INT
            );""",
            """CREATE TABLE IF NOT EXISTS services (
                service_id SERIAL PRIMARY KEY, namespace VARCHAR(50), name VARCHAR(100), type VARCHAR(50), cluster_ip VARCHAR(50)
            );""",
            """CREATE TABLE IF NOT EXISTS deployments (
                deployment_id SERIAL PRIMARY KEY, namespace VARCHAR(50), name VARCHAR(100), replicas INT, available_replicas INT
            );""",
            """CREATE TABLE IF NOT EXISTS incidents (
                incident_id SERIAL PRIMARY KEY, description TEXT, severity VARCHAR(20), status VARCHAR(20), created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );""",
            """CREATE TABLE IF NOT EXISTS alerts (
                alert_id SERIAL PRIMARY KEY, alert_name VARCHAR(100), component VARCHAR(100), is_active BOOLEAN
            );"""
        ]

        print("🏗️ [Postgres Init] Creating 7 Ops Database tables...")
        for query in table_queries:
            cursor.execute(query)

        cursor.execute("SELECT COUNT(*) FROM pods;")
        if cursor.fetchone() == 0:
            print("🌱 [Postgres Init] Seeding mock Kubernetes operational data...")
            
            cursor.execute("INSERT INTO clusters (name, region, status) VALUES ('prod-cluster-1', 'us-east-1', 'Healthy');")
            cursor.execute("INSERT INTO nodes (cluster_id, name, instance_type, status) VALUES (1, 'ip-10-0-0-1', 't3.large', 'Ready');")
            
            cursor.execute("""
                INSERT INTO pods (namespace, name, status, restart_count) 
                VALUES 
                ('default', 'nginx-frontend', 'Running', 0), 
                ('kube-system', 'payment-service-pod', 'CrashLoopBackOff', 12);
            """)
            
            cursor.execute("INSERT INTO incidents (description, severity, status) VALUES ('Payment service pod crashing repeatedly', 'High', 'Open');")

        conn.commit()
        cursor.close()
        conn.close()
        print("✅ [Postgres Init] Successfully initialized and seeded 7 Ops tables in PostgreSQL 16!")

    except Exception as e:
        print(f"❌ [Postgres Init] Error initializing database: {e}")

if __name__ == "__main__":
    init_postgres_db()