from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from main import get_graph, HumanMessage
import os

app = Flask(__name__, static_folder='static', static_url_path='')
CORS(app)  # Enable CORS for frontend

@app.route('/')
def index():
    return send_from_directory('static', 'index.html')

# Store conversation histories per session
conversations = {}

@app.route('/api/chat', methods=['POST'])
def chat():
    try:
        data = request.json
        user_message = data.get('message', '').strip()
        session_id = data.get('session_id', 'default')
        mode = data.get('mode', 'trials')  # 'trials', 'drugs', or 'unified'
        
        if not user_message:
            return jsonify({'error': 'Message cannot be empty'}), 400
        
        # Get or create conversation history for this session (separate per mode)
        session_key = f"{session_id}_{mode}"
        if session_key not in conversations:
            conversations[session_key] = []
        
        conversation_history = conversations[session_key]
        
        # Add user message to history
        conversation_history.append(HumanMessage(content=user_message))
        
        # Get the appropriate graph based on mode
        graph = get_graph(mode)
        
        # Get response from chatbot
        result = graph.invoke({"messages": conversation_history})
        
        # Get the assistant's response (last message)
        assistant_message = result['messages'][-1]
        
        # Update conversation history
        conversations[session_key] = result['messages']
        
        return jsonify({
            'response': assistant_message.content,
            'session_id': session_id,
            'mode': mode
        })
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/clear', methods=['POST'])
def clear_conversation():
    try:
        data = request.json
        session_id = data.get('session_id', 'default')
        mode = data.get('mode', 'trials')
        
        # Clear the conversation for this session and mode
        session_key = f"{session_id}_{mode}"
        if session_key in conversations:
            conversations[session_key] = []
        
        return jsonify({'success': True, 'session_id': session_id, 'mode': mode})
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/health', methods=['GET'])
def health():
    return jsonify({'status': 'healthy'})

if __name__ == '__main__':
    # Use port 5001 by default to avoid conflict with macOS AirPlay Receiver on port 5000
    port = int(os.environ.get('PORT', 5001))
    print(f"\n{'='*60}")
    print(f"Clinical Trials Assistant Server")
    print(f"{'='*60}")
    print(f"Server running on: http://localhost:{port}")
    print(f"Open this URL in your browser to access the chatbot")
    print(f"{'='*60}\n")
    app.run(host='0.0.0.0', port=port, debug=True)

