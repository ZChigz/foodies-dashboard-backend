from app import create_app

# 👇 THIS MUST BE AT TOP LEVEL (not inside any if block)
app = create_app()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
