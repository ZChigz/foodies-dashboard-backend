"""
Riders Routes
Handles rider availability status and real-time GPS location tracking.
"""

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from app.supabase_client import get_supabase
from datetime import datetime

bp = Blueprint("riders", __name__, url_prefix="/api/riders")


@bp.route("", methods=["GET"])
def list_all_riders():
    """
    Get all riders (public endpoint).
    
    Returns:
        - 200: List of all riders
        - 500: Server error
    """
    try:
        supabase = get_supabase()
        response = supabase.table("riders").select("*").execute()

        return jsonify({"riders": response.data}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("/availability", methods=["PATCH"])
@jwt_required()
def toggle_availability():
    """
    Toggle rider availability (online/offline).
    Riders can only update their own availability.
    
    Request JSON:
        - available (boolean): Availability status
    
    Returns:
        - 200: Availability updated successfully
        - 400: Invalid role or missing data
        - 500: Server error
    """
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
@bp.route("/me/location", methods=["POST"])
@jwt_required()
def broadcast_location():
    """
    Broadcast rider GPS location (real-time tracking).
    Typically called frequently (every 30 seconds or on movement).
    
    Request JSON:
        - latitude (float): Latitude coordinate
        - longitude (float): Longitude coordinate
    
    Returns:
        - 200: Location updated successfully
        - 400: Invalid role or missing coordinates
        - 500: Server error
    """
    try:
        identity = get_jwt_identity()
        user_id = identity["id"]
        role = identity["role"]

        if role != "rider":
            return jsonify({"error": "Only riders can broadcast location"}), 400

        data = request.get_json()

        # Called by Rider App every 15 seconds (Spec Section 8.3 requirement)
        # Do NOT call more frequently - conserves data on Zimbabwean mobile networks

        if not data:
            return jsonify({"error": "Missing request body"}), 400

        latitude = data.get("latitude", data.get("lat"))
        longitude = data.get("longitude", data.get("lng"))

        if latitude is None or longitude is None:
            return jsonify({"error": "Missing required fields: latitude/longitude or lat/lng"}), 400

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
                "lat": latitude,
                "lng": longitude,
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


@bp.route("/active", methods=["GET"])
@jwt_required()
def get_active_riders():
    """
    Get riders currently on an active delivery.
    Active delivery statuses: picked_up, on_the_way.

    Returns:
        - 200: List of active riders
        - 500: Server error
    """
    try:
        supabase = get_supabase()

        active_orders = (
            supabase.table("orders")
            .select("rider_id")
            .in_("status", ["picked_up", "on_the_way"])
            .execute()
        )

        rider_ids = sorted({row.get("rider_id") for row in (active_orders.data or []) if row.get("rider_id")})

        if not rider_ids:
            return jsonify({"riders": []}), 200

        riders = (
            supabase.table("riders")
            .select("*")
            .in_("id", rider_ids)
            .execute()
        )

        return jsonify({"riders": riders.data or []}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("/location/<rider_id>", methods=["GET"])
@jwt_required()
def get_rider_location(rider_id):
    """
    Get rider's current location (for tracking deliveries).
    Authorization: Only customers with active orders from this rider,
    or the rider themselves can view the location.
    
    Returns:
        - 200: Rider location data
        - 403: Unauthorized to view this location
        - 404: Rider location not found
        - 500: Server error
    """
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
    """
    Get all available riders (public endpoint for dispatcher/matching system).
    
    Query Parameters:
        - city (optional): Filter by city
    
    Returns:
        - 200: List of available riders
        - 500: Server error
    """
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
