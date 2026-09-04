import sqlite3
db = sqlite3.connect('data/database/missing_child_ai.db')
q = "SELECT sql FROM sqlite_master WHERE type='table' AND name='cases'"
for row in db.execute(q):
    print(row[0])
db.close()