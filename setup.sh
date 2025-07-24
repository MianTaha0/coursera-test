#!/bin/bash

echo "🚀 Setting up AI Background Removal Tool..."

# Check if Python 3 is installed
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 is not installed. Please install Python 3 first."
    exit 1
fi

echo "✅ Python 3 found: $(python3 --version)"

# Install dependencies
echo "📦 Installing Python dependencies..."
python3 -m pip install -r requirements.txt

if [ $? -eq 0 ]; then
    echo "✅ Dependencies installed successfully!"
else
    echo "❌ Failed to install dependencies. Please check the error above."
    exit 1
fi

# Create assets directory if it doesn't exist
echo "📁 Setting up assets directory..."
mkdir -p assets

echo "
🎉 Setup complete!

📋 Next steps:
1. Add your images to the assets/ folder (see assets/placeholder-info.md for details)
2. Start the backend server:
   python3 app.py

3. Open index.html in your browser or serve it locally:
   python3 -m http.server 8080
   Then visit: http://localhost:8080

📖 For more information, check README.md

🔗 Backend API will run on: http://localhost:5000
🌐 Frontend can be served on: http://localhost:8080
"