import sqlite3
db = sqlite3.connect('data/database/missing_child_ai.db')
db.execute("DROP TABLE IF EXISTS cases_new")
db.commit()
print("Dropped cases_new")
for row in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'cases%'"):
    print(row[0])
db.close()