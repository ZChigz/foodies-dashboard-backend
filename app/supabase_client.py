"""
Supabase Client Singleton
Provides a single instance of Supabase client for the entire application.
"""

import os
from supabase import create_client

_supabase_client = None


def get_supabase():
    """
    Get or create a Supabase client instance.
    Uses SUPABASE_URL and SUPABASE_SERVICE_KEY from environment variables.
    
    Returns:
        Supabase client instance
    """
    global _supabase_client

    if _supabase_client is None:
        supabase_url = os.getenv("SUPABASE_URL", "").strip()
        supabase_service_key = (os.getenv("SUPABASE_SERVICE_KEY") or os.getenv("SUPABASE_SERVICE_ROLE_KEY") or "").strip()

        if not supabase_url or not supabase_service_key:
            raise ValueError(
                "SUPABASE_URL and SUPABASE_SERVICE_KEY (or SUPABASE_SERVICE_ROLE_KEY) must be set in environment variables"
            )

        _supabase_client = create_client(supabase_url, supabase_service_key)

    return _supabase_client
