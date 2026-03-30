"""
Payments Routes
Handles F Drive payment methods:
- EcoCash (Paynow mobile money)
- OneMoney (Paynow mobile money)
- Card (Paynow redirect)
- Cash on Delivery (no gateway processing)
"""

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from app.supabase_client import get_supabase
import os
from datetime import datetime

try:
    from paynow import Paynow
except ImportError:
    Paynow = None

bp = Blueprint("payments", __name__, url_prefix="/api/payments")


@bp.route("/initiate", methods=["POST"])
@jwt_required()
def initiate_payment():
    """
    Initiate payment for an order.
    Supports: ecocash, onemoney, card, cash.
    
    Request JSON:
        - order_id (string): Order ID to pay for
        - amount (float): Payment amount in ZWL
        - payment_method (string): "ecocash" | "onemoney" | "card" | "cash"
        - phone (string): Required for ecocash and onemoney
    
    Returns:
        - 200: Payment initiated successfully
        - 400: Missing required fields, invalid payment method, or missing phone for mobile money
        - 404: Order not found
        - 500: Server error
    """
    try:
        identity = get_jwt_identity()
        user_id = identity["id"]

        data = request.get_json()

        if not data or not all(k in data for k in ["order_id", "amount", "payment_method"]):
            return jsonify({"error": "Missing required fields: order_id, amount, payment_method"}), 400

        order_id = data["order_id"]
        amount = float(data["amount"])
        payment_method = str(data["payment_method"]).strip().lower()
        phone = str(data.get("phone", "")).strip()

        valid_methods = ["ecocash", "onemoney", "card", "cash"]
        if payment_method not in valid_methods:
            return jsonify(
                {
                    "error": "Invalid payment method. Must be one of: 'ecocash', 'onemoney', 'card', 'cash'"
                }
            ), 400

        if payment_method in ["ecocash", "onemoney"] and not phone:
            return jsonify(
                {"error": "Phone number is required for mobile money payments (ecocash or onemoney)"}
            ), 400

        # Verify order exists and belongs to customer
        supabase = get_supabase()
        order_response = supabase.table("orders").select("*").eq("id", order_id).execute()

        if not order_response.data:
            return jsonify({"error": "Order not found"}), 404

        order = order_response.data[0]

        if order["customer_id"] != user_id:
            return jsonify({"error": "Unauthorized to pay for this order"}), 403

        # Cash on Delivery flow: do not call Paynow, move order directly to order_received.
        if payment_method == "cash":
            supabase.table("orders").update(
                {
                    "status": "order_received",
                }
            ).eq("id", order_id).execute()

            return jsonify({"ok": True, "method": "cash", "order_id": order_id, "status": "order_received"}), 200

        # For gateway methods, persist a payment row before attempting Paynow.
        payment_response = supabase.table("payments").insert(
            {
                "order_id": order_id,
                "customer_id": user_id,
                "amount": amount,
                "payment_method": payment_method,
                "phone": phone if phone else None,
                "status": "pending",
                "created_at": datetime.utcnow().isoformat(),
            }
        ).execute()

        if not payment_response.data:
            return jsonify({"error": "Failed to create payment record"}), 500

        payment_row = payment_response.data[0]
        payment_id = payment_row["id"]

        if Paynow is None:
            return jsonify({"error": "Paynow SDK is not installed"}), 500

        paynow = Paynow(
            os.getenv("PAYNOW_INTEGRATION_ID"),
            os.getenv("PAYNOW_INTEGRATION_KEY"),
            os.getenv("PAYNOW_RETURN_URL", "http://localhost:3000/payment/return"),
            os.getenv("PAYNOW_RESULT_URL", "http://localhost:5000/api/payments/webhook"),
        )

        # Build Paynow payment object used by both mobile money and card flows.
        paynow_payment = paynow.create_payment(f"order-{order_id}", f"order-{order_id}@fdrive.local")
        paynow_payment.add(f"Order {order_id}", amount)

        # EcoCash flow: mobile wallet push via Paynow send_mobile(..., 'ecocash').
        if payment_method == "ecocash":
            paynow_response = paynow.send_mobile(paynow_payment, phone, "ecocash")

        # OneMoney flow: mobile wallet push via Paynow send_mobile(..., 'onemoney').
        elif payment_method == "onemoney":
            paynow_response = paynow.send_mobile(paynow_payment, phone, "onemoney")

        # Card flow: redirect-based checkout via Paynow send(payment).
        elif payment_method == "card":
            paynow_response = paynow.send(paynow_payment)

        else:
            return jsonify({"error": "Unsupported payment method"}), 400

        if not getattr(paynow_response, "success", False):
            supabase.table("payments").update(
                {
                    "status": "failed",
                    "updated_at": datetime.utcnow().isoformat(),
                }
            ).eq("id", payment_id).execute()
            return jsonify({"error": "Failed to initiate payment with Paynow"}), 500

        poll_url = getattr(paynow_response, "poll_url", None)
        redirect_url = getattr(paynow_response, "redirect_url", None)

        supabase.table("payments").update(
            {
                "status": "pending",
                "updated_at": datetime.utcnow().isoformat(),
            }
        ).eq("id", payment_id).execute()

        supabase.table("orders").update(
            {
                "paynow_poll_url": poll_url,
            }
        ).eq("id", order_id).execute()

        response_payload = {
            "ok": True,
            "payment_id": payment_id,
            "order_id": order_id,
            "method": payment_method,
            "status": "pending",
        }

        if redirect_url:
            response_payload["redirect_url"] = redirect_url

        return jsonify(response_payload), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("/status/<payment_id>", methods=["GET"])
@jwt_required()
def get_payment_status(payment_id):
    """
    Check payment status.
    Customers can only check their own payments.
    
    Returns:
        - 200: Payment status
        - 403: Unauthorized to view this payment
        - 404: Payment not found
        - 500: Server error
    """
    try:
        identity = get_jwt_identity()
        user_id = identity["id"]

        supabase = get_supabase()

        # Client may send either a payment_id or an order_id.
        response = supabase.table("payments").select("*").eq("id", payment_id).execute()
        if not response.data:
            response = supabase.table("payments").select("*").eq("order_id", payment_id).execute()

        if not response.data:
            # Graceful response for pending/no-payment-yet flows.
            return jsonify({"payment_id": None, "order_id": payment_id, "status": "pending"}), 200

        payment = response.data[0]

        if payment.get("customer_id") and payment["customer_id"] != user_id:
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
    """
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
    """
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

        # If payment is completed, move order into restaurant workflow
        if our_status == "completed":
            payment = response.data[0]
            order_id = payment["order_id"]

            supabase.table("orders").update(
                {
                    "status": "order_received",
                }
            ).eq("id", order_id).execute()

        return jsonify({"message": "Webhook processed successfully"}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("/<order_id>/refund", methods=["POST"])
@jwt_required()
def refund_payment(order_id):
    """
    Refund a payment for an order (for cancelled orders).
    Only customers can request refunds for their own orders.
    
    Returns:
        - 200: Refund initiated successfully
        - 403: Unauthorized to refund this payment
        - 404: Order or payment not found
        - 500: Server error
    """
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
