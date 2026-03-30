"""
F Drive API - Application Factory
Initializes Flask app, configures JWT, CORS, and registers blueprints
"""

from flask import Flask, jsonify
from flask_cors import CORS
from flask_jwt_extended import JWTManager
from datetime import timedelta
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()


def create_app():
    """
    Application factory function that creates and configures the Flask app.
    Returns configured Flask app instance.
    """
    app = Flask(__name__)

    # ============ Configuration ============
    app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev-secret-key-change-in-production")
    app.config["JWT_SECRET_KEY"] = os.getenv("JWT_SECRET_KEY", "jwt-secret-key-change-in-production")
    app.config["JWT_ACCESS_TOKEN_EXPIRES"] = timedelta(
        seconds=int(os.getenv("JWT_ACCESS_TOKEN_EXPIRES", 3600))
    )
    # Store identity in a dedicated claim so dict identities don't break JWT subject validation.
    app.config["JWT_IDENTITY_CLAIM"] = "identity"
    # Backward compatibility for previously-issued tokens that used non-string sub claims.
    app.config["JWT_VERIFY_SUB"] = False

    # ============ CORS Configuration ============
    allowed_origins = os.getenv("ALLOWED_ORIGINS", "http://localhost:3000,http://localhost:5000").split(",")
    CORS(app, resources={r"/api/*": {"origins": allowed_origins}})

    # ============ JWT Configuration ============
    jwt = JWTManager(app)

    @jwt.invalid_token_loader
    def invalid_token_callback(error_string):
        return jsonify({"error": "Invalid token", "details": error_string}), 401

    @jwt.unauthorized_loader
    def missing_token_callback(error_string):
        return jsonify({"error": "Authorization token is required", "details": error_string}), 401

    @jwt.expired_token_loader
    def expired_token_callback(jwt_header, jwt_payload):
        return jsonify({"error": "Token has expired"}), 401

    # ============ Register Blueprints ============
    try:
        from app.routes import auth, orders_complete as orders, menu, restaurants, riders, payments
        from app.routes.admin import admin_bp

        app.register_blueprint(auth.bp)
        app.register_blueprint(orders.bp)
        app.register_blueprint(menu.bp)
        app.register_blueprint(restaurants.bp)
        app.register_blueprint(riders.bp)
        app.register_blueprint(payments.bp)
        app.register_blueprint(admin_bp, url_prefix='/api/admin')
    except Exception as e:
        print(f"ERROR registering blueprints: {e}")
        import traceback
        traceback.print_exc()
        raise

    # ============ Health Check Endpoint ============
    @app.route("/", methods=["GET"])
    def health_check():
        """Health check endpoint - indicates API is running."""
        return jsonify(
            {
                "status": "ok",
                "app": "F Drive API",
                "version": os.getenv("APP_VERSION", "1.0.0"),
            }
        )

    # ============ Error Handlers ============
    @app.errorhandler(404)
    def not_found(error):
        """Handle 404 errors."""
        return jsonify({"error": "Resource not found"}), 404

    @app.errorhandler(500)
    def internal_error(error):
        """Handle 500 errors."""
        return jsonify({"error": "Internal server error"}), 500

    return app
