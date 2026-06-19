from langchain_core.prompts import PromptTemplate
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.output_parsers import StrOutputParser
import sqlite3

DB_SCHEMA = """
Table: pod_metrics
Columns: pod_name (VARCHAR), namespace (VARCHAR), cpu_usage_cores (FLOAT), memory_usage_mb (FLOAT), status (VARCHAR)

Table: cluster_incidents
Columns: incident_id (INT), description (VARCHAR), severity (VARCHAR), resolved (BOOLEAN)
"""

def generate_sql(query: str) -> str:
    """
    Text2SQL: Generates a schema-aware SQL query from natural language.
    """
    print("\n🛠️ [Text2SQL] Generating SQL query from natural language...")
    llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash", temperature=0.0)
    
    prompt = PromptTemplate.from_template(
        "You are a strict PostgreSQL data analyst. Given the following database schema, write a valid SQL SELECT query to answer the user's question.\n"
        "Return ONLY the raw SQL query. Do not include markdown formatting like ```sql.\n\n"
        "Schema:\n{schema}\n\n"
        "Question: {query}\n\nSQL Query:"
    )
    
    chain = prompt | llm | StrOutputParser()
    
    try:
        sql_query = chain.invoke({"schema": DB_SCHEMA, "query": query})
        sql_query = sql_query.replace("```sql", "").replace("```", "").strip()
        print(f"✅ [Text2SQL] Generated Query: {sql_query}")
        return sql_query
    except Exception as e:
        print(f"⚠️ [Text2SQL] Failed to generate SQL: {e}")
        return ""

def validate_sql(sql_query: str) -> bool:
    """
    Security: Ensures the query is strictly a SELECT statement and uses a blocklist.
    """
    print("🛡️ [Text2SQL] Validating SQL query for safety...")
    
    dangerous_keywords = ["DROP", "DELETE", "UPDATE", "INSERT", "ALTER", "TRUNCATE", "GRANT", "REVOKE", "EXECUTE"]
    upper_query = sql_query.upper().strip()
    
    if not upper_query.startswith("SELECT"):
        print("❌ [Text2SQL] Validation Failed: Query must start with SELECT.")
        return False
        
    for keyword in dangerous_keywords:
        if f" {keyword} " in f" {upper_query} " or upper_query.startswith(f"{keyword} "):
            print(f"❌ [Text2SQL] Validation Failed: Dangerous keyword '{keyword}' detected!")
            return False
            
    print("✅ [Text2SQL] Query validation passed. Safe to execute.")
    return True

def setup_mock_database():
    """Creates a local SQLite database to simulate our PostgreSQL Kubernetes DB."""
    conn = sqlite3.connect("kubernetes_mock.db")
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS pod_metrics (
            pod_name TEXT,
            namespace TEXT,
            cpu_usage_cores REAL,
            memory_usage_mb REAL,
            status TEXT
        )
    ''')
    
    cursor.execute("SELECT COUNT(*) FROM pod_metrics")
    if cursor.fetchone() == 0:
        mock_data = [
            ('nginx-ingress', 'kube-system', 0.5, 256.0, 'Running'),
            ('frontend-webapp-1', 'production', 1.2, 1024.0, 'Running'),
            ('backend-api-3', 'production', 0.8, 600.0, 'CrashLoopBackOff'),
            ('redis-cache', 'database', 0.2, 150.0, 'Running'),
            ('prometheus-server', 'monitoring', 2.0, 4096.0, 'Running')
        ]
        cursor.executemany('''
            INSERT INTO pod_metrics (pod_name, namespace, cpu_usage_cores, memory_usage_mb, status)
            VALUES (?, ?, ?, ?, ?)
        ''', mock_data)
        conn.commit()
        
    return conn

def execute_sql(sql_query: str) -> dict:
    """
    Execute SQL: Runs the validated SELECT query against the database.
    """
    print(f"\n🏃 [Text2SQL] Executing query...")
    try:
        conn = setup_mock_database()
        cursor = conn.cursor()
        cursor.execute(sql_query)
        
        columns = [description for description in cursor.description]
        rows = cursor.fetchall()
        conn.close()
        
        print(f"✅ [Text2SQL] Execution successful. Retrieved {len(rows)} rows.")
        return {"columns": columns, "rows": rows}
    except Exception as e:
        print(f"❌ [Text2SQL] Database execution failed: {e}")
        return {"columns": [], "rows": [], "error": str(e)}

def format_sql_results(db_results: dict) -> list[dict]:
    """
    Format Results: Converts raw database rows into text context for the LLM.
    We return it as a list of dictionaries to perfectly match what our LLM expects!
    """
    print("📝 [Text2SQL] Formatting rows into LLM context...")
    
    if "error" in db_results:
        return [{"document": f"Database Error: {db_results['error']}"}]
        
    if not db_results["rows"]:
        return [{"document": "The database query returned 0 results."}]
        
    columns = db_results["columns"]
    formatted_rows = []
    
    for row in db_results["rows"]:
        row_dict = dict(zip(columns, row))
        row_string = ", ".join([f"{k}: {v}" for k, v in row_dict.items()])
        formatted_rows.append({"document": f"Database Record -> {row_string}"})
        
    print("✅ [Text2SQL] Successfully formatted database results.")
    return formatted_rows
