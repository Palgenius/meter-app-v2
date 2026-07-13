import sqlite3
db = sqlite3.connect('/opt/meter-app-v2/database/active.db')
c = db.cursor()
c.execute("UPDATE readings_15min SET send_status='pending', sent_at=NULL WHERE send_status='sent'")
affected = c.rowcount
db.commit()
print(f'Reset {affected} records from sent -> pending')
c.execute('SELECT send_status, COUNT(*) FROM readings_15min GROUP BY send_status')
for r in c.fetchall():
    print(f'  {r[0]}: {r[1]}')
db.close()