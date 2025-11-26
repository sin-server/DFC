import os
import json
import time
import logging
from flask import Flask, request, jsonify
from interpreter import interpreter

app = Flask(__name__)

# ==========================================
# 1. DYNAMIC CONFIGURATION (The "Bring Your Own Key" Logic)
# ==========================================
# These ENVs are injected by your Dockerfile/n8n at runtime
USER_API_KEY = os.environ.get("OPENAI_API_KEY")
USER_API_BASE = os.environ.get("OPENAI_API_BASE") # e.g., https://api.openai.com/v1 or http://10.0.0.5:11434
SYSTEM_PROMPT = os.environ.get("SYSTEM_PROMPT", "You are a cyber-gladiator. Your goal is to win.")

# Configure the Interpreter
interpreter.offline = False # Set to False so it attempts to connect to the custom endpoint
interpreter.llm.api_key = USER_API_KEY
interpreter.llm.api_base = USER_API_BASE
interpreter.llm.model = os.environ.get("MODEL_NAME", "gpt-4-turbo") # Default fallback
interpreter.llm.context_window = 128000
interpreter.llm.max_tokens = 4096
interpreter.auto_run = True # CRITICAL: Don't ask for permission in the arena
interpreter.system_message = SYSTEM_PROMPT

# Validation
if not USER_API_KEY and "localhost" not in str(USER_API_BASE):
    print("WARNING: No API Key found. Agent might fail.")

# ==========================================
# 2. THE BLACK BOX (Data Logger)
# ==========================================
LOG_FILE = "/app/logs/match_telemetry.jsonl"
os.makedirs("/app/logs", exist_ok=True)

def log_telemetry(prompt, full_response, tools_used):
    """
    Saves the turn data for future Model Training (The Flywheel).
    """
    entry = {
        "timestamp": time.time(),
        "role": "user",
        "input": prompt,
        "output_text": full_response,
        "tools_executed": tools_used, # Captures the Python/Bash code run
    }
    with open(LOG_FILE, "a") as f:
        f.write(json.dumps(entry) + "\n")

# ==========================================
# 3. THE ENDPOINT
# ==========================================
@app.route('/chat', methods=['POST'])
def chat():
    data = request.json
    prompt = data.get('prompt')
    
    if not prompt:
        return jsonify({"error": "No prompt provided"}), 400

    print(f"[*] Incoming Command: {prompt}")

    # We collect the response components separately
    response_text = ""
    code_blocks = []
    
    try:
        # We use stream=True to keep the connection alive, but we aggregate locally
        # because we need to parse Code vs Text for the logger.
        for chunk in interpreter.chat(prompt, stream=True, display=True):
            
            # Open Interpreter chunks are dictionaries
            if isinstance(chunk, dict):
                
                # Capture Text (The "Thought")
                if chunk.get("type") == "message" and "content" in chunk:
                    content = chunk["content"]
                    if content:
                        response_text += content
                
                # Capture Code (The "Action")
                if chunk.get("type") == "code" and "content" in chunk:
                    # We append to the last block or start a new one
                    code_blocks.append(chunk["content"])

                # Capture Console Output (The "Result")
                if chunk.get("type") == "console" and "content" in chunk:
                    # Optional: Log the result of the code
                    pass

    except Exception as e:
        error_msg = f"Agent Crash: {str(e)}"
        print(error_msg)
        return jsonify({"error": error_msg}), 500

    # Save to the Black Box
    log_telemetry(prompt, response_text, code_blocks)

    # Return structured data to the frontend
    return jsonify({
        "response": response_text.strip(),
        "actions_taken": code_blocks,
        "status": "success"
    })

if __name__ == '__main__':
    # Listen on all interfaces so the Bridge Network can hit it
    app.run(host='0.0.0.0', port=5001)
