#!/usr/bin/env python3
"""
F DRIVE BACKEND - COMPLETE PROJECT SETUP
This script creates all project files and folders in one go.
Run once: python setup.py
"""

import os
import sys

# Change to script directory
os.chdir(os.path.dirname(os.path.abspath(__file__)))

# Define complete file structure
FILES_CONTENT = {
    "app/__init__.py": """\"\"\"
F Drive API - Application Factory
Initializes Flask app, configures JWT, CORS, and registers blueprints
\"\"\"

from flask import Flask, jsonify
from flask_cors import CORS
from flask_jwt_extended import JWTManager
from datetime import timedelta
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()


def create_app():
    \"\"\"
    Application factory function that creates and configures the Flask app.
    Returns configured Flask app instance.
    \"\"\"
    app = Flask(__name__)

    # ============ Configuration ============
    app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev-secret-key-change-in-production")
    app.config["JWT_SECRET_KEY"] = os.getenv("JWT_SECRET_KEY", "jwt-secret-key-change-in-production")
    app.config["JWT_ACCESS_TOKEN_EXPIRES"] = timedelta(
        seconds=int(os.getenv("JWT_ACCESS_TOKEN_EXPIRES", 3600))
    )

    # ============ CORS Configuration ============
    allowed_origins = os.getenv("ALLOWED_ORIGINS", "http://localhost:3000,http://localhost:5000").split(",")
    CORS(app, resources={r"/api/*": {"origins": allowed_origins}})

    # ============ JWT Configuration ============
    jwt = JWTManager(app)

    # ============ Register Blueprints ============
    from app.routes import auth, orders, menu, restaurants, riders, payments

    app.register_blueprint(auth.bp)
    app.register_blueprint(orders.bp)
    app.register_blueprint(menu.bp)
    app.register_blueprint(restaurants.bp)
    app.register_blueprint(riders.bp)
    app.register_blueprint(payments.bp)

    # ============ Health Check Endpoint ============
    @app.route("/", methods=["GET"])
    def health_check():
        \"\"\"Health check endpoint - indicates API is running.\"\"\"
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
        \"\"\"Handle 404 errors.\"\"\"
        return jsonify({"error": "Resource not found"}), 404

    @app.errorhandler(500)
    def internal_error(error):
        \"\"\"Handle 500 errors.\"\"\"
        return jsonify({"error": "Internal server error"}), 500

    return app
""",

    "app/supabase_client.py": """\"\"\"
Supabase Client Singleton
Provides a single instance of Supabase client for the entire application.
\"\"\"

import os
from supabase import create_client

_supabase_client = None


def get_supabase():
    \"\"\"
    Get or create a Supabase client instance.
    Uses SUPABASE_URL and SUPABASE_SERVICE_KEY from environment variables.
    
    Returns:
        Supabase client instance
    \"\"\"
    global _supabase_client

    if _supabase_client is None:
        supabase_url = os.getenv("SUPABASE_URL")
        supabase_service_key = os.getenv("SUPABASE_SERVICE_KEY")

        if not supabase_url or not supabase_service_key:
            raise ValueError(
                "SUPABASE_URL and SUPABASE_SERVICE_KEY must be set in environment variables"
            )

        _supabase_client = create_client(supabase_url, supabase_service_key)

    return _supabase_client
""",

    "app/routes/__init__.py": "# Routes package",

    "app/routes/auth.py": """\"\"\"
Authentication Routes
Handles user registration, login, and profile retrieval.
\"\"\"

from flask import Blueprint, request, jsonify
from flask_jwt_extended import create_access_token, jwt_required, get_jwt_identity
from app.supabase_client import get_supabase
import bcrypt

bp = Blueprint("auth", __name__, url_prefix="/api/auth")


@bp.route("/register", methods=["POST"])
def register():
    \"\"\"
    Register a new user (customer, rider, or restaurant owner).
    
    Request JSON:
        - email (string): User email
        - password (string): User password (will be hashed)
        - name (string): User full name
        - role (string): "customer", "rider", or "restaurant"
    
    Returns:
        - 201: User created successfully with access token
        - 400: Missing required fields or email already exists
        - 500: Server error
    \"\"\"
    try:
        data = request.get_json()

        # Validate required fields
        if not data or not all(k in data for k in ["email", "password", "name", "role"]):
            return jsonify({"error": "Missing required fields: email, password, name, role"}), 400

        email = data["email"]
        password = data["password"]
        name = data["name"]
        role = data["role"]

        if role not in ["customer", "rider", "restaurant"]:
            return jsonify({"error": "Invalid role. Must be 'customer', 'rider', or 'restaurant'"}), 400

        # Hash password
        hashed_password = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

        # Insert into database
        supabase = get_supabase()
        response = supabase.table("users").insert(
            {
                "email": email,
                "password": hashed_password,
                "name": name,
                "role": role,
            }
        ).execute()

        if not response.data:
            return jsonify({"error": "Failed to create user"}), 500

        user = response.data[0]
        user_id = user["id"]

        # Create JWT token
        identity = {"id": user_id, "role": role}
        access_token = create_access_token(identity=identity)

        return (
            jsonify(
                {
                    "message": "User registered successfully",
                    "user_id": user_id,
                    "access_token": access_token,
                    "role": role,
                }
            ),
            201,
        )

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("/login", methods=["POST"])
def login():
    \"\"\"
    Authenticate a user and return JWT token.
    
    Request JSON:
        - email (string): User email
        - password (string): User password
    
    Returns:
        - 200: Login successful with access token
        - 400: Missing email or password
        - 401: Invalid credentials
        - 500: Server error
    \"\"\"
    try:
        data = request.get_json()

        if not data or not all(k in data for k in ["email", "password"]):
            return jsonify({"error": "Missing required fields: email, password"}), 400

        email = data["email"]
        password = data["password"]

        # Query user from database
        supabase = get_supabase()
        response = supabase.table("users").select("*").eq("email", email).execute()

        if not response.data:
            return jsonify({"error": "Invalid email or password"}), 401

        user = response.data[0]

        # Verify password
        if not bcrypt.checkpw(password.encode("utf-8"), user["password"].encode("utf-8")):
            return jsonify({"error": "Invalid email or password"}), 401

        # Create JWT token
        identity = {"id": user["id"], "role": user["role"]}
        access_token = create_access_token(identity=identity)

        return (
            jsonify(
                {
                    "message": "Login successful",
                    "user_id": user["id"],
                    "access_token": access_token,
                    "role": user["role"],
                }
            ),
            200,
        )

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("/me", methods=["GET"])
@jwt_required()
def get_me():
    \"\"\"
    Get current authenticated user's profile.
    Requires valid JWT token.
    
    Returns:
        - 200: User profile data
        - 401: Unauthorized (invalid or missing token)
        - 500: Server error
    \"\"\"
    try:
        identity = get_jwt_identity()
        user_id = identity["id"]

        # Query user from database
        supabase = get_supabase()
        response = supabase.table("users").select("id, email, name, role, created_at").eq("id", user_id).execute()

        if not response.data:
            return jsonify({"error": "User not found"}), 404

        user = response.data[0]

        return jsonify(
            {
                "id": user["id"],
                "email": user["email"],
                "name": user["name"],
                "role": user["role"],
                "created_at": user["created_at"],
            }
        ), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500
""",

    "app/routes/orders.py": """\"\"\"
Orders Routes
Handles order creation, retrieval, updates, and status transitions.
\"\"\"

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from app.supabase_client import get_supabase
from datetime import datetime

bp = Blueprint("orders", __name__, url_prefix="/api/orders")


@bp.route("", methods=["POST"])
@jwt_required()
def create_order():
    \"\"\"
    Create a new order (customers only).
    
    Request JSON:
        - restaurant_id (string): ID of restaurant
        - items (array): Order items with menu_item_id and quantity
        - delivery_address (string): Delivery address
        - delivery_phone (string): Delivery phone number
    
    Returns:
        - 201: Order created successfully
        - 400: Missing required fields or invalid role
        - 500: Server error
    \"\"\"
    try:
        identity = get_jwt_identity()
        user_id = identity["id"]
        role = identity["role"]

        if role != "customer":
            return jsonify({"error": "Only customers can create orders"}), 400

        data = request.get_json()

        if not data or not all(k in data for k in ["restaurant_id", "items", "delivery_address", "delivery_phone"]):
            return jsonify({"error": "Missing required fields"}), 400

        supabase = get_supabase()

        # Create order
        response = supabase.table("orders").insert(
            {
                "customer_id": user_id,
                "restaurant_id": data["restaurant_id"],
                "items": data["items"],
                "delivery_address": data["delivery_address"],
                "delivery_phone": data["delivery_phone"],
                "status": "pending",
                "created_at": datetime.utcnow().isoformat(),
            }
        ).execute()

        if not response.data:
            return jsonify({"error": "Failed to create order"}), 500

        order = response.data[0]

        return jsonify(
            {
                "message": "Order created successfully",
                "order_id": order["id"],
                "status": order["status"],
            }
        ), 201

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("/<order_id>", methods=["GET"])
@jwt_required()
def get_order(order_id):
    \"\"\"
    Retrieve order details by ID.
    Users can only see their own orders or orders they're involved with.
    
    Returns:
        - 200: Order details
        - 404: Order not found
        - 403: Unauthorized to view this order
        - 500: Server error
    \"\"\"
    try:
        identity = get_jwt_identity()
        user_id = identity["id"]

        supabase = get_supabase()
        response = supabase.table("orders").select("*").eq("id", order_id).execute()

        if not response.data:
            return jsonify({"error": "Order not found"}), 404

        order = response.data[0]

        # Authorization check
        if (
            order["customer_id"] != user_id
            and order.get("rider_id") != user_id
            and order["restaurant_id"] != user_id
        ):
            return jsonify({"error": "Unauthorized to view this order"}), 403

        return jsonify(order), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("/customer/<customer_id>", methods=["GET"])
@jwt_required()
def get_customer_orders(customer_id):
    \"\"\"
    Retrieve all orders for a customer.
    Customers can only view their own orders.
    
    Returns:
        - 200: List of orders
        - 403: Unauthorized
        - 500: Server error
    \"\"\"
    try:
        identity = get_jwt_identity()
        user_id = identity["id"]

        if user_id != customer_id:
            return jsonify({"error": "Unauthorized to view these orders"}), 403

        supabase = get_supabase()
        response = supabase.table("orders").select("*").eq("customer_id", customer_id).execute()

        return jsonify({"orders": response.data}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("/<order_id>/status", methods=["PATCH"])
@jwt_required()
def update_order_status(order_id):
    \"\"\"
    Update order status (restaurants assign to rider, riders update delivery status).
    Valid status transitions:
    - pending -> accepted (restaurant)
    - accepted -> assigned_to_rider (restaurant)
    - assigned_to_rider -> picked_up (rider)
    - picked_up -> delivered (rider)
    
    Request JSON:
        - status (string): New status
    
    Returns:
        - 200: Status updated successfully
        - 400: Invalid status transition
        - 403: Unauthorized to update this order
        - 404: Order not found
        - 500: Server error
    \"\"\"
    try:
        identity = get_jwt_identity()
        user_id = identity["id"]
        role = identity["role"]

        data = request.get_json()

        if not data or "status" not in data:
            return jsonify({"error": "Missing status field"}), 400

        new_status = data["status"]

        supabase = get_supabase()
        response = supabase.table("orders").select("*").eq("id", order_id).execute()

        if not response.data:
            return jsonify({"error": "Order not found"}), 404

        order = response.data[0]

        # Authorization check
        if role == "restaurant" and order["restaurant_id"] != user_id:
            return jsonify({"error": "Unauthorized to update this order"}), 403

        if role == "rider" and order.get("rider_id") != user_id:
            return jsonify({"error": "Unauthorized to update this order"}), 403

        # Validate status transition
        current_status = order["status"]
        valid_transitions = {
            "pending": ["accepted"],
            "accepted": ["assigned_to_rider"],
            "assigned_to_rider": ["picked_up"],
            "picked_up": ["delivered"],
        }

        if current_status not in valid_transitions or new_status not in valid_transitions.get(
            current_status, []
        ):
            return jsonify(
                {"error": f"Invalid status transition from {current_status} to {new_status}"}
            ), 400

        # Update order
        update_data = {"status": new_status}
        if new_status == "assigned_to_rider":
            update_data["rider_id"] = user_id

        response = supabase.table("orders").update(update_data).eq("id", order_id).execute()

        return jsonify({"message": "Order status updated", "status": new_status}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("/<order_id>", methods=["DELETE"])
@jwt_required()
def delete_order(order_id):
    \"\"\"
    Delete an order (customers can only delete pending orders).
    
    Returns:
        - 200: Order deleted successfully
        - 403: Cannot delete non-pending orders
        - 404: Order not found
        - 500: Server error
    \"\"\"
    try:
        identity = get_jwt_identity()
        user_id = identity["id"]

        supabase = get_supabase()
        response = supabase.table("orders").select("*").eq("id", order_id).execute()

        if not response.data:
            return jsonify({"error": "Order not found"}), 404

        order = response.data[0]

        if order["customer_id"] != user_id:
            return jsonify({"error": "Unauthorized to delete this order"}), 403

        if order["status"] != "pending":
            return jsonify(
                {"error": "Can only delete orders with 'pending' status"}
            ), 403

        supabase.table("orders").delete().eq("id", order_id).execute()

        return jsonify({"message": "Order deleted successfully"}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500
""",

    "app/routes/menu.py": """\"\"\"
Menu Routes
Handles menu item management (GET, POST, PATCH, DELETE).
\"\"\"

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from app.supabase_client import get_supabase
from datetime import datetime

bp = Blueprint("menu", __name__, url_prefix="/api/menu")


@bp.route("/<restaurant_id>", methods=["GET"])
def get_menu_items(restaurant_id):
    \"\"\"
    Get all menu items for a restaurant (public endpoint).
    
    Returns:
        - 200: List of menu items
        - 500: Server error
    \"\"\"
    try:
        supabase = get_supabase()
        response = supabase.table("menu_items").select("*").eq("restaurant_id", restaurant_id).execute()

        return jsonify({"items": response.data}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("", methods=["POST"])
@jwt_required()
def create_menu_item():
    \"\"\"
    Create a new menu item (restaurants only).
    
    Request JSON:
        - name (string): Item name
        - description (string): Item description
        - price (float): Item price
        - category (string): Item category (e.g., "appetizer", "main", "dessert")
        - image_url (string): URL to item image
        - available (boolean): Is item available
    
    Returns:
        - 201: Menu item created successfully
        - 400: Missing required fields or invalid role
        - 500: Server error
    \"\"\"
    try:
        identity = get_jwt_identity()
        user_id = identity["id"]
        role = identity["role"]

        if role != "restaurant":
            return jsonify({"error": "Only restaurants can create menu items"}), 400

        data = request.get_json()

        if not data or not all(
            k in data for k in ["name", "description", "price", "category", "image_url"]
        ):
            return jsonify({"error": "Missing required fields"}), 400

        supabase = get_supabase()

        response = supabase.table("menu_items").insert(
            {
                "restaurant_id": user_id,
                "name": data["name"],
                "description": data["description"],
                "price": data["price"],
                "category": data["category"],
                "image_url": data["image_url"],
                "available": data.get("available", True),
                "created_at": datetime.utcnow().isoformat(),
            }
        ).execute()

        if not response.data:
            return jsonify({"error": "Failed to create menu item"}), 500

        item = response.data[0]

        return (
            jsonify(
                {
                    "message": "Menu item created successfully",
                    "item_id": item["id"],
                }
            ),
            201,
        )

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("/<item_id>", methods=["GET"])
def get_menu_item(item_id):
    \"\"\"
    Get a specific menu item by ID (public endpoint).
    
    Returns:
        - 200: Menu item details
        - 404: Menu item not found
        - 500: Server error
    \"\"\"
    try:
        supabase = get_supabase()
        response = supabase.table("menu_items").select("*").eq("id", item_id).execute()

        if not response.data:
            return jsonify({"error": "Menu item not found"}), 404

        return jsonify(response.data[0]), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("/<item_id>", methods=["PATCH"])
@jwt_required()
def update_menu_item(item_id):
    \"\"\"
    Update a menu item (restaurants can only update their own items).
    Can update: name, description, price, category, image_url, available
    
    Request JSON:
        - name, description, price, category, image_url, or available (any combination)
    
    Returns:
        - 200: Menu item updated successfully
        - 403: Unauthorized to update this item
        - 404: Menu item not found
        - 500: Server error
    \"\"\"
    try:
        identity = get_jwt_identity()
        user_id = identity["id"]

        supabase = get_supabase()
        response = supabase.table("menu_items").select("*").eq("id", item_id).execute()

        if not response.data:
            return jsonify({"error": "Menu item not found"}), 404

        item = response.data[0]

        if item["restaurant_id"] != user_id:
            return jsonify({"error": "Unauthorized to update this menu item"}), 403

        data = request.get_json()

        if not data:
            return jsonify({"error": "No data to update"}), 400

        # Prepare update data (only update fields that are provided)
        update_data = {}
        for field in ["name", "description", "price", "category", "image_url", "available"]:
            if field in data:
                update_data[field] = data[field]

        response = supabase.table("menu_items").update(update_data).eq("id", item_id).execute()

        return (
            jsonify(
                {
                    "message": "Menu item updated successfully",
                    "item_id": item_id,
                }
            ),
            200,
        )

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("/<item_id>", methods=["DELETE"])
@jwt_required()
def delete_menu_item(item_id):
    \"\"\"
    Delete a menu item (restaurants can only delete their own items).
    
    Returns:
        - 200: Menu item deleted successfully
        - 403: Unauthorized to delete this item
        - 404: Menu item not found
        - 500: Server error
    \"\"\"
    try:
        identity = get_jwt_identity()
        user_id = identity["id"]

        supabase = get_supabase()
        response = supabase.table("menu_items").select("*").eq("id", item_id).execute()

        if not response.data:
            return jsonify({"error": "Menu item not found"}), 404

        item = response.data[0]

        if item["restaurant_id"] != user_id:
            return jsonify({"error": "Unauthorized to delete this menu item"}), 403

        supabase.table("menu_items").delete().eq("id", item_id).execute()

        return jsonify({"message": "Menu item deleted successfully"}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500
""",

    "app/routes/restaurants.py": """\"\"\"
Restaurants Routes
Handles restaurant listing, details, and status management.
\"\"\"

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from app.supabase_client import get_supabase
from datetime import datetime

bp = Blueprint("restaurants", __name__, url_prefix="/api/restaurants")


@bp.route("", methods=["GET"])
def get_restaurants():
    \"\"\"
    Get all restaurants (public endpoint).
    Optionally filter by status (open/closed).
    
    Query Parameters:
        - status (optional): "open" or "closed"
    
    Returns:
        - 200: List of restaurants
        - 500: Server error
    \"\"\"
    try:
        status = request.args.get("status")

        supabase = get_supabase()

        if status:
            response = supabase.table("restaurants").select("*").eq("status", status).execute()
        else:
            response = supabase.table("restaurants").select("*").execute()

        return jsonify({"restaurants": response.data}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("/<restaurant_id>", methods=["GET"])
def get_restaurant(restaurant_id):
    \"\"\"
    Get restaurant details by ID (public endpoint).
    
    Returns:
        - 200: Restaurant details
        - 404: Restaurant not found
        - 500: Server error
    \"\"\"
    try:
        supabase = get_supabase()
        response = supabase.table("restaurants").select("*").eq("id", restaurant_id).execute()

        if not response.data:
            return jsonify({"error": "Restaurant not found"}), 404

        restaurant = response.data[0]

        return jsonify(restaurant), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("/toggle-status/<restaurant_id>", methods=["PATCH"])
@jwt_required()
def toggle_restaurant_status(restaurant_id):
    \"\"\"
    Toggle restaurant open/closed status (restaurant owners only).
    
    Returns:
        - 200: Status toggled successfully
        - 403: Unauthorized to toggle this restaurant's status
        - 404: Restaurant not found
        - 500: Server error
    \"\"\"
    try:
        identity = get_jwt_identity()
        user_id = identity["id"]
        role = identity["role"]

        if role != "restaurant":
            return jsonify({"error": "Only restaurant owners can toggle status"}), 403

        supabase = get_supabase()
        response = supabase.table("restaurants").select("*").eq("id", restaurant_id).execute()

        if not response.data:
            return jsonify({"error": "Restaurant not found"}), 404

        restaurant = response.data[0]

        # Authorization check - restaurant must own this account
        if restaurant["owner_id"] != user_id:
            return jsonify({"error": "Unauthorized to toggle this restaurant's status"}), 403

        # Toggle status
        new_status = "closed" if restaurant["status"] == "open" else "open"

        response = supabase.table("restaurants").update(
            {
                "status": new_status,
                "updated_at": datetime.utcnow().isoformat(),
            }
        ).eq("id", restaurant_id).execute()

        return (
            jsonify(
                {
                    "message": f"Restaurant status toggled to {new_status}",
                    "restaurant_id": restaurant_id,
                    "status": new_status,
                }
            ),
            200,
        )

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("", methods=["POST"])
@jwt_required()
def create_restaurant():
    \"\"\"
    Create a new restaurant (restaurant owners only - typically during account creation).
    
    Request JSON:
        - name (string): Restaurant name
        - description (string): Restaurant description
        - phone (string): Contact phone number
        - address (string): Physical address
        - city (string): City location
        - image_url (string): Restaurant logo/image URL
    
    Returns:
        - 201: Restaurant created successfully
        - 400: Missing required fields or invalid role
        - 500: Server error
    \"\"\"
    try:
        identity = get_jwt_identity()
        user_id = identity["id"]
        role = identity["role"]

        if role != "restaurant":
            return jsonify({"error": "Only restaurant owners can create restaurants"}), 400

        data = request.get_json()

        if not data or not all(
            k in data
            for k in ["name", "description", "phone", "address", "city", "image_url"]
        ):
            return jsonify({"error": "Missing required fields"}), 400

        supabase = get_supabase()

        response = supabase.table("restaurants").insert(
            {
                "owner_id": user_id,
                "name": data["name"],
                "description": data["description"],
                "phone": data["phone"],
                "address": data["address"],
                "city": data["city"],
                "image_url": data["image_url"],
                "status": "open",
                "created_at": datetime.utcnow().isoformat(),
            }
        ).execute()

        if not response.data:
            return jsonify({"error": "Failed to create restaurant"}), 500

        restaurant = response.data[0]

        return (
            jsonify(
                {
                    "message": "Restaurant created successfully",
                    "restaurant_id": restaurant["id"],
                }
            ),
            201,
        )

    except Exception as e:
        return jsonify({"error": str(e)}), 500
""",

    "app/routes/riders.py": """\"\"\"
Riders Routes
Handles rider availability status and real-time GPS location tracking.
\"\"\"

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from app.supabase_client import get_supabase
from datetime import datetime

bp = Blueprint("riders", __name__, url_prefix="/api/riders")


@bp.route("/availability", methods=["PATCH"])
@jwt_required()
def toggle_availability():
    \"\"\"
    Toggle rider availability (online/offline).
    Riders can only update their own availability.
    
    Request JSON:
        - available (boolean): Availability status
    
    Returns:
        - 200: Availability updated successfully
        - 400: Invalid role or missing data
        - 500: Server error
    \"\"\"
    try:
        identity = get_jwt_identity()
        user_id = identity["id"]
        role = identity["role"]

        if role != "rider":
            return jsonify({"error": "Only riders can update their availability"}), 400

        data = request.get_json()

        if data is None or "available" not in data:
            return jsonify({"error": "Missing 'available' field"}), 400

        supabase = get_supabase()

        response = supabase.table("riders").update(
            {
                "available": data["available"],
                "updated_at": datetime.utcnow().isoformat(),
            }
        ).eq("user_id", user_id).execute()

        availability_status = "online" if data["available"] else "offline"

        return (
            jsonify(
                {
                    "message": f"Availability set to {availability_status}",
                    "available": data["available"],
                }
            ),
            200,
        )

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("/location", methods=["POST"])
@jwt_required()
def broadcast_location():
    \"\"\"
    Broadcast rider GPS location (real-time tracking).
    Typically called frequently (every 30 seconds or on movement).
    
    Request JSON:
        - latitude (float): Latitude coordinate
        - longitude (float): Longitude coordinate
    
    Returns:
        - 200: Location updated successfully
        - 400: Invalid role or missing coordinates
        - 500: Server error
    \"\"\"
    try:
        identity = get_jwt_identity()
        user_id = identity["id"]
        role = identity["role"]

        if role != "rider":
            return jsonify({"error": "Only riders can broadcast location"}), 400

        data = request.get_json()

        if not data or not all(k in data for k in ["latitude", "longitude"]):
            return jsonify({"error": "Missing required fields: latitude, longitude"}), 400

        latitude = data["latitude"]
        longitude = data["longitude"]

        # Validate coordinates
        if not isinstance(latitude, (int, float)) or not isinstance(longitude, (int, float)):
            return jsonify({"error": "Latitude and longitude must be numbers"}), 400

        if not (-90 <= latitude <= 90):
            return jsonify({"error": "Latitude must be between -90 and 90"}), 400

        if not (-180 <= longitude <= 180):
            return jsonify({"error": "Longitude must be between -180 and 180"}), 400

        supabase = get_supabase()

        # Update rider location - using upsert pattern
        response = supabase.table("rider_locations").upsert(
            {
                "rider_id": user_id,
                "latitude": latitude,
                "longitude": longitude,
                "updated_at": datetime.utcnow().isoformat(),
            }
        ).execute()

        return (
            jsonify(
                {
                    "message": "Location broadcast successfully",
                    "latitude": latitude,
                    "longitude": longitude,
                }
            ),
            200,
        )

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("/location/<rider_id>", methods=["GET"])
@jwt_required()
def get_rider_location(rider_id):
    \"\"\"
    Get rider's current location (for tracking deliveries).
    Authorization: Only customers with active orders from this rider,
    or the rider themselves can view the location.
    
    Returns:
        - 200: Rider location data
        - 403: Unauthorized to view this location
        - 404: Rider location not found
        - 500: Server error
    \"\"\"
    try:
        identity = get_jwt_identity()
        user_id = identity["id"]

        # Authorization: Rider can view their own, customers can view their active riders
        if user_id != rider_id:
            supabase = get_supabase()
            # Check if requester has an active order with this rider
            order_response = supabase.table("orders").select("*").eq(
                "rider_id", rider_id
            ).eq("customer_id", user_id).execute()

            if not order_response.data:
                return jsonify({"error": "Unauthorized to view this location"}), 403

        supabase = get_supabase()
        response = supabase.table("rider_locations").select("*").eq("rider_id", rider_id).execute()

        if not response.data:
            return jsonify({"error": "Rider location not found"}), 404

        location = response.data[0]

        return jsonify(location), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("/available", methods=["GET"])
def get_available_riders():
    \"\"\"
    Get all available riders (public endpoint for dispatcher/matching system).
    
    Query Parameters:
        - city (optional): Filter by city
    
    Returns:
        - 200: List of available riders
        - 500: Server error
    \"\"\"
    try:
        city = request.args.get("city")

        supabase = get_supabase()

        if city:
            response = supabase.table("riders").select("*").eq("available", True).eq(
                "city", city
            ).execute()
        else:
            response = supabase.table("riders").select("*").eq("available", True).execute()

        return jsonify({"riders": response.data}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500
""",

    "app/routes/payments.py": """\"\"\"
Payments Routes
Handles Paynow Zimbabwe integration for EcoCash and card payments.
\"\"\"

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from app.supabase_client import get_supabase
import os
from datetime import datetime

bp = Blueprint("payments", __name__, url_prefix="/api/payments")


@bp.route("/initiate", methods=["POST"])
@jwt_required()
def initiate_payment():
    \"\"\"
    Initiate a payment using Paynow Zimbabwe.
    Supports EcoCash and card payments.
    
    Request JSON:
        - order_id (string): Order ID to pay for
        - amount (float): Payment amount in ZWL
        - payment_method (string): "ecocash" or "card"
        - phone (string): Phone number for EcoCash (if payment_method is ecocash)
    
    Returns:
        - 200: Payment initiated successfully
        - 400: Missing required fields or invalid payment method
        - 404: Order not found
        - 500: Server error
    \"\"\"
    try:
        identity = get_jwt_identity()
        user_id = identity["id"]

        data = request.get_json()

        if not data or not all(k in data for k in ["order_id", "amount", "payment_method"]):
            return jsonify({"error": "Missing required fields: order_id, amount, payment_method"}), 400

        order_id = data["order_id"]
        amount = data["amount"]
        payment_method = data["payment_method"]

        if payment_method not in ["ecocash", "card"]:
            return jsonify({"error": "Invalid payment method. Must be 'ecocash' or 'card'"}), 400

        if payment_method == "ecocash" and "phone" not in data:
            return jsonify({"error": "Phone number required for EcoCash payments"}), 400

        # Verify order exists and belongs to customer
        supabase = get_supabase()
        order_response = supabase.table("orders").select("*").eq("id", order_id).execute()

        if not order_response.data:
            return jsonify({"error": "Order not found"}), 404

        order = order_response.data[0]

        if order["customer_id"] != user_id:
            return jsonify({"error": "Unauthorized to pay for this order"}), 403

        # Create payment record in database
        payment_response = supabase.table("payments").insert(
            {
                "order_id": order_id,
                "customer_id": user_id,
                "amount": amount,
                "payment_method": payment_method,
                "phone": data.get("phone"),
                "status": "pending",
                "created_at": datetime.utcnow().isoformat(),
            }
        ).execute()

        if not payment_response.data:
            return jsonify({"error": "Failed to create payment record"}), 500

        payment = payment_response.data[0]
        payment_id = payment["id"]

        # TODO: Integrate with Paynow SDK
        # Example structure:
        # paynow = Paynow(
        #     integration_id=os.getenv("PAYNOW_INTEGRATION_ID"),
        #     integration_key=os.getenv("PAYNOW_INTEGRATION_KEY")
        # )
        # 
        # invoice = paynow.create_invoice({
        #     "items": [{"title": f"Order {order_id}", "amount": amount}],
        #     "redirect_url": os.getenv("PAYNOW_RETURN_URL")
        # })
        #
        # link = paynow.send_invoice(invoice)

        return (
            jsonify(
                {
                    "message": "Payment initiated successfully",
                    "payment_id": payment_id,
                    "amount": amount,
                    "payment_method": payment_method,
                    "status": "pending",
                    # "payment_link": link  # Add after Paynow integration
                }
            ),
            200,
        )

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("/status/<payment_id>", methods=["GET"])
@jwt_required()
def get_payment_status(payment_id):
    \"\"\"
    Check payment status.
    Customers can only check their own payments.
    
    Returns:
        - 200: Payment status
        - 403: Unauthorized to view this payment
        - 404: Payment not found
        - 500: Server error
    \"\"\"
    try:
        identity = get_jwt_identity()
        user_id = identity["id"]

        supabase = get_supabase()
        response = supabase.table("payments").select("*").eq("id", payment_id).execute()

        if not response.data:
            return jsonify({"error": "Payment not found"}), 404

        payment = response.data[0]

        if payment["customer_id"] != user_id:
            return jsonify({"error": "Unauthorized to view this payment"}), 403

        return (
            jsonify(
                {
                    "payment_id": payment["id"],
                    "order_id": payment["order_id"],
                    "amount": payment["amount"],
                    "payment_method": payment["payment_method"],
                    "status": payment["status"],
                    "created_at": payment["created_at"],
                }
            ),
            200,
        )

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("/webhook", methods=["POST"])
def payment_webhook():
    \"\"\"
    Webhook endpoint for Paynow to send payment status updates.
    Called automatically by Paynow when payment status changes.
    
    Request format (from Paynow):
        - reference (string): Payment reference/ID
        - status (string): Payment status (Paid, Failed, etc.)
        - amount (float): Payment amount
        - timestamp (string): Transaction timestamp
    
    Returns:
        - 200: Webhook processed successfully
        - 400: Missing required fields
        - 500: Server error
    \"\"\"
    try:
        data = request.get_json()

        if not data or not all(k in data for k in ["reference", "status"]):
            return jsonify({"error": "Missing required fields"}), 400

        payment_id = data["reference"]
        payment_status = data["status"].lower()

        # Map Paynow status to our status
        status_mapping = {
            "paid": "completed",
            "failed": "failed",
            "pending": "pending",
            "awaiting delivery": "pending",
        }

        our_status = status_mapping.get(payment_status, payment_status)

        supabase = get_supabase()

        # Update payment status
        response = supabase.table("payments").update(
            {
                "status": our_status,
                "updated_at": datetime.utcnow().isoformat(),
            }
        ).eq("id", payment_id).execute()

        if not response.data:
            return jsonify({"error": "Payment not found"}), 404

        # If payment is completed, update order status
        if our_status == "completed":
            payment = response.data[0]
            order_id = payment["order_id"]

            supabase.table("orders").update(
                {
                    "payment_status": "paid",
                }
            ).eq("id", order_id).execute()

        return jsonify({"message": "Webhook processed successfully"}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("/<order_id>/refund", methods=["POST"])
@jwt_required()
def refund_payment(order_id):
    \"\"\"
    Refund a payment for an order (for cancelled orders).
    Only customers can request refunds for their own orders.
    
    Returns:
        - 200: Refund initiated successfully
        - 403: Unauthorized to refund this payment
        - 404: Order or payment not found
        - 500: Server error
    \"\"\"
    try:
        identity = get_jwt_identity()
        user_id = identity["id"]

        supabase = get_supabase()

        # Verify order exists and belongs to customer
        order_response = supabase.table("orders").select("*").eq("id", order_id).execute()

        if not order_response.data:
            return jsonify({"error": "Order not found"}), 404

        order = order_response.data[0]

        if order["customer_id"] != user_id:
            return jsonify({"error": "Unauthorized to refund this order"}), 403

        # Find associated payment
        payment_response = supabase.table("payments").select("*").eq("order_id", order_id).execute()

        if not payment_response.data:
            return jsonify({"error": "No payment found for this order"}), 404

        payment = payment_response.data[0]

        if payment["status"] != "completed":
            return jsonify({"error": "Can only refund completed payments"}), 400

        # Update payment status to refunded
        refund_response = supabase.table("payments").update(
            {
                "status": "refunded",
                "updated_at": datetime.utcnow().isoformat(),
            }
        ).eq("id", payment["id"]).execute()

        # TODO: Call Paynow refund API
        # Example:
        # paynow = Paynow(...)
        # paynow.refund(payment["id"], payment["amount"])

        return (
            jsonify(
                {
                    "message": "Refund initiated successfully",
                    "payment_id": payment["id"],
                    "refund_status": "pending",
                }
            ),
            200,
        )

    except Exception as e:
        return jsonify({"error": str(e)}), 500
""",
}


def setup():
    """Create all project files."""
    created_count = 0
    failed_count = 0

    print("\\n" + "="*70)
    print("  F DRIVE BACKEND - PROJECT SETUP")
    print("="*70 + "\\n")

    for filepath, content in FILES_CONTENT.items():
        try:
            # Create directory if it doesn't exist
            directory = os.path.dirname(filepath)
            if directory and not os.path.exists(directory):
                os.makedirs(directory)

            # Write file
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(content)

            print(f"  ✓ {filepath}")
            created_count += 1

        except Exception as e:
            print(f"  ✗ {filepath} - Error: {e}")
            failed_count += 1

    print("\\n" + "="*70)
    print(f"  CREATED: {created_count} files")
    if failed_count > 0:
        print(f"  FAILED: {failed_count} files")
    print("="*70 + "\\n")

    if failed_count == 0:
        print("  ✅ Project setup complete!\\n")
        print("  NEXT STEPS:")
        print("  1. Create .env file from .env.example")
        print("  2. pip install -r requirements.txt")
        print("  3. python run.py\\n")
        return True
    return False


if __name__ == "__main__":
    try:
        if setup():
            sys.exit(0)
        else:
            sys.exit(1)
    except KeyboardInterrupt:
        print("\\n\\n  ⚠️  Setup cancelled by user")
        sys.exit(1)
