"""
F DRIVE - AUTHENTICATION ROUTES
Handles user registration, login, and profile retrieval for three user roles:
- customer: Food ordering customers
- rider: Delivery personnel
- restaurant: Restaurant owners/managers

JWT tokens include role information for role-based access control.
"""

from flask import Blueprint, request, jsonify
from flask_jwt_extended import create_access_token, jwt_required, get_jwt_identity
from app.supabase_client import get_supabase
import os

# Create Blueprint for authentication routes
bp = Blueprint("auth", __name__, url_prefix="/api/auth")


@bp.route("/register", methods=["POST"])
def register():
    """
    Register a new user and create their profile.
    
    Accepts three user roles:
    - customer: email, password, name, phone
    - rider: email, password, name, phone, vehicle_type
    - restaurant: email, password, name, phone, restaurant_name, address
    
    Process:
    1. Validate all required fields for the role
    2. Create user in Supabase Auth (sb.auth.sign_up())
    3. Create profile record in the appropriate table (customers, riders, restaurants)
    4. Generate JWT token with user ID and role
    
    Returns:
    - 201: Registration successful with JWT token
    - 400: Missing required fields or invalid role
    - 409: Email already exists
    - 500: Server error during registration
    """
    try:
        data = request.get_json()

        # Validate that we have JSON data
        if not data:
            return jsonify({"error": "Request body is required"}), 400

        # Extract common fields
        email = data.get("email", "").strip()
        password = data.get("password", "").strip()
        name = data.get("name", "").strip()
        phone = data.get("phone", "").strip()
        role = data.get("role", "").strip().lower()

        # Validate common fields
        if not all([email, password, name, phone, role]):
            return jsonify(
                {"error": "Missing required fields: email, password, name, phone, role"}
            ), 400

        # Validate role
        if role not in ["customer", "rider", "restaurant"]:
            return jsonify(
                {"error": "Invalid role. Must be 'customer', 'rider', or 'restaurant'"}
            ), 400

        # Role-specific validation
        if role == "rider":
            vehicle_type = data.get("vehicle_type", "").strip()
            if not vehicle_type:
                return jsonify({"error": "Riders must provide vehicle_type"}), 400

        if role == "restaurant":
            restaurant_name = data.get("restaurant_name", "").strip()
            address = data.get("address", "").strip()
            if not all([restaurant_name, address]):
                return jsonify(
                    {"error": "Restaurants must provide restaurant_name and address"}
                ), 400

        # Get Supabase client
        supabase = get_supabase()

        # 1. Create user in Supabase Auth
        try:
            auth_response = supabase.auth.sign_up(
                {"email": email, "password": password}
            )
        except Exception as auth_error:
            error_msg = str(auth_error)
            if "already registered" in error_msg.lower():
                return jsonify({"error": "Email already registered"}), 409
            return jsonify({"error": f"Authentication error: {error_msg}"}), 500

        user_id = auth_response.user.id

        # 2. Create profile record in appropriate table based on role
        try:
            if role == "customer":
                profile_data = {
                    "id": user_id,
                    "name": name,
                    "email": email,
                    "phone": phone,
                    "avatar_url": None,
                }
                supabase.table("customers").insert(profile_data).execute()

            elif role == "rider":
                profile_data = {
                    "id": user_id,
                    "name": name,
                    "email": email,
                    "phone": phone,
                    "vehicle_type": data["vehicle_type"],
                    "vehicle_plate": data.get("vehicle_plate"),
                    "avatar_url": None,
                    "is_available": False,
                    "rating": 0,
                    "total_deliveries": 0,
                }
                supabase.table("riders").insert(profile_data).execute()

            elif role == "restaurant":
                profile_data = {
                    "id": user_id,
                    "restaurant_name": data["restaurant_name"],
                    "email": email,
                    "phone": phone,
                    "address": data["address"],
                    "image_url": None,
                    "is_open": True,
                    "rating": 0,
                    "delivery_fee": 0,
                    "avg_time": "30 mins",
                }
                supabase.table("restaurants").insert(profile_data).execute()

        except Exception as profile_error:
            # If profile creation fails, attempt to delete the auth user
            try:
                supabase.auth.admin.delete_user(user_id)
            except:
                pass
            return (
                jsonify(
                    {"error": f"Failed to create profile: {str(profile_error)}"}
                ),
                500,
            )

        # 3. Generate JWT token with role information
        jwt_identity = {"id": user_id, "role": role}
        access_token = create_access_token(identity=jwt_identity)

        # Return success response
        return (
            jsonify(
                {
                    "message": "Registration successful",
                    "user_id": user_id,
                    "email": email,
                    "role": role,
                    "access_token": access_token,
                }
            ),
            201,
        )

    except Exception as e:
        return jsonify({"error": f"Registration failed: {str(e)}"}), 500


@bp.route("/login", methods=["POST"])
def login():
    """
    Authenticate a user and return JWT token with their profile.
    
    Accepts:
    - email: User email address
    - password: User password
    - role: Expected role (customer, rider, or restaurant)
    
    Process:
    1. Sign in user with Supabase Auth (sb.auth.sign_in_with_password())
    2. Verify user has a profile in the correct role table
    3. Fetch complete profile data
    4. Generate JWT token with user ID and role
    
    Returns:
    - 200: Login successful with JWT token and profile
    - 400: Missing email, password, or role
    - 401: Invalid credentials
    - 403: User exists but not in the specified role table
    - 500: Server error during login
    """
    try:
        data = request.get_json()

        # Validate request data
        if not data:
            return jsonify({"error": "Request body is required"}), 400

        email = data.get("email", "").strip()
        password = data.get("password", "").strip()
        role = data.get("role", "").strip().lower()

        # Validate required fields
        if not all([email, password, role]):
            return jsonify({"error": "Missing required fields: email, password, role"}), 400

        # Validate role
        if role not in ["customer", "rider", "restaurant"]:
            return jsonify(
                {"error": "Invalid role. Must be 'customer', 'rider', or 'restaurant'"}
            ), 400

        # Get Supabase client
        supabase = get_supabase()

        # 1. Sign in user with Supabase Auth
        try:
            auth_response = supabase.auth.sign_in_with_password(
                {"email": email, "password": password}
            )
        except Exception as auth_error:
            error_msg = str(auth_error).lower()
            if "invalid login credentials" in error_msg:
                return jsonify({"error": "Invalid email or password"}), 401
            if "user not confirmed" in error_msg:
                return jsonify({"error": "Please confirm your email"}), 401
            return jsonify({"error": "Authentication failed"}), 401

        user_id = auth_response.user.id

        # 2. Verify user has profile in the correct role table
        try:
            if role == "customer":
                profile_response = (
                    supabase.table("customers")
                    .select("*")
                    .eq("id", user_id)
                    .execute()
                )
            elif role == "rider":
                profile_response = (
                    supabase.table("riders")
                    .select("*")
                    .eq("id", user_id)
                    .execute()
                )
            elif role == "restaurant":
                profile_response = (
                    supabase.table("restaurants")
                    .select("*")
                    .eq("id", user_id)
                    .execute()
                )

            # Check if profile exists
            if not profile_response.data or len(profile_response.data) == 0:
                return (
                    jsonify(
                        {
                            "error": f"User is not registered as a {role}. Please register with the correct role."
                        }
                    ),
                    403,
                )

            profile = profile_response.data[0]

        except Exception as profile_error:
            return (
                jsonify({"error": f"Failed to retrieve profile: {str(profile_error)}"}),
                500,
            )

        # 3. Generate JWT token with role information
        jwt_identity = {"id": user_id, "role": role}
        access_token = create_access_token(identity=jwt_identity)

        # Return success response with profile
        return (
            jsonify(
                {
                    "message": "Login successful",
                    "user_id": user_id,
                    "email": email,
                    "role": role,
                    "access_token": access_token,
                    "profile": profile,
                }
            ),
            200,
        )

    except Exception as e:
        return jsonify({"error": f"Login failed: {str(e)}"}), 500


@bp.route("/me", methods=["GET"])
@jwt_required()
def get_me():
    """
    Get current authenticated user's complete profile.
    
    Requires:
    - Valid JWT token in Authorization header (Bearer <token>)
    
    Process:
    1. Extract user ID and role from JWT identity
    2. Query the appropriate profile table based on role
    3. Return user's profile data
    
    Returns:
    - 200: User profile data
    - 401: No JWT token or invalid token
    - 404: User profile not found
    - 500: Server error retrieving profile
    """
    try:
        # Extract identity from JWT token
        identity = get_jwt_identity()
        user_id = identity.get("id")
        role = identity.get("role")

        # Validate identity data
        if not user_id or not role:
            return jsonify({"error": "Invalid token identity"}), 401

        # Get Supabase client
        supabase = get_supabase()

        # Fetch profile from appropriate table based on role
        try:
            if role == "customer":
                response = (
                    supabase.table("customers")
                    .select("*")
                    .eq("id", user_id)
                    .execute()
                )
            elif role == "rider":
                response = (
                    supabase.table("riders")
                    .select("*")
                    .eq("id", user_id)
                    .execute()
                )
            elif role == "restaurant":
                response = (
                    supabase.table("restaurants")
                    .select("*")
                    .eq("id", user_id)
                    .execute()
                )
            else:
                return jsonify({"error": "Invalid role in token"}), 401

            # Check if profile exists
            if not response.data or len(response.data) == 0:
                return jsonify({"error": "User profile not found"}), 404

            profile = response.data[0]

        except Exception as query_error:
            return (
                jsonify(
                    {"error": f"Failed to retrieve profile: {str(query_error)}"}
                ),
                500,
            )

        # Return user profile with role information
        return jsonify({"user_id": user_id, "role": role, "profile": profile}), 200

    except Exception as e:
        return jsonify({"error": f"Failed to get user profile: {str(e)}"}), 500
