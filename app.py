import os
import time
import json
import hashlib
import sqlite3
import re
from web3 import Web3
from dotenv import load_dotenv
import google.generativeai as genai
from flask import Flask, request, jsonify, render_template, flash
from functools import wraps
import logging
from config import Config, validate_participant_name, validate_document_hash
import base64


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('app.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config['SECRET_KEY'] = os.urandom(24)
config = Config()
web3 = config.get_web3()

def handle_errors(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except ValueError as e:
            logger.error(f"Validation error: {str(e)}")
            return jsonify({"error": str(e)}), 400
        except ConnectionError as e:
            logger.error(f"Blockchain connection error: {str(e)}")
            return jsonify({"error": "Blockchain connection failed"}), 503
        except Exception as e:
            logger.error(f"Unexpected error: {str(e)}")
            return jsonify({"error": "An unexpected error occurred"}), 500
    return decorated_function

load_dotenv()
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
genai.configure(api_key=GOOGLE_API_KEY)

neoxt_url = "https://neoxt4seed1.ngd.network"
web3 = Web3(Web3.HTTPProvider(neoxt_url))

# Check if the connection is successful
if web3.is_connected():
    print("Connected to blockchain")
else:
    print("Failed to connect to blockchain")

# Define your wallet address, private key and chain ID
from_address = "0x8883bFFa42A7f5B509D0929c6fFa041e46E18e2f"
private_key = "9b63cd445ab8312da178e90693290d0d2c98a334f77634013f5d8cfce60f644f"
chain_id = 12227332

dictionary = {}

# SQLite database connection
conn = sqlite3.connect('document_verification.db')
c = conn.cursor()

# Create a table if it doesn't exist
c.execute('''
    CREATE TABLE IF NOT EXISTS documents (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        participant_name TEXT,
        document_hash TEXT,
        txn_hash TEXT,
        timestamp TEXT
    )
''')
conn.commit()
conn.close()

# Function to add document hash to the database
def store_in_db(participant_name, document_hash, txn_hash):
    timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
    conn = sqlite3.connect('document_verification.db')
    c = conn.cursor()
    c.execute('INSERT INTO documents (participant_name, document_hash, txn_hash, timestamp) VALUES (?, ?, ?, ?)',
              (participant_name, document_hash, txn_hash, timestamp))
    conn.commit()
    conn.close()

def extract_participant_info(file_content, file_extension):
    """Extract participant information from document using Gemini Vision AI"""
    try:
        # Convert file content to base64
        content_b64 = base64.b64encode(file_content).decode('utf-8')
        mime_type = 'application/pdf' if file_extension.lower() == '.pdf' else 'image/jpeg'
        
        # Use Gemini Pro Vision model
        model = genai.GenerativeModel("gemini-1.5-flash")
        
        # Create image part for the model
        image_part = {
            "mime_type": mime_type,
            "data": content_b64
        }
        
        prompt = """Extract the full name of the participant from this document.
        Return ONLY the full name, nothing else. If multiple names are found, return the most prominent one.
        If no valid name is found, respond with 'NO_NAME_FOUND'."""
        
        response = model.generate_content([prompt, image_part])
        extracted_name = response.text.strip()
        
        if extracted_name == 'NO_NAME_FOUND':
            raise ValueError("Could not extract participant name from document")
            
        # Validate the extracted name
        validated_name = validate_participant_name(extracted_name)
        return validated_name
        
    except Exception as e:
        logger.error(f"Error extracting participant info: {str(e)}")
        raise ValueError(f"Failed to extract participant information: {str(e)}")

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/verify')
def verify():
    return render_template('verify.html')

@app.route('/verify_document', methods=['POST'])
@handle_errors
def verify_document():
    try:
        file_content = request.files.get('file')
        
        if not file_content:
            raise ValueError("No file provided")
        
        # Get file extension and validate
        filename = file_content.filename
        file_extension = os.path.splitext(filename)[1].lower()
        if file_extension not in ['.pdf', '.jpg', '.jpeg', '.png']:
            raise ValueError("Unsupported file format. Please upload a PDF or image file.")
        
        # Read and hash the uploaded file
        content = file_content.read()
        calculated_hash = hashlib.sha256(content).hexdigest()
        
        # Extract participant name using Gemini Vision AI
        extracted_name = extract_participant_info(content, file_extension)
        
        # Query the database for the participant's document
        conn = sqlite3.connect('document_verification.db')
        c = conn.cursor()
        c.execute('SELECT document_hash, txn_hash FROM documents WHERE participant_name = ? ORDER BY timestamp DESC LIMIT 1', 
                 (extracted_name,))
        result = c.fetchone()
        conn.close()
        
        if not result:
            return jsonify({
                'status': 'error',
                'message': f'No document found for participant: {extracted_name}',
                'extracted_name': extracted_name
            }), 404
        
        stored_hash, transaction_hash = result
        
        # Verify the document hash
        if calculated_hash == stored_hash:
            # Verify on blockchain
            try:
                # Get transaction receipt
                tx_receipt = web3.eth.get_transaction_receipt(transaction_hash)
                if tx_receipt and tx_receipt['status'] == 1:
                    return jsonify({
                        'status': 'success',
                        'message': '✅ Document verification successful! The document is authentic and verified on blockchain.',
                        'transaction_hash': transaction_hash,
                        'stored_hash': stored_hash,
                        'extracted_name': extracted_name
                    })
                else:
                    return jsonify({
                        'status': 'warning',
                        'message': '⚠️ Document matches database but blockchain verification failed.',
                        'transaction_hash': transaction_hash,
                        'stored_hash': stored_hash,
                        'extracted_name': extracted_name
                    })
            except Exception as e:
                logger.error(f"Blockchain verification error: {str(e)}")
                return jsonify({
                    'status': 'warning',
                    'message': '⚠️ Document matches database but blockchain verification failed.',
                    'stored_hash': stored_hash,
                    'extracted_name': extracted_name
                })
        else:
            return jsonify({
                'status': 'error',
                'message': '❌ Document verification failed! The document has been modified or is not authentic.',
                'stored_hash': stored_hash,
                'extracted_name': extracted_name
            }), 400
            
    except Exception as e:
        logger.error(f"Document verification error: {str(e)}")
        raise

@app.route('/upload_details')
def upload_details():
    return render_template('upload.html')

@app.route('/upload')
def upload():
    return render_template('upload.html')

@app.route('/upload_data', methods=['POST'])
@handle_errors
def upload_data():
    try:
        file_content = request.files.get('file')
        
        if not file_content:
            raise ValueError("No file provided")
            
        # Get file extension
        filename = file_content.filename
        file_extension = os.path.splitext(filename)[1].lower()
        
        # Validate file type
        if file_extension not in ['.pdf', '.jpg', '.jpeg', '.png']:
            raise ValueError("Unsupported file format. Please upload a PDF or image file.")
        
        # Read file content
        content = file_content.read()
        
        # Extract participant name using Gemini Vision AI
        participant_name = extract_participant_info(content, file_extension)
        
        # Calculate document hash
        document_hash = hashlib.sha256(content).hexdigest()
        
        # Get blockchain account
        account = web3.eth.account.from_key(private_key)
        
        # Log transaction preparation
        logger.info(f"Preparing transaction with account: {account.address}")
        
        # Get current gas price with a small increase for faster processing
        gas_price = web3.eth.gas_price
        gas_price_with_premium = int(gas_price * 1.1)  # Add 10% to gas price
        
        # Prepare transaction
        transaction = {
            'from': account.address,
            'to': from_address,
            'value': web3.to_wei(0, 'ether'),
            'gas': 100000,
            'gasPrice': gas_price_with_premium,
            'nonce': web3.eth.get_transaction_count(account.address),
            'data': web3.to_hex(text=document_hash),
            'chainId': chain_id
        }
        
        logger.info(f"Transaction details: {transaction}")
        
        try:
            # Estimate gas to check if transaction will fail
            estimated_gas = web3.eth.estimate_gas(transaction)
            logger.info(f"Estimated gas: {estimated_gas}")
            transaction['gas'] = estimated_gas
        except Exception as gas_error:
            logger.error(f"Gas estimation failed: {str(gas_error)}")
            raise ValueError(f"Transaction would fail: {str(gas_error)}")
        
        # Sign transaction
        signed_txn = account.sign_transaction(transaction)
        logger.info("Transaction signed successfully")
        
        # Send raw transaction
        tx_hash = web3.eth.send_raw_transaction(signed_txn.raw_transaction)
        logger.info(f"Transaction sent with hash: {tx_hash.hex()}")
        
        # Wait for transaction receipt
        tx_receipt = web3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
        logger.info(f"Transaction receipt received: {tx_receipt}")
        
        if tx_receipt.status == 1:
            # Store in database
            store_in_db(participant_name, document_hash, tx_hash.hex())
            
            logger.info(f"Successfully uploaded document for {participant_name}")
            return jsonify({
                'status': 'success',
                'transaction_hash': tx_hash.hex(),
                'participant_name': participant_name,
                'message': 'Document uploaded successfully'
            })
        else:
            logger.error(f"Transaction failed with receipt: {tx_receipt}")
            raise ValueError(f"Transaction failed on the blockchain. Receipt: {tx_receipt}")
            
    except Exception as e:
        logger.error(f"Error in upload_data: {str(e)}")
        raise

@app.route('/result')
def result():
    global dictionary
    return render_template('result.html', dictionary=dictionary, verify_result="")

if __name__ == '__main__':
    app.run(debug=True)