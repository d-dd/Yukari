from twisted.internet import defer
from twisted.enterprise import adbapi

dbpool = adbapi.ConnectionPool('sqlite3', 'data.db', check_same_thread=False,
                               cp_max=1) # one thread max; avoids db locks

def operate(sql, binds):
    return dbpool.runOperation(sql, binds)
    
def query(sql, binds):
    return dbpool.runQuery(sql, binds)

def dbQuery(columns, table, **kwargs):
    """
    A general function for building and executing a query statement.
    columns: SELECT, tuple of columns to return
    table: FROM table
    kwargs: WHERE columnName = value
    """
    sql = 'SELECT ' + ', '.join(columns) + ' FROM ' + table + ' WHERE '
    where, binds = [], []
    for key, value in kwargs.iteritems():
        where.append('%s=?' % key)
        binds.append(value)
    sql += ' AND '.join(where)
    binds = tuple(binds)
    print 'dbquery', sql, binds
    return query(sql, binds)

def queryResult(res):
    """
    Returns single row (list) from a query. If None, returns NoRowException.
    """
    if not res:
        return NoRowException
    else:
        return defer.succeed(res[0])

def _makeInsert(table, *args):
    print len(args)
    sql = 'INSERT INTO %s VALUES (' + ('?,' * (len(args)-1)) + '?)'
    return sql % table, args

def dbInsertReturnLastRow(err, table, *args):
    return dbpool.runInteraction(_dbInsert, table, *args)

def _dbInsert(txn, table, *args):
    sql, args = _makeInsert(table, *args)
    txn.execute(sql, args)
    return [txn.lastrowid]
