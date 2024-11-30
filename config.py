import os
from dotenv import load_dotenv
from web3 import Web3

class Config:
    def __init__(self):
        load_dotenv()
        
        # Load environment variables with validation
        self.google_api_key = self._get_required_env('GOOGLE_API_KEY')
        self.web3_provider = self._get_required_env('WEB3_PROVIDER')
        self.contract_address = self._get_required_env('CONTRACT_ADDRESS')
        
        # Store private key in memory only, not as instance variable
        self._private_key = self._get_required_env('PRIVATE_KEY')
    
    def _get_required_env(self, key):
        value = os.getenv(key)
        if not value:
            raise ValueError(f"Missing required environment variable: {key}")
        return value
    
    def get_private_key(self):
        # Method to securely access private key when needed
        return self._private_key
    
    def get_web3(self):
        # Initialize Web3 with retry mechanism
        try:
            web3 = Web3(Web3.HTTPProvider(self.web3_provider))
            if not web3.is_connected():
                raise ConnectionError("Failed to connect to Web3 provider")
            return web3
        except Exception as e:
            raise ConnectionError(f"Web3 initialization failed: {str(e)}")

# Input validation utilities
def validate_participant_name(name):
    if not name or not isinstance(name, str):
        raise ValueError("Invalid participant name")
    if not name.strip() or len(name) > 100:
        raise ValueError("Participant name must be between 1 and 100 characters")
    if not name.replace(" ", "").isalnum():
        raise ValueError("Participant name can only contain letters, numbers, and spaces")
    return name.strip()

def validate_document_hash(hash_str):
    if not hash_str or not isinstance(hash_str, str):
        raise ValueError("Invalid document hash")
    if not re.match(r'^[a-fA-F0-9]{64}$', hash_str):
        raise ValueError("Invalid hash format")
    return hash_str.lower()
