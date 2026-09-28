from slowapi import Limiter
from slowapi.util import get_remote_address

# Single Limiter instance shared by main.py (app registration) and routes.py
# (decorator usage). Defining it here prevents circular imports.
#
# Storage: in-memory (default). Rate limit counters exist only in the memory
# of the pod they're tracking — they are NOT shared across replicas. See the
# project summary simplifications table for the production alternative.
limiter = Limiter(key_func=get_remote_address)
