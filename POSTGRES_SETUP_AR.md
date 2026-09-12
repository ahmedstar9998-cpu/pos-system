# إعداد PostgreSQL — بدون تكلفة ترخيص

PostgreSQL نفسه مجاني. على Windows يمكنك تثبيته محليًا على نفس الجهاز الذي يشغّل SHAKWEER NET.

بعد إنشاء قاعدة باسم `shakweer_pos` ومستخدم `shakweer`:

```text
DATABASE_URL=postgresql+psycopg://shakweer:كلمة_المرور@127.0.0.1:5432/shakweer_pos
```

ثم شغّل النظام؛ الجداول تُنشأ تلقائيًا.

لنقل قاعدة SQLite الحالية:

```text
python scripts\migrate_sqlite_to_postgres.py C:\path\to\shakweer_net.db
```

لا تفتح منفذ PostgreSQL للإنترنت. اجعل الاتصال به محليًا أو داخل الشبكة الموثوقة فقط.
