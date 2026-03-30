"""
F DRIVE - AUTHENTICATION ROUTES
Handles user registration, login, and profile retrieval for three user roles:
- customer: Food ordering customers
- rider: Delivery personnel
- restaurant: Restaurant owners/managers
- admin: Platform owner/admin user

JWT tokens include role information for role-based access control.
"""

from flask import Blueprint, request, jsonify
from flask_jwt_extended import create_access_token, jwt_required, get_jwt_identity
from app.supabase_client import get_supabase
import os

# Create Blueprint for authentication routes
bp = Blueprint("auth", __name__, url_prefix="/api/auth")


def _get_admin_emails():
    """Return normalized admin emails from ADMIN_EMAILS env var."""
    raw = os.getenv("ADMIN_EMAILS", "")
    return {email.strip().lower() for email in raw.split(",") if email.strip()}


def _is_admin_email(email):
    return str(email or "").strip().lower() in _get_admin_emails()


def _is_mvp_admin_login(email, password):
    """Simple MVP admin credential fallback."""
    allow_mvp = os.getenv("ALLOW_MVP_ADMIN_LOGIN", "true").strip().lower() == "true"
    mvp_user = os.getenv("MVP_ADMIN_USERNAME", "admin").strip()
    mvp_pass = os.getenv("MVP_ADMIN_PASSWORD", "admin").strip()
    return allow_mvp and str(email).strip() == mvp_user and str(password).strip() == mvp_pass


def _find_admin_profile(supabase, user_id=None, email=None):
    """
    Find admin profile from configured admin tables.
    Tries tables from ADMIN_TABLES env var, defaulting to overall_admin,admins,admin_users.
    """
    tables_raw = os.getenv("ADMIN_TABLES", "overall_admin,admins,admin_users")
    tables = [t.strip() for t in tables_raw.split(",") if t.strip()]

    for table in tables:
        try:
            if user_id:
                by_id = supabase.table(table).select("*").eq("id", user_id).limit(1).execute()
                if by_id.data:
                    return by_id.data[0], table

            if email:
                by_email = supabase.table(table).select("*").eq("email", email).limit(1).execute()
                if by_email.data:
                    return by_email.data[0], table
        except Exception:
            continue

    return None, None


def _find_admin_by_credentials(supabase, login_value, password_value):
    """
    MVP fallback: authenticate directly from admin table credentials.
    Useful when admin rows exist in DB but not in Supabase auth.users.
    """
    tables_raw = os.getenv("ADMIN_TABLES", "overall_admin,admins,admin_users")
    login_cols_raw = os.getenv("ADMIN_LOGIN_COLUMNS", "email,username,phone")
    pass_cols_raw = os.getenv("ADMIN_PASSWORD_COLUMNS", "password,pass")

    tables = [t.strip() for t in tables_raw.split(",") if t.strip()]
    login_cols = [c.strip() for c in login_cols_raw.split(",") if c.strip()]
    pass_cols = [c.strip() for c in pass_cols_raw.split(",") if c.strip()]

    for table in tables:
        for login_col in login_cols:
            for pass_col in pass_cols:
                try:
                    response = (
                        supabase.table(table)
                        .select("*")
                        .eq(login_col, login_value)
                        .eq(pass_col, password_value)
                        .limit(1)
                        .execute()
                    )
                    if response.data:
                        return response.data[0], table
                except Exception:
                    continue

    return None, None


def _find_user_by_phone(phone):
    """
    Resolve app users by phone for OTP login.
    OTP login is only for customer and rider apps.
    """
    supabase = get_supabase()

    customer = (
        supabase.table("customers")
        .select("id")
        .eq("phone", phone)
        .limit(1)
        .execute()
    )
    if customer.data:
        return {"id": customer.data[0]["id"], "role": "customer"}

    rider = (
        supabase.table("riders")
        .select("id")
        .eq("phone", phone)
        .limit(1)
        .execute()
    )
    if rider.data:
        return {"id": rider.data[0]["id"], "role": "rider"}

    return None


@bp.route("/register", methods=["POST"])
def register():
    """
    Register a new user and create their profile.
    
    Accepts user roles:
    - customer: email, password, name, phone
    - rider: email, password, name, phone, vehicle_type
    - restaurant: email, password, name, phone, restaurant_name, address
    - admin: email, password, name, phone
    
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
        # Accept JSON with or without Content-Type header
        data = request.get_json(force=True, silent=True)

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
        if role not in ["customer", "rider", "restaurant", "admin"]:
            return jsonify(
                {"error": "Invalid role. Must be 'customer', 'rider', 'restaurant', or 'admin'"}
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
            print(f"DEBUG: auth_response = {auth_response}")
            print(f"DEBUG: auth_response type = {type(auth_response)}")
        except Exception as auth_error:
            print(f"DEBUG: auth_error = {auth_error}")
            error_msg = str(auth_error).lower()
            if "already registered" in error_msg:
                return jsonify({"error": "Email already registered"}), 409
            if "rate limit" in error_msg:
                return jsonify({"error": "Too many registration attempts. Please try again in 15 minutes."}), 429
            return jsonify({"error": f"Authentication error: {str(auth_error)}"}), 500

        try:
            user_id = auth_response.user.id
        except Exception as user_error:
            print(f"DEBUG: user_error = {user_error}")
            print(f"DEBUG: auth_response.user = {getattr(auth_response, 'user', 'NO USER ATTR')}")
            return jsonify({"error": f"Failed to get user ID: {str(user_error)}"}), 500

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
    Authenticate a user directly with Supabase Auth.

    Accepts:
    - email: User email address
    - password: User password

    Process:
    1. Sign in with Supabase Auth (sb.auth.sign_in_with_password())
    2. Return Supabase access token and basic user info

    Returns:
    - 200: access_token, user_id, email
    - 400: Missing email or password
    - 401: Invalid credentials / unconfirmed user
    - 500: Server error during login
    """
    try:
        # Accept JSON with or without Content-Type header
        data = request.get_json(force=True, silent=True)

        # Validate request data
        if not data:
            return jsonify({"error": "Request body is required"}), 400

        email = data.get("email", "").strip()
        password = data.get("password", "").strip()
        # Validate required fields
        if not all([email, password]):
            return jsonify({"error": "Missing required fields: email, password"}), 400

        # MVP fallback login for platform owner dashboard.
        if _is_mvp_admin_login(email, password):
            access_token = create_access_token(identity={"id": "mvp-admin", "role": "admin"})
            return (
                jsonify(
                    {
                        "access_token": access_token,
                        "token": access_token,
                        "user_id": "mvp-admin",
                        "id": "mvp-admin",
                        "email": email,
                        "role": "admin",
                    }
                ),
                200,
            )

        # Get Supabase client
        supabase = get_supabase()

        # 1. Sign in user with Supabase Auth
        try:
            auth_response = supabase.auth.sign_in_with_password(
                {"email": email, "password": password}
            )
        except Exception as auth_error:
            error_msg = str(auth_error).lower()
            admin_row, admin_table = _find_admin_by_credentials(supabase, email, password)
            if admin_row:
                admin_id = str(admin_row.get("id") or f"admin-{email}")
                access_token = create_access_token(identity={"id": admin_id, "role": "admin"})
                return (
                    jsonify(
                        {
                            "access_token": access_token,
                            "token": access_token,
                            "user_id": admin_id,
                            "id": admin_id,
                            "email": admin_row.get("email", email),
                            "role": "admin",
                            "admin_source": admin_table,
                        }
                    ),
                    200,
                )

            if "invalid login credentials" in error_msg:
                return jsonify({"error": "Invalid email or password"}), 401
            if "user not confirmed" in error_msg:
                return jsonify({"error": "Please confirm your email"}), 401
            return jsonify({"error": f"Authentication failed: {str(auth_error)}"}), 401

        if not auth_response.user or not auth_response.session:
            return jsonify({"error": "Authentication failed: empty Supabase session"}), 401

        user_id = auth_response.user.id
        user_email = auth_response.user.email

        role = None
        rider_profile = None
        admin_profile, admin_table = _find_admin_profile(supabase, user_id=user_id, email=user_email)

        # Prefer real admin table profile if present.
        if admin_profile:
            role = "admin"
        # Admins can also be controlled via ADMIN_EMAILS env var for the platform owner dashboard.
        elif _is_admin_email(user_email):
            role = "admin"
        elif (
            supabase.table("restaurants").select("id").eq("id", user_id).limit(1).execute().data
        ):
            role = "restaurant"
        elif (
            supabase.table("riders").select("id, is_approved").eq("id", user_id).limit(1).execute().data
        ):
            rider_profile = (
                supabase.table("riders").select("id, is_approved").eq("id", user_id).limit(1).execute().data[0]
            )
            role = "rider"
        elif (
            supabase.table("customers").select("id").eq("id", user_id).limit(1).execute().data
        ):
            role = "customer"

        if not role:
            return jsonify({"error": "User profile not found"}), 404

        if role == "rider" and not (rider_profile or {}).get("is_approved", False):
            return jsonify(
                {
                    "error": "Your rider account is pending admin approval. Please wait for confirmation."
                }
            ), 403

        # Keep backend JWT for protected Flask routes while using Supabase auth for credential validation.
        jwt_identity = {"id": user_id, "role": role}
        access_token = create_access_token(identity=jwt_identity)

        # Return success response
        return (
            jsonify(
                {
                    "access_token": access_token,
                    "token": access_token,
                    "user_id": user_id,
                    "id": user_id,
                    "email": user_email,
                    "role": role,
                    "admin_source": admin_table if role == "admin" and admin_table else None,
                }
            ),
            200,
        )

    except Exception as e:
        return jsonify({"error": f"Login failed: {str(e)}"}), 500


@bp.route("/send-otp", methods=["POST"])
def send_otp_code():
    """
    Send an SMS OTP for customer/rider mobile login.

    Request JSON:
        - phone (string): Phone number to receive OTP

    Returns:
        - 200: OTP sent
        - 400: Missing or invalid phone
        - 500: SMS send failure
    """
    try:
        data = request.get_json(force=True, silent=True)
        if not data:
            return jsonify({"error": "Request body is required"}), 400

        phone = data.get("phone", "").strip()
        if not phone:
            return jsonify({"error": "Missing required field: phone"}), 400

        otp = generate_otp()
        store_otp(phone, otp)

        if not send_otp(phone, otp):
            return jsonify({"error": "Failed to send OTP"}), 500

        return jsonify({"ok": True, "message": "OTP sent"}), 200

    except Exception as e:
        return jsonify({"error": f"Failed to send OTP: {str(e)}"}), 500


@bp.route("/verify-otp", methods=["POST"])
def verify_otp_code():
    """
    Verify SMS OTP and issue JWT token.

    Request JSON:
        - phone (string)
        - otp (string)

    Returns:
        - 200: JWT token and user info
        - 400: Invalid/expired OTP or invalid input
    """
    try:
        data = request.get_json(force=True, silent=True)
        if not data:
            return jsonify({"error": "Request body is required"}), 400

        phone = data.get("phone", "").strip()
        otp = str(data.get("otp", "")).strip()

        if not phone or not otp:
            return jsonify({"error": "Missing required fields: phone, otp"}), 400

        if not verify_otp(phone, otp):
            return jsonify({"error": "Invalid or expired OTP"}), 400

        user = _find_user_by_phone(phone)
        if not user:
            return jsonify({"error": "No customer or rider account found for this phone"}), 400

        access_token = create_access_token(identity={"id": user["id"], "role": user["role"]})

        return (
            jsonify(
                {
                    "ok": True,
                    "access_token": access_token,
                    "token": access_token,
                    "user_id": user["id"],
                    "id": user["id"],
                    "role": user["role"],
                }
            ),
            200,
        )

    except Exception as e:
        return jsonify({"error": f"Failed to verify OTP: {str(e)}"}), 500


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
            elif role == "admin":
                admin_profile, admin_table = _find_admin_profile(supabase, user_id=user_id)
                profile = admin_profile or {
                    "id": user_id,
                    "role": "admin",
                    "email_allowlisted": True,
                }
                if admin_table:
                    profile["admin_table"] = admin_table
                return jsonify({"user_id": user_id, "role": role, "profile": profile}), 200
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
