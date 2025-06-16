from flask import Flask, render_template, redirect, url_for, request, session, make_response, flash, g
from sqlite3 import DatabaseError
import database
import sqlite3
from datetime import datetime
import os
import logging
import re
from sqlite3 import IntegrityError
from jinja2 import TemplateError
from database import get_booking_by_id

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

try:
    import matplotlib.pyplot as plt
except ImportError:
    logger.warning("Matplotlib not installed. Chart generation will be skipped.")
    plt = None

app = Flask(__name__)
app.secret_key = 'your_secure_secret_key'  # Replace with a secure key

# Database connection management
def get_db():
    if 'db' not in g:
        logger.info("Opening database connection for request")
        g.db = database.get_db_connection()
    return g.db

@app.teardown_appcontext
def close_db(error):
    if hasattr(g, 'db'):
        logger.info("Closing database connection for request")
        g.db.close()

@app.route('/')
def login():
    return render_template('login.html')

@app.route('/new-user-registration-system')
def new_user_registration():
    return render_template('new-user-registration-system.html')

@app.route('/admin-login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        conn = get_db()
        c = conn.cursor()
        c.execute('SELECT * FROM admin WHERE username = ? AND password = ?', (username, password))
        admin = c.fetchone()
        if admin:
            session['admin_id'] = admin['id']
            return redirect(url_for('admin_dashboard'))
        else:
            return render_template('admin-login.html', error='Invalid username or password')
    return render_template('admin-login.html')

@app.route('/admin-dashboard')
def admin_dashboard():
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute('''
            SELECT b.user_id, b.slot_id, u.fullname, b.vehicle_number, u.pincode, u.address
            FROM parking_bookings b
            JOIN users u ON b.user_id = u.id
            WHERE b.status = 'booked'
        ''')
        bookings = [
            {
                'user_id': booking['user_id'],
                'slot_id': booking['slot_id'],
                'fullname': booking['fullname'],
                'vehicle_number': booking['vehicle_number'],
                'pincode': booking['pincode'],
                'address': booking['address']
            } for booking in c.fetchall()
        ]
        c.execute('SELECT id, location_name, address, pincode, price_per_hour, max_spots FROM parking_lots')
        lots = c.fetchall()
        parking_lots_with_slots = []
        for lot in lots:
            lot_id = lot['id']
            c.execute('SELECT id, slot_number, status FROM parking_slots WHERE parking_lot_id = ? ORDER BY slot_number', (lot_id,))
            slots = c.fetchall()
            available_count = sum(1 for slot in slots if slot['status'] == 'available')
            c.execute('''SELECT slot_id, vehicle_number FROM parking_bookings WHERE status = 'booked' AND slot_id IN ({})'''.format(','.join(['?']*len(slots))), [slot['id'] for slot in slots])
            booked_vehicles = dict(c.fetchall())
            for i, slot in enumerate(slots):
                if slot['status'] == 'booked':
                    vehicle_number = booked_vehicles.get(slot['id'])
                    if vehicle_number:
                        slots[i] = (*slot, vehicle_number)
            parking_lots_with_slots.append((lot, slots, available_count))
        return render_template('admin-dashboard.html', bookings=bookings, lots=parking_lots_with_slots)
    except DatabaseError as e:
        logger.error(f"Database error in admin_dashboard: {e}")
        return "Error fetching data", 500

@app.route('/logout')
def logout():
    session.pop('admin_id', None)
    session.pop('user_id', None)
    session.pop('username', None)
    return redirect(url_for('admin_login'))

@app.route('/admin-users', methods=['GET'])
def admin_users():
    query = request.args.get('query', '').strip()
    active_bookings = []
    past_bookings = []

    try:
        conn = get_db()
        c = conn.cursor()

        base_query = '''
            SELECT u.fullname AS user_name, u.email, pb.location_name, ps.slot_number, 
                   pb.vehicle_number, 
                   strftime('%Y-%m-%d %H:%M:%S', pb.booking_time) AS booking_time, 
                   pb.unbooking_time, pb.status
            FROM parking_bookings pb
            LEFT JOIN users u ON pb.user_id = u.id
            LEFT JOIN parking_slots ps ON pb.slot_id = ps.id
        '''

        if query:
            search_condition = '''
                WHERE (LOWER(COALESCE(u.fullname, '')) LIKE ? 
                       OR LOWER(COALESCE(pb.vehicle_number, '')) LIKE ? 
                       OR LOWER(COALESCE(pb.location_name, '')) LIKE ?)
            '''
            search_params = (f'%{query.lower()}%', f'%{query.lower()}%', f'%{query.lower()}%')

            # Active bookings (status = 'booked')
            full_query = base_query + search_condition + " AND pb.status = 'booked' ORDER BY pb.booking_time DESC"
            c.execute(full_query, search_params)
            active_bookings = c.fetchall()

            # Past bookings (status != 'booked')
            full_query = base_query + search_condition + " AND pb.status != 'booked' ORDER BY pb.unbooking_time DESC"
            c.execute(full_query, search_params)
            past_bookings = c.fetchall()
        else:
            # Fetch all active bookings
            full_query = base_query + " WHERE pb.status = 'booked' ORDER BY pb.booking_time DESC"
            c.execute(full_query)
            active_bookings = c.fetchall()

            # Fetch all past bookings
            full_query = base_query + " WHERE pb.status != 'booked' ORDER BY pb.unbooking_time DESC"
            c.execute(full_query)
            past_bookings = c.fetchall()

    except DatabaseError as e:
        logger.error(f"Database error in admin_users: {e}")
        return "Error fetching data from database", 500

    return render_template('admin-user.html', active_bookings=active_bookings, past_bookings=past_bookings, query=query)

@app.route('/register_user', methods=['GET', 'POST'])
def register_user():
    if request.method == 'POST':
        email = request.form['email']
        username = request.form['username']
        password = request.form['password']
        fullname = request.form['fullname']
        address = request.form['address']
        pincode = request.form['pincode']
        database.insert_user(email, username, password, fullname, address, pincode)
        return render_template('login.html')
    return render_template('new-user-registration-system.html')

def valid_user(username, password):
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT * FROM users WHERE username = ? AND password = ?', (username, password))
    user = c.fetchone()
    if user:
        return {
            'id': user['id'],
            'email': user['email'],
            'username': user['username'],
            'password': user['password'],
            'fullname': user['fullname'],
            'address': user['address'],
            'pincode': user['pincode']
        }
    return None

@app.route('/user-login', methods=['GET', 'POST'])
def user_login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = valid_user(username, password)
        if user:
            session['user_id'] = user['id']
            session['username'] = username
            return redirect(url_for('user_booking', username=username))
        else:
            return render_template('login.html', error_message="Invalid username or password.")
    response = make_response(render_template('login.html'))
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

def get_user_from_db(username):
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT * FROM users WHERE username = ?', (username,))
    user = c.fetchone()
    if user:
        return {
            'id': user['id'],
            'email': user['email'],
            'username': user['username'],
            'password': user['password'],
            'fullname': user['fullname'],
            'address': user['address'],
            'pincode': user['pincode']
        }
    return None

@app.route('/profile/<username>')
def user_profile(username):
    user = get_user_from_db(username)
    if not user:
        return "User not found", 404
    edit_profile_url = url_for('edit_profile', username=username)
    return render_template('user-profile.html', user=user, edit_profile_url=edit_profile_url)

@app.route('/edit-profile/<username>', methods=['GET', 'POST'])
def edit_profile(username):
    if 'username' not in session or session['username'] != username:
        return redirect(url_for('user_login'))
    
    user = get_user_from_db(username)
    if not user:
        return "User not found", 404
    
    if request.method == 'POST':
        fullname = request.form.get('fullname')
        address = request.form.get('address')
        pincode = request.form.get('pincode')
        email = request.form.get('email')
        
        # Basic validation
        if not all([fullname, address, pincode, email]):
            return render_template('edit-profile.html', user=user, error_message="All fields are required.")
        
        # Email validation
        if not re.match(r"[^@]+@[^@]+\.[^@]+", email):
            return render_template('edit-profile.html', user=user, error_message="Invalid email format.")
        
        # Pincode validation (assuming 6 digits for simplicity)
        if not re.match(r"^\d{6}$", pincode):
            return render_template('edit-profile.html', user=user, error_message="Pincode must be 6 digits.")
        
        try:
            # Update user details in the database
            database.update_user(user['id'], fullname, address, pincode, email)
            flash("Profile updated successfully!", "success")
            return redirect(url_for('user_profile', username=username))
        except DatabaseError as e:
            logger.error(f"Database error in updating profile: {e}")
            return render_template('edit-profile.html', user=user, error_message="An error occurred while updating the profile."), 500
        
    return render_template('edit-profile.html', user=user)

@app.route('/user-booking/<username>', methods=['GET'])
def user_booking(username):
    if 'username' not in session or session['username'] != username:
        return redirect(url_for('user_login'))
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT id, fullname, username FROM users WHERE username = ?', (username,))
    user = c.fetchone()
    if not user:
        return render_template('login.html', message="User not found.")
    user_data = {
        'id': user['id'],
        'fullname': user['fullname'],
        'username': user['username']
    }
    if 'user_id' not in session:
        session['user_id'] = user['id']
    search_query = request.args.get('search', '').strip()
    if search_query:
        c.execute('''
            SELECT * FROM parking_lots
            WHERE LOWER(location_name) LIKE ? OR pincode LIKE ?
        ''', (f'%{search_query.lower()}%', f'%{search_query}%'))
    else:
        c.execute('SELECT * FROM parking_lots')
    lots = c.fetchall()
    parking_lots_with_slots = []
    for lot in lots:
        try:
            c.execute('SELECT id, slot_number, status FROM parking_slots WHERE parking_lot_id = ? ORDER BY slot_number', (lot['id'],))
            slots = c.fetchall()
            parking_lots_with_slots.append((lot, slots))
        except DatabaseError as e:
            logger.error(f"Database error in fetching slots: {e}")
            return "Database error occurred", 500
    # Fetch active bookings for the user
    c.execute('''
        SELECT id, slot_id, lot_id, status
        FROM parking_bookings
        WHERE user_id = ? AND status = 'booked'
    ''', (user_data['id'],))
    bookings = c.fetchall()
    response = make_response(render_template(
        'user-booking.html',
        user=user_data,
        lots=parking_lots_with_slots,
        bookings=bookings
    ))
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

@app.route('/user-logout')
def user_logout():
    session.pop('user_id', None)
    session.pop('username', None)
    return redirect(url_for('user_login'))

@app.route('/book-slot/<lot_id>/<slot_id>', methods=['POST'])
def book_slot_user(lot_id, slot_id):
    if not session.get('user_id'):
        return redirect(url_for('user_login'))
    conn = get_db()
    c = conn.cursor()
    vehicle_number = request.form.get('vehicle_number')
    if not vehicle_number:
        return render_template('user-booking.html', error_message="Please provide your vehicle number.", lot_id=lot_id, username=session.get('username')), 400
    try:
        c.execute('SELECT id, status FROM parking_slots WHERE parking_lot_id = ? AND slot_number = ?',
                  (lot_id, slot_id))
        slot = c.fetchone()
        if not slot or slot['status'] != 'available':
            return render_template('user-booking.html', error_message="Slot is not available", lot_id=lot_id, username=session.get('username')), 400
        # Fetch location_name from parking_lots
        c.execute('SELECT location_name FROM parking_lots WHERE id = ?', (lot_id,))
        location_name = c.fetchone()['location_name']
        c.execute('UPDATE parking_slots SET status = ? WHERE id = ?',
                  ('booked', slot['id']))
        c.execute('INSERT INTO parking_bookings (slot_id, lot_id, user_id, vehicle_number, location_name, status, booking_time) VALUES (?, ?, ?, ?, ?, ?, datetime("now", "+5 hours", "30 minutes"))',
                  (slot['id'], lot_id, session['user_id'], vehicle_number, location_name, 'booked'))
        conn.commit()
    except DatabaseError as e:
        logger.error(f"Database error in booking slot: {e}")
        conn.rollback()
        return render_template('user-booking.html', error_message="An error occurred while booking the slot.", username=session.get('username')), 500
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        return render_template('user-booking.html', error_message="An unexpected error occurred.", username=session.get('username')), 500
    return redirect(url_for('user_booking', username=session.get('username')))

@app.route('/unbook-slot/<lot_id>/<slot_id>', methods=['POST'])
def unbook_slot_user(lot_id, slot_id):
    if not session.get('user_id'):
        return redirect(url_for('user_login'))
    conn = get_db()
    c = conn.cursor()
    try:
        c.execute('''
            SELECT b.id, p.location_name, ps.slot_number, b.vehicle_number, 
                   strftime('%Y-%m-%d %H:%M:%S', b.booking_time) AS booking_time
            FROM parking_bookings b
            LEFT JOIN parking_lots p ON b.lot_id = p.id
            LEFT JOIN parking_slots ps ON b.slot_id = ps.id
            WHERE b.lot_id = ? AND ps.slot_number = ? AND b.user_id = ? AND b.status = 'booked'
        ''', (lot_id, slot_id, session['user_id']))
        booking = c.fetchone()
        if not booking:
            flash("No active booking found for this slot.", "error")
        else:
            # Redirect to receipt page instead of unbooking directly
            return redirect(url_for('unbook_receipt', booking_id=booking['id']))
    except DatabaseError as e:
        logger.error(f"Database error in unbooking slot: {e}")
        flash("An error occurred while processing the unbooking.", "error")
    return redirect(url_for('user_booking', username=session['username']))

@app.route('/user/unbook-receipt/<int:booking_id>', methods=['GET'])
def unbook_receipt(booking_id):
    if 'username' not in session:
        return redirect(url_for('user_login'))
    
    conn = get_db()
    c = conn.cursor()
    try:
        # Fetch booking details
        c.execute('''
            SELECT b.id, b.user_id, b.vehicle_number, b.lot_id, b.slot_id, 
                   strftime('%Y-%m-%d %H:%M:%S', b.booking_time) AS booking_time,
                   b.location_name, ps.slot_number, u.fullname, u.id AS user_id
            FROM parking_bookings b
            JOIN parking_slots ps ON b.slot_id = ps.id
            JOIN users u ON b.user_id = u.id
            WHERE b.id = ? AND b.user_id = ?
        ''', (booking_id, session['user_id']))
        booking = c.fetchone()
        
        if not booking:
            flash("Booking not found or not authorized.", "error")
            return redirect(url_for('user_booking_history', username=session['username']))
        
        # Fetch price per hour
        c.execute('SELECT price_per_hour FROM parking_lots WHERE id = ?', (booking['lot_id'],))
        price_per_hour = c.fetchone()['price_per_hour']
        
        # Calculate total cost
        current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        booking_time = booking['booking_time']
        duration_seconds = (datetime.strptime(current_time, '%Y-%m-%d %H:%M:%S') - 
                           datetime.strptime(booking_time, '%Y-%m-%d %H:%M:%S')).total_seconds()
        
        if duration_seconds <= 0:
            hours = 0
        elif duration_seconds < 3600:
            hours = 1.0
        else:
            hours = duration_seconds / 3600.0
        
        total_cost = price_per_hour * hours
        
        receipt_data = {
            'user_name': booking['fullname'],
            'user_id': booking['user_id'],
            'vehicle_number': booking['vehicle_number'],
            'booking_time': booking_time,
            'unbooking_time': current_time,
            'total_cost': total_cost
        }
        
        return render_template('unbook-receipt.html', receipt_data=receipt_data, booking_id=booking_id)
    except DatabaseError as e:
        logger.error(f"Database error in unbook_receipt: {e}")
        flash("Error fetching receipt data.", "error")
        return redirect(url_for('user_booking_history', username=session['username']))
    except Exception as e:
        logger.error(f"Unexpected error in unbook_receipt: {e}")
        flash("An unexpected error occurred.", "error")
        return redirect(url_for('user_booking_history', username=session['username']))

@app.route('/user/unbook-parking/<int:booking_id>', methods=['POST'])
def unbook_parking(booking_id):
    if 'username' not in session:
        return redirect(url_for('user_login'))
    
    conn = get_db()
    c = conn.cursor()
    try:
        # Fetch booking details
        c.execute('''
            SELECT b.id, b.user_id, b.vehicle_number, b.lot_id, b.slot_id, 
                   strftime('%Y-%m-%d %H:%M:%S', b.booking_time) AS booking_time,
                   b.location_name, ps.slot_number
            FROM parking_bookings b
            JOIN parking_slots ps ON b.slot_id = ps.id
            WHERE b.id = ? AND b.user_id = ?
        ''', (booking_id, session['user_id']))
        booking = c.fetchone()
        
        if not booking:
            flash("Booking not found or not authorized.", "error")
            return redirect(url_for('user_booking_history', username=session['username']))
        
        # Fetch price per hour
        c.execute('SELECT price_per_hour FROM parking_lots WHERE id = ?', (booking['lot_id'],))
        price_per_hour = c.fetchone()['price_per_hour']
        
        # Calculate total cost
        unbooking_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        duration_seconds = (datetime.strptime(unbooking_time, '%Y-%m-%d %H:%M:%S') - 
                           datetime.strptime(booking['booking_time'], '%Y-%m-%d %H:%M:%S')).total_seconds()
        
        if duration_seconds <= 0:
            hours = 0
        elif duration_seconds < 3600:
            hours = 1.0
        else:
            hours = duration_seconds / 3600.0
        
        total_cost = price_per_hour * hours
        
        # Update parking_bookings and parking_slots
        c.execute('''
            UPDATE parking_bookings
            SET status = 'unbooked', 
                unbooking_time = datetime("now", "+5 hours", "30 minutes"),
                total_cost = ?
            WHERE id = ?
        ''', (total_cost, booking_id))
        
        c.execute('''
            UPDATE parking_slots
            SET status = 'available'
            WHERE id = ?
        ''', (booking['slot_id'],))
        
        conn.commit()
        
        # Flash success message
        flash(f"Unbooked successfully! Details:\n"
              f"Parking Lot: {booking['location_name'] or 'N/A'}\n"
              f"Slot Number: {booking['slot_number'] or 'N/A'}\n"
              f"Vehicle Number: {booking['vehicle_number']}\n"
              f"Booking Time: {booking['booking_time']}\n"
              f"Unbooking Time: {unbooking_time}\n"
              f"Total Cost: ₹{total_cost}", "success")
        
        return redirect(url_for('user_summery', username=session['username']))
    except DatabaseError as e:
        logger.error(f"Error during unbooking: {e}")
        conn.rollback()
        flash("An error occurred while unbooking.", "error")
        return redirect(url_for('user_booking_history', username=session['username']))
    except Exception as e:
        logger.error(f"Unexpected error during unbooking: {e}")
        conn.rollback()
        flash("An unexpected error occurred.", "error")
        return redirect(url_for('user_booking_history', username=session['username']))

@app.route('/summery/<username>')
def user_summery(username):
    # Fetch user details
    user = get_user_from_db(username)
    if not user:
        return "User not found", 404

    conn = get_db()
    
    try:
        # Fetch active bookings (status = 'booked')
        active_bookings = conn.execute('''
            SELECT * FROM parking_bookings 
            WHERE user_id = ? AND status = 'booked'
        ''', (user['id'],)).fetchall()

        # Fetch total bookings
        total_bookings = conn.execute('''
            SELECT COUNT(*) as count FROM parking_bookings 
            WHERE user_id = ?
        ''', (user['id'],)).fetchone()['count']

        # Fetch recent bookings (last 5, ordered by booking time)
        recent_bookings = conn.execute('''
            SELECT pb.id, pb.location_name, ps.slot_number, pb.vehicle_number, 
                   strftime('%Y-%m-%d %H:%M:%S', pb.booking_time) AS booking_time, 
                   pb.status
            FROM parking_bookings pb
            JOIN parking_slots ps ON pb.slot_id = ps.id
            WHERE pb.user_id = ?
            ORDER BY pb.booking_time DESC
            LIMIT 5
        ''', (user['id'],)).fetchall()

        # Calculate total cost using total_cost column
        total_cost = conn.execute('''
            SELECT SUM(total_cost) as total
            FROM parking_bookings
            WHERE user_id = ? AND total_cost IS NOT NULL
        ''', (user['id'],)).fetchone()['total'] or 0.0

        # Fetch most booked place
        most_booked = conn.execute('''
            SELECT pb.location_name, COUNT(*) as count
            FROM parking_bookings pb
            WHERE pb.user_id = ?
            GROUP BY pb.location_name
            ORDER BY count DESC
            LIMIT 1
        ''', (user['id'],)).fetchone()

        most_booked_place = most_booked['location_name'] if most_booked else "None"
        most_booked_count = most_booked['count'] if most_booked else 0

        # Generate booking trend chart (bookings per month)
        chart_path = None
        if plt is not None:
            try:
                bookings_per_month = conn.execute('''
                    SELECT strftime('%Y-%m', booking_time) as month, COUNT(*) as count
                    FROM parking_bookings
                    WHERE user_id = ?
                    GROUP BY month
                    ORDER BY month
                ''', (user['id'],)).fetchall()

                if bookings_per_month:  # Only generate chart if there is data
                    months = [row['month'] for row in bookings_per_month]
                    counts = [row['count'] for row in bookings_per_month]
                    
                    plt.figure(figsize=(8, 4))
                    plt.bar(months, counts, color='skyblue')
                    plt.title('Bookings Per Month')
                    plt.xlabel('Month')
                    plt.ylabel('Number of Bookings')
                    plt.xticks(rotation=45)
                    plt.tight_layout()
                    
                    # Save chart to static folder
                    chart_path = f'static/charts/bookings_{username}.png'
                    os.makedirs(os.path.dirname(chart_path), exist_ok=True)
                    plt.savefig(chart_path)
                    plt.close()
                    logger.info(f"Chart generated and saved to {chart_path}")
                else:
                    logger.info("No booking data available for chart generation")
            except Exception as e:
                logger.error(f"Error generating chart: {e}")
                chart_path = None
        else:
            logger.info("Skipping chart generation due to missing Matplotlib")

        return render_template('user-summery.html', 
                            user=user,
                            active_bookings=active_bookings,
                            total_bookings=total_bookings,
                            recent_bookings=recent_bookings,
                            total_cost=total_cost,
                            most_booked_place=most_booked_place,
                            most_booked_count=most_booked_count,
                            chart_path=chart_path)
    except DatabaseError as e:
        logger.error(f"Database error in user_summery: {e}")
        return "Error fetching summary data", 500

# Existing routes (omitted for brevity, assume unchanged unless specified)

@app.route('/admin/parking/edit/<int:lot_id>', methods=['GET', 'POST'])
def edit_parking_lot(lot_id):
    conn = get_db()
    c = conn.cursor()

    if request.method == 'POST':
        location_name = request.form.get('location_name')
        address = request.form.get('address')
        pincode = request.form.get('pincode')
        price_per_hour = request.form.get('price_per_hour')
        max_spots = request.form.get('max_spots')

        # Fetch original data
        c.execute('SELECT * FROM parking_lots WHERE id = ?', (lot_id,))
        lot = c.fetchone()
        c.execute('SELECT COUNT(*) FROM parking_slots WHERE parking_lot_id = ? AND status = "booked"', (lot_id,))
        booked_slots_count = c.fetchone()[0]

        if not all([location_name, address, pincode, price_per_hour, max_spots]):
            flash("All fields are required.", "error")
            return render_template('edit-lot.html', lot=lot, booked_slots_count=booked_slots_count), 400

        try:
            price_per_hour = float(price_per_hour)
            max_spots = int(max_spots)
            if price_per_hour < 0 or max_spots < 0:
                flash("Price and spots must be non-negative.", "error")
                return render_template('edit-lot.html', lot=lot, booked_slots_count=booked_slots_count), 400
            if not re.match(r"^\d{6}$", pincode):
                flash("Pincode must be a 6-digit number.", "error")
                return render_template('edit-lot.html', lot=lot, booked_slots_count=booked_slots_count), 400
        except ValueError:
            flash("Price per hour and max spots must be valid numbers.", "error")
            return render_template('edit-lot.html', lot=lot, booked_slots_count=booked_slots_count), 400

        # Count current slots
        c.execute('SELECT COUNT(*) FROM parking_slots WHERE parking_lot_id = ?', (lot_id,))
        existing_slots = c.fetchone()[0]

        if max_spots < existing_slots:
            # Trying to reduce
            available_slots = existing_slots - booked_slots_count
            slots_to_delete = existing_slots - max_spots

            if booked_slots_count == existing_slots:
                flash("Cannot reduce slots: all slots are currently booked.", "error")
                return render_template('edit-lot.html', lot=lot, booked_slots_count=booked_slots_count), 400

            if slots_to_delete > available_slots:
                flash(f"Cannot reduce slots: only {available_slots} available but need to remove {slots_to_delete}.", "error")
                return render_template('edit-lot.html', lot=lot, booked_slots_count=booked_slots_count), 400

            # Delete specific available slots
            c.execute('''
                DELETE FROM parking_slots
                WHERE id IN (
                    SELECT id FROM parking_slots
                    WHERE parking_lot_id = ? AND status = 'available'
                    ORDER BY slot_number
                    LIMIT ?
                )
            ''', (lot_id, slots_to_delete))

            database.reassign_slot_numbers(conn, lot_id)

        elif max_spots > existing_slots:
            # Add new slots
            for slot_number in range(existing_slots + 1, max_spots + 1):
                c.execute('''
                    INSERT INTO parking_slots (parking_lot_id, slot_number, status)
                    VALUES (?, ?, 'available')
                ''', (lot_id, slot_number))

            database.reassign_slot_numbers(conn, lot_id)

        # Update lot details
        c.execute('''
            UPDATE parking_lots
            SET location_name = ?, address = ?, pincode = ?, price_per_hour = ?, max_spots = ?
            WHERE id = ?
        ''', (location_name, address, pincode, price_per_hour, max_spots, lot_id))

        conn.commit()
        flash("Parking lot updated successfully!", "success")
        return redirect(url_for('admin_dashboard'))

    # GET method
    c.execute('SELECT * FROM parking_lots WHERE id = ?', (lot_id,))
    lot = c.fetchone()
    c.execute('SELECT COUNT(*) FROM parking_slots WHERE parking_lot_id = ? AND status = "booked"', (lot_id,))
    booked_slots_count = c.fetchone()[0]
    return render_template('edit-lot.html', lot=lot, booked_slots_count=booked_slots_count)

@app.route('/manage-slot/<int:slot_id>', methods=['GET', 'POST'])
def manage_slot(slot_id):
    conn = get_db()
    c = conn.cursor()
    if request.method == 'POST':
        new_status = request.form.get('status')
        c.execute('UPDATE parking_slots SET status = ? WHERE id = ?', (new_status, slot_id))
        conn.commit()
        return redirect(url_for('admin_dashboard'))
    c.execute('SELECT id, slot_number, status FROM parking_slots WHERE id = ?', (slot_id,))
    slot = c.fetchone()
    return render_template('manage_slot.html', slot=slot)

def get_db():
    if 'db' not in g:
        logger.info("Opening database connection for request")
        g.db = database.get_db_connection()
    return g.db

@app.teardown_appcontext
def close_db(error):
    if hasattr(g, 'db'):
        logger.info("Closing database connection for request")
        g.db.close()

# Existing routes (omitted for brevity, assume unchanged unless specified)

@app.route('/admin/parking/delete/<int:lot_id>', methods=['POST'])
def delete_parking_lot(lot_id):
    if 'admin_id' not in session:
        logger.info("No admin_id in session, redirecting to admin_login")
        return redirect(url_for('admin_login'))
    
    conn = get_db()
    c = conn.cursor()
    try:
        logger.info(f"Checking booked slots for parking_lot_id: {lot_id}")
        c.execute('SELECT COUNT(*) FROM parking_slots WHERE parking_lot_id = ? AND status = "booked"', (lot_id,))
        booked_slots = c.fetchone()[0]
        logger.info(f"Found {booked_slots} booked slots for lot_id: {lot_id}")
        if booked_slots > 0:
            flash(f"Cannot delete parking lot: {booked_slots} slot(s) are currently booked.", "error")
            return redirect(url_for('admin_dashboard'))
        
        logger.info(f"No booked slots for lot_id: {lot_id}, redirecting to confirmation")
        return redirect(url_for('delete_parking_lot_confirm', lot_id=lot_id))
    except DatabaseError as e:
        logger.error(f"Database error in delete_parking_lot for lot_id {lot_id}: {e}")
        conn.rollback()
        flash(f"Database error: {str(e)}", "error")
        return redirect(url_for('admin_dashboard'))
    except Exception as e:
        logger.error(f"Unexpected error in delete_parking_lot for lot_id {lot_id}: {e}")
        conn.rollback()
        flash(f"Unexpected error: {str(e)}", "error")
        return redirect(url_for('admin_dashboard'))

# In app.py, within the delete_parking_lot_confirm route
@app.route('/admin/parking/delete-confirm/<int:lot_id>', methods=['GET', 'POST'])
def delete_parking_lot_confirm(lot_id):
    if 'admin_id' not in session:
        logger.info("No admin_id in session, redirecting to admin_login")
        return redirect(url_for('admin_login'))
    
    conn = get_db()
    c = conn.cursor()
    
    try:
        logger.info(f"Fetching parking lot details for lot_id: {lot_id}")
        c.execute('SELECT id, location_name, address, pincode, max_spots FROM parking_lots WHERE id = ?', (lot_id,))
        lot = c.fetchone()
        if not lot:
            logger.warning(f"Parking lot not found for lot_id: {lot_id}")
            flash("Parking lot not found.", "error")
            return redirect(url_for('admin_dashboard'))
        
        # Count booked slots
        c.execute('SELECT COUNT(*) FROM parking_slots WHERE parking_lot_id = ? AND status = "booked"', (lot_id,))
        booked_slots_count = c.fetchone()[0]
        logger.info(f"Booked slots for lot_id {lot_id}: {booked_slots_count}")
        
        if request.method == 'POST':
            # Double-check for booked slots to prevent race conditions
            c.execute('SELECT COUNT(*) FROM parking_slots WHERE parking_lot_id = ? AND status = "booked"', (lot_id,))
            booked_slots = c.fetchone()[0]
            logger.info(f"Confirmation check: Found {booked_slots} booked slots for lot_id: {lot_id}")
            if booked_slots > 0:
                flash(f"Cannot delete parking lot: {booked_slots} slot(s) are currently booked.", "error")
                return redirect(url_for('admin_dashboard'))
            
            # Perform deletion in a transaction
            logger.info(f"Deleting parking lot with lot_id: {lot_id}")
            try:
                c.execute('DELETE FROM parking_bookings WHERE lot_id = ?', (lot_id,))
                c.execute('DELETE FROM parking_slots WHERE parking_lot_id = ?', (lot_id,))
                c.execute('DELETE FROM parking_lots WHERE id = ?', (lot_id,))
                conn.commit()
                logger.info(f"Successfully deleted parking lot with lot_id: {lot_id}")
                flash("Parking lot deleted successfully!", "success")
            except IntegrityError as e:
                conn.rollback()
                logger.error(f"Integrity error during deletion for lot_id {lot_id}: {e}")
                flash(f"Cannot delete parking lot due to database constraints: {str(e)}", "error")
                return redirect(url_for('admin_dashboard'))
            except DatabaseError as e:
                conn.rollback()
                logger.error(f"Database error during deletion for lot_id {lot_id}: {e}")
                flash(f"Database error during deletion: {str(e)}", "error")
                return redirect(url_for('admin_dashboard'))
            
            return redirect(url_for('admin_dashboard'))
        
        # GET: Render confirmation page
        logger.info(f"Rendering delete confirmation page for lot_id: {lot_id}")
        # Fetch only active bookings
        c.execute('''
            SELECT b.id, b.user_id, b.vehicle_number, b.slot_id, 
                   strftime('%Y-%m-%d %H:%M:%S', b.booking_time) AS booking_time,
                   strftime('%Y-%m-%d %H:%M:%S', b.unbooking_time) AS unbooking_time,
                   b.total_cost, b.status, COALESCE(u.fullname, 'Unknown') AS fullname, 
                   COALESCE(ps.slot_number, 0) AS slot_number
            FROM parking_bookings b
            LEFT JOIN users u ON b.user_id = u.id
            LEFT JOIN parking_slots ps ON b.slot_id = ps.id
            WHERE b.lot_id = ? AND b.status = 'booked'
            ORDER BY b.booking_time DESC
        ''', (lot_id,))
        bookings = c.fetchall()
        
        return render_template('delete-confirmation.html', lot=lot, bookings=bookings, booked_slots_count=booked_slots_count)
    
    except TemplateError as e:
        logger.error(f"Template error in delete_parking_lot_confirm for lot_id {lot_id}: {e}")
        flash(f"Template error: {str(e)}", "error")
        return redirect(url_for('admin_dashboard'))
    except DatabaseError as e:
        logger.error(f"Database error in delete_parking_lot_confirm for lot_id {lot_id}: {e}")
        conn.rollback()
        flash(f"Database error: {str(e)}", "error")
        return redirect(url_for('admin_dashboard'))
    except Exception as e:
        logger.error(f"Unexpected error in delete_parking_lot_confirm for lot_id {lot_id}: {e}")
        conn.rollback()
        flash(f"Unexpected error: {str(e)}", "error")
        return redirect(url_for('admin_dashboard'))

@app.route('/admin-view-booking/<lot_id>/<slot_id>')
def admin_view_booking(lot_id, slot_id):
    conn = get_db()
    c = conn.cursor()
    try:
        c.execute('''SELECT s.slot_number, b.vehicle_number, u.fullname, u.email, 
                            strftime('%Y-%m-%d %H:%M:%S', b.booking_time) AS booking_time
                     FROM parking_slots s
                     JOIN parking_bookings b ON s.id = b.slot_id
                     JOIN users u ON b.user_id = u.id
                     WHERE s.parking_lot_id = ? AND s.id = ? AND b.status = 'booked' ''', (lot_id, slot_id))
        booking_details = c.fetchone()
        if not booking_details:
            return render_template('booking-not-found.html'), 404

        c.execute('SELECT id, location_name, address, pincode, price_per_hour FROM parking_lots WHERE id = ?', (lot_id,))
        lot_details = c.fetchone()
        booking_data = {
            'slot_number': booking_details['slot_number'],
            'vehicle_number': booking_details['vehicle_number'],
            'user_fullname': booking_details['fullname'],
            'user_email': booking_details['email'],
            'booking_time': booking_details['booking_time']
        }
        lot_data = {
            'id': lot_details['id'],
            'location_name': lot_details['location_name'],
            'address': lot_details['address'],
            'pincode': lot_details['pincode'],
            'price_per_hour': lot_details['price_per_hour']
        }
        return render_template('admin-view-booking.html', booking_data=booking_data, lot=lot_data)
    except DatabaseError as e:
        logger.error(f"Database error: {e}")
        return "Error fetching booking data", 500

@app.route('/user/<username>/booking-history', methods=['GET'])
def user_booking_history(username):
    if 'username' not in session or session['username'] != username:
        return redirect(url_for('user_login'))
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT id, fullname, username FROM users WHERE username = ?', (username,))
    user = c.fetchone()
    if not user:
        return render_template('login.html', message="User not found.")
    user_data = {
        'id': user['id'],
        'fullname': user['fullname'],
        'username': user['username']
    }
    c.execute('''
        SELECT b.id, b.location_name, ps.slot_number, b.vehicle_number, 
               strftime('%Y-%m-%d %H:%M:%S', b.booking_time) AS booking_time, 
               b.status, 
               strftime('%Y-%m-%d %H:%M:%S', b.unbooking_time) AS unbooking_time
        FROM parking_bookings b
        LEFT JOIN parking_slots ps ON b.slot_id = ps.id
        WHERE b.user_id = ? AND b.status = 'booked'
    ''', (user_data['id'],))
    active_bookings = c.fetchall()
    c.execute('''
        SELECT b.id, b.location_name, ps.slot_number, b.vehicle_number, 
               strftime('%Y-%m-%d %H:%M:%S', b.booking_time) AS booking_time, 
               b.status, 
               strftime('%Y-%m-%d %H:%M:%S', b.unbooking_time) AS unbooking_time
        FROM parking_bookings b
        LEFT JOIN parking_slots ps ON b.slot_id = ps.id
        WHERE b.user_id = ? AND b.status = 'unbooked'
    ''', (user_data['id'],))
    all_bookings = c.fetchall()
    response = make_response(render_template('user-booking-history.html', user=user_data, active_bookings=active_bookings, all_bookings=all_bookings))
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response

@app.route('/admin-summery')
def admin_summery():
    # Check if admin is logged in
    if 'admin_id' not in session:
        return redirect(url_for('admin_login'))

    conn = get_db()
    
    try:
        # Fetch system overview
        total_parking_lots = conn.execute('SELECT COUNT(*) as count FROM parking_lots').fetchone()['count']
        total_users = conn.execute('SELECT COUNT(*) as count FROM users').fetchone()['count']

        # Fetch active bookings (status = 'booked')
        active_bookings = conn.execute('''
            SELECT * FROM parking_bookings 
            WHERE status = 'booked'
        ''').fetchall()

        # Fetch total bookings
        total_bookings = conn.execute('SELECT COUNT(*) as count FROM parking_bookings').fetchone()['count']

        # Calculate total revenue using total_cost column
        total_revenue = conn.execute('''
            SELECT SUM(total_cost) as total
            FROM parking_bookings
            WHERE total_cost IS NOT NULL
        ''').fetchone()['total'] or 0.0

        # Fetch most booked parking lot
        most_booked = conn.execute('''
            SELECT pb.location_name, COUNT(*) as count
            FROM parking_bookings pb
            GROUP BY pb.location_name
            ORDER BY count DESC
            LIMIT 1
        ''').fetchone()

        most_booked_lot = most_booked['location_name'] if most_booked else "None"
        most_booked_count = most_booked['count'] if most_booked else 0

        # Fetch recent bookings (last 5, ordered by booking time)
        recent_bookings = conn.execute('''
            SELECT pb.id, pb.location_name, ps.slot_number, pb.vehicle_number, 
                   strftime('%Y-%m-%d %H:%M:%S', pb.booking_time) AS booking_time, 
                   pb.status, u.fullname
            FROM parking_bookings pb
            JOIN parking_slots ps ON pb.slot_id = ps.id
            JOIN users u ON pb.user_id = u.id
            ORDER BY pb.booking_time DESC
            LIMIT 5
        ''').fetchall()

        # Generate booking trend chart (bookings per month)
        chart_path = None
        if plt is not None:
            try:
                bookings_per_month = conn.execute('''
                    SELECT strftime('%Y-%m', booking_time) as month, COUNT(*) as count
                    FROM parking_bookings
                    GROUP BY month
                    ORDER BY month
                ''').fetchall()

                if bookings_per_month:  # Only generate chart if there is data
                    months = [row['month'] for row in bookings_per_month]
                    counts = [row['count'] for row in bookings_per_month]
                    
                    plt.figure(figsize=(8, 4))
                    plt.bar(months, counts, color='skyblue')
                    plt.title('System-Wide Bookings Per Month')
                    plt.xlabel('Month')
                    plt.ylabel('Number of Bookings')
                    plt.xticks(rotation=45)
                    plt.tight_layout()
                    
                    # Save chart to static folder
                    chart_path = 'static/charts/admin_bookings.png'
                    os.makedirs(os.path.dirname(chart_path), exist_ok=True)
                    plt.savefig(chart_path)
                    plt.close()
                    logger.info(f"Chart generated and saved to {chart_path}")
                else:
                    logger.info("No booking data available for chart generation")
            except Exception as e:
                logger.error(f"Error generating chart: {e}")
                chart_path = None
        else:
            logger.info("Skipping chart generation due to missing Matplotlib")

        return render_template('admin-summery.html',
                            total_parking_lots=total_parking_lots,
                            total_users=total_users,
                            active_bookings=active_bookings,
                            total_bookings=total_bookings,
                            total_revenue=total_revenue,
                            most_booked_lot=most_booked_lot,
                            most_booked_count=most_booked_count,
                            recent_bookings=recent_bookings,
                            chart_path=chart_path)
    except DatabaseError as e:
        logger.error(f"Database error in admin_summery: {e}")
        return "Error fetching summary data", 500

@app.route('/add-parking-lot')
def add_parking_lot():
    return render_template('new-parking-lot.html')

@app.route('/submit-location', methods=['POST'])
def submit_location():
    location_name = request.form['location_name']
    address = request.form['address']
    pincode = request.form['pincode']
    price_per_hour = float(request.form['price_per_hour'])
    max_spots = int(request.form['max_spots'])
    database.insert_parking_lot(location_name, address, pincode, price_per_hour, max_spots)
    return redirect(url_for('admin_dashboard'))


@app.route("/booking/<int:slot_id>")
def booking_detail(slot_id):
    booking = get_booking_by_id(slot_id)
    if not booking:
        return render_template("booking-not-found.html"), 404
    return render_template("booking-detail.html", booking=booking)


if __name__ == '__main__':
    app.run(debug=True)