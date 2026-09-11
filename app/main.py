import os, uuid
from datetime import datetime, date, timedelta
from fastapi import FastAPI, Request, HTTPException, Depends, Form
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import text
from dotenv import load_dotenv
ROOT=os.path.dirname(os.path.dirname(__file__))
load_dotenv(os.path.join(ROOT,'.env'))
from .db import db, init_schema, q, one, scalar, cash_balance, cash_move, audit
from .security import verify_password, make_session, read_session, hash_password

app=FastAPI(title='SHAKWEER NET Web POS',version='2.0.0')
app.mount('/static',StaticFiles(directory=os.path.join(ROOT,'static')),name='static')
templates=Jinja2Templates(directory=os.path.join(ROOT,'templates'))
init_schema()

PAGES=[
 ('dashboard','الرئيسية','perm_pos'),('pos','المبيعات والكاشير','perm_pos'),('products','المخزون','perm_inventory'),
 ('customers','العملاء والديون','perm_customers'),('maintenance','الصيانة','perm_maintenance'),('cashbox','الخزنة','perm_pos'),
 ('returns','المرتجعات','perm_pos'),('expenses','المصروفات','perm_expenses'),('attendance','الحضور وساعات العمل','perm_payroll'),('employees','الموظفون','perm_payroll'),('payroll','الرواتب والسلف','perm_payroll'),
 ('faults','أعطال الإنترنت','perm_pos'),('orders','الطلبات','perm_pos'),('advances','السلف','perm_pos'),('bands','الباندات والسرعات','perm_pos'),('reports','التقارير','perm_reports'),
 ('stock','حركات المخزون','perm_inventory'),('users','المستخدمون','perm_audit'),('audit','سجل التدقيق','perm_audit'),('settings','الإعدادات','perm_audit')]

def current_user(request:Request,s:Session):
    tok=request.cookies.get('shakweer_session'); data=read_session(tok) if tok else None
    return one(s,'SELECT * FROM users WHERE id=:id AND is_active=1',{'id':data['id']}) if data else None

def require_user(request,s):
    u=current_user(request,s)
    if not u: raise HTTPException(401,'يجب تسجيل الدخول')
    return u

def require_admin(u):
    if u['role']!='admin': raise HTTPException(403,'صلاحية المدير مطلوبة')

def allowed(u,perm): return u['role']=='admin' or bool(u.get(perm,0))
def need(u,perm):
    if not allowed(u,perm): raise HTTPException(403,'لا تملك صلاحية هذه الشاشة')

def now_start_end():
    d=date.today(); return f'{d} 00:00:00',f'{d} 23:59:59'

def product_rows(s): return q(s,"""SELECT p.*,c.name category_name FROM products p LEFT JOIN categories c ON c.id=p.category_id ORDER BY p.id DESC""")

@app.get('/',response_class=HTMLResponse)
def home(request:Request,s:Session=Depends(db)):
    u=current_user(request,s)
    if not u:return RedirectResponse('/login',303)
    return templates.TemplateResponse('index.html',{'request':request,'user':u,'pages':PAGES})
@app.get('/login',response_class=HTMLResponse)
def login_page(request:Request): return templates.TemplateResponse('login.html',{'request':request})
@app.post('/login')
def login(request:Request,username:str=Form(...),password:str=Form(...),s:Session=Depends(db)):
    u=one(s,'SELECT * FROM users WHERE username=:u AND is_active=1',{'u':username})
    if not u or not verify_password(password,u['password_hash']): return RedirectResponse('/login?error=1',303)
    if len(u['password_hash'])==64:
        s.execute(text('UPDATE users SET password_hash=:p WHERE id=:id'),{'p':hash_password(password),'id':u['id']})
        s.commit()
    audit(s,u['id'],'تسجيل دخول','دخول إلى النظام'); s.commit()
    r=RedirectResponse('/',303); r.set_cookie('shakweer_session',make_session(u['id']),httponly=True,samesite='lax',max_age=86400); return r
@app.post('/logout')
def logout():
    r=RedirectResponse('/login',303); r.delete_cookie('shakweer_session'); return r

@app.get('/api/me')
def me(request:Request,s:Session=Depends(db)): return require_user(request,s)

@app.get('/api/dashboard')
def dashboard(request:Request,s:Session=Depends(db)):
    u=require_user(request,s); start,end=now_start_end()
    return {'balance':cash_balance(s),'cash_in':float(scalar(s,"SELECT COALESCE(SUM(amount),0) FROM cash_transactions WHERE direction='in' AND created_at BETWEEN :a AND :b",{'a':start,'b':end}) or 0),'cash_out':float(scalar(s,"SELECT COALESCE(SUM(amount),0) FROM cash_transactions WHERE direction='out' AND created_at BETWEEN :a AND :b",{'a':start,'b':end}) or 0),'sales':float(scalar(s,"SELECT COALESCE(SUM(total_amount),0) FROM sales_invoices WHERE created_at BETWEEN :a AND :b",{'a':start,'b':end}) or 0),'ready_maintenance':int(scalar(s,"SELECT COUNT(*) FROM maintenance_tickets WHERE status='repaired'") or 0),'faults':int(scalar(s,"SELECT COUNT(*) FROM net_faults WHERE status!='تم الحل'") or 0),'low_stock':int(scalar(s,"SELECT COUNT(*) FROM products WHERE stock_qty<=min_stock") or 0),'credit_invoices':int(scalar(s,"SELECT COUNT(*) FROM sales_invoices WHERE remaining_amount>0") or 0),'notifications':q(s,"""SELECT 'cash_out' kind,'صرف نقدي' title,COALESCE(SUM(amount),0) amount FROM cash_transactions WHERE direction='out' AND created_at BETWEEN :a AND :b UNION ALL SELECT 'cash_in','دخل نقدي',COALESCE(SUM(amount),0) FROM cash_transactions WHERE direction='in' AND created_at BETWEEN :a AND :b UNION ALL SELECT 'ready','صيانة جاهزة',COUNT(*) FROM maintenance_tickets WHERE status='repaired' UNION ALL SELECT 'low','مخزون منخفض',COUNT(*) FROM products WHERE stock_qty<=min_stock UNION ALL SELECT 'fault','أعطال إنترنت',COUNT(*) FROM net_faults WHERE status!='تم الحل' UNION ALL SELECT 'credit','فواتير آجلة',COUNT(*) FROM sales_invoices WHERE remaining_amount>0""",{'a':start,'b':end})}

@app.get('/api/products')
def products(request:Request,s:Session=Depends(db)):
    u=require_user(request,s); need(u,'perm_inventory'); return product_rows(s)
@app.get('/api/categories')
def categories(request:Request,s:Session=Depends(db)):
    require_user(request,s); return q(s,'SELECT * FROM categories ORDER BY name')
@app.post('/api/products')
async def create_product(request:Request,s:Session=Depends(db)):
    u=require_user(request,s); need(u,'perm_inventory'); d=await request.json()
    try:
        r=s.execute(text("INSERT INTO products(barcode,name,category_id,unit,cost_price,sell_price,stock_qty,min_stock) VALUES(:b,:n,:c,:u,:cp,:sp,:q,:m) RETURNING id"),{'b':d['barcode'],'n':d['name'],'c':d.get('category_id'),'u':d.get('unit','قطعة'),'cp':float(d.get('cost_price',0)),'sp':float(d.get('sell_price',0)),'q':float(d.get('stock_qty',0)),'m':float(d.get('min_stock',5))}).first()
        audit(s,u['id'],'إضافة منتج',d['name']); s.commit(); return {'id':r[0] if r else scalar(s,'SELECT last_insert_rowid()')}
    except Exception as e: s.rollback(); raise HTTPException(400,'الباركود موجود أو البيانات غير صحيحة')
@app.put('/api/products/{pid}')
async def update_product(pid:int,request:Request,s:Session=Depends(db)):
    u=require_user(request,s); need(u,'perm_inventory'); d=await request.json()
    s.execute(text('UPDATE products SET barcode=:b,name=:n,category_id=:c,unit=:u,cost_price=:cp,sell_price=:sp,stock_qty=:q,min_stock=:m WHERE id=:id'),{'b':d['barcode'],'n':d['name'],'c':d.get('category_id'),'u':d.get('unit','قطعة'),'cp':float(d.get('cost_price',0)),'sp':float(d.get('sell_price',0)),'q':float(d.get('stock_qty',0)),'m':float(d.get('min_stock',5)),'id':pid}); audit(s,u['id'],'تعديل منتج',str(pid)); s.commit(); return {'ok':True}

@app.get('/api/pos/products')
def pos_products(request:Request,s:Session=Depends(db)):
    u=require_user(request,s); need(u,'perm_pos'); return product_rows(s)
@app.post('/api/pos/sale')
async def create_sale(request:Request,s:Session=Depends(db)):
    u=require_user(request,s); need(u,'perm_pos'); d=await request.json(); items=d.get('items',[])
    if not items: raise HTTPException(400,'أضف منتجًا واحدًا على الأقل')
    try:
        subtotal=0; normalized=[]
        for it in items:
            p=one(s,'SELECT * FROM products WHERE id=:id',{'id':int(it['product_id'])})
            if not p: raise HTTPException(400,'منتج غير موجود')
            qty=float(it['quantity']); price=float(it.get('unit_price',p['sell_price']))
            if qty<=0 or float(p['stock_qty'])<qty: raise HTTPException(400,f"المخزون غير كافٍ: {p['name']}")
            total=qty*price; subtotal+=total; normalized.append((p,qty,price,total))
        discount=max(0,float(d.get('discount',0))); tax_amount=max(0,float(d.get('tax_amount',0))); total=max(0,subtotal-discount+tax_amount); paid=float(d.get('paid',total if d.get('payment_type','cash')=='cash' else 0));
        if paid<0 or paid>total: raise HTTPException(400,'المبلغ المدفوع غير صحيح')
        remaining=total-paid; cust=d.get('customer_id'); inv=f"INV-{datetime.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:4].upper()}"
        r=s.execute(text("INSERT INTO sales_invoices(invoice_number,customer_id,user_id,payment_type,payment_method,subtotal,discount_amount,tax_amount,total_amount,paid_amount,remaining_amount,notes) VALUES(:n,:c,:u,:pt,:pm,:sub,:dis,:tax,:tot,:paid,:rem,:notes) RETURNING id"),{'n':inv,'c':cust,'u':u['id'],'pt':d.get('payment_type','cash'),'pm':d.get('payment_method','cash'),'sub':subtotal,'dis':discount,'tax':float(d.get('tax_amount',0)),'tot':total,'paid':paid,'rem':remaining,'notes':d.get('notes','')}).first(); sid=r[0]
        for p,qty,price,itotal in normalized:
            s.execute(text("INSERT INTO sales_items(invoice_id,product_id,quantity,unit_price,cost_price,total_price) VALUES(:i,:p,:q,:up,:cp,:t)"),{'i':sid,'p':p['id'],'q':qty,'up':price,'cp':p['cost_price'],'t':itotal})
            s.execute(text("UPDATE products SET stock_qty=stock_qty-:q WHERE id=:id AND stock_qty>=:q"),{'q':qty,'id':p['id']})
            s.execute(text("INSERT INTO stock_movements(product_id,quantity,movement_type,reference_type,reference_id,notes,user_id) VALUES(:p,:q,'out','sale',:rid,'بيع',:u)"),{'p':p['id'],'q':-qty,'rid':sid,'u':u['id']})
        if cust and remaining>0:s.execute(text('UPDATE customers SET balance=balance+:v WHERE id=:id'),{'v':remaining,'id':cust})
        if paid>0: cash_move(s,'in',paid,'مبيعات','فاتورة مبيعات',u['id'],inv,'sale',sid)
        audit(s,u['id'],'بيع',inv); s.commit(); return {'ok':True,'invoice_number':inv,'total':total,'paid':paid,'remaining':remaining}
    except HTTPException: s.rollback(); raise
    except Exception as e: s.rollback(); raise HTTPException(400,'تعذر حفظ الفاتورة')

@app.get('/api/sales')
def sales(request:Request,s:Session=Depends(db)):
    u=require_user(request,s); need(u,'perm_pos'); return q(s,"""SELECT s.*,c.name customer_name,u.full_name user_name FROM sales_invoices s LEFT JOIN customers c ON c.id=s.customer_id LEFT JOIN users u ON u.id=s.user_id ORDER BY s.id DESC LIMIT 500""")
@app.get('/api/sales/{invoice_number}/items')
def sale_items(invoice_number:str,request:Request,s:Session=Depends(db)):
    u=require_user(request,s); need(u,'perm_pos'); return q(s,"""SELECT si.*,p.name,p.barcode FROM sales_items si JOIN sales_invoices s ON s.id=si.invoice_id JOIN products p ON p.id=si.product_id WHERE s.invoice_number=:n""",{'n':invoice_number})

@app.get('/api/customers')
def customers(request:Request,s:Session=Depends(db)):
    u=require_user(request,s); need(u,'perm_customers'); return q(s,'SELECT * FROM customers ORDER BY id DESC')
@app.post('/api/customers')
async def create_customer(request:Request,s:Session=Depends(db)):
    u=require_user(request,s); need(u,'perm_customers'); d=await request.json(); r=s.execute(text('INSERT INTO customers(name,phone,address,balance) VALUES(:n,:p,:a,0) RETURNING id'),{'n':d['name'],'p':d.get('phone',''),'a':d.get('address','')}).first(); audit(s,u['id'],'إضافة عميل',d['name']); s.commit(); return {'id':r[0]}
@app.post('/api/customers/{cid}/payment')
async def customer_payment(cid:int,request:Request,s:Session=Depends(db)):
    u=require_user(request,s); need(u,'perm_customers'); d=await request.json(); amount=float(d['amount']); c=one(s,'SELECT * FROM customers WHERE id=:id',{'id':cid})
    if not c or amount<=0 or amount>float(c['balance']): raise HTTPException(400,'مبلغ السداد غير صحيح')
    r=s.execute(text('INSERT INTO customer_payments(customer_id,user_id,amount,notes) VALUES(:c,:u,:a,:n) RETURNING id'),{'c':cid,'u':u['id'],'a':amount,'n':d.get('notes','')}).first(); s.execute(text('UPDATE customers SET balance=balance-:a WHERE id=:id'),{'a':amount,'id':cid}); cash_move(s,'in',amount,'تحصيل ديون','سداد عميل',u['id'],d.get('notes',''),'customer_payment',r[0]); audit(s,u['id'],'سداد عميل',str(cid)); s.commit(); return {'ok':True}

@app.get('/api/cashbox')
def cashbox(request:Request,s:Session=Depends(db)):
    u=require_user(request,s); need(u,'perm_pos'); start,end=now_start_end(); return {'balance':cash_balance(s),'today_in':float(scalar(s,"SELECT COALESCE(SUM(amount),0) FROM cash_transactions WHERE direction='in' AND created_at BETWEEN :a AND :b",{'a':start,'b':end}) or 0),'today_out':float(scalar(s,"SELECT COALESCE(SUM(amount),0) FROM cash_transactions WHERE direction='out' AND created_at BETWEEN :a AND :b",{'a':start,'b':end}) or 0),'rows':q(s,"""SELECT ct.*,u.full_name user_name FROM cash_transactions ct LEFT JOIN users u ON u.id=ct.user_id ORDER BY ct.id DESC LIMIT 500""")}
@app.post('/api/cashbox/move')
async def cashbox_move(request:Request,s:Session=Depends(db)):
    u=require_user(request,s); need(u,'perm_pos'); d=await request.json(); a=float(d.get('amount',0)); direction=d.get('direction');
    if a<=0 or direction not in ('in','out'): raise HTTPException(400,'حركة غير صحيحة')
    if direction=='out' and cash_balance(s)<a: raise HTTPException(400,'الرصيد الحالي لا يسمح بهذه المصروفات')
    cash_move(s,direction,a,d.get('category','يدوي'),'حركة خزنة',u['id'],d.get('notes',''),'manual',None); audit(s,u['id'],'حركة خزنة',f'{direction} {a}'); s.commit(); return {'ok':True}

@app.get('/api/maintenance')
def maintenance(request:Request,s:Session=Depends(db)):
    u=require_user(request,s); need(u,'perm_maintenance'); return q(s,"""SELECT t.*,c.name customer_name,c.phone customer_phone,u.full_name user_name,COALESCE((SELECT SUM(amount) FROM maintenance_payments mp WHERE mp.ticket_id=t.id),0) paid_total FROM maintenance_tickets t JOIN customers c ON c.id=t.customer_id JOIN users u ON u.id=t.user_id ORDER BY t.id DESC LIMIT 500""")
@app.post('/api/maintenance')
async def create_maintenance(request:Request,s:Session=Depends(db)):
    u=require_user(request,s); need(u,'perm_maintenance'); d=await request.json(); cust=int(d['customer_id']); ticket=next_no(s,'MT-')
    r=s.execute(text("""INSERT INTO maintenance_tickets(ticket_number,customer_id,device_type,device_model,serial_imei,problem_desc,accessories,status,estimated_cost,discount_amount,prepaid_amount,final_cost,technician_notes,user_id) VALUES(:t,:c,:dt,:dm,:si,:pd,:a,'received',:ec,:dis,:pre,:fc,:tn,:u) RETURNING id"""),{'t':ticket,'c':cust,'dt':d['device_type'],'dm':d['device_model'],'si':d.get('serial_imei',''),'pd':d['problem_desc'],'a':d.get('accessories',''),'ec':float(d.get('estimated_cost',0)),'dis':float(d.get('discount',0)),'pre':float(d.get('prepaid',0)),'fc':float(d.get('final_cost',0)),'tn':d.get('technician_notes',''),'u':u['id']}).first(); tid=r[0]
    pre=float(d.get('prepaid',0));
    if pre>0:
        r2=s.execute(text('INSERT INTO maintenance_payments(ticket_id,user_id,amount,notes) VALUES(:t,:u,:a,:n) RETURNING id'),{'t':tid,'u':u['id'],'a':pre,'n':'مقدم عند الاستلام'}).first(); cash_move(s,'in',pre,'صيانة','مقدم صيانة',u['id'],ticket,'maintenance_prepaid',tid)
    audit(s,u['id'],'فتح صيانة',ticket); s.commit(); return {'ok':True,'ticket_number':ticket}
@app.patch('/api/maintenance/{tid}/status')
async def maintenance_status(tid:int,request:Request,s:Session=Depends(db)):
    u=require_user(request,s); need(u,'perm_maintenance'); d=await request.json(); status=d.get('status');
    if status not in ('received','in_progress','waiting_parts','repaired','delivered','cancelled'): raise HTTPException(400,'حالة غير صحيحة')
    s.execute(text("UPDATE maintenance_tickets SET status=:st,delivered_at=CASE WHEN :st='delivered' THEN CURRENT_TIMESTAMP ELSE delivered_at END WHERE id=:id"),{'st':status,'id':tid}); audit(s,u['id'],'تغيير حالة صيانة',f'{tid}:{status}'); s.commit(); return {'ok':True}
@app.post('/api/maintenance/{tid}/payment')
async def maintenance_payment(tid:int,request:Request,s:Session=Depends(db)):
    u=require_user(request,s); need(u,'perm_maintenance'); d=await request.json(); a=float(d['amount']); t=one(s,'SELECT * FROM maintenance_tickets WHERE id=:id',{'id':tid})
    if not t or a<=0: raise HTTPException(400,'دفعة غير صحيحة')
    paid=float(scalar(s,'SELECT COALESCE(SUM(amount),0) FROM maintenance_payments WHERE ticket_id=:id',{'id':tid}) or 0); due=max(0,float(t['final_cost'])-paid)
    if a>due: raise HTTPException(400,'المبلغ أكبر من المتبقي')
    r=s.execute(text('INSERT INTO maintenance_payments(ticket_id,user_id,amount,notes) VALUES(:t,:u,:a,:n) RETURNING id'),{'t':tid,'u':u['id'],'a':a,'n':d.get('notes','')}).first(); cash_move(s,'in',a,'صيانة','تحصيل صيانة',u['id'],d.get('notes',''),'maintenance_payment',r[0]); audit(s,u['id'],'تحصيل صيانة',str(tid)); s.commit(); return {'ok':True}

@app.get('/api/returns')
def returns(request:Request,s:Session=Depends(db)):
    u=require_user(request,s); need(u,'perm_pos'); return q(s,"""SELECT r.*,p.name product_name FROM product_returns r LEFT JOIN products p ON p.id=r.product_id ORDER BY r.id DESC LIMIT 500""")
@app.post('/api/returns')
async def create_return(request:Request,s:Session=Depends(db)):
    u=require_user(request,s); need(u,'perm_pos'); d=await request.json(); inv=d['invoice_number']; pid=int(d['product_id']); qty=float(d['quantity']);
    sold=one(s,"""SELECT si.*,s.total_amount,s.paid_amount FROM sales_items si JOIN sales_invoices s ON s.id=si.invoice_id WHERE s.invoice_number=:n AND si.product_id=:p""",{'n':inv,'p':pid})
    if not sold or qty<=0: raise HTTPException(400,'المنتج غير موجود على الفاتورة')
    already=float(scalar(s,'SELECT COALESCE(SUM(quantity),0) FROM product_returns WHERE invoice_number=:n AND product_id=:p',{'n':inv,'p':pid}) or 0)
    if qty>float(sold['quantity'])-already: raise HTTPException(400,'الكمية المرتجعة أكبر من المسموح')
    refund=qty*float(sold['unit_price']); paid_refund=min(refund,float(sold['paid_amount']));
    r=s.execute(text('INSERT INTO product_returns(invoice_number,product_id,quantity,refund_amount,reason,user_id) VALUES(:n,:p,:q,:a,:r,:u) RETURNING id'),{'n':inv,'p':pid,'q':qty,'a':paid_refund,'r':d.get('reason',''),'u':u['id']}).first(); s.execute(text('UPDATE products SET stock_qty=stock_qty+:q WHERE id=:p'),{'q':qty,'p':pid}); s.execute(text("INSERT INTO stock_movements(product_id,quantity,movement_type,reference_type,reference_id,notes,user_id) VALUES(:p,:q,'in','return',:rid,:n,:u)"),{'p':pid,'q':qty,'rid':r[0],'n':d.get('reason','مرتجع'),'u':u['id']});
    if paid_refund: cash_move(s,'out',paid_refund,'مرتجع','مرتجع مبيعات',u['id'],d.get('reason',''),'return',r[0])
    audit(s,u['id'],'مرتجع',inv); s.commit(); return {'ok':True,'refund':paid_refund}

@app.get('/api/expenses')
def expenses(request:Request,s:Session=Depends(db)):
    u=require_user(request,s); need(u,'perm_expenses'); return q(s,"SELECT e.*,u.full_name FROM expenses e JOIN users u ON u.id=e.user_id ORDER BY e.id DESC LIMIT 500")
@app.post('/api/expenses')
async def create_expense(request:Request,s:Session=Depends(db)):
    u=require_user(request,s); need(u,'perm_expenses'); d=await request.json(); a=float(d['amount']);
    if a<=0 or cash_balance(s)<a: raise HTTPException(400,'الرصيد لا يكفي')
    r=s.execute(text('INSERT INTO expenses(user_id,category,amount,notes) VALUES(:u,:c,:a,:n) RETURNING id'),{'u':u['id'],'c':d['category'],'a':a,'n':d.get('notes','')}).first(); cash_move(s,'out',a,'مصروف',d['category'],u['id'],d.get('notes',''),'expense',r[0]); audit(s,u['id'],'مصروف',d['category']); s.commit(); return {'ok':True}

@app.get('/api/attendance')
def attendance(request:Request,s:Session=Depends(db)):
    u=require_user(request,s); need(u,'perm_payroll')
    rows=q(s,"SELECT a.*,u.full_name FROM attendance a JOIN users u ON u.id=a.user_id ORDER BY a.id DESC LIMIT 1000")
    openrow=one(s,"SELECT a.*,u.full_name FROM attendance a JOIN users u ON u.id=a.user_id WHERE a.user_id=:u AND a.clock_out IS NULL ORDER BY a.id DESC LIMIT 1",{'u':u['id']})
    today=one(s,"SELECT COALESCE(SUM(total_hours),0) hours,COALESCE(SUM(total_wage),0) wage FROM attendance WHERE user_id=:u AND DATE(clock_in)=DATE(CURRENT_TIMESTAMP)",{'u':u['id']})
    return {'rows':rows,'status':{'on_shift':bool(openrow),'current':openrow,'today_hours':float(today['hours'] or 0),'today_wage':float(today['wage'] or 0)}}
@app.post('/api/attendance/clock')
async def clock(request:Request,s:Session=Depends(db)):
    u=require_user(request,s); need(u,'perm_pos'); d=await request.json(); action=d.get('action')
    openrow=one(s,'SELECT * FROM attendance WHERE user_id=:u AND clock_out IS NULL ORDER BY id DESC LIMIT 1',{'u':u['id']})
    if action=='in' and not openrow:
        s.execute(text('INSERT INTO attendance(user_id,clock_in,hourly_rate) VALUES(:u,CURRENT_TIMESTAMP,:r)'),{'u':u['id'],'r':float(u.get('hourly_rate',0))})
    elif action=='out' and openrow:
        if s.bind.dialect.name=='postgresql':
            sql="UPDATE attendance SET clock_out=CURRENT_TIMESTAMP,total_hours=ROUND((EXTRACT(EPOCH FROM (CURRENT_TIMESTAMP-clock_in))/3600)::numeric,2),total_wage=ROUND((EXTRACT(EPOCH FROM (CURRENT_TIMESTAMP-clock_in))/3600*hourly_rate)::numeric,2) WHERE id=:id"
        else:
            sql="UPDATE attendance SET clock_out=CURRENT_TIMESTAMP,total_hours=ROUND((julianday(CURRENT_TIMESTAMP)-julianday(clock_in))*24,2),total_wage=ROUND((julianday(CURRENT_TIMESTAMP)-julianday(clock_in))*24*hourly_rate,2) WHERE id=:id"
        s.execute(text(sql),{'id':openrow['id']})
    else: raise HTTPException(400,'الحالة غير صحيحة')
    audit(s,u['id'],'حضور',action); s.commit(); return {'ok':True}
@app.post('/api/attendance/settle')
async def settle_wage(request:Request,s:Session=Depends(db)):
    u=require_user(request,s); need(u,'perm_payroll'); d=await request.json(); amount=float(d['amount']); target=int(d.get('user_id',u['id']))
    if amount<=0 or cash_balance(s)<amount: raise HTTPException(400,'المبلغ غير صحيح أو الخزنة لا تكفي')
    r=s.execute(text('INSERT INTO weekly_wages(user_id,amount,period_start,period_end) VALUES(:u,:a,:ps,:pe) RETURNING id'),{'u':target,'a':amount,'ps':d.get('period_start'),'pe':d.get('period_end')}).first(); cash_move(s,'out',amount,'رواتب','تسوية أجور أسبوعية',u['id'],'','attendance_wage',r[0]); audit(s,u['id'],'صرف أجر أسبوعي',str(target)); s.commit(); return {'ok':True}

@app.get('/api/faults')
def faults(request:Request,s:Session=Depends(db)):
    u=require_user(request,s); need(u,'perm_pos'); return q(s,'SELECT * FROM net_faults ORDER BY id DESC LIMIT 500')
@app.post('/api/faults')
async def create_fault(request:Request,s:Session=Depends(db)):
    u=require_user(request,s); need(u,'perm_pos'); d=await request.json(); r=s.execute(text('INSERT INTO net_faults(subscriber_name,phone,fault_desc,status,priority) VALUES(:n,:p,:d,:st,:pr) RETURNING id'),{'n':d['subscriber_name'],'p':d.get('phone',''),'d':d['fault_desc'],'st':d.get('status','معلق'),'pr':d.get('priority','متوسط')}).first(); audit(s,u['id'],'عطل إنترنت',d['subscriber_name']); s.commit(); return {'ok':True,'id':r[0]}
@app.get('/api/orders')
def orders(request:Request,s:Session=Depends(db)):
    u=require_user(request,s); need(u,'perm_pos'); return q(s,'SELECT * FROM daily_orders ORDER BY id DESC LIMIT 500')
@app.post('/api/orders')
async def create_order(request:Request,s:Session=Depends(db)):
    u=require_user(request,s); need(u,'perm_pos'); d=await request.json(); r=s.execute(text('INSERT INTO daily_orders(order_details,status,customer_name,phone,amount,priority,due_at,notes) VALUES(:d,:st,:cn,:ph,:am,:pr,:due,:no) RETURNING id'),{'d':d['order_details'],'st':d.get('status','جديد'),'cn':d.get('customer_name',''),'ph':d.get('phone',''),'am':float(d.get('amount',0)),'pr':d.get('priority','عادي'),'due':d.get('due_at'),'no':d.get('notes','')}).first(); audit(s,u['id'],'طلب',d['order_details']); s.commit(); return {'ok':True,'id':r[0]}

@app.get('/api/advances')
def advances(request:Request,s:Session=Depends(db)):
    u=require_user(request,s); need(u,'perm_pos'); return q(s,'SELECT a.*,u.full_name FROM cashier_advances a JOIN users u ON u.id=a.user_id ORDER BY a.id DESC LIMIT 500')
@app.post('/api/advances')
async def create_advance(request:Request,s:Session=Depends(db)):
    u=require_user(request,s); need(u,'perm_pos'); d=await request.json(); a=float(d['amount']); target=int(d.get('user_id',u['id']))
    if a<=0 or cash_balance(s)<a: raise HTTPException(400,'الرصيد لا يكفي')
    r=s.execute(text('INSERT INTO cashier_advances(user_id,amount,notes) VALUES(:u,:a,:n) RETURNING id'),{'u':target,'a':a,'n':d.get('notes','')}).first(); cash_move(s,'out',a,'سلفة','سلفة كاشير',u['id'],d.get('notes',''),'advance',r[0]); audit(s,u['id'],'سلفة',str(target)); s.commit(); return {'ok':True,'id':r[0]}

@app.get('/api/reports')
def reports(request:Request,s:Session=Depends(db)):
    u=require_user(request,s); need(u,'perm_reports'); return {'sales_by_day':q(s,"SELECT DATE(created_at) day,COUNT(*) invoices,COALESCE(SUM(total_amount),0) total,COALESCE(SUM(paid_amount),0) paid FROM sales_invoices GROUP BY DATE(created_at) ORDER BY day DESC LIMIT 90"),'cash_by_day':q(s,"SELECT DATE(created_at) day,SUM(CASE WHEN direction='in' THEN amount ELSE 0 END) cash_in,SUM(CASE WHEN direction='out' THEN amount ELSE 0 END) cash_out FROM cash_transactions GROUP BY DATE(created_at) ORDER BY day DESC LIMIT 90"),'maintenance':q(s,"SELECT status,COUNT(*) count FROM maintenance_tickets GROUP BY status"),'stock':q(s,"SELECT id,barcode,name,stock_qty,min_stock,sell_price FROM products WHERE stock_qty<=min_stock ORDER BY stock_qty ASC LIMIT 100")}

@app.get('/api/users')
def users(request:Request,s:Session=Depends(db)):
    u=require_user(request,s); require_admin(u); return q(s,'SELECT id,username,full_name,role,is_active,created_at,perm_pos,perm_maintenance,perm_inventory,perm_customers,perm_expenses,perm_payroll,perm_reports,perm_audit FROM users ORDER BY id DESC')
@app.post('/api/users')
async def create_user(request:Request,s:Session=Depends(db)):
    u=require_user(request,s); require_admin(u); d=await request.json();
    try:
        r=s.execute(text('INSERT INTO users(username,password_hash,full_name,role,is_active,perm_pos,perm_maintenance,perm_inventory,perm_customers,perm_expenses,perm_payroll,perm_reports,perm_audit) VALUES(:un,:p,:fn,:r,1,:pp,:pm,:pi,:pc,:pe,:ppy,:pr,:pa) RETURNING id'),{'un':d['username'],'p':hash_password(d['password']),'fn':d['full_name'],'r':d.get('role','cashier'),'pp':int(d.get('perm_pos',1)),'pm':int(d.get('perm_maintenance',1)),'pi':int(d.get('perm_inventory',0)),'pc':int(d.get('perm_customers',1)),'pe':int(d.get('perm_expenses',0)),'ppy':int(d.get('perm_payroll',0)),'pr':int(d.get('perm_reports',0)),'pa':int(d.get('perm_audit',0))}).first(); audit(s,u['id'],'إضافة مستخدم',d['username']); s.commit(); return {'id':r[0]}
    except Exception: s.rollback(); raise HTTPException(400,'اسم المستخدم مستخدم بالفعل')
@app.patch('/api/users/{uid}')
async def update_user(uid:int,request:Request,s:Session=Depends(db)):
    u=require_user(request,s); require_admin(u); d=await request.json();
    fields=['full_name','role','is_active','perm_pos','perm_maintenance','perm_inventory','perm_customers','perm_expenses','perm_payroll','perm_reports','perm_audit']; vals={k:d[k] for k in fields if k in d};
    if vals:
        sets=','.join(f'{k}=:{k}' for k in vals); vals['id']=uid; s.execute(text(f'UPDATE users SET {sets} WHERE id=:id'),vals)
    if d.get('password'): s.execute(text('UPDATE users SET password_hash=:p WHERE id=:id'),{'p':hash_password(d['password']),'id':uid})
    audit(s,u['id'],'تعديل مستخدم',str(uid)); s.commit(); return {'ok':True}

@app.get('/api/audit')
def audit_api(request:Request,s:Session=Depends(db)):
    u=require_user(request,s); require_admin(u); return q(s,'SELECT a.*,u.full_name FROM audit_logs a JOIN users u ON u.id=a.user_id ORDER BY a.id DESC LIMIT 1000')
@app.get('/api/settings')
def settings(request:Request,s:Session=Depends(db)):
    u=require_user(request,s); require_admin(u); return q(s,'SELECT key,value FROM settings ORDER BY key')
@app.put('/api/settings')
async def update_settings(request:Request,s:Session=Depends(db)):
    u=require_user(request,s); require_admin(u); d=await request.json()
    for k,v in d.items(): s.execute(text("INSERT INTO settings(key,value) VALUES(:k,:v) ON CONFLICT(key) DO UPDATE SET value=excluded.value"),{'k':k,'v':str(v)})
    audit(s,u['id'],'تعديل إعدادات','تحديث إعدادات النظام'); s.commit(); return {'ok':True}


# -------------------- Extended operations --------------------
@app.get('/api/attendance/status')
def attendance_status(request:Request,s:Session=Depends(db)):
    u=require_user(request,s); need(u,'perm_payroll')
    openrow=one(s,"SELECT a.*,u.full_name FROM attendance a JOIN users u ON u.id=a.user_id WHERE a.user_id=:u AND a.clock_out IS NULL ORDER BY a.id DESC LIMIT 1",{'u':u['id']})
    today=one(s,"SELECT COALESCE(SUM(total_hours),0) hours,COALESCE(SUM(total_wage),0) wage FROM attendance WHERE user_id=:u AND DATE(clock_in)=DATE(CURRENT_TIMESTAMP)",{'u':u['id']})
    return {'on_shift':bool(openrow),'current':openrow,'today_hours':float(today['hours'] or 0),'today_wage':float(today['wage'] or 0)}

@app.get('/api/employees')
def employees(request:Request,s:Session=Depends(db)):
    u=require_user(request,s); need(u,'perm_payroll')
    return q(s,'SELECT * FROM employees ORDER BY id DESC')

@app.post('/api/employees')
async def create_employee(request:Request,s:Session=Depends(db)):
    u=require_user(request,s); require_admin(u); d=await request.json()
    r=s.execute(text('INSERT INTO employees(full_name,phone,job_title,basic_salary,is_active) VALUES(:n,:p,:j,:b,1) RETURNING id'),{'n':d['full_name'],'p':d.get('phone',''),'j':d.get('job_title',''),'b':float(d.get('basic_salary',0))}).first()
    audit(s,u['id'],'إضافة موظف',d['full_name']); s.commit(); return {'ok':True,'id':r[0]}

@app.get('/api/payroll')
def payroll(request:Request,s:Session=Depends(db)):
    u=require_user(request,s); need(u,'perm_payroll')
    return {'attendance_wages':q(s,"SELECT DATE(clock_in) day,u.full_name,ROUND(COALESCE(SUM(total_hours),0),2) hours,ROUND(COALESCE(SUM(total_wage),0),2) wage FROM attendance a JOIN users u ON u.id=a.user_id WHERE clock_out IS NOT NULL GROUP BY DATE(clock_in),u.id,u.full_name ORDER BY day DESC LIMIT 180"),
            'advances':q(s,"SELECT a.*,u.full_name FROM cashier_advances a JOIN users u ON u.id=a.user_id WHERE a.is_deducted=0 ORDER BY a.id DESC"),
            'weekly':q(s,"SELECT w.*,u.full_name FROM weekly_wages w JOIN users u ON u.id=w.user_id ORDER BY w.id DESC LIMIT 100")}

@app.patch('/api/attendance/{aid}')
async def edit_attendance(aid:int,request:Request,s:Session=Depends(db)):
    u=require_user(request,s); require_admin(u); d=await request.json()
    if 'notes' in d: s.execute(text('UPDATE attendance SET notes=:n WHERE id=:id'),{'n':d['notes'],'id':aid})
    if 'hourly_rate' in d: s.execute(text('UPDATE attendance SET hourly_rate=:r,total_wage=ROUND(total_hours*:r,2) WHERE id=:id'),{'r':float(d['hourly_rate']),'id':aid})
    audit(s,u['id'],'تعديل حضور',str(aid)); s.commit(); return {'ok':True}

@app.patch('/api/advances/{aid}/deduct')
async def deduct_advance(aid:int,request:Request,s:Session=Depends(db)):
    u=require_user(request,s); require_admin(u); d=await request.json()
    a=one(s,'SELECT * FROM cashier_advances WHERE id=:id',{'id':aid})
    if not a: raise HTTPException(404,'السلفة غير موجودة')
    if a['is_deducted']: raise HTTPException(400,'السلفة مسجلة كمخصومة بالفعل')
    s.execute(text("UPDATE cashier_advances SET is_deducted=1,deducted_at=CURRENT_TIMESTAMP,deduction_notes=:n WHERE id=:id"),{'n':d.get('notes','تم الخصم من مستحقات الموظف'),'id':aid})
    audit(s,u['id'],'خصم سلفة',str(aid)); s.commit(); return {'ok':True}

@app.get('/api/faults/summary')
def faults_summary(request:Request,s:Session=Depends(db)):
    u=require_user(request,s); need(u,'perm_pos')
    return {'total':int(scalar(s,'SELECT COUNT(*) FROM net_faults') or 0),'open':int(scalar(s,"SELECT COUNT(*) FROM net_faults WHERE status!='تم الحل'") or 0),'resolved':int(scalar(s,"SELECT COUNT(*) FROM net_faults WHERE status='تم الحل'") or 0),'by_status':q(s,'SELECT status,COUNT(*) count FROM net_faults GROUP BY status')}

@app.patch('/api/faults/{fid}')
async def update_fault(fid:int,request:Request,s:Session=Depends(db)):
    u=require_user(request,s); need(u,'perm_pos'); d=await request.json(); status=d.get('status','معلق')
    allowed_status=['معلق','جاري المتابعة','تم الحل','ملغي']
    if status not in allowed_status: raise HTTPException(400,'حالة عطل غير صحيحة')
    s.execute(text("UPDATE net_faults SET status=:st,priority=COALESCE(:pr,priority),resolution_notes=COALESCE(:rn,resolution_notes),assigned_to=COALESCE(:as,assigned_to),updated_at=CURRENT_TIMESTAMP,resolved_at=CASE WHEN :st='تم الحل' THEN CURRENT_TIMESTAMP ELSE resolved_at END WHERE id=:id"),{'st':status,'pr':d.get('priority'),'rn':d.get('resolution_notes'),'as':d.get('assigned_to'),'id':fid})
    audit(s,u['id'],'تحديث عطل إنترنت',f'{fid}:{status}'); s.commit(); return {'ok':True}

@app.get('/api/orders/summary')
def orders_summary(request:Request,s:Session=Depends(db)):
    u=require_user(request,s); need(u,'perm_pos')
    return {'total':int(scalar(s,'SELECT COUNT(*) FROM daily_orders') or 0),'by_status':q(s,'SELECT status,COUNT(*) count FROM daily_orders GROUP BY status')}

@app.patch('/api/orders/{oid}')
async def update_order(oid:int,request:Request,s:Session=Depends(db)):
    u=require_user(request,s); need(u,'perm_pos'); d=await request.json(); status=d.get('status')
    statuses=['جديد','قيد التنفيذ','جاهز','تم التسليم','ملغي']
    if status and status not in statuses: raise HTTPException(400,'حالة طلب غير صحيحة')
    sets=[]; vals={'id':oid}
    for k in ['status','customer_name','phone','amount','priority','due_at','notes']:
        if k in d: sets.append(f'{k}=:{k}'); vals[k]=d[k]
    if 'status' in d: sets.append('updated_at=CURRENT_TIMESTAMP')
    if sets: s.execute(text(f"UPDATE daily_orders SET {','.join(sets)} WHERE id=:id"),vals)
    audit(s,u['id'],'تحديث طلب',str(oid)); s.commit(); return {'ok':True}

@app.get('/api/bands')
def bands(request:Request,s:Session=Depends(db)):
    u=require_user(request,s); need(u,'perm_pos'); return q(s,'SELECT * FROM internet_bands ORDER BY is_active DESC,id DESC')

@app.post('/api/bands')
async def create_band(request:Request,s:Session=Depends(db)):
    u=require_user(request,s); require_admin(u); d=await request.json()
    try:
        r=s.execute(text('INSERT INTO internet_bands(name,download_mbps,upload_mbps,description,is_active) VALUES(:n,:d,:up,:ds,1) RETURNING id'),{'n':d['name'],'d':float(d.get('download_mbps',0)),'up':float(d.get('upload_mbps',0)),'ds':d.get('description','')}).first()
    except Exception: s.rollback(); raise HTTPException(400,'اسم الباند مستخدم بالفعل')
    audit(s,u['id'],'إضافة باند',d['name']); s.commit(); return {'ok':True,'id':r[0]}

@app.patch('/api/bands/{bid}/toggle')
async def toggle_band(bid:int,request:Request,s:Session=Depends(db)):
    u=require_user(request,s); require_admin(u); b=one(s,'SELECT * FROM internet_bands WHERE id=:id',{'id':bid})
    if not b: raise HTTPException(404,'الباند غير موجود')
    active=0 if int(b['is_active']) else 1
    s.execute(text('UPDATE internet_bands SET is_active=:a,updated_at=CURRENT_TIMESTAMP WHERE id=:id'),{'a':active,'id':bid}); audit(s,u['id'],'تغيير حالة باند',f'{b["name"]}:{active}'); s.commit(); return {'ok':True,'is_active':active}

@app.get('/api/stock/movements')
def stock_movements(request:Request,s:Session=Depends(db)):
    u=require_user(request,s); need(u,'perm_inventory')
    return q(s,"SELECT sm.*,p.name product_name,p.barcode,u.full_name user_name FROM stock_movements sm JOIN products p ON p.id=sm.product_id LEFT JOIN users u ON u.id=sm.user_id ORDER BY sm.id DESC LIMIT 1000")

@app.post('/api/stock/adjust')
async def stock_adjust(request:Request,s:Session=Depends(db)):
    u=require_user(request,s); need(u,'perm_inventory'); d=await request.json(); pid=int(d['product_id']); qty=float(d['quantity']); typ=d.get('movement_type','in')
    if typ not in ['in','out','adjust']: raise HTTPException(400,'نوع حركة غير صحيح')
    p=one(s,'SELECT * FROM products WHERE id=:id',{'id':pid});
    if not p: raise HTTPException(404,'المنتج غير موجود')
    old=float(p['stock_qty']); new=float(d.get('new_stock')) if typ=='adjust' and d.get('new_stock') is not None else old + qty if typ=='in' else old-qty
    if new<0: raise HTTPException(400,'المخزون لا يمكن أن يكون سالباً')
    delta=new-old
    s.execute(text('UPDATE products SET stock_qty=:q,updated_at=CURRENT_TIMESTAMP WHERE id=:id'),{'q':new,'id':pid})
    s.execute(text('INSERT INTO stock_movements(product_id,quantity,movement_type,notes,user_id) VALUES(:p,:q,:t,:n,:u)'),{'p':pid,'q':delta,'t':typ,'n':d.get('notes',''),'u':u['id']})
    audit(s,u['id'],'تعديل مخزون',f'{p["name"]}:{old}->{new}'); s.commit(); return {'ok':True,'old':old,'new':new}

@app.get('/api/reports/summary')
def reports_summary(request:Request,s:Session=Depends(db),date_from:str|None=None,date_to:str|None=None):
    u=require_user(request,s); need(u,'perm_reports')
    start=date_from or str(date.today()); end=date_to or start
    sales=one(s,"SELECT COUNT(*) invoices,COALESCE(SUM(subtotal),0) subtotal,COALESCE(SUM(discount_amount),0) discount,COALESCE(SUM(total_amount),0) total,COALESCE(SUM(paid_amount),0) paid,COALESCE(SUM(remaining_amount),0) remaining FROM sales_invoices WHERE DATE(created_at) BETWEEN :a AND :b",{'a':start,'b':end})
    cash=one(s,"SELECT COALESCE(SUM(CASE WHEN direction='in' THEN amount ELSE 0 END),0) cash_in,COALESCE(SUM(CASE WHEN direction='out' THEN amount ELSE 0 END),0) cash_out FROM cash_transactions WHERE DATE(created_at) BETWEEN :a AND :b",{'a':start,'b':end})
    maint=int(scalar(s,"SELECT COUNT(*) FROM maintenance_tickets WHERE DATE(received_at) BETWEEN :a AND :b",{'a':start,'b':end}) or 0)
    faults=int(scalar(s,"SELECT COUNT(*) FROM net_faults WHERE DATE(created_at) BETWEEN :a AND :b",{'a':start,'b':end}) or 0)
    orders=int(scalar(s,"SELECT COUNT(*) FROM daily_orders WHERE DATE(created_at) BETWEEN :a AND :b",{'a':start,'b':end}) or 0)
    return {'date_from':start,'date_to':end,'sales':sales,'cash':cash,'maintenance':maint,'faults':faults,'orders':orders,'cash_balance':cash_balance(s),'low_stock':q(s,'SELECT id,barcode,name,stock_qty,min_stock FROM products WHERE stock_qty<=min_stock ORDER BY stock_qty')}

@app.get('/api/reports/share-text')
def report_share_text(request:Request,s:Session=Depends(db),date_from:str|None=None,date_to:str|None=None):
    d=reports_summary(request,s,date_from,date_to)
    x=d['sales']; c=d['cash']; currency='جنيه'
    text_report=f"تقرير SHAKWEER NET | {d['date_from']} إلى {d['date_to']}\nالمبيعات: {float(x['total'] or 0):.2f} {currency}\nالمحصل: {float(x['paid'] or 0):.2f} {currency}\nالآجل: {float(x['remaining'] or 0):.2f} {currency}\nدخل الخزنة: {float(c['cash_in'] or 0):.2f} {currency}\nخرج الخزنة: {float(c['cash_out'] or 0):.2f} {currency}\nرصيد الخزنة: {d['cash_balance']:.2f} {currency}\nالصيانة: {d['maintenance']}\nأعطال الإنترنت: {d['faults']}\nالطلبات: {d['orders']}\nالمخزون المنخفض: {len(d['low_stock'])}"
    return {'text':text_report}


@app.get('/api/cashbox/session')
def cash_session(request:Request,s:Session=Depends(db)):
    u=require_user(request,s); need(u,'perm_pos')
    active=one(s,'SELECT * FROM cash_sessions WHERE closed_at IS NULL ORDER BY id DESC LIMIT 1')
    return {'active':active,'balance':cash_balance(s)}

@app.post('/api/cashbox/session/open')
async def cash_open(request:Request,s:Session=Depends(db)):
    u=require_user(request,s); need(u,'perm_pos'); d=await request.json()
    if one(s,'SELECT id FROM cash_sessions WHERE closed_at IS NULL ORDER BY id DESC LIMIT 1'): raise HTTPException(400,'يوجد وردية خزنة مفتوحة بالفعل')
    opening=float(d.get('opening_balance',cash_balance(s)))
    r=s.execute(text('INSERT INTO cash_sessions(user_id,opening_balance,expected_balance,notes) VALUES(:u,:o,:e,:n) RETURNING id'),{'u':u['id'],'o':opening,'e':cash_balance(s),'n':d.get('notes','')}).first()
    audit(s,u['id'],'فتح وردية خزنة',str(r[0])); s.commit(); return {'ok':True,'id':r[0]}

@app.post('/api/cashbox/session/close')
async def cash_close(request:Request,s:Session=Depends(db)):
    u=require_user(request,s); require_admin(u); d=await request.json(); row=one(s,'SELECT * FROM cash_sessions WHERE closed_at IS NULL ORDER BY id DESC LIMIT 1')
    if not row: raise HTTPException(400,'لا توجد وردية خزنة مفتوحة')
    actual=float(d['actual_balance'])
    expected=cash_balance(s); diff=actual-expected
    s.execute(text('UPDATE cash_sessions SET closed_at=CURRENT_TIMESTAMP,expected_balance=:e,actual_balance=:a,difference=:d,notes=COALESCE(:n,notes) WHERE id=:id'),{'e':expected,'a':actual,'d':diff,'n':d.get('notes'),'id':row['id']})
    audit(s,u['id'],'قفل وردية خزنة',f'{row["id"]}: فرق {diff:.2f}'); s.commit(); return {'ok':True,'expected':expected,'difference':diff}

@app.get('/api/cashbox/sessions')
def cash_sessions(request:Request,s:Session=Depends(db)):
    u=require_user(request,s); need(u,'perm_pos'); return q(s,'SELECT cs.*,u.full_name FROM cash_sessions cs LEFT JOIN users u ON u.id=cs.user_id ORDER BY cs.id DESC LIMIT 100')

@app.post('/api/categories')
async def create_category(request:Request,s:Session=Depends(db)):
    u=require_user(request,s); need(u,'perm_inventory'); d=await request.json()
    try:
        r=s.execute(text('INSERT INTO categories(name) VALUES(:n) RETURNING id'),{'n':d['name']}).first()
        audit(s,u['id'],'إضافة تصنيف',d['name']); s.commit(); return {'ok':True,'id':r[0]}
    except Exception: s.rollback(); raise HTTPException(400,'التصنيف موجود بالفعل')

@app.get('/api/backup')
def backup(request:Request,s:Session=Depends(db)):
    u=require_user(request,s); require_admin(u)
    if s.bind.dialect.name!='sqlite': raise HTTPException(400,'نسخ ملف قاعدة البيانات متاح محلياً مع SQLite؛ استخدم نسخة PostgreSQL الاحتياطية على الخادم.')
    db_path=s.bind.url.database
    if not os.path.isabs(db_path): db_path=os.path.abspath(os.path.join(ROOT,db_path))
    if not os.path.exists(db_path): raise HTTPException(404,'ملف قاعدة البيانات غير موجود')
    audit(s,u['id'],'نسخة احتياطية','SQLite'); s.commit()
    return FileResponse(db_path,media_type='application/octet-stream',filename=f'shakweer_net_backup_{datetime.now():%Y%m%d_%H%M%S}.db')

@app.get('/api/health')
def health(s:Session=Depends(db)): return {'ok':True,'database':s.bind.dialect.name,'time':datetime.now().isoformat()}
