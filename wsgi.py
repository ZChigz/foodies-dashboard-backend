"""
WSGI entry point for Render deployment
"""
from app import create_app

app = create_app()

if __name__ == "__main__":
    app.run()
