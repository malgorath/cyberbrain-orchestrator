"""
Real LLM Client Implementation

Sends requests to actual LLM endpoints (vLLM, OpenAI-compatible APIs).
Extracts token counts from responses. NEVER stores prompt/response content.

CONTRACT:
- Sends POST requests to /v1/completions
- Extracts tokens from response['usage']
- Returns dict with 'usage' containing token counts
- Raises exceptions on errors (timeout, connection, rate limit)
"""
import requests
import logging
from typing import Dict, Optional

logger = logging.getLogger(__name__)


class LLMClient:
    """Client for sending requests to LLM endpoints."""
    
    def __init__(self, endpoint: str = "http://localhost:8000/v1", timeout: int = 30):
        """
        Initialize LLM client.
        
        Args:
            endpoint: Base URL for LLM API (default: localhost:8000/v1)
            timeout: Request timeout in seconds (default: 30)
        """
        self.endpoint = endpoint
        self.timeout = timeout
    
    def complete(self, prompt: str, model: str = "mistral-7b", max_tokens: int = 500) -> Dict:
        """
        Send completion request to LLM endpoint.
        
        CONTRACT:
        - Sends prompt to /v1/completions
        - Returns dict with 'usage' containing token counts
        - Raises requests exceptions on errors
        - NEVER stores prompt or response content
        
        Args:
            prompt: Prompt text (NOT stored)
            model: Model ID
            max_tokens: Max completion tokens
        
        Returns:
            Dict with structure:
            {
                'usage': {
                    'prompt_tokens': int,
                    'completion_tokens': int,
                    'total_tokens': int
                }
            }
        """
        url = f"{self.endpoint}/completions"
        
        payload = {
            "model": model,
            "prompt": prompt,
            "max_tokens": max_tokens,
            "temperature": 0.7
        }
        
        try:
            response = requests.post(
                url,
                json=payload,
                timeout=self.timeout,
                headers={"Content-Type": "application/json"}
            )
            
            # Handle error status codes
            if response.status_code == 429:
                raise Exception(f"Rate limit exceeded: {response.text}")
            elif response.status_code >= 500:
                raise Exception(f"Server error ({response.status_code}): {response.text}")
            elif response.status_code != 200:
                raise Exception(f"Request failed ({response.status_code}): {response.text}")
            
            # Parse response
            data = response.json()
            
            # Extract token counts (required)
            if 'usage' not in data:
                raise ValueError("Response missing 'usage' field")
            
            return data
        
        except requests.exceptions.Timeout:
            logger.error(f"LLM request timeout after {self.timeout}s")
            raise
        
        except requests.exceptions.ConnectionError as e:
            logger.error(f"Failed to connect to LLM endpoint: {e}")
            raise
        
        except Exception as e:
            logger.error(f"LLM request failed: {e}")
            raise
