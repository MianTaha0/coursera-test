from flask import Flask, request, send_file, jsonify
from flask_cors import CORS
import os
from PIL import Image
from rembg import remove
import io
import uuid
from werkzeug.utils import secure_filename

app = Flask(__name__)
CORS(app)  # Enable CORS for frontend integration

# Configuration
UPLOAD_FOLDER = 'uploads'
PROCESSED_FOLDER = 'processed'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'bmp', 'webp'}

# Create directories if they don't exist
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(PROCESSED_FOLDER, exist_ok=True)

def allowed_file(filename):
    """Check if uploaded file has allowed extension"""
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def remove_background_and_add_white(image_path):
    """Remove background and replace with white background"""
    try:
        # Read the input image
        with open(image_path, 'rb') as input_file:
            input_data = input_file.read()
        
        # Remove background
        output_data = remove(input_data)
        
        # Convert to PIL Image
        img_no_bg = Image.open(io.BytesIO(output_data)).convert("RGBA")
        
        # Create white background
        white_bg = Image.new("RGB", img_no_bg.size, (255, 255, 255))
        
        # Paste the image with removed background onto white background
        white_bg.paste(img_no_bg, mask=img_no_bg.split()[-1])  # Use alpha channel as mask
        
        return white_bg
    except Exception as e:
        print(f"Error processing image: {str(e)}")
        return None

@app.route('/')
def home():
    """Home route with API information"""
    return jsonify({
        "message": "Background Removal API",
        "endpoints": {
            "/": "API information",
            "/upload": "POST - Upload image for background removal",
            "/health": "GET - Health check"
        },
        "supported_formats": list(ALLOWED_EXTENSIONS)
    })

@app.route('/health')
def health():
    """Health check endpoint"""
    return jsonify({"status": "healthy", "service": "background-removal-api"})

@app.route('/upload', methods=['POST'])
def upload_file():
    """Upload and process image - remove background and add white background"""
    try:
        # Check if file is in request
        if 'file' not in request.files:
            return jsonify({'error': 'No file provided'}), 400
        
        file = request.files['file']
        
        # Check if file is selected
        if file.filename == '':
            return jsonify({'error': 'No file selected'}), 400
        
        # Check if file type is allowed
        if not allowed_file(file.filename):
            return jsonify({
                'error': 'File type not allowed',
                'allowed_types': list(ALLOWED_EXTENSIONS)
            }), 400
        
        # Generate unique filename
        unique_id = str(uuid.uuid4())
        original_extension = file.filename.rsplit('.', 1)[1].lower()
        input_filename = f"{unique_id}_input.{original_extension}"
        output_filename = f"{unique_id}_output.png"
        
        input_path = os.path.join(UPLOAD_FOLDER, input_filename)
        output_path = os.path.join(PROCESSED_FOLDER, output_filename)
        
        # Save uploaded file
        file.save(input_path)
        
        # Process image - remove background and add white background
        processed_image = remove_background_and_add_white(input_path)
        
        if processed_image is None:
            # Clean up uploaded file
            if os.path.exists(input_path):
                os.remove(input_path)
            return jsonify({'error': 'Failed to process image'}), 500
        
        # Save processed image
        processed_image.save(output_path, 'PNG')
        
        # Clean up uploaded file
        if os.path.exists(input_path):
            os.remove(input_path)
        
        return jsonify({
            'message': 'Image processed successfully',
            'download_url': f'/download/{output_filename}',
            'file_id': unique_id
        })
    
    except Exception as e:
        return jsonify({'error': f'Server error: {str(e)}'}), 500

@app.route('/download/<filename>')
def download_file(filename):
    """Download processed image"""
    try:
        file_path = os.path.join(PROCESSED_FOLDER, filename)
        
        if not os.path.exists(file_path):
            return jsonify({'error': 'File not found'}), 404
        
        # Send file and delete after sending
        def remove_file(response):
            try:
                os.remove(file_path)
            except Exception as e:
                print(f"Error removing file: {e}")
            return response
        
        return send_file(
            file_path,
            as_attachment=True,
            download_name=f"processed_{filename}",
            mimetype='image/png'
        )
    
    except Exception as e:
        return jsonify({'error': f'Download error: {str(e)}'}), 500

@app.route('/cleanup')
def cleanup():
    """Clean up old files (optional endpoint for maintenance)"""
    try:
        removed_count = 0
        
        # Clean uploads folder
        for filename in os.listdir(UPLOAD_FOLDER):
            file_path = os.path.join(UPLOAD_FOLDER, filename)
            if os.path.isfile(file_path):
                os.remove(file_path)
                removed_count += 1
        
        # Clean processed folder
        for filename in os.listdir(PROCESSED_FOLDER):
            file_path = os.path.join(PROCESSED_FOLDER, filename)
            if os.path.isfile(file_path):
                os.remove(file_path)
                removed_count += 1
        
        return jsonify({
            'message': f'Cleanup completed. Removed {removed_count} files.'
        })
    
    except Exception as e:
        return jsonify({'error': f'Cleanup error: {str(e)}'}), 500

if __name__ == '__main__':
    print("Starting Background Removal API...")
    print("Supported file formats:", ALLOWED_EXTENSIONS)
    print("Upload endpoint: POST /upload")
    print("Health check: GET /health")
    app.run(debug=True, host='0.0.0.0', port=5000)