import os
from langchain_core.prompts import PromptTemplate
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.output_parsers import StrOutputParser
import psycopg2
import psycopg2.extras

DB_URI = os.getenv("DB_URI", "postgresql://postgres:postgres@postgres:5432/postgres")

_CACHED_SCHEMA = None

def get_dynamic_schema() -> str:
    """
    Dynamically extracts the schema (tables and columns) from the live PostgreSQL database.
    Caches the result in memory to reduce database load on subsequent queries.
    """
    global _CACHED_SCHEMA
    if _CACHED_SCHEMA:
        return _CACHED_SCHEMA

    print("🔍 [Text2SQL] Fetching dynamic schema from Postgres information_schema...")
    try:
        conn = psycopg2.connect(DB_URI)
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        
        schema_query = """
            SELECT table_name, column_name, data_type
            FROM information_schema.columns
            WHERE table_schema = 'public'
            ORDER BY table_name, ordinal_position;
        """
        cursor.execute(schema_query)
        rows = cursor.fetchall()
        
        schema_dict = {}
        for row in rows:
            t_name = row['table_name']
            if t_name not in schema_dict:
                schema_dict[t_name] = []
            
            data_type = row['data_type'].upper()
            schema_dict[t_name].append(f"{row['column_name']} ({data_type})")
            
        formatted_schema = ""
        for table, cols in schema_dict.items():
            formatted_schema += f"Table: {table}\nColumns: {', '.join(cols)}\n\n"
            
        cursor.close()
        conn.close()
        
        _CACHED_SCHEMA = formatted_schema.strip()
        print("✅ [Text2SQL] Dynamic schema loaded successfully.")
        return _CACHED_SCHEMA
        
    except Exception as e:
        print(f"❌ [Text2SQL] Failed to fetch dynamic schema: {e}")
        return "Error: Unable to retrieve database schema."

def generate_sql(query: str) -> str:
    """
    Text2SQL: Generates a schema-aware SQL query from natural language.
    """
    print("\n🛠️ [Text2SQL] Generating SQL query from natural language...")
    
    live_schema = get_dynamic_schema()
    
    llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash", temperature=0.0)
    
    prompt = PromptTemplate.from_template(
        "You are a strict PostgreSQL data analyst. Given the following database schema, write a valid SQL SELECT query to answer the user's question.\n"
        "Return ONLY the raw SQL query. Do not include markdown formatting like ```sql.\n\n"
        "Schema:\n{schema}\n\n"
        "Question: {query}\n\nSQL Query:"
    )
    
    chain = prompt | llm | StrOutputParser()
    
    try:
        sql_query = chain.invoke({"schema": live_schema, "query": query})
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

def execute_sql(sql_query: str) -> list[dict]:
    """
    Execute SQL: Runs the validated SELECT query against the PostgreSQL database.
    """
    print("\n🐘 [Text2SQL] Executing query against PostgreSQL...")
    
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