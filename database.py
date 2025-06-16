import sqlite3

def get_db_connection():
    conn = sqlite3.connect('parking_app.db')
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Initialize the database, create tables, insert default data, and migrate schema."""
    conn = get_db_connection()
    c = conn.cursor()

    # Create admin table
    c.execute(''' 
        CREATE TABLE IF NOT EXISTS admin (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL,
            password TEXT NOT NULL
        )
    ''')

    # Insert default admin if not exists
    c.execute("SELECT * FROM admin WHERE username = ?", ('admin',))
    if not c.fetchone():
        c.execute('INSERT INTO admin (username, password) VALUES (?, ?)', ('admin', 'admin123'))

    # Create users table
    c.execute(''' 
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL,
            username TEXT NOT NULL,
            password TEXT NOT NULL,
            fullname TEXT NOT NULL,
            address TEXT NOT NULL,
            pincode TEXT NOT NULL,
            slot_id INTEGER
        )
    ''')

    # Create parking_lots table
    c.execute(''' 
        CREATE TABLE IF NOT EXISTS parking_lots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            location_name TEXT NOT NULL,
            address TEXT NOT NULL,
            pincode TEXT NOT NULL,
            price_per_hour REAL NOT NULL,
            max_spots INTEGER NOT NULL
        )
    ''')

    # Create parking_slots table
    c.execute(''' 
        CREATE TABLE IF NOT EXISTS parking_slots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            parking_lot_id INTEGER NOT NULL,
            slot_number INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'available',
            FOREIGN KEY (parking_lot_id) REFERENCES parking_lots(id)
        )
    ''')

    # Create parking_bookings table
    c.execute(''' 
        CREATE TABLE IF NOT EXISTS parking_bookings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            slot_id INTEGER NOT NULL,
            lot_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            vehicle_number TEXT NOT NULL,
            location_name TEXT,
            status TEXT NOT NULL DEFAULT 'booked',
            booking_time TIMESTAMP DEFAULT (datetime('now', '+5 hours', '30 minutes')),
            unbooking_time TIMESTAMP,
            total_cost REAL,
            FOREIGN KEY (slot_id) REFERENCES parking_slots(id),
            FOREIGN KEY (lot_id) REFERENCES parking_lots(id),
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    ''')

    # Migrate existing database: Add location_name column if not exists
    c.execute("PRAGMA table_info(parking_bookings)")
    columns = [col['name'] for col in c.fetchall()]
    if 'location_name' not in columns:
        c.execute('ALTER TABLE parking_bookings ADD COLUMN location_name TEXT')

    # Migrate existing database: Add total_cost column if not exists
    if 'total_cost' not in columns:
        c.execute('ALTER TABLE parking_bookings ADD COLUMN total_cost REAL')

    # Populate location_name for existing bookings
    c.execute('''
        UPDATE parking_bookings
        SET location_name = (
            SELECT location_name
            FROM parking_lots
            WHERE parking_lots.id = parking_bookings.lot_id
        )
        WHERE location_name IS NULL
    ''')

    # Migrate existing booking_time to IST
    c.execute('''
        UPDATE parking_bookings
        SET booking_time = datetime(booking_time, '+5 hours', '30 minutes')
        WHERE booking_time IS NOT NULL
    ''')

    conn.commit()
    conn.close()

def insert_user(email, username, password, fullname, address, pincode):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute(''' 
        INSERT INTO users (email, username, password, fullname, address, pincode)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (email, username, password, fullname, address, pincode))
    conn.commit()
    conn.close()

def insert_parking_lot(location_name, address, pincode, price_per_hour, max_spots):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute(''' 
        INSERT INTO parking_lots (location_name, address, pincode, price_per_hour, max_spots)
        VALUES (?, ?, ?, ?, ?)
    ''', (location_name, address, pincode, price_per_hour, max_spots))
    lot_id = c.lastrowid
    for slot_number in range(1, max_spots + 1):
        c.execute(''' 
            INSERT INTO parking_slots (parking_lot_id, slot_number, status)
            VALUES (?, ?, 'available')
        ''', (lot_id, slot_number))
    conn.commit()
    conn.close()

def update_user(user_id, fullname, address, pincode, email, slot_id=None):
    """Update user details in the database, optionally updating slot_id."""
    conn = get_db_connection()
    c = conn.cursor()
    if slot_id is not None:
        c.execute(''' 
            UPDATE users
            SET fullname = ?, address = ?, pincode = ?, email = ?, slot_id = ?
            WHERE id = ?
        ''', (fullname, address, pincode, email, slot_id, user_id))
    else:
        c.execute(''' 
            UPDATE users
            SET fullname = ?, address = ?, pincode = ?, email = ?
            WHERE id = ?
        ''', (fullname, address, pincode, email, user_id))
    conn.commit()
    conn.close()

def has_booked_slots(conn, parking_lot_id):
    """Check if any slots in the parking lot are booked."""
    c = conn.cursor()
    c.execute('SELECT COUNT(*) FROM parking_slots WHERE parking_lot_id = ? AND status = "booked"', (parking_lot_id,))
    count = c.fetchone()[0]
    return count > 0

def reassign_slot_numbers(conn, parking_lot_id):
    """Reassign slot numbers in chronological order for a parking lot."""
    c = conn.cursor()
    c.execute('SELECT id, status FROM parking_slots WHERE parking_lot_id = ? ORDER BY slot_number', (parking_lot_id,))
    slots = c.fetchall()
    for index, slot in enumerate(slots, start=1):
        c.execute('UPDATE parking_slots SET slot_number = ? WHERE id = ?', (index, slot['id']))
    conn.commit()






def get_booking_by_id(slot_id):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('''
        SELECT b.id, b.vehicle_number, b.booking_time, b.unbooking_time, b.status, 
               b.total_cost, ps.slot_number, pl.location_name, u.fullname, u.email
        FROM parking_bookings b
        JOIN parking_slots ps ON b.slot_id = ps.id
        JOIN parking_lots pl ON b.lot_id = pl.id
        JOIN users u ON b.user_id = u.id
        WHERE b.slot_id = ?
        ORDER BY b.booking_time DESC
        LIMIT 1
    ''', (slot_id,))
    booking = c.fetchone()
    conn.close()
    return booking





# Initialize the database
init_db()