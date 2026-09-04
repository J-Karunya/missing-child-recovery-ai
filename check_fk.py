import sqlite3
db = sqlite3.connect('data/database/missing_child_ai.db')
for row in db.execute("SELECT sql FROM sqlite_master WHERE type='table'"):
    if row[0] and 'REFERENCES cases' in row[0]:
        print(row[0])
db.close()