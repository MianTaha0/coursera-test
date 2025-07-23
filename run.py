#!/usr/bin/env python3
"""
Simple startup script for the Background Removal API
This script checks dependencies and starts the Flask application
"""

import sys
import subprocess
import importlib
import os

def check_python_version():
    """Check if Python version is compatible"""
    if sys.version_info < (3, 7):
        print("❌ Python 3.7 or higher is required")
        print(f"Current version: {sys.version}")
        return False
    print(f"✅ Python version: {sys.version}")
    return True

def check_dependencies():
    """Check if all required dependencies are installed"""
    required_packages = [
        'flask',
        'flask_cors',
        'PIL',
        'rembg',
        'werkzeug',
        'numpy'
    ]
    
    missing_packages = []
    
    for package in required_packages:
        try:
            if package == 'PIL':
                importlib.import_module('PIL')
            else:
                importlib.import_module(package)
            print(f"✅ {package}")
        except ImportError:
            print(f"❌ {package} - Not installed")
            missing_packages.append(package)
    
    return missing_packages

def install_dependencies():
    """Install missing dependencies"""
    print("\n🔧 Installing dependencies...")
    try:
        subprocess.check_call([sys.executable, '-m', 'pip', 'install', '--break-system-packages', '-r', 'requirements.txt'])
        print("✅ Dependencies installed successfully")
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ Failed to install dependencies: {e}")
        return False

def start_app():
    """Start the Flask application"""
    print("\n🚀 Starting Background Removal API...")
    print("📍 Server will be available at: http://localhost:5000")
    print("📄 Open frontend_example.html in your browser to test the UI")
    print("🛑 Press Ctrl+C to stop the server\n")
    
    try:
        # Import and run the app
        from app import app
        app.run(debug=True, host='0.0.0.0', port=5000)
    except KeyboardInterrupt:
        print("\n👋 Server stopped by user")
    except Exception as e:
        print(f"❌ Error starting server: {e}")

def main():
    """Main function to setup and start the application"""
    print("🎨 Background Removal API Setup")
    print("=" * 50)
    
    # Check Python version
    if not check_python_version():
        sys.exit(1)
    
    # Check if requirements.txt exists
    if not os.path.exists('requirements.txt'):
        print("❌ requirements.txt not found")
        sys.exit(1)
    
    # Check dependencies
    print("\n📦 Checking dependencies...")
    missing = check_dependencies()
    
    if missing:
        print(f"\n⚠️  Missing packages: {', '.join(missing)}")
        install_deps = input("Install missing dependencies? (y/n): ").lower().strip()
        
        if install_deps in ['y', 'yes']:
            if not install_dependencies():
                sys.exit(1)
            
            # Check again after installation
            print("\n📦 Re-checking dependencies...")
            missing = check_dependencies()
            if missing:
                print(f"❌ Still missing: {', '.join(missing)}")
                print("Please install manually: pip install -r requirements.txt")
                sys.exit(1)
        else:
            print("Cannot start without required dependencies")
            sys.exit(1)
    
    print("\n✅ All dependencies are available")
    
    # Start the application
    start_app()

if __name__ == "__main__":
    main()