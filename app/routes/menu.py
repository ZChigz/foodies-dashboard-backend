"""
Menu Routes
Handles menu item management (GET, POST, PATCH, DELETE).
"""

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from app.supabase_client import get_supabase
from datetime import datetime

bp = Blueprint("menu", __name__, url_prefix="/api/menu")


@bp.route("", methods=["GET"])
def list_all_menu_items():
    """
    Get all menu items from all restaurants (public endpoint).
    
    Returns:
        - 200: List of all menu items
        - 500: Server error
    """
    try:
        supabase = get_supabase()
        response = supabase.table("menu_items").select("*").execute()

        return jsonify({"items": response.data}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("/<restaurant_id>", methods=["GET"])
def get_menu_items(restaurant_id):
    """
    Get all menu items for a restaurant (public endpoint).
    
    Returns:
        - 200: List of menu items
        - 500: Server error
    """
    try:
        supabase = get_supabase()
        response = supabase.table("menu_items").select("*").eq("restaurant_id", restaurant_id).execute()

        return jsonify({"items": response.data}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("", methods=["POST"])
@jwt_required()
def create_menu_item():
    """
    Create a new menu item (restaurants only).
    
    Request JSON:
        - name (string): Item name
        - description (string): Item description
        - price (float): Item price
        - category (string): Item category (e.g., "appetizer", "main", "dessert")
        - image_url (string): URL to item image
        - is_available (boolean): Is item available (or available for backward compatibility)
    
    Returns:
        - 201: Menu item created successfully
        - 400: Missing required fields or invalid role
        - 500: Server error
    """
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
                "is_available": data.get("is_available", data.get("available", True)),
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
    """
    Get a specific menu item by ID (public endpoint).
    
    Returns:
        - 200: Menu item details
        - 404: Menu item not found
        - 500: Server error
    """
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
    """
    Update a menu item (restaurants can only update their own items).
    Can update: name, description, price, category, image_url, is_available
    
    Request JSON:
        - name, description, price, category, image_url, is_available, or available (any combination)
    
    Returns:
        - 200: Menu item updated successfully
        - 403: Unauthorized to update this item
        - 404: Menu item not found
        - 500: Server error
    """
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
        for field in ["name", "description", "price", "category", "image_url", "is_available"]:
            if field in data:
                update_data[field] = data[field]

        # Backward compatibility for clients still sending "available"
        if "available" in data and "is_available" not in update_data:
            update_data["is_available"] = data["available"]

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
    """
    Delete a menu item (restaurants can only delete their own items).
    
    Returns:
        - 200: Menu item deleted successfully
        - 403: Unauthorized to delete this item
        - 404: Menu item not found
        - 500: Server error
    """
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
