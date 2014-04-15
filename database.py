
from twisted.enterprise import adbapi

dbpool = adbapi.ConnectionPool('sqlite3', 'data.db', check_same_thread=False)

def operate(sql, binds):
    return dbpool.runOperation(sql, binds)
    
def query(sql, binds):
    return dbpool.runQuery(sql, binds)
