#!/usr/bin/env python3
# -*- coding: utf-8 -*

__author__ = 'qiaolifeng'

import sys
import asyncio
import logging

from common import connect_mongodb, log


async def create_pool(**kw):
    logging.info('create database connection pool...')
    global __pool
    __pool = connect_mongodb()


async def select(sql, args, size=None):
    log(sql, args)
    global __pool
    if not __pool:
        sys.exit(0)
    if sql.get('find') == 'Number':
        container_list = sql['where']
        entry_list = __pool.stress_job_status.find(
            {"test_bed": container_list}).count()
    if sql.get('find') == 'All':
        if sql['orderby'].split(" ")[1] == "desc":
            sort = -1
        elif sql['orderby'].split(" ")[1] == "asc":
            sort = 1
        else:
            return -1
        entry_list = __pool.stress_job_status.find(
            {"test_bed": sql['where']}).skip(
            int(sql['limit'][0])).limit(
            int(sql['limit'][1])).sort(
            sql['orderby'].split(" ")[0], sort)
    if sql.get('find') == 'PrimaryKey':
        entry_list = __pool.stress_job_status.find(
            {'test_bed': sql.get('test_bed'),
             'job_name': sql.get('job_name'),
             'ips': sql.get('ips')})
    return entry_list


async def execute(sql, args):
    log(sql, args)
    global __pool
    if not __pool:
        sys.exit(0)
    __pool.stress_job_status.update(sql, args)
    return 1


def create_args_string(num):
    L = []
    for n in range(num):
        L.append('?')
    return ', '.join(L)


class Field(object):

    def __init__(self, name, column_type, primary_key, default):
        self.name = name
        self.column_type = column_type
        self.primary_key = primary_key
        self.default = default

    def __str__(self):
        return '<%s, %s:%s>' % (self.__class__.__name__, self.column_type, self.name)


class StringField(Field):

    def __init__(self, name=None, primary_key=False, default=None, ddl='varchar(100)'):
        super().__init__(name, ddl, primary_key, default)


class BooleanField(Field):

    def __init__(self, name=None, default=False):
        super().__init__(name, 'boolean', False, default)


class IntegerField(Field):

    def __init__(self, name=None, primary_key=False, default=0):
        super().__init__(name, 'bigint', primary_key, default)


class FloatField(Field):

    def __init__(self, name=None, primary_key=False, default=0.0):
        super().__init__(name, 'real', primary_key, default)


class TextField(Field):

    def __init__(self, name=None, default=None):
        super().__init__(name, 'text', False, default)


class ModelMetaclass(type):

    def __new__(cls, name, bases, attrs):
        if name == 'Model':
            return type.__new__(cls, name, bases, attrs)
        tableName = attrs.get('__table__', None) or name
        logging.info('found model: %s (table: %s)' % (name, tableName))
        mappings = dict()
        fields = []
        primaryKey = None
        for k, v in attrs.items():
            if isinstance(v, Field):
                logging.info('  found mapping: %s ==> %s' % (k, v))
                mappings[k] = v
                if v.primary_key:
                    # 找到主键:
                    if primaryKey:
                        raise StandardError('Duplicate primary key for field: %s' % k)
                    primaryKey = k
                else:
                    fields.append(k)
        if not primaryKey:
            raise StandardError('Primary key not found.')
        for k in mappings.keys():
            attrs.pop(k)
        escaped_fields = list(map(lambda f: '`%s`' % f, fields))
        attrs['__mappings__'] = mappings # 保存属性和列的映射关系
        attrs['__table__'] = tableName
        attrs['__primary_key__'] = primaryKey # 主键属性名
        attrs['__fields__'] = fields # 除主键外的属性名
        attrs['__select__'] = 'select `%s`, %s from `%s`' % (primaryKey, ', '.join(escaped_fields), tableName)
        attrs['__insert__'] = 'insert into `%s` (%s, `%s`) values (%s)' % (tableName, ', '.join(escaped_fields), primaryKey, create_args_string(len(escaped_fields) + 1))
        attrs['__update__'] = 'update `%s` set %s where `%s`=?' % (tableName, ', '.join(map(lambda f: '`%s`=?' % (mappings.get(f).name or f), fields)), primaryKey)
        attrs['__delete__'] = 'delete from `%s` where `%s`=?' % (tableName, primaryKey)
        return type.__new__(cls, name, bases, attrs)


class Model(dict, metaclass=ModelMetaclass):

    def __init__(self, **kw):
        super(Model, self).__init__(**kw)

    def __getattr__(self, key):
        try:
            return self[key]
        except KeyError:
            raise AttributeError(r"'Model' object has no attribute '%s'" % key)

    def __setattr__(self, key, value):
        self[key] = value

    def getValue(self, key):
        return getattr(self, key, None)

    def getValueOrDefault(self, key):
        value = getattr(self, key, None)
        if value is None:
            field = self.__mappings__[key]
            if field.default is not None:
                value = field.default() if callable(field.default) else field.default
                logging.debug('using default value for %s: %s' % (key, str(value)))
                setattr(self, key, value)
        return value

    @classmethod
    async def findAll(cls, selected=None, args=None, **kw):
        """
        find objects by where clause.
        """
        sql = {'find': 'All'}
        if selected:
            sql['where'] = selected
        if args is None:
            args = []
        orderby = kw.get('orderBy', None)
        if orderby:
            sql['orderby'] = orderby
        limit = kw.get('limit', None)
        if limit is not None:
            if isinstance(limit, int):
                sql['limit'] = limit
                args.append(limit)
            elif isinstance(limit, tuple) and len(limit) == 2:
                sql['limit'] = limit
                args.extend(limit)
            else:
                raise ValueError('Invalid limit value: %s' % str(limit))
        rs = await select(sql, args)
        return rs

    @classmethod
    async def findNumber(cls, selectField, selected=None, args=None):
        """
        find number by select and where.
        """
        sql = {'find': "Number", 'where': selectField}
        if selected:
            sql['select'] = selected
        rs = await select(sql, args, 1)
        if rs == 0:
            return None
        return rs

    @classmethod
    async def find(cls, pk):
        """
        :param pk:
        :return:
        find object by primary key.
        """
        sql = pk
        sql['find'] = 'PrimaryKey'
        rs = await select(sql, 1)
        return cls(**rs[0])

    @asyncio.coroutine
    def save(self):
        args = list(map(self.getValueOrDefault, self.__fields__))
        args.append(self.getValueOrDefault(self.__primary_key__))
        rows = yield from execute(self.__insert__, args)
        if rows != 1:
            logging.warning('failed to insert record: affected rows: %s' % rows)

    async def update(where, *kwargs):
        print(where)
        print(*kwargs)
        rows = await execute(where, *kwargs)
        print(rows)
        if rows != 1:
            logging.warning('failed to update by primary key: affected rows: %s' % rows)

    @asyncio.coroutine
    def remove(self):
        args = [self.getValue(self.__primary_key__)]
        rows = yield from execute(self.__delete__, args)
        if rows != 1:
            logging.warning('failed to remove by primary key: affected rows: %s' % rows)