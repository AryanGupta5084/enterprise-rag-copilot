import re
import tiktoken
from pydantic import BaseModel, field_validator
from llm_guard.input_scanners import PromptInjection, Toxicity
import jwt
from fastapi import HTTPException, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

DAILY_TOKEN_USAGE = {}

class SecureQueryRequest(BaseModel):
    query: str

    @field_validator('query')
    @classmethod
    def check_prompt_injection(cls, value: str) -> str:
        """
        L1 Guardrail: Pydantic + Regex validation.
        Instantly blocks basic prompt injection patterns before they reach the LLM.
        """
        print("🛡️ [Security L1] Scanning input with Regex for injection patterns...")
        
        injection_patterns = [
            r"(?i)ignore\s+all\s+previous\s+instructions",
            r"(?i)you\s+are\s+now",
            r"(?i)bypass\s+security",
            r"(?i)print\s+your\s+system\s+prompt",
            r"(?i)forget\s+everything"
        ]
        
        for pattern in injection_patterns:
            if re.search(pattern, value):
                print(f"🚨 [Security L1] MALICIOUS INPUT BLOCKED: Matched pattern '{pattern}'")
                raise ValueError("Security Violation: Potential prompt injection detected.")
                
        print("✅ [Security L1] Input passed Regex validation.")
        return value
    
def truncate_input(text: str, max_tokens: int = 1000) -> str:
    """
    L5 Guardrail: Input Restructure (tiktoken truncate).
    Ensures the input does not exceed our maximum token limit to protect the budget.
    """
    print(f"\n🛡️ [Security L5] Checking token count for input...")
    
    encoding = tiktoken.get_encoding("cl100k_base")
    tokens = encoding.encode(text)
    
    if len(tokens) > max_tokens:
        print(f"⚠️ [Security L5] Input exceeded {max_tokens} tokens (Received {len(tokens)} tokens). Truncating...")
        truncated_text = encoding.decode(tokens[:max_tokens])
        return truncated_text
        
    print(f"✅ [Security L5] Input is within token limits ({len(tokens)} tokens).")
    return text

def scan_input_llm_guard(prompt: str) -> str:
    """
    L2 Guardrail: Advanced LLM-Guard Scan.
    Uses ML models to detect sophisticated prompt injections, jailbreaks, and toxicity.
    """
    print(f"\n🛡️ [Security L2] Running advanced LLM-Guard scan for toxicity and injections...")
    
    scanners = [
        PromptInjection(), 
        Toxicity()
    ]
    
    for scanner in scanners:
        sanitized_prompt, is_valid, risk_score = scanner.scan(prompt)
        
        if not is_valid:
            print(f"🚨 [Security L2] ADVANCED THREAT BLOCKED: Failed {scanner.__class__.__name__} check with Risk Score {risk_score}")
            raise ValueError(f"Security Violation: Input blocked by {scanner.__class__.__name__} scanner.")
            
    print("✅ [Security L2] Input passed advanced ML security scan.")
    return prompt

def redact_pii(text: str) -> str:
    """
    L7a Guardrail: PII Redaction & Content Moderation.
    Automatically masks sensitive data like Credit Cards and Emails before they reach the LLM.
    """
    print(f"\n🛡️ [Security L7a] Scanning for sensitive PII...")
    
    email_pattern = r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+'
    sanitized_text = re.sub(email_pattern, "[EMAIL_REDACTED]", text)
    
    cc_pattern = r'\b(?:\d[ -]*?){13,16}\b'
    sanitized_text = re.sub(cc_pattern, "[CREDIT_CARD_REDACTED]", sanitized_text)
    
    if sanitized_text != text:
        print("🚨 [Security L7a] PII DETECTED: Sensitive data has been automatically masked.")
    else:
        print("✅ [Security L7a] No PII detected.")
        
    return sanitized_text

token_bearer = HTTPBearer()
SECRET_KEY = "enterprise-rag-super-secret-key"
def verify_jwt_token(credentials: HTTPAuthorizationCredentials = Security(token_bearer)) -> str:
    """
    L4a Guardrail: JWT Auth (PyJWT).
    Validates the Bearer token to ensure the user is authorized.
    """
    print(f"\n🛡️ [Security L4a] Validating JWT Authentication token...")
    
    try:
        payload = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=["HS256"])
        username = payload.get("sub", "Unknown User")
        print(f"✅ [Security L4a] User '{username}' authenticated successfully.")
        return username
        
    except jwt.ExpiredSignatureError:
        print("🚨 [Security L4a] AUTH BLOCKED: JWT Token Expired.")
        raise HTTPException(status_code=401, detail="Security Violation: Token has expired")
        
    except jwt.InvalidTokenError:
        print("🚨 [Security L4a] AUTH BLOCKED: Invalid JWT Token.")
        raise HTTPException(status_code=401, detail="Security Violation: Invalid or malformed token")
    
def check_token_budget(username: str, estimated_tokens: int) -> None:
    """
    L6 Guardrail: Token Budget (100k / day / user).
    Ensures the authenticated user has not exceeded their daily allowance.
    """
    print(f"\n🛡️ [Security L6] Checking daily token budget for '{username}'...")
    
    if username not in DAILY_TOKEN_USAGE:
        DAILY_TOKEN_USAGE[username] = 0
        
    current_usage = DAILY_TOKEN_USAGE[username]
    
    if current_usage + estimated_tokens > 100000:
        print(f"🚨 [Security L6] BUDGET EXCEEDED: '{username}' attempted to use {current_usage + estimated_tokens}/100000 tokens.")
        raise ValueError("Security Violation: Daily token budget of 100,000 tokens exceeded. Please try again tomorrow.")
        
    DAILY_TOKEN_USAGE[username] += estimated_tokens
    print(f"✅ [Security L6] Budget OK. '{username}' has consumed {DAILY_TOKEN_USAGE[username]}/100000 tokens today.")

def spotlight_context(retrieved_docs: list[dict]) -> str:
    """
    L8 Guardrail: Wraps the final retrieved and reranked documents in strict 
    XML tags to prevent context-poisoning attacks during LLM generation.
    """
    print("\n🛡️ [Security L8] Spotlighting context with XML-delimited chunks...")
    
    if not retrieved_docs:
        return "<retrieved_context>\n  No documents found.\n</retrieved_context>"
        
    xml_context = "<retrieved_context>\n"
    for i, doc in enumerate(retrieved_docs):
        doc_text = doc.get("text", str(doc)) 
        xml_context += f"  <document index='{i+1}'>\n    {doc_text}\n  </document>\n"
    xml_context += "</retrieved_context>"
    
    print("✅ [Security L8] Context successfully wrapped in XML tags.")
    return xml_context

def post_process_output(text: str) -> str:
    """
    L7b Guardrail: Output Moderation & PII Redaction.
    Scans the LLM's generated output before sending it back to the user to ensure 
    no sensitive internal data, credentials, or PII are leaked.
    """
    print("\n🛡️ [L7b Guardrail] Running Output Moderation and PII Redaction...")
    
    if not text:
        return text

    banned_words = ["super_secret_admin_password", "master_db_credentials"]
    for word in banned_words:
        if word in text.lower():
            print("⚠️ [L7b Guardrail] Blocked sensitive internal keyword.")
            text = text.replace(word, "[REDACTED_INTERNAL_DATA]")

    text = re.sub(r'\bAKIA[0-9A-Z]{16}\b', '[AWS_KEY_REDACTED]', text)
    
    text = re.sub(r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+', '[EMAIL_REDACTED]', text)
    
    text = re.sub(r'\b\d{3}-\d{2}-\d{4}\b', '[SSN_REDACTED]', text)

    print("✅ [L7b Guardrail] Output successfully sanitized.")
    return text