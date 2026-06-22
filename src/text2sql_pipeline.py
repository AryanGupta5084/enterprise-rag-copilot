from langchain_core.prompts import PromptTemplate
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.output_parsers import StrOutputParser
import psycopg2
import psycopg2.extras

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

DB_URI = "postgresql://postgres:postgres@localhost:5432/postgres"

def execute_sql(sql_query: str) -> list[dict]:
    """
    Execute SQL: Runs the validated SELECT query against the PostgreSQL 16 database.
    """
    print("\n🐘 [Text2SQL] Executing query against PostgreSQL 16...")
    
    try:
        conn = psycopg2.connect(DB_URI)
        
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        
        cursor.execute(sql_query)
        results = cursor.fetchall()
        
        conn.commit()
        cursor.close()
        conn.close()
        
        print(f"✅ [Text2SQL] Successfully retrieved {len(results)} rows from Postgres.")
        
        return [dict(row) for row in results]
        
    except Exception as e:
        print(f"❌ [Text2SQL] PostgreSQL Execution Error: {e}")
        return [{"error": str(e)}]


def format_sql_results(db_results: list[dict]) -> list[dict]:
    """
    Format Results (rows -> context): 
    Prepares the database rows to be passed securely into the LLM context.
    """
    if not db_results:
        return [{"text": "No results found in the database."}]
    
    if "error" in db_results:
        return [{"text": f"Database error occurred: {db_results['error']}"}]
        
    formatted_string = "Database Query Results:\n"
    for i, row in enumerate(db_results):
        formatted_string += f"Row {i+1}: {row}\n"
        
    return [{"text": formatted_string}]