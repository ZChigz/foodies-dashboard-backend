<<<<<<< HEAD
╔══════════════════════════════════════════════════════════════════════════════╗
║                   F DRIVE BACKEND - COMPLETE SETUP GUIDE                    ║
║                                                                              ║
║  Food Delivery Platform API for Harare, Zimbabwe                            ║
╚══════════════════════════════════════════════════════════════════════════════╝

PROJECT STRUCTURE:
═════════════════

fdrive-backend/
├── run.py                          ← Entry point (python run.py)
├── requirements.txt                ← All dependencies
├── .env.example                    ← Environment template
├── .env                            ← Your actual config (create from .env.example)
├── app/
│   ├── __init__.py                 ← App factory & JWT/CORS setup
│   ├── supabase_client.py          ← Supabase singleton
│   └── routes/
│       ├── __init__.py
│       ├── auth.py                 ← /api/auth/* endpoints
│       ├── orders.py               ← /api/orders/* endpoints  
│       ├── menu.py                 ← /api/menu/* endpoints
│       ├── restaurants.py          ← /api/restaurants/* endpoints
│       ├── riders.py               ← /api/riders/* endpoints
│       └── payments.py             ← /api/payments/* endpoints


QUICK START:
════════════

1. BUILD PROJECT STRUCTURE:
   cd "c:\Users\bruce\Desktop\foodies dashboard backend"
   python build_project.py

2. INSTALL DEPENDENCIES:
   pip install -r requirements.txt

3. CONFIGURE ENVIRONMENT:
   - Copy .env.example to .env
   - Fill in your actual values:
     * SUPABASE_URL & SUPABASE_SERVICE_KEY
     * JWT_SECRET_KEY (generate a random string)
     * PAYNOW credentials (for payments)

4. RUN THE SERVER:
   python run.py

   Server will run on: http://localhost:5000
   Health check: GET http://localhost:5000/


API ENDPOINTS:
══════════════

🔐 AUTHENTICATION (/api/auth/)
  POST   /register          - Register new user
  POST   /login             - Login & get JWT token
  GET    /me                - Get current user (requires JWT)

📦 ORDERS (/api/orders/)
  POST   /                  - Create new order
  GET    /<order_id>        - Get order details
  GET    /customer/<id>     - List customer's orders
  PATCH  /<order_id>/status - Update order status
  DELETE /<order_id>        - Cancel order

🍽️  MENU (/api/menu/)
  GET    /<restaurant_id>   - Get restaurant's menu items
  POST   /                  - Create menu item (restaurant only)
  GET    /<item_id>         - Get menu item details
  PATCH  /<item_id>         - Update menu item (restaurant only)
  DELETE /<item_id>         - Delete menu item (restaurant only)

🏪 RESTAURANTS (/api/restaurants/)
  GET    /                  - List all restaurants
  GET    /<restaurant_id>   - Get restaurant details
  POST   /                  - Create restaurant (restaurant owner)
  PATCH  /toggle-status/<id>- Toggle open/closed (restaurant owner)

🚴 RIDERS (/api/riders/)
  PATCH  /availability      - Toggle online/offline
  POST   /location          - Broadcast GPS location
  GET    /location/<id>     - Get rider's current location
  GET    /available         - List available riders

💳 PAYMENTS (/api/payments/)
  POST   /initiate          - Start Paynow payment
  GET    /status/<id>       - Check payment status
  POST   /webhook           - Paynow webhook (auto-called)
  POST   /<order_id>/refund - Refund payment


AUTHENTICATION DETAILS:
═══════════════════════

JWT Token Format:
  {
    "id": "user_uuid",
    "role": "customer|rider|restaurant"  
  }

User Roles:
  - "customer"    → Orders food, makes payments
  - "rider"       → Delivers food, broadcasts location
  - "restaurant"  → Manages menu, accepts orders

All protected routes require:
  Authorization: Bearer <JWT_TOKEN>

Register Request:
  {
    "email": "user@example.com",
    "password": "secure_password",
    "name": "Full Name",
    "role": "customer|rider|restaurant"
  }

Login Request:
  {
    "email": "user@example.com",
    "password": "secure_password"
  }


ENVIRONMENT VARIABLES (.env):
═══════════════════════════════

# Flask
FLASK_ENV=development
FLASK_DEBUG=True
SECRET_KEY=your-random-secret-key-here

# JWT
JWT_SECRET_KEY=your-random-jwt-key-here
JWT_ACCESS_TOKEN_EXPIRES=3600

# Supabase
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_KEY=your-service-role-key

# Paynow Zimbabwe
PAYNOW_INTEGRATION_ID=your-paynow-id
PAYNOW_INTEGRATION_KEY=your-paynow-key
PAYNOW_RESULT_URL=https://yourdomain.com/api/payments/webhook
PAYNOW_RETURN_URL=https://yourdomain.com/payment-status

# App Config
APP_NAME=F Drive API
APP_VERSION=1.0.0
ALLOWED_ORIGINS=http://localhost:3000,http://localhost:5000


DATABASE TABLES (Create in Supabase):
═════════════════════════════════════

users
  - id (UUID, primary)
  - email (TEXT, unique)
  - password (TEXT)
  - name (TEXT)
  - role (TEXT) - customer/rider/restaurant
  - created_at (TIMESTAMP)

restaurants
  - id (UUID, primary)
  - owner_id (UUID, foreign key → users.id)
  - name (TEXT)
  - description (TEXT)
  - phone (TEXT)
  - address (TEXT)
  - city (TEXT)
  - image_url (TEXT)
  - status (TEXT) - open/closed
  - created_at (TIMESTAMP)

menu_items
  - id (UUID, primary)
  - restaurant_id (UUID, foreign key → restaurants.id)
  - name (TEXT)
  - description (TEXT)
  - price (NUMERIC)
  - category (TEXT)
  - image_url (TEXT)
  - available (BOOLEAN)
  - created_at (TIMESTAMP)

orders
  - id (UUID, primary)
  - customer_id (UUID, foreign key → users.id)
  - restaurant_id (UUID, foreign key → restaurants.id)
  - rider_id (UUID, nullable, foreign key → users.id)
  - items (JSONB) - array of {menu_item_id, quantity}
  - delivery_address (TEXT)
  - delivery_phone (TEXT)
  - status (TEXT) - pending/accepted/assigned_to_rider/picked_up/delivered
  - payment_status (TEXT) - unpaid/paid
  - created_at (TIMESTAMP)

payments
  - id (UUID, primary)
  - order_id (UUID, foreign key → orders.id)
  - customer_id (UUID, foreign key → users.id)
  - amount (NUMERIC)
  - payment_method (TEXT) - ecocash/card
  - phone (TEXT, nullable)
  - status (TEXT) - pending/completed/failed/refunded
  - created_at (TIMESTAMP)

riders
  - id (UUID, primary)
  - user_id (UUID, unique, foreign key → users.id)
  - available (BOOLEAN)
  - city (TEXT)
  - created_at (TIMESTAMP)
  - updated_at (TIMESTAMP)

rider_locations
  - id (UUID, primary)
  - rider_id (UUID, unique, foreign key → users.id)
  - latitude (NUMERIC)
  - longitude (NUMERIC)
  - updated_at (TIMESTAMP)


EXAMPLE USAGE:
══════════════

1. REGISTER A CUSTOMER:
   POST /api/auth/register
   {
     "email": "customer@example.co.zw",
     "password": "password123",
     "name": "John Doe",
     "role": "customer"
   }
   
   Response:
   {
     "message": "User registered successfully",
     "user_id": "abc-123-def",
     "access_token": "eyJ0eXAiOiJKV1QiLCJhbGc...",
     "role": "customer"
   }

2. LOGIN:
   POST /api/auth/login
   {
     "email": "customer@example.co.zw",
     "password": "password123"
   }

3. GET CURRENT USER PROFILE:
   GET /api/auth/me
   Headers: Authorization: Bearer eyJ0eXAiOiJKV1QiLCJhbGc...

4. CREATE AN ORDER:
   POST /api/orders
   Headers: Authorization: Bearer <token>
   {
     "restaurant_id": "rest-123",
     "items": [
       {"menu_item_id": "item-1", "quantity": 2},
       {"menu_item_id": "item-2", "quantity": 1}
     ],
     "delivery_address": "123 Main St, Harare",
     "delivery_phone": "+263771234567"
   }

5. INITIATE PAYMENT:
   POST /api/payments/initiate
   Headers: Authorization: Bearer <token>
   {
     "order_id": "order-123",
     "amount": 50000,
     "payment_method": "ecocash",
     "phone": "+263771234567"
   }


DEPLOYMENT:
═══════════

For production, use Gunicorn:
  gunicorn -w 4 -b 0.0.0.0:5000 "app:create_app()"

With environment variables in a .env file on the server.


TROUBLESHOOTING:
════════════════

❌ "ModuleNotFoundError: No module named 'app'"
   → Make sure you're running from the fdrive-backend directory
   → The app/ folder exists in the same directory as run.py

❌ "SUPABASE_URL and SUPABASE_SERVICE_KEY must be set"
   → Create .env file with your Supabase credentials
   → Copy from .env.example and fill in your actual values

❌ "No JWT token in request headers"
   → Include Authorization header: Authorization: Bearer <token>
   → This header is required for all protected endpoints (@jwt_required)

❌ "Invalid email or password"
   → Make sure the user exists in the database
   → Double-check email spelling and exact password


SECURITY NOTES:
═══════════════

✓ JWT tokens expire after 1 hour (configurable)
✓ Passwords are hashed with bcrypt
✓ Service Role Key used (admin access for backend)
✓ Role-based access control on all endpoints
✓ CORS configured for allowed origins only

⚠️  NEVER commit .env file to version control
⚠️  NEVER expose JWT_SECRET_KEY or SERVICE_KEY
⚠️  Change SECRET_KEY & JWT_SECRET_KEY in production


FILES INCLUDED:
═══════════════

✓ run.py                    - Entry point
✓ requirements.txt          - Dependencies
✓ .env.example              - Config template
✓ app/__init__.py           - App factory
✓ app/supabase_client.py    - Supabase singleton
✓ app/routes/auth.py        - Authentication
✓ app/routes/orders.py      - Orders management
✓ app/routes/menu.py        - Menu management
✓ app/routes/restaurants.py - Restaurant management
✓ app/routes/riders.py      - Rider management
✓ app/routes/payments.py    - Payment processing


READY TO GO! 🚀
═══════════════

Your F Drive backend is fully scaffolded with:
✅ JWT authentication with role-based access control
✅ Supabase integration for real-time database
✅ Paynow payment gateway integration
✅ Order management with status transitions
✅ Restaurant menu management
✅ Rider GPS tracking
✅ Real-time payment webhooks
✅ Proper error handling
✅ CORS configuration for frontend
✅ Production-ready with Gunicorn support

Next: Run build_project.py to create all files, then pip install requirements.txt!
=======
# foodies-dashboard-backend
Flask backend for F Drive food delivery at Foodies (Pvt) Ltd, Harare, Zimbabwe
>>>>>>> c3a6850958ddaea99329cd2504d9ce492a960ef4
