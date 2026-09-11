import os,hashlib,hmac
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
SECRET=os.getenv('SHAKWEER_SECRET','CHANGE-ME-SHAKWEER-SECRET')
ser=URLSafeTimedSerializer(SECRET,salt='shakweer-session')
def hash_password(p): return 'pbkdf2$'+hashlib.pbkdf2_hmac('sha256',p.encode(),b'shakweer-net',120000).hex()
def verify_password(p,h):
    if h.startswith('pbkdf2$'): return hmac.compare_digest(hash_password(p),h)
    if len(h)==64: return hmac.compare_digest(hashlib.sha256(p.encode()).hexdigest(),h)
    return False
def make_session(uid): return ser.dumps({'id':uid})
def read_session(tok):
    try:return ser.loads(tok,max_age=86400)
    except (BadSignature,SignatureExpired):return None
