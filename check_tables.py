import sqlite3
db = sqlite3.connect('data/database/missing_child_ai.db')
for row in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'cases%'"):
    print(row[0])
db.close()