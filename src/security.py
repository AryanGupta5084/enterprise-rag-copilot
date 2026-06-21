import re
import tiktoken
from pydantic import BaseModel, field_validator
from llm_guard.input_scanners import PromptInjection, Toxicity

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
        
        # Common prompt injection triggers
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
    
    # Load the encoding for standard OpenAI models (e.g., GPT-4o)
    encoding = tiktoken.get_encoding("cl100k_base")
    tokens = encoding.encode(text)
    
    if len(tokens) > max_tokens:
        print(f"⚠️ [Security L5] Input exceeded {max_tokens} tokens (Received {len(tokens)} tokens). Truncating...")
        # Truncate the list of tokens to the max_tokens limit and decode back to text
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
    
    # Initialize the specific scanners we want to use
    scanners = [
        PromptInjection(), 
        Toxicity()
    ]
    
    for scanner in scanners:
        # The scanner evaluates the text and returns whether it is safe
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
    
    # Regex to catch standard Email addresses
    email_pattern = r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+'
    sanitized_text = re.sub(email_pattern, "[EMAIL_REDACTED]", text)
    
    # Regex to catch standard 14-16 digit Credit Card numbers (with or without dashes/spaces)
    cc_pattern = r'\b(?:\d[ -]*?){13,16}\b'
    sanitized_text = re.sub(cc_pattern, "[CREDIT_CARD_REDACTED]", sanitized_text)
    
    if sanitized_text != text:
        print("🚨 [Security L7a] PII DETECTED: Sensitive data has been automatically masked.")
    else:
        print("✅ [Security L7a] No PII detected.")
        
    return sanitized_text