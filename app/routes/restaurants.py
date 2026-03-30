"""
Restaurants Routes
Handles restaurant listing, details, and status management.
"""

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from app.supabase_client import get_supabase
from datetime import datetime

bp = Blueprint("restaurants", __name__, url_prefix="/api/restaurants")


@bp.route("", methods=["GET"])
def get_restaurants():
    """
    Get all restaurants (public endpoint).
    Optionally filter by status (open/closed).
    
    Query Parameters:
        - status (optional): "open" or "closed"
    
    Returns:
        - 200: List of restaurants
        - 500: Server error
    """
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
    """
    Get restaurant details by ID (public endpoint).
    
    Returns:
        - 200: Restaurant details
        - 404: Restaurant not found
        - 500: Server error
    """
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
    """
    Toggle restaurant open/closed status (restaurant owners only).
    
    Returns:
        - 200: Status toggled successfully
        - 403: Unauthorized to toggle this restaurant's status
        - 404: Restaurant not found
        - 500: Server error
    """
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

        # Authorization check - modern schema uses restaurant id == user_id.
        owner_id = restaurant.get("owner_id")
        if owner_id is not None and owner_id != user_id:
            return jsonify({"error": "Unauthorized to toggle this restaurant's status"}), 403
        if owner_id is None and restaurant.get("id") != user_id:
            return jsonify({"error": "Unauthorized to toggle this restaurant's status"}), 403

        # Support both schemas:
        # - current: is_open (bool)
        # - legacy:  status ("open"/"closed")
        if "is_open" in restaurant:
            current_open = bool(restaurant.get("is_open"))
        else:
            current_open = restaurant.get("status") == "open"
        new_open = not current_open
        new_status = "open" if new_open else "closed"

        update_data = {}
        if "is_open" in restaurant:
            update_data["is_open"] = new_open
        if "status" in restaurant:
            update_data["status"] = new_status

        response = supabase.table("restaurants").update(
            update_data
        ).eq("id", restaurant_id).execute()

        return (
            jsonify(
                {
                    "message": f"Restaurant status toggled to {new_status}",
                    "restaurant_id": restaurant_id,
                    "is_open": new_open,
                    "status": new_status,
                }
            ),
            200,
        )

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("/me/toggle-open", methods=["PATCH"])
@jwt_required()
def toggle_my_restaurant_open():
    """
    Toggle current restaurant's open state using authenticated restaurant ID.
    Compatible endpoint for dashboard clients.
    """
    try:
        identity = get_jwt_identity()
        user_id = identity.get("id")
        role = identity.get("role")

        if role != "restaurant":
            return jsonify({"error": "Only restaurant owners can toggle status"}), 403

        supabase = get_supabase()
        response = supabase.table("restaurants").select("*").eq("id", user_id).execute()

        if not response.data:
            return jsonify({"error": "Restaurant not found"}), 404

        restaurant = response.data[0]
        if "is_open" in restaurant:
            current_open = bool(restaurant.get("is_open"))
        else:
            current_open = restaurant.get("status") == "open"
        new_open = not current_open
        new_status = "open" if new_open else "closed"

        update_data = {}
        if "is_open" in restaurant:
            update_data["is_open"] = new_open
        if "status" in restaurant:
            update_data["status"] = new_status

        supabase.table("restaurants").update(update_data).eq("id", user_id).execute()

        return jsonify(
            {
                "message": f"Restaurant status toggled to {new_status}",
                "restaurant_id": user_id,
                "is_open": new_open,
                "status": new_status,
            }
        ), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("", methods=["POST"])
@jwt_required()
def create_restaurant():
    """
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
    """
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
