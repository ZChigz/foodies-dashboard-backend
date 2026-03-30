"""
F DRIVE - ADMIN ROUTES
Complete platform management and analytics endpoints.
All routes require admin role and JWT authentication.
"""

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from app.supabase_client import get_supabase
from datetime import datetime, timedelta
from functools import wraps
from collections import defaultdict

admin_bp = Blueprint("admin", __name__)


def admin_required(f):
    """Decorator to enforce admin-only access."""
    @wraps(f)
    @jwt_required()
    def decorated_function(*args, **kwargs):
        identity = get_jwt_identity()
        if identity.get('role') != 'admin':
            return jsonify({'error': 'Admin only'}), 403
        return f(*args, **kwargs)
    return decorated_function


def get_today_start():
    """Return today's date at midnight (start of day)."""
    return datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).isoformat()


def get_most_recent_monday():
    """Return most recent Monday's date at midnight."""
    today = datetime.now()
    days_since_monday = today.weekday()
    monday = today - timedelta(days=days_since_monday)
    return monday.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()



# ============================================================================
# OVERVIEW ENDPOINT
# ============================================================================

@admin_bp.route("/overview", methods=["GET"])
@admin_required
def get_overview():
    """
    Get admin dashboard overview.
    Returns: orders_today, active_riders, revenue_today, pending_issues, recent_orders
    """
    try:
        supabase = get_supabase()
        today_start = get_today_start()
        now = datetime.now().isoformat()
        twenty_mins_ago = (datetime.now() - timedelta(minutes=20)).isoformat()

        # Orders today count
        orders_today_response = supabase.table('orders').select(
            'id', count='exact'
        ).gte('created_at', today_start).execute()
        orders_today = orders_today_response.count or 0

        # Active riders count
        active_riders_response = supabase.table('riders').select(
            'id', count='exact'
        ).eq('is_available', True).execute()
        active_riders = active_riders_response.count or 0

        # Revenue today (sum of delivered orders)
        revenue_response = supabase.table('orders').select('total').eq(
            'status', 'delivered'
        ).gte('delivered_at', today_start).execute()
        revenue_today = sum(order.get('total', 0) for order in revenue_response.data) if revenue_response.data else 0

        # Pending issues (order_received older than 20 minutes)
        pending_response = supabase.table('orders').select(
            'id', count='exact'
        ).eq('status', 'order_received').lt('created_at', twenty_mins_ago).execute()
        pending_issues = pending_response.count or 0

        # Recent 10 orders with joins
        recent_orders_response = supabase.table('orders').select(
            'id, status, total, created_at, customers(name), restaurants(restaurant_name)'
        ).order('created_at', desc=True).limit(10).execute()
        recent_orders = recent_orders_response.data if recent_orders_response.data else []

        return jsonify({
            'orders_today': orders_today,
            'active_riders': active_riders,
            'revenue_today': float(revenue_today),
            'pending_issues': pending_issues,
            'recent_orders': recent_orders
        }), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ============================================================================
# ORDERS ENDPOINTS
# ============================================================================

@admin_bp.route("/orders", methods=["GET"])
@admin_required
def get_all_orders():
    """
    Get all orders with optional filters.
    Query params: status, restaurant_id, payment_method, date_from, date_to, search
    """
    try:
        supabase = get_supabase()
        query = supabase.table('orders').select(
            'id, status, total, created_at, customers(name, phone), restaurants(restaurant_name), riders(name), payment_method'
        )

        # Apply filters
        status = request.args.get('status')
        if status:
            query = query.eq('status', status)

        restaurant_id = request.args.get('restaurant_id')
        if restaurant_id:
            query = query.eq('restaurant_id', restaurant_id)

        payment_method = request.args.get('payment_method')
        if payment_method:
            query = query.eq('payment_method', payment_method)

        date_from = request.args.get('date_from')
        if date_from:
            query = query.gte('created_at', date_from)

        date_to = request.args.get('date_to')
        if date_to:
            query = query.lte('created_at', date_to)

        # Execute before search filter (which requires post-processing)
        response = query.order('created_at', desc=True).execute()
        orders = response.data if response.data else []

        # Search filter (client-side after join because Supabase can't search joined fields easily)
        search = request.args.get('search')
        if search:
            search_lower = search.lower()
            orders = [
                order for order in orders
                if (order.get('customers') and search_lower in str(order['customers'].get('name', '')).lower()) or
                   search_lower in str(order.get('id', '')).lower()
            ]

        return jsonify(orders), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@admin_bp.route("/orders/<order_id>", methods=["GET"])
@admin_required
def get_order_detail(order_id):
    """Get full order details with all joins."""
    try:
        supabase = get_supabase()
        response = supabase.table('orders').select(
            '*, customers(*), restaurants(*), riders(*)'
        ).eq('id', order_id).single().execute()

        return jsonify(response.data), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@admin_bp.route("/orders/<order_id>/cancel", methods=["PATCH", "OPTIONS"])
@admin_required
def cancel_order(order_id):
    """Cancel an order."""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        supabase = get_supabase()
        
        # First verify order exists
        check = supabase.table('orders').select('id, status').eq('id', order_id).single().execute()
        if not check.data:
            return jsonify({'error': 'Order not found'}), 404
        
        current_status = check.data.get('status')
        if current_status == 'cancelled':
            return jsonify({'error': 'Order is already cancelled'}), 400
        
        now = datetime.now().isoformat()

        response = supabase.table('orders').update({
            'status': 'cancelled',
            'cancelled_at': now
        }).eq('id', order_id).execute()

        if not response.data:
            return jsonify({'error': 'Failed to cancel order'}), 500

        return jsonify({'success': True, 'data': response.data}), 200

    except Exception as e:
        return jsonify({'error': str(e), 'type': type(e).__name__}), 500


# ============================================================================
# RIDERS ENDPOINTS
# ============================================================================

@admin_bp.route("/riders", methods=["GET"])
@admin_required
def get_all_riders():
    """Get all riders with today's job count."""
    try:
        supabase = get_supabase()
        today_start = get_today_start()

        response = supabase.table('riders').select('*').execute()
        riders = response.data if response.data else []

        # Add jobs_today count for each rider
        for rider in riders:
            jobs_response = supabase.table('orders').select(
                'id', count='exact'
            ).eq('rider_id', rider['id']).eq('status', 'delivered').gte(
                'delivered_at', today_start
            ).execute()
            rider['jobs_today'] = jobs_response.count or 0

        return jsonify(riders), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@admin_bp.route("/riders/<rider_id>/approve", methods=["PATCH", "OPTIONS"])
@admin_required
def approve_rider(rider_id):
    """Approve a rider."""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        supabase = get_supabase()
        response = supabase.table('riders').update({
            'is_approved': True
        }).eq('id', rider_id).execute()

        return jsonify({'success': True, 'data': response.data}), 200

    except Exception as e:
        return jsonify({'error': str(e), 'type': type(e).__name__}), 500


@admin_bp.route("/riders/<rider_id>/suspend", methods=["PATCH", "OPTIONS"])
@admin_required
def suspend_rider(rider_id):
    """Suspend a rider."""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        supabase = get_supabase()
        response = supabase.table('riders').update({
            'is_approved': False
        }).eq('id', rider_id).execute()

        return jsonify({'success': True, 'data': response.data}), 200

    except Exception as e:
        return jsonify({'error': str(e), 'type': type(e).__name__}), 500


# ============================================================================
# RESTAURANTS ENDPOINTS
# ============================================================================

@admin_bp.route("/restaurants", methods=["GET"])
@admin_required
def get_all_restaurants():
    """Get all restaurants with orders_today and revenue_today counts."""
    try:
        supabase = get_supabase()
        today_start = get_today_start()

        response = supabase.table('restaurants').select('*').execute()
        restaurants = response.data if response.data else []

        # Add stats for each restaurant
        for restaurant in restaurants:
            # Orders today
            orders_response = supabase.table('orders').select(
                'id', count='exact'
            ).eq('restaurant_id', restaurant['id']).gte(
                'created_at', today_start
            ).execute()
            restaurant['orders_today'] = orders_response.count or 0

            # Revenue today
            revenue_response = supabase.table('orders').select('total').eq(
                'restaurant_id', restaurant['id']
            ).eq('status', 'delivered').gte(
                'delivered_at', today_start
            ).execute()
            restaurant['revenue_today'] = sum(
                order.get('total', 0) for order in revenue_response.data
            ) if revenue_response.data else 0

        return jsonify(restaurants), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@admin_bp.route("/restaurants", methods=["POST", "OPTIONS"])
@admin_required
def create_restaurant():
    """Create a new restaurant - accepts restaurant_name and optional fields.
    
    Admin can create restaurants WITHOUT requiring a manager user first.
    user_id can be linked later when manager account is created.
    """
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        # Try to get JSON in multiple ways
        data = None
        
        # Method 1: Force parse
        try:
            data = request.get_json(force=True)
        except:
            pass
        
        # Method 2: Silent parse
        if data is None:
            try:
                data = request.get_json(silent=True)
            except:
                pass
        
        # Method 3: Empty dict fallback
        if data is None:
            data = {}
        
        # Accept request even with empty body - just need restaurant_name
        restaurant_name = None
        
        # Search for restaurant_name in any form
        for key in data.keys():
            if 'restaurant' in key.lower() and 'name' in key.lower():
                restaurant_name = str(data[key]).strip()
                break
        
        # If not found, try exact key
        if not restaurant_name and 'restaurant_name' in data:
            restaurant_name = str(data['restaurant_name']).strip()
        
        # If STILL not found, accept first string value longer than 3 chars as restaurant name
        if not restaurant_name:
            for key, value in data.items():
                if isinstance(value, str) and len(str(value).strip()) > 3:
                    restaurant_name = str(value).strip()
                    break
        
        # Finally, if nothing worked, return helpful error
        if not restaurant_name:
            return jsonify({
                'error': 'Could not find restaurant_name field',
                'received_body': data,
                'received_keys': list(data.keys()) if data else [],
                'expected_body': {'restaurant_name': 'required', 'email': 'optional', 'phone': 'optional', 'address': 'optional', 'delivery_fee': 'optional'}
            }), 400

        supabase = get_supabase()
        insert_payload = {
            'restaurant_name': restaurant_name,
            'email': str(data.get('email', '')).strip(),
            'phone': str(data.get('phone', '')).strip(),
            'address': str(data.get('address', '')).strip(),
            'is_open': True,
            'created_at': datetime.now().isoformat()
        }
        
        # Add delivery_fee if provided
        if 'delivery_fee' in data:
            try:
                insert_payload['delivery_fee'] = float(data['delivery_fee'])
            except:
                insert_payload['delivery_fee'] = 0

        # NOTE: user_id is NOT set here - admin creates restaurant without manager
        # Manager can be added later via update when auth account is created in Supabase

        response = supabase.table('restaurants').insert(insert_payload).execute()

        created_restaurant = response.data[0] if response.data else insert_payload
        
        return jsonify({
            'success': True,
            'restaurant': created_restaurant,
            'note': 'Restaurant created. Create manager account in Supabase dashboard, then link via user_id'
        }), 201

    except Exception as e:
        import traceback
        return jsonify({
            'error': str(e), 
            'type': type(e).__name__,
            'hint': 'Run RESTAURANTS_TABLE_FIX.sql in Supabase to fix schema',
            'traceback': traceback.format_exc()
        }), 500


@admin_bp.route("/restaurants/<restaurant_id>", methods=["PATCH", "OPTIONS"])
@admin_required
def update_restaurant(restaurant_id):
    """Update restaurant details. Maps 'name' to 'restaurant_name' if needed."""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        data = request.get_json() or {}
        
        if not data:
            return jsonify({'error': 'Request body is required'}), 400

        # Map 'name' to 'restaurant_name' if provided (frontend compatibility)
        if 'name' in data and 'restaurant_name' not in data:
            data['restaurant_name'] = data.pop('name')
        
        # Only allow specific columns to be updated
        allowed_fields = {'restaurant_name', 'email', 'phone', 'address', 'delivery_fee', 'is_open', 'user_id'}
        update_data = {k: v for k, v in data.items() if k in allowed_fields}
        
        if not update_data:
            return jsonify({
                'error': 'No valid fields to update',
                'allowed_fields': list(allowed_fields),
                'received_fields': list(data.keys())
            }), 400

        supabase = get_supabase()
        response = supabase.table('restaurants').update(update_data).eq(
            'id', restaurant_id
        ).execute()

        if not response.data:
            return jsonify({'error': 'Restaurant not found'}), 404

        return jsonify({'success': True, 'data': response.data}), 200

    except Exception as e:
        error_msg = str(e)
        # Helpful hint if schema cache issue
        if 'schema cache' in error_msg.lower():
            return jsonify({
                'error': error_msg,
                'type': type(e).__name__,
                'hint': 'Supabase schema cache outdated. Refresh in Supabase dashboard or wait 60 seconds'
            }), 500
        return jsonify({'error': error_msg, 'type': type(e).__name__}), 500


@admin_bp.route("/restaurants/<restaurant_id>/toggle", methods=["PATCH", "OPTIONS"])
@admin_required
def toggle_restaurant_status(restaurant_id):
    """Toggle restaurant is_open status."""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        supabase = get_supabase()

        # Get current status
        current = supabase.table('restaurants').select('is_open').eq(
            'id', restaurant_id
        ).single().execute()

        if not current.data:
            return jsonify({'error': 'Restaurant not found'}), 404

        new_status = not current.data.get('is_open', True)

        response = supabase.table('restaurants').update({
            'is_open': new_status
        }).eq('id', restaurant_id).execute()

        return jsonify({'success': True, 'is_open': new_status}), 200

    except Exception as e:
        return jsonify({'error': str(e), 'type': type(e).__name__}), 500


# ============================================================================
# PROMOTIONS ENDPOINTS
# ============================================================================

@admin_bp.route("/promotions", methods=["GET"])
@admin_required
def get_all_promotions():
    """Get all promotional codes. Returns empty list if table doesn't exist."""
    try:
        supabase = get_supabase()
        response = supabase.table('promo_codes').select('*').execute()
        return jsonify(response.data if response.data else []), 200
    except Exception as e:
        if 'relation' in str(e).lower() or 'does not exist' in str(e).lower():
            return jsonify([]), 200
        return jsonify({'error': str(e)}), 500


@admin_bp.route("/promotions", methods=["POST", "OPTIONS"])
@admin_required
def create_promotion():
    """Create a new promotional code. Table must exist."""
    # Handle CORS OPTIONS request
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        # Get JSON data - handle both empty and malformed requests
        try:
            data = request.get_json(force=True, silent=False)
        except Exception as json_err:
            data = None
        
        if data is None:
            try:
                data = request.get_json(silent=True)
            except:
                data = None
        
        if not data:
            return jsonify({
                'error': 'Request body is required and must be valid JSON',
                'content_type': request.content_type,
            }), 400
        
        # Get code - trim whitespace
        code = None
        if 'code' in data:
            code = str(data.get('code', '')).strip() if data.get('code') else None
        
        if not code:
            return jsonify({
                'error': 'code field is required and cannot be empty',
                'received': data
            }), 400

        # discount_percent defaults to 10 if not provided
        discount_percent = 10
        if 'discount_percent' in data:
            try:
                discount_percent = float(data.get('discount_percent'))
            except (ValueError, TypeError):
                return jsonify({'error': 'discount_percent must be a number'}), 400
        
        if discount_percent < 0 or discount_percent > 100:
            return jsonify({'error': 'discount_percent must be between 0 and 100'}), 400

        supabase = get_supabase()
        response = supabase.table('promo_codes').insert({
            'code': code,
            'discount_percent': discount_percent,
            'is_active': data.get('is_active', True),
            'valid_from': data.get('valid_from'),
            'valid_until': data.get('valid_until'),
            'created_at': datetime.now().isoformat()
        }).execute()

        return jsonify(response.data[0] if response.data else {}), 201

    except Exception as e:
        error_str = str(e).lower()
        if 'relation' in error_str or 'does not exist' in error_str:
            return jsonify({'error': 'promo_codes table does not exist. Please run MIGRATION_MISSING_TABLES.sql in Supabase.'}), 500
        return jsonify({'error': str(e), 'type': type(e).__name__}), 500


@admin_bp.route("/promotions/<promo_id>", methods=["PATCH", "OPTIONS"])
@admin_required
def update_promotion(promo_id):
    """Update a promotional code or toggle is_active."""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        # Get JSON data
        try:
            data = request.get_json(force=True, silent=False)
        except:
            data = request.get_json(silent=True)
        
        if not data:
            return jsonify({'error': 'Request body is required'}), 400

        supabase = get_supabase()
        update_data = {}

        # Handle each field safely
        if 'code' in data:
            update_data['code'] = str(data['code']).strip()
        
        if 'discount_percent' in data:
            try:
                update_data['discount_percent'] = float(data['discount_percent'])
            except (ValueError, TypeError):
                return jsonify({'error': 'discount_percent must be a number'}), 400
        
        if 'is_active' in data:
            update_data['is_active'] = bool(data['is_active'])
        
        if 'valid_from' in data:
            update_data['valid_from'] = data['valid_from']
        
        if 'valid_until' in data:
            update_data['valid_until'] = data['valid_until']

        # If toggling is_active without providing it, flip the current value
        if 'toggle' in data and data['toggle'] is True:
            current = supabase.table('promo_codes').select('is_active').eq(
                'id', promo_id
            ).single().execute()
            if current.data:
                update_data['is_active'] = not current.data.get('is_active', True)
            else:
                return jsonify({'error': 'Promo code not found'}), 404
        
        if not update_data and 'toggle' not in data:
            return jsonify({'error': 'No fields to update'}), 400

        response = supabase.table('promo_codes').update(update_data).eq(
            'id', promo_id
        ).execute()

        if not response.data:
            return jsonify({'error': 'Promo code not found'}), 404

        return jsonify({'success': True, 'data': response.data}), 200

    except Exception as e:
        return jsonify({'error': str(e), 'type': type(e).__name__}), 500


@admin_bp.route("/promotions/<promo_id>", methods=["DELETE", "OPTIONS"])
@admin_required
def delete_promotion(promo_id):
    """Delete a promotional code."""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        supabase = get_supabase()
        response = supabase.table('promo_codes').delete().eq('id', promo_id).execute()

        return jsonify({'success': True}), 200

    except Exception as e:
        return jsonify({'error': str(e), 'type': type(e).__name__}), 500


# ============================================================================
# PAYOUTS ENDPOINTS
# ============================================================================

@admin_bp.route("/payouts", methods=["GET"])
@admin_required
def get_payouts():
    """
    Get payouts for riders in a given week.
    Query param: week_start (date string, default=most recent Monday)
    """
    try:
        supabase = get_supabase()
        week_start = request.args.get('week_start')

        if not week_start:
            week_start = get_most_recent_monday()

        # Calculate week end
        week_start_dt = datetime.fromisoformat(week_start)
        week_end_dt = week_start_dt + timedelta(days=7)
        week_end = week_end_dt.isoformat()

        # Get all riders
        riders_response = supabase.table('riders').select('id, name, phone').execute()
        riders = riders_response.data if riders_response.data else []

        payouts = []
        for rider in riders:
            # Get delivered orders for this rider in this week
            orders_response = supabase.table('orders').select('total').eq(
                'rider_id', rider['id']
            ).eq('status', 'delivered').gte(
                'delivered_at', week_start
            ).lt('delivered_at', week_end).execute()

            orders = orders_response.data if orders_response.data else []

            # Calculate payout
            gross = sum(order.get('total', 0) for order in orders)
            platform_fee = gross * 0.15
            rider_net = gross * 0.80

            payouts.append({
                'rider_id': rider['id'],
                'rider_name': rider['name'],
                'rider_phone': rider['phone'],
                'deliveries': len(orders),
                'gross': float(gross),
                'platform_fee': float(platform_fee),
                'rider_net': float(rider_net),
                'week_start': week_start
            })

        return jsonify(payouts), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@admin_bp.route("/payouts/mark-paid", methods=["POST"])
@admin_required
def mark_payout_paid():
    """Mark a payout as paid. Creates payouts_log entry."""
    try:
        data = request.get_json() or {}
        required = ['rider_id', 'week_start']

        if not all(field in data for field in required):
            return jsonify({'error': f'Missing required fields: {", ".join(required)}'}), 400

        supabase = get_supabase()

        # Calculate the total amount for this payout
        week_start = data['week_start']
        week_start_dt = datetime.fromisoformat(week_start)
        week_end_dt = week_start_dt + timedelta(days=7)
        week_end = week_end_dt.isoformat()

        orders_response = supabase.table('orders').select('total').eq(
            'rider_id', data['rider_id']
        ).eq('status', 'delivered').gte(
            'delivered_at', week_start
        ).lt('delivered_at', week_end).execute()

        orders = orders_response.data if orders_response.data else []
        gross = sum(order.get('total', 0) for order in orders)
        rider_net = gross * 0.80

        # Create or update payouts_log entry
        now = datetime.now().isoformat()
        try:
            response = supabase.table('payouts_log').insert({
                'rider_id': data['rider_id'],
                'week_start': week_start,
                'amount': float(rider_net),
                'paid_at': now
            }).execute()
            return jsonify({'success': True, 'data': response.data}), 201
        except Exception as e:
            error_str = str(e).lower()
            if 'relation' in error_str or 'does not exist' in error_str:
                return jsonify({'error': 'payouts_log table does not exist. Please create it in Supabase.'}), 500
            raise

    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ============================================================================
# ANALYTICS ENDPOINTS
# ============================================================================

@admin_bp.route("/analytics/revenue", methods=["GET"])
@admin_required
def get_revenue_analytics():
    """Get revenue data for the last N days."""
    try:
        days = int(request.args.get('days', 30))
        supabase = get_supabase()

        revenue_data = []
        for i in range(days, 0, -1):
            day = datetime.now() - timedelta(days=i)
            day_start = day.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
            day_end = (day + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()

            response = supabase.table('orders').select('total').eq(
                'status', 'delivered'
            ).gte('delivered_at', day_start).lt(
                'delivered_at', day_end
            ).execute()

            revenue = sum(
                order.get('total', 0) for order in response.data
            ) if response.data else 0

            revenue_data.append({
                'date': day.strftime('%Y-%m-%d'),
                'revenue': float(revenue)
            })

        return jsonify(revenue_data), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@admin_bp.route("/analytics/peak-hours", methods=["GET"])
@admin_required
def get_peak_hours_analytics():
    """Get order count by hour."""
    try:
        supabase = get_supabase()
        response = supabase.table('orders').select('created_at').execute()

        # Count orders by hour
        hour_counts = {}
        if response.data:
            for order in response.data:
                try:
                    created_at = datetime.fromisoformat(order['created_at'].replace('Z', '+00:00'))
                    hour = created_at.hour
                    hour_counts[hour] = hour_counts.get(hour, 0) + 1
                except:
                    pass

        peak_hours = [
            {'hour': hour, 'count': count}
            for hour, count in sorted(hour_counts.items())
        ]

        return jsonify(peak_hours), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@admin_bp.route("/analytics/top-items", methods=["GET"])
@admin_required
def get_top_items_analytics():
    """Get top 10 menu items from delivered orders."""
    try:
        supabase = get_supabase()
        response = supabase.table('orders').select('items').eq(
            'status', 'delivered'
        ).execute()

        # Unnest and aggregate items
        item_counts = {}
        if response.data:
            for order in response.data:
                items = order.get('items', [])
                if isinstance(items, list):
                    for item in items:
                        if isinstance(item, dict):
                            item_name = item.get('name', 'Unknown')
                            item_qty = item.get('qty', 1)
                            if item_name not in item_counts:
                                item_counts[item_name] = {'qty': 0, 'name': item_name}
                            item_counts[item_name]['qty'] += item_qty

        top_items = sorted(
            item_counts.values(),
            key=lambda x: x['qty'],
            reverse=True
        )[:10]

        return jsonify(top_items), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@admin_bp.route("/analytics/payments", methods=["GET"])
@admin_required
def get_payments_analytics():
    """Get payment method breakdown."""
    try:
        supabase = get_supabase()
        response = supabase.table('orders').select('payment_method, total').execute()

        # Aggregate by payment method
        payment_data = {}
        if response.data:
            for order in response.data:
                method = order.get('payment_method', 'unknown')
                total = order.get('total', 0)
                if method not in payment_data:
                    payment_data[method] = {'count': 0, 'total': 0}
                payment_data[method]['count'] += 1
                payment_data[method]['total'] += total

        payments = [
            {
                'payment_method': method,
                'count': data['count'],
                'total': float(data['total'])
            }
            for method, data in payment_data.items()
        ]

        return jsonify(payments), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ============================================================================
# SETTINGS ENDPOINTS
# ============================================================================

@admin_bp.route("/settings", methods=["GET"])
@admin_required
def get_platform_settings():
    """Get all platform configuration settings. Returns empty list if table doesn't exist."""
    try:
        supabase = get_supabase()
        response = supabase.table('platform_config').select('*').execute()
        return jsonify(response.data if response.data else []), 200
    except Exception as e:
        error_str = str(e).lower()
        if 'relation' in error_str or 'does not exist' in error_str:
            return jsonify([]), 200
        return jsonify({'error': str(e)}), 500


@admin_bp.route("/settings/<key>", methods=["PATCH", "OPTIONS"])
@admin_required
def update_platform_setting(key):
    """Update a platform configuration setting."""
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        data = request.get_json() or {}

        if 'value' not in data:
            return jsonify({'error': 'Missing required field: value'}), 400

        supabase = get_supabase()
        response = supabase.table('platform_config').update({
            'value': str(data['value'])
        }).eq('key', key).execute()

        return jsonify({'success': True, 'data': response.data}), 200

    except Exception as e:
        error_str = str(e).lower()
        if 'relation' in error_str or 'does not exist' in error_str:
            return jsonify({'error': 'platform_config table does not exist. Please create it in Supabase.'}), 500
        return jsonify({'error': str(e), 'type': type(e).__name__}), 500
