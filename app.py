from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from datetime import datetime, timedelta
from functools import wraps
from sqlalchemy import func, desc
import os
import json

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key-change-this-later'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///store.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = 'static/uploads'
app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024  # 5MB max

# Create upload folder if not exists
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}

db = SQLAlchemy(app)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# Models
class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    price = db.Column(db.Float, nullable=False)
    cost = db.Column(db.Float, default=0)
    image = db.Column(db.String(200))
    category = db.Column(db.String(50))
    stock = db.Column(db.Integer, default=10)
    featured = db.Column(db.Boolean, default=False)
    sales_count = db.Column(db.Integer, default=0)
    reviews = db.relationship('Review', backref='product', lazy=True, cascade='all, delete-orphan')
    
    @property
    def average_rating(self):
        if not self.reviews:
            return 0
        return sum(r.rating for r in self.reviews) / len(self.reviews)
    
    @property
    def total_revenue(self):
        return self.sales_count * self.price
    
    @property
    def total_profit(self):
        return self.sales_count * (self.price - self.cost)

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=False)
    phone = db.Column(db.String(20))
    password = db.Column(db.String(200), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_active = db.Column(db.Boolean, default=True)
    orders = db.relationship('Order', backref='user', lazy=True)
    reviews = db.relationship('Review', backref='user', lazy=True)
    
    @property
    def total_spent(self):
        return sum(order.total for order in self.orders if order.status == 'delivered')
    
    @property
    def orders_count(self):
        return len(self.orders)

class Order(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    customer_name = db.Column(db.String(100), nullable=False)
    phone = db.Column(db.String(20), nullable=False)
    email = db.Column(db.String(100))
    address = db.Column(db.Text, nullable=False)
    items = db.Column(db.Text, nullable=False)
    total = db.Column(db.Float, nullable=False)
    status = db.Column(db.String(20), default='pending')
    date = db.Column(db.DateTime, default=datetime.utcnow)
    
    @property
    def profit(self):
        items = json.loads(self.items)
        total_profit = 0
        for item in items:
            product = Product.query.get(item['id'])
            if product:
                profit_per_item = (product.price - product.cost) * item['quantity']
                total_profit += profit_per_item
        return total_profit

class Admin(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)

class Review(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    rating = db.Column(db.Integer, nullable=False)
    comment = db.Column(db.Text)
    date = db.Column(db.DateTime, default=datetime.utcnow)

class Wishlist(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    added_date = db.Column(db.DateTime, default=datetime.utcnow)

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('يجب تسجيل الدخول أولاً', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('admin_logged_in'):
            return redirect(url_for('admin_login'))
        return f(*args, **kwargs)
    return decorated_function

@app.route('/')
def index():
    search = request.args.get('search', '')
    category = request.args.get('category', '')
    
    query = Product.query
    
    if search:
        query = query.filter(Product.name.contains(search) | Product.description.contains(search))
    
    if category:
        query = query.filter(Product.category == category)
    
    products = query.all()
    featured_products = Product.query.filter_by(featured=True).limit(4).all()
    best_sellers = Product.query.order_by(desc(Product.sales_count)).limit(6).all()
    categories = db.session.query(Product.category).distinct().all()
    categories = [c[0] for c in categories if c[0]]
    
    return render_template('index.html', products=products, featured_products=featured_products, 
                         categories=categories, current_category=category, search_query=search,
                         best_sellers=best_sellers)

@app.route('/product/<int:id>')
def product_detail(id):
    product = Product.query.get_or_404(id)
    reviews = Review.query.filter_by(product_id=id).order_by(Review.date.desc()).all()
    
    is_in_wishlist = False
    if 'user_id' in session:
        is_in_wishlist = Wishlist.query.filter_by(user_id=session['user_id'], product_id=id).first() is not None
    
    return render_template('product_detail.html', product=product, reviews=reviews, is_in_wishlist=is_in_wishlist)

@app.route('/add_review/<int:product_id>', methods=['POST'])
@login_required
def add_review(product_id):
    rating = int(request.form['rating'])
    comment = request.form['comment']
    
    existing = Review.query.filter_by(user_id=session['user_id'], product_id=product_id).first()
    if existing:
        flash('لقد قمت بتقييم هذا المنتج من قبل', 'warning')
        return redirect(url_for('product_detail', id=product_id))
    
    review = Review(
        product_id=product_id,
        user_id=session['user_id'],
        rating=rating,
        comment=comment
    )
    db.session.add(review)
    db.session.commit()
    flash('تم إضافة تقييمك بنجاح!', 'success')
    return redirect(url_for('product_detail', id=product_id))

@app.route('/wishlist')
@login_required
def wishlist():
    wishlist_items = db.session.query(Product).join(Wishlist).filter(
        Wishlist.user_id == session['user_id']
    ).all()
    return render_template('wishlist.html', products=wishlist_items)

@app.route('/add_to_wishlist/<int:id>')
@login_required
def add_to_wishlist(id):
    existing = Wishlist.query.filter_by(user_id=session['user_id'], product_id=id).first()
    if existing:
        flash('المنتج موجود بالفعل في المفضلة', 'info')
    else:
        wishlist_item = Wishlist(user_id=session['user_id'], product_id=id)
        db.session.add(wishlist_item)
        db.session.commit()
        flash('تم إضافة المنتج للمفضلة!', 'success')
    return redirect(request.referrer or url_for('index'))

@app.route('/remove_from_wishlist/<int:id>')
@login_required
def remove_from_wishlist(id):
    item = Wishlist.query.filter_by(user_id=session['user_id'], product_id=id).first()
    if item:
        db.session.delete(item)
        db.session.commit()
        flash('تم حذف المنتج من المفضلة', 'info')
    return redirect(url_for('wishlist'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name = request.form['name']
        email = request.form['email']
        phone = request.form['phone']
        password = request.form['password']
        
        if User.query.filter_by(email=email).first():
            flash('البريد الإلكتروني مستخدم بالفعل', 'danger')
            return redirect(url_for('register'))
        
        user = User(
            name=name,
            email=email,
            phone=phone,
            password=generate_password_hash(password)
        )
        db.session.add(user)
        db.session.commit()
        
        flash('تم التسجيل بنجاح! يمكنك تسجيل الدخول الآن', 'success')
        return redirect(url_for('login'))
    
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        
        user = User.query.filter_by(email=email).first()
        
        if user and check_password_hash(user.password, password):
            if not user.is_active:
                flash('حسابك معطل. تواصل مع الإدارة', 'danger')
                return redirect(url_for('login'))
            
            session['user_id'] = user.id
            session['user_name'] = user.name
            flash(f'أهلاً {user.name}!', 'success')
            return redirect(url_for('index'))
        else:
            flash('البريد الإلكتروني أو كلمة المرور غير صحيحة', 'danger')
    
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('user_id', None)
    session.pop('user_name', None)
    flash('تم تسجيل الخروج', 'info')
    return redirect(url_for('index'))

@app.route('/profile')
@login_required
def profile():
    user = User.query.get(session['user_id'])
    orders = Order.query.filter_by(user_id=user.id).order_by(Order.date.desc()).all()
    return render_template('profile.html', user=user, orders=orders)

@app.route('/add_to_cart/<int:id>')
def add_to_cart(id):
    product = Product.query.get_or_404(id)
    cart = session.get('cart', [])
    
    found = False
    for item in cart:
        if item['id'] == id:
            item['quantity'] += 1
            found = True
            break
    
    if not found:
        cart.append({
            'id': product.id,
            'name': product.name,
            'price': product.price,
            'image': product.image,
            'quantity': 1
        })
    
    session['cart'] = cart
    flash('تم إضافة المنتج للسلة!', 'success')
    return redirect(url_for('index'))

@app.route('/cart')
def cart():
    cart = session.get('cart', [])
    total = sum(item['price'] * item['quantity'] for item in cart)
    return render_template('cart.html', cart=cart, total=total)

@app.route('/remove_from_cart/<int:id>')
def remove_from_cart(id):
    cart = session.get('cart', [])
    cart = [item for item in cart if item['id'] != id]
    session['cart'] = cart
    flash('تم حذف المنتج من السلة', 'info')
    return redirect(url_for('cart'))

@app.route('/checkout', methods=['GET', 'POST'])
def checkout():
    cart = session.get('cart', [])
    if not cart:
        flash('السلة فارغة!', 'warning')
        return redirect(url_for('index'))
    
    total = sum(item['price'] * item['quantity'] for item in cart)
    
    if request.method == 'POST':
        order = Order(
            user_id=session.get('user_id'),
            customer_name=request.form['name'],
            phone=request.form['phone'],
            email=request.form.get('email', ''),
            address=request.form['address'],
            items=json.dumps(cart),
            total=total
        )
        db.session.add(order)
        
        for item in cart:
            product = Product.query.get(item['id'])
            if product:
                product.sales_count += item['quantity']
                product.stock -= item['quantity']
        
        db.session.commit()
        
        session['cart'] = []
        flash('تم إرسال طلبك بنجاح! سنتواصل معك قريباً', 'success')
        return redirect(url_for('order_success', order_id=order.id))
    
    user = None
    if 'user_id' in session:
        user = User.query.get(session['user_id'])
    
    return render_template('checkout.html', cart=cart, total=total, user=user)

@app.route('/order_success/<int:order_id>')
def order_success(order_id):
    order = Order.query.get_or_404(order_id)
    return render_template('order_success.html', order=order)

@app.route('/whatsapp_order')
def whatsapp_order():
    cart = session.get('cart', [])
    if not cart:
        return redirect(url_for('index'))
    
    message = "السلام عليكم، أريد طلب:\n\n"
    total = 0
    for item in cart:
        message += f"• {item['name']} - الكمية: {item['quantity']} - السعر: {item['price']} جنيه\n"
        total += item['price'] * item['quantity']
    
    message += f"\nالإجمالي: {total} جنيه"
    
    whatsapp_number = "201234567890"
    whatsapp_url = f"https://wa.me/{whatsapp_number}?text={message}"
    
    return redirect(whatsapp_url)

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        admin = Admin.query.filter_by(username=username).first()
        
        if admin and check_password_hash(admin.password, password):
            session['admin_logged_in'] = True
            session['admin_username'] = username
            return redirect(url_for('admin_dashboard'))
        else:
            flash('اسم المستخدم أو كلمة المرور خاطئة', 'danger')
    
    return render_template('admin_login.html')

@app.route('/admin/logout')
def admin_logout():
    session.pop('admin_logged_in', None)
    session.pop('admin_username', None)
    return redirect(url_for('index'))

@app.route('/admin/dashboard')
@admin_required
def admin_dashboard():
    total_orders = Order.query.count()
    total_revenue = db.session.query(func.sum(Order.total)).filter(Order.status.in_(['delivered', 'shipped'])).scalar() or 0
    total_customers = User.query.count()
    pending_orders = Order.query.filter_by(status='pending').count()
    
    delivered_orders = Order.query.filter_by(status='delivered').all()
    total_profit = sum(order.profit for order in delivered_orders)
    
    recent_orders = Order.query.order_by(Order.date.desc()).limit(10).all()
    
    top_products = Product.query.order_by(desc(Product.sales_count)).limit(5).all()
    
    today = datetime.now().date()
    daily_sales = []
    for i in range(6, -1, -1):
        date = today - timedelta(days=i)
        start = datetime.combine(date, datetime.min.time())
        end = datetime.combine(date, datetime.max.time())
        
        day_revenue = db.session.query(func.sum(Order.total)).filter(
            Order.date.between(start, end),
            Order.status.in_(['delivered', 'shipped'])
        ).scalar() or 0
        
        daily_sales.append({
            'date': date.strftime('%Y-%m-%d'),
            'revenue': float(day_revenue)
        })
    
    return render_template('admin_dashboard.html', 
                         total_orders=total_orders,
                         total_revenue=total_revenue,
                         total_profit=total_profit,
                         total_customers=total_customers,
                         pending_orders=pending_orders,
                         recent_orders=recent_orders,
                         top_products=top_products,
                         daily_sales=daily_sales)

@app.route('/admin/orders')
@admin_required
def admin_orders():
    orders = Order.query.order_by(Order.date.desc()).all()
    return render_template('admin_orders.html', orders=orders)

@app.route('/admin/customers')
@admin_required
def admin_customers():
    customers = User.query.order_by(User.created_at.desc()).all()
    return render_template('admin_customers.html', customers=customers)

@app.route('/admin/customer/<int:id>/toggle_status')
@admin_required
def toggle_customer_status(id):
    customer = User.query.get_or_404(id)
    customer.is_active = not customer.is_active
    db.session.commit()
    status = 'تفعيل' if customer.is_active else 'تعطيل'
    flash(f'تم {status} حساب {customer.name}', 'success')
    return redirect(url_for('admin_customers'))

@app.route('/admin/reports')
@admin_required
def admin_reports():
    products = Product.query.all()
    
    category_profits = db.session.query(
        Product.category,
        func.sum(Product.sales_count * (Product.price - Product.cost)).label('profit')
    ).group_by(Product.category).all()
    
    total_profit = sum(p.total_profit for p in products)
    total_revenue = sum(p.total_revenue for p in products)
    total_cost = sum(p.sales_count * p.cost for p in products)
    
    return render_template('admin_reports.html',
                         products=products,
                         category_profits=category_profits,
                         total_profit=total_profit,
                         total_revenue=total_revenue,
                         total_cost=total_cost)

@app.route('/admin/order/<int:id>/update_status', methods=['POST'])
@admin_required
def update_order_status(id):
    order = Order.query.get_or_404(id)
    order.status = request.json['status']
    db.session.commit()
    return jsonify({'success': True})

@app.route('/admin/products')
@admin_required
def admin_products():
    products = Product.query.all()
    return render_template('admin_products.html', products=products)

@app.route('/admin/add_product', methods=['GET', 'POST'])
@admin_required
def add_product():
    if request.method == 'POST':
        image_path = None
        if 'image_file' in request.files:
            file = request.files['image_file']
            if file and file.filename and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                filename = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{filename}"
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                image_path = f"/static/uploads/{filename}"
        
        if not image_path:
            image_path = request.form.get('image_url', '')
        
        product = Product(
            name=request.form['name'],
            description=request.form['description'],
            price=float(request.form['price']),
            cost=float(request.form.get('cost', 0)),
            image=image_path,
            category=request.form['category'],
            stock=int(request.form['stock']),
            featured='featured' in request.form
        )
        db.session.add(product)
        db.session.commit()
        flash('تم إضافة المنتج بنجاح!', 'success')
        return redirect(url_for('admin_products'))
    
    return render_template('add_product.html')

@app.route('/admin/product/<int:id>/edit', methods=['GET', 'POST'])
@admin_required
def edit_product(id):
    product = Product.query.get_or_404(id)
    
    if request.method == 'POST':
        product.name = request.form['name']
        product.description = request.form['description']
        product.price = float(request.form['price'])
        product.cost = float(request.form.get('cost', 0))
        product.category = request.form['category']
        product.stock = int(request.form['stock'])
        product.featured = 'featured' in request.form
        
        if 'image_file' in request.files:
            file = request.files['image_file']
            if file and file.filename and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                filename = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{filename}"
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                product.image = f"/static/uploads/{filename}"
        elif request.form.get('image_url'):
            product.image = request.form['image_url']
        
        db.session.commit()
        flash('تم تحديث المنتج بنجاح!', 'success')
        return redirect(url_for('admin_products'))
    
    return render_template('edit_product.html', product=product)

@app.route('/admin/product/<int:id>/delete')
@admin_required
def delete_product(id):
    product = Product.query.get_or_404(id)
    db.session.delete(product)
    db.session.commit()
    flash('تم حذف المنتج', 'success')
    return redirect(url_for('admin_products'))

@app.route('/admin/product/<int:id>/toggle_featured')
@admin_required
def toggle_featured(id):
    product = Product.query.get_or_404(id)
    product.featured = not product.featured
    db.session.commit()
    flash('تم تحديث حالة العرض الخاص', 'success')
    return redirect(url_for('admin_products'))

def init_db():
    with app.app_context():
        db.create_all()
        
        if not Admin.query.filter_by(username='admin').first():
            admin = Admin(
                username='admin',
                password=generate_password_hash('admin123')
            )
            db.session.add(admin)
        
        if Product.query.count() == 0:
            sample_products = [
                Product(name='دمية باربي', description='دمية باربي جميلة للأطفال', price=150, cost=80,
                       image='https://images.unsplash.com/photo-1558618666-fcd25c85cd64?w=400', category='دمى', featured=True, sales_count=45),
                Product(name='سيارة ريموت كنترول', description='سيارة سباق بريموت كنترول', price=300, cost=180,
                       image='https://images.unsplash.com/photo-1558544956-f2a45c81f5a6?w=400', category='سيارات', featured=True, sales_count=38),
                Product(name='مكعبات تركيب', description='مكعبات ليجو ملونة', price=200, cost=120,
                       image='https://images.unsplash.com/photo-1587654780291-39c9404d746b?w=400', category='تعليمية', sales_count=52),
                Product(name='طائرة ورقية', description='طائرة ورقية ملونة', price=50, cost=25,
                       image='https://images.unsplash.com/photo-1559827260-dc66d52bef19?w=400', category='خارجية', sales_count=67),
                Product(name='دفتر تلوين', description='دفتر تلوين مع أقلام', price=80, cost=40,
                       image='https://images.unsplash.com/photo-1513542789411-b6a5d4f31634?w=400', category='فنية', sales_count=29),
                Product(name='كرة قدم', description='كرة قدم احترافية للأطفال', price=120, cost=70,
                       image='https://images.unsplash.com/photo-1614632537197-38a17061c2bd?w=400', category='رياضية', featured=True, sales_count=41),
            ]
            for product in sample_products:
                db.session.add(product)
        
        db.session.commit()
        print("Database initialized!")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
