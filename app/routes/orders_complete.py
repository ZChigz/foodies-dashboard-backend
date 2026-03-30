"""
F DRIVE - ORDERS ROUTES
Complete order lifecycle management for food delivery platform.

ORDER STATUS FLOW:
    pending_payment → order_received → preparing → picked_up → on_the_way → delivered
    
    pending_payment: Order placed, awaiting payment confirmation
    order_received: Payment received, restaurant notified
    preparing:      Restaurant actively making the food
    picked_up:      Rider collected from restaurant
    on_the_way:     Rider en route to customer
    delivered:      Order delivered to customer

ROLE-BASED STATUS TRANSITIONS:
    - CUSTOMER:     Can only view their orders
    - RESTAURANT:   order_received→preparing, preparing→picked_up
    - RIDER:        picked_up→on_the_way, on_the_way→delivered
    - SYSTEM:       pending_payment→order_received (via payment webhook)
"""

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity, verify_jwt_in_request
from flask_jwt_extended.exceptions import JWTExtendedException
from app.supabase_client import get_supabase
from datetime import datetime

bp = Blueprint("orders", __name__, url_prefix="/api/orders")

# Define valid status transitions by role
STATUS_TRANSITIONS = {
    "restaurant": {
        "order_received": "preparing",
        "preparing": "picked_up",
    },
    "rider": {
        "picked_up": "on_the_way",
        "on_the_way": "delivered",
    },
    "system": {
        "pending_payment": "order_received",
    },
}


@bp.route("", methods=["POST"])
@bp.route("/", methods=["POST"])
@jwt_required()
def create_order():
    """
    Create a new order (customer only).
    
    Requires:
    - Valid JWT token with customer role
    - Request body with order details
    
    Request JSON:
        - restaurant_id (UUID): ID of restaurant
        - items (array): Array of order items with menu_item_id, name, quantity, price
        - delivery_address (string): Delivery location
        - phone (string): Customer contact phone
        - subtotal (float): Sum of item prices
        - payment_method (string): "ecocash" or "card"
    
    Response:
        - 201: Order created successfully, status=pending_payment
        - 400: Missing fields, invalid role, or validation error
        - 403: User is not a customer
        - 500: Server error
    """
    try:
        identity = get_jwt_identity()
        user_id = identity.get("id")
        role = identity.get("role")

        if role != "customer":
            return jsonify({"error": "Only customers can create orders"}), 403

        data = request.get_json(force=True, silent=True)

        if not data:
            return jsonify({"error": "Request body is required"}), 400

        # Validate required fields
        required_fields = ["restaurant_id", "items", "delivery_address", "phone", "subtotal", "payment_method"]
        if not all(field in data for field in required_fields):
            return jsonify({"error": f"Missing required fields: {', '.join(required_fields)}"}), 400

        restaurant_id = data.get("restaurant_id")
        items = data.get("items", [])
        delivery_address = data.get("delivery_address", "").strip()
        phone = data.get("phone", "").strip()
        subtotal = float(data.get("subtotal", 0))
        payment_method = data.get("payment_method", "").lower()

        # Validate items is not empty
        if not items or len(items) == 0:
            return jsonify({"error": "Order must include at least one item"}), 400

        # Validate payment method
        if payment_method not in ["ecocash", "card"]:
            return jsonify({"error": "Payment method must be 'ecocash' or 'card'"}), 400

        # Calculate total: subtotal + 0.50 delivery fee
        delivery_fee = 0.50
        total = subtotal + delivery_fee

        supabase = get_supabase()

        # Verify restaurant exists
        restaurant_check = supabase.table("restaurants").select("id").eq("id", restaurant_id).execute()
        if not restaurant_check.data:
            return jsonify({"error": "Restaurant not found"}), 400

        # Create order
        order_data = {
            "customer_id": user_id,
            "restaurant_id": restaurant_id,
            "rider_id": None,
            "items": items,  # Stored as JSONB snapshot
            "delivery_address": delivery_address,
            "phone": phone,
            "subtotal": subtotal,
            "delivery_fee": delivery_fee,
            "total": total,
            "status": "pending_payment",
            "payment_method": payment_method,
            "paynow_poll_url": None,
            "created_at": datetime.utcnow().isoformat(),
            "picked_up_at": None,
            "delivered_at": None,
        }

        response = supabase.table("orders").insert(order_data).execute()

        if not response.data:
            return jsonify({"error": "Failed to create order"}), 500

        order = response.data[0]

        return (
            jsonify(
                {
                    "message": "Order created successfully",
                    "order_id": order["id"],
                    "status": order["status"],
                    "total": order["total"],
                }
            ),
            201,
        )

    except ValueError as ve:
        return jsonify({"error": f"Invalid numeric value: {str(ve)}"}), 400
    except Exception as e:
        return jsonify({"error": f"Failed to create order: {str(e)}"}), 500


@bp.route("", methods=["GET"])
@bp.route("/", methods=["GET"])
def list_orders():
    """
    List orders filtered by user role (role-based access control).
    
    Requires: Valid JWT token
    
    Response by role:
        - CUSTOMER: Returns their own orders with restaurant details
        - RESTAURANT: Returns orders for their restaurant with customer details
        - RIDER: Returns orders assigned to them with restaurant and customer details
    
    Response:
        - 200: List of orders
        - 400: Invalid role
        - 500: Server error
    """
    try:
        supabase = get_supabase()
        restaurant_id = request.args.get("restaurant_id") or request.args.get("restaurantId")

        # Public filter mode: allow restaurant-specific lookup without requiring JWT.
        if restaurant_id:
            response = (
                supabase.table("orders")
                .select("id, restaurant_id, rider_id, total, status, created_at, picked_up_at, delivered_at")
                .eq("restaurant_id", restaurant_id)
                .order("created_at", desc=True)
                .execute()
            )
            return jsonify({"orders": response.data}), 200

        # Protected mode: no filter requires valid JWT and role-based scope.
        verify_jwt_in_request()
        identity = get_jwt_identity() or {}
        user_id = identity.get("id")
        role = identity.get("role")

        if role == "customer":
            # Customers see their own orders with restaurant info
            response = (
                supabase.table("orders")
                .select("*, restaurants(id, restaurant_name, address, phone)")
                .eq("customer_id", user_id)
                .order("created_at", desc=True)
                .execute()
            )

        elif role == "restaurant":
            # Restaurants see orders for their restaurant with customer info
            response = (
                supabase.table("orders")
                .select("*, customers(id, name, phone, email)")
                .eq("restaurant_id", user_id)
                .order("created_at", desc=True)
                .execute()
            )

        elif role == "rider":
            # Riders see their assigned orders with restaurant and customer info
            response = (
                supabase.table("orders")
                .select(
                    "*, restaurants(id, restaurant_name, address, phone), customers(id, name, phone, email)"
                )
                .eq("rider_id", user_id)
                .order("created_at", desc=True)
                .execute()
            )

        else:
            return jsonify({"error": "Invalid role"}), 400

        return jsonify({"orders": response.data}), 200

    except JWTExtendedException as e:
        return jsonify({"error": f"Unauthorized: {str(e)}"}), 401
    except Exception as e:
        return jsonify({"error": f"Failed to list orders: {str(e)}"}), 500


@bp.route("/<order_id>", methods=["GET"])
@jwt_required()
def get_order(order_id):
    """
    Get full order details with restaurant, customer, and rider information.
    
    Requires: Valid JWT token (user must be customer, restaurant owner, or assigned rider)
    
    Response:
        - 200: Complete order details with joins
        - 403: User not authorized to view this order
        - 404: Order not found
        - 500: Server error
    """
    try:
        identity = get_jwt_identity()
        user_id = identity.get("id")
        role = identity.get("role")

        supabase = get_supabase()

        # Fetch order with all joins
        response = (
            supabase.table("orders")
            .select(
                "*, restaurants(id, restaurant_name, address, phone, rating), "
                "customers(id, name, phone, email), riders(id, name, phone, vehicle_type)"
            )
            .eq("id", order_id)
            .execute()
        )

        if not response.data:
            return jsonify({"error": "Order not found"}), 404

        order = response.data[0]

        # Authorization: User must be customer, restaurant owner, or assigned rider
        if role == "customer" and order["customer_id"] != user_id:
            return jsonify({"error": "Unauthorized to view this order"}), 403
        elif role == "restaurant" and order["restaurant_id"] != user_id:
            return jsonify({"error": "Unauthorized to view this order"}), 403
        elif role == "rider" and order["rider_id"] != user_id:
            return jsonify({"error": "Unauthorized to view this order"}), 403

        return jsonify(order), 200

    except Exception as e:
        return jsonify({"error": f"Failed to retrieve order: {str(e)}"}), 500


@bp.route("/<order_id>/status", methods=["PATCH"])
@jwt_required()
def update_order_status(order_id):
    """
    Update order status with role-based validation.
    
    Requires: Valid JWT token (restaurant or rider based on status transition)
    
    Request JSON:
        - status (string): New status
    
    Valid transitions:
        - RESTAURANT: order_received→preparing, preparing→picked_up
        - RIDER: picked_up→on_the_way, on_the_way→delivered
    
    Records timestamps:
        - picked_up_at: When status becomes "picked_up"
        - delivered_at: When status becomes "delivered"
    
    Response:
        - 200: Status updated successfully
        - 400: Invalid status transition for user role
        - 403: User not authorized for this operation
        - 404: Order not found
        - 500: Server error
    """
    try:
        identity = get_jwt_identity()
        user_id = identity.get("id")
        role = identity.get("role")

        data = request.get_json(force=True, silent=True)

        if not data or "status" not in data:
            return jsonify({"error": "Status field is required"}), 400

        new_status = data.get("status", "").strip().lower()

        supabase = get_supabase()

        # Fetch current order
        response = supabase.table("orders").select("*").eq("id", order_id).execute()

        if not response.data:
            return jsonify({"error": "Order not found"}), 404

        order = response.data[0]
        current_status = order["status"]

        # Validate status transition based on role
        if role == "restaurant":
            if order["restaurant_id"] != user_id:
                return jsonify({"error": "Unauthorized: You do not own this restaurant"}), 403

            if current_status not in STATUS_TRANSITIONS["restaurant"]:
                return jsonify(
                    {
                        "error": f"Invalid transition from '{current_status}'. "
                        f"Restaurant can transition from: {list(STATUS_TRANSITIONS['restaurant'].keys())}"
                    }
                ), 400

            if STATUS_TRANSITIONS["restaurant"][current_status] != new_status:
                return jsonify(
                    {
                        "error": f"Invalid transition: {current_status}→{new_status}. "
                        f"From '{current_status}' can only go to '{STATUS_TRANSITIONS['restaurant'][current_status]}'"
                    }
                ), 400

        elif role == "rider":
            if order["rider_id"] != user_id:
                return jsonify({"error": "Unauthorized: This order is not assigned to you"}), 403

            if current_status not in STATUS_TRANSITIONS["rider"]:
                return jsonify(
                    {
                        "error": f"Invalid transition from '{current_status}'. "
                        f"Rider can transition from: {list(STATUS_TRANSITIONS['rider'].keys())}"
                    }
                ), 400

            if STATUS_TRANSITIONS["rider"][current_status] != new_status:
                return jsonify(
                    {
                        "error": f"Invalid transition: {current_status}→{new_status}. "
                        f"From '{current_status}' can only go to '{STATUS_TRANSITIONS['rider'][current_status]}'"
                    }
                ), 400

        else:
            return jsonify({"error": "Only restaurants and riders can update order status"}), 403

        # Prepare update data
        update_data = {
            "status": new_status,
        }

        # Record timestamps for specific status changes
        if new_status == "picked_up":
            update_data["picked_up_at"] = datetime.utcnow().isoformat()
        elif new_status == "delivered":
            update_data["delivered_at"] = datetime.utcnow().isoformat()

        # Update order
        response = supabase.table("orders").update(update_data).eq("id", order_id).execute()

        if not response.data:
            return jsonify({"error": "Failed to update order status"}), 500

        updated_order = response.data[0]

        return (
            jsonify(
                {
                    "message": f"Order status updated to '{new_status}'",
                    "order_id": order_id,
                    "status": updated_order["status"],
                    "picked_up_at": updated_order.get("picked_up_at"),
                    "delivered_at": updated_order.get("delivered_at"),
                }
            ),
            200,
        )

    except Exception as e:
        return jsonify({"error": f"Failed to update order status: {str(e)}"}), 500


@bp.route("/available/for-riders", methods=["GET"])
@jwt_required()
def get_available_orders_for_riders():
    """
    Get all orders ready for pickup (status=picked_up, no rider assigned).
    For riders to see available delivery jobs.
    
    Requires: Valid JWT token (rider only)
    
    Includes restaurant details for navigation:
        - restaurant_name
        - address
        - phone
    
    Response:
        - 200: List of available orders
        - 403: User is not a rider
        - 500: Server error
    """
    try:
        identity = get_jwt_identity()
        role = identity.get("role")

        if role != "rider":
            return jsonify({"error": "Only riders can view available orders"}), 403

        supabase = get_supabase()

        # Get orders with status=picked_up and no rider assigned
        response = (
            supabase.table("orders")
            .select("*, restaurants(id, restaurant_name, address, phone), customers(id, name, phone)")
            .eq("status", "picked_up")
            .is_("rider_id", "null")
            .order("created_at", desc=True)
            .execute()
        )

        return jsonify({"available_orders": response.data}), 200

    except Exception as e:
        return jsonify({"error": f"Failed to retrieve available orders: {str(e)}"}), 500


@bp.route("/<order_id>/assign-rider", methods=["POST"])
@jwt_required()
def assign_rider_to_order(order_id):
    """
    Assign a rider to an order and set their availability to offline.
    
    Requires:
        - Valid JWT token (rider only)
        - Order must have status=picked_up
        - Order must not already have a rider assigned
    
    Process:
        1. Set rider_id on the order
        2. Set rider's is_available=False
    
    Response:
        - 200: Rider assigned successfully
        - 400: Invalid order status or rider already assigned
        - 403: User is not a rider
        - 404: Order or rider not found
        - 500: Server error
    """
    try:
        identity = get_jwt_identity()
        user_id = identity.get("id")
        role = identity.get("role")

        if role != "rider":
            return jsonify({"error": "Only riders can accept deliveries"}), 403

        supabase = get_supabase()

        # Fetch order
        order_response = supabase.table("orders").select("*").eq("id", order_id).execute()

        if not order_response.data:
            return jsonify({"error": "Order not found"}), 404

        order = order_response.data[0]

        # Validate order status
        if order["status"] != "picked_up":
            return jsonify(
                {
                    "error": f"Order must have status 'picked_up' to accept. Current status: '{order['status']}'"
                }
            ), 400

        # Validate no rider already assigned
        if order["rider_id"] is not None:
            return jsonify({"error": "This order already has a rider assigned"}), 400

        # Verify rider exists
        rider_check = supabase.table("riders").select("*").eq("id", user_id).execute()
        if not rider_check.data:
            return jsonify({"error": "Rider profile not found"}), 404

        # Update order with rider assignment
        supabase.table("orders").update(
            {
                "rider_id": user_id,
            }
        ).eq("id", order_id).execute()

        # Set rider's availability to offline (not available for new orders)
        supabase.table("riders").update({"is_available": False}).eq("id", user_id).execute()

        return (
            jsonify(
                {
                    "message": "Order assigned to rider successfully",
                    "order_id": order_id,
                    "rider_id": user_id,
                    "status": "picked_up",
                }
            ),
            200,
        )

    except Exception as e:
        return jsonify({"error": f"Failed to assign rider: {str(e)}"}), 500
