#!/usr/bin/env python3
# -*- coding: utf-8 -*-

__author__ = 'qiaolifeng'

' url handlers '

from aiohttp import web
from subprocess import check_output, CalledProcessError

import re
import time
import json
import logging
import hashlib
import asyncio
import docker

from coroweb import get, post
from apis import Page, APIError, APIValueError, APIPermissionError, \
    APIResourceNotFoundError
from models import User, Comment, Blog, next_id
from config import configs
from common import get_run_containers, PAGE_SIZE, HOSTNAME
from job_handler import job_start

import markdown2

COOKIE_NAME = 'awesession'
_COOKIE_KEY = configs.session.secret
RUNNING_TEST_BED = get_run_containers()


def check_admin(request):
    print('user role is :%s' % request.__user__.admin)
    if request.__user__ is None or not request.__user__.admin:
        raise APIPermissionError()


def check_actived(request):
    print('use is actived: %s' % request.__user__.actived)
    pass


def get_page_index(page_str):
    p = 1
    try:
        p = int(page_str)
    except ValueError as e:
        pass
    if p < 1:
        p = 1
    return p


def user2cookie(user, max_age):
    """
    Generate cookie str by user.
    """
    # build cookie string by: id-expires-sha1
    expires = str(int(time.time() + max_age))
    s = '%s-%s-%s-%s' % (user.id, user.passwd, expires, _COOKIE_KEY)
    L = [user.id, expires, hashlib.sha1(s.encode('utf-8')).hexdigest()]
    return '-'.join(L)


def text2html(text):
    lines = map(
        lambda s: '<p>%s</p>' % s.replace(
            '&', '&amp;').replace(
            '<', '&lt;').replace(
            '>', '&gt;'), filter(lambda s: s.strip() != '', text.split('\n')))
    return ''.join(lines)


@asyncio.coroutine
def cookie2user(cookie_str):
    """
    Parse cookie and load user if cookie is valid.
    """
    if not cookie_str:
        return None
    try:
        L = cookie_str.split('-')
        if len(L) != 3:
            return None
        uid, expires, sha1 = L
        if int(expires) < time.time():
            return None
        user = yield from User.find(uid)
        if user is None:
            return None
        s = '%s-%s-%s-%s' % (uid, user.passwd, expires, _COOKIE_KEY)
        if sha1 != hashlib.sha1(s.encode('utf-8')).hexdigest():
            logging.info('invalid sha1')
            return None
        user.passwd = '******'
        return user
    except Exception as e:
        logging.exception(e)
        return None


@get('/')
async def index(*, page='1'):
    page_index = get_page_index(page)
    # print('root {}'.format(page_index))
    global RUNNING_TEST_BED
    test_bed_name = RUNNING_TEST_BED[0]['Names'][0][1:] + '-' + HOSTNAME
    if RUNNING_TEST_BED is not None:
        num = await Blog.findNumber(test_bed_name, 'count(id)')
        page = Page(num, page_index, PAGE_SIZE)
        # print(page)
        logs = await Blog.findAll(
            test_bed_name,
            orderBy='startTime desc',
            limit=(page.offset, page.limit))
    else:
        page = 0
        logs = []
    return {
        '__template__': 'logs.html',
        'page': page,
        'containers': RUNNING_TEST_BED,
        'logs': logs,
        'selected': RUNNING_TEST_BED[0]['Names'][0][1:]
    }


@get('/{container}')
async def index_container(*, container, page='1'):
    page_index = get_page_index(page)
    # print('{} {}'.format(container, page_index))
    global RUNNING_TEST_BED
    for entry in RUNNING_TEST_BED:
        if entry['Names'][0][1:] == container:
            test_bed_name = entry['Names'][0][1:] + '-' + HOSTNAME
    if test_bed_name is not None:
        num = await Blog.findNumber(test_bed_name, 'count(id)')
        page = Page(num, page_index, PAGE_SIZE)
        # print(page)
        logs = await Blog.findAll(
            test_bed_name,
            orderBy='startTime desc',
            limit=(page.offset, page.limit))
    else:
        page = 0
        logs = []
    return {
        '__template__': 'logs.html',
        'page': page,
        'containers': RUNNING_TEST_BED,
        'logs': logs,
        'selected': container
    }


@get('/blog/{id}')
def get_blog(id):
    blog = yield from Blog.find(id)
    comments = yield from Comment.findAll(
        'blog_id=?', [id], orderBy='created_at desc')
    for c in comments:
        c.html_content = text2html(c.content)
        blog.html_content = markdown2.markdown(blog.content)
    return {
        '__template__': 'blog.html',
        'blog': blog,
        'comments': comments
    }


@get('/register')
def register():
    return {
        '__template__': 'register.html'
    }


@get('/signin')
def signin():
    return {
        '__template__': 'signin.html'
    }


@post('/api/authenticate')
def authenticate(*, email, passwd):
    if not email:
        raise APIValueError('email', 'Invalid email.')
    if not passwd:
        raise APIValueError('passwd', 'Invalid password.')
    users = yield from User.findAll('email=?', [email])
    if len(users) == 0:
        raise APIValueError('email', 'Email not exist.')
    user = users[0]
    # check passwd:
    sha1 = hashlib.sha1()
    sha1.update(user.id.encode('utf-8'))
    sha1.update(b':')
    sha1.update(passwd.encode('utf-8'))
    if user.passwd != sha1.hexdigest():
        raise APIValueError('passwd', 'Invalid password.')
    # authenticate ok, set cookie:
    r = web.Response()
    r.set_cookie(COOKIE_NAME, user2cookie(user, 86400), max_age=86400, httponly=True)
    user.passwd = '******'
    r.content_type = 'application/json'
    r.body = json.dumps(user, ensure_ascii=False).encode('utf-8')
    return r


@post('/api/update')
async def update_all():
    logging.info('Updating the status')
    client = docker.APIClient()
    try:
        r = web.Response()
        r.content_type = 'application/json'
        r.body = json.dumps({'test_bed': '', 'job_name': ''}, ensure_ascii=False).encode('utf-8')

        hostname = check_output(r"hostname", shell=True).strip()
        hostname = hostname.decode('utf-8').split('\n')
        if len(hostname) > 0:
            hostname = hostname[0]
        else:
            hostname = ""
        viewjob = check_output(r"docker ps --format {{.ID}}:{{.Names}}", shell=True).strip()
        viewjob = viewjob.decode('utf-8').split('\n')
        i = 0
        while i < len(viewjob):
            """
            cmd = r'docker inspect -f {{{{.State.Pid}}}} {containerid}'.format(containerid=viewjob[i].split(":")[0])
            pid = check_output(cmd, shell=True).strip().decode('utf-8').split('\n')
            cmd = 'nsenter --target {pid} --mount --uts --ipc --net --pid'.format(pid=pid[0])
            print(cmd)
            result = check_output(cmd, shell=True).strip()
            result = result.decode('utf-8').split('\n')
            print(result[0])
            """
            containername = viewjob[i].split(":")[1]
            cmd = 'ps -o cmd:255 -C python'
            exec_id = client.exec_create(containername, cmd)['Id']
            result = client.exec_start(exec_id).decode('utf-8').split('\n')
            j = 1
            while j < len(result):
                if result[j] != '':
                    status = result[j].split(']')[0].strip()[1:]
                    job_name = result[j].split(']')[1].strip()[1:]
                    ips = result[j].split(']')[5].strip()[1:]
                    print(result[j])
                    blogs = await Blog.find({'test_bed': '{container_name}-{hostname}'.format(
                        container_name=viewjob[i].split(":")[1], hostname=hostname),
                        'job_name': job_name,
                        'ips': ips})
                    if blogs['job_status'] == 1 and status == 'Abort':
                        print(blogs['job_status'])
                        print(status)
                        print(blogs['ips'])
                        if blogs['ips'] == ips:
                            print('need update')
                            """
                            await Blog.update({'test_bed': '{container_name}-{hostname}'.format(
                                container_name=viewjob[i].split(":")[1],
                                hostname=hostname),
                                'job_name': job_name,
                                'ips': ips},
                                {'$set': {"job_status": 0}})
                            """
                    r.body = json.dumps({'test_bed': blogs['test_bed'],
                                         'job_name': blogs['job_name']},
                                        ensure_ascii=False).encode('utf-8')
                j += 1
            i += 1
    except CalledProcessError:
        return []
    return {
        '__template__': 'logs.html',
        'containers': RUNNING_TEST_BED,
    }


@get('/job/{test_bed}/{job_name}/start')
async def start(*, test_bed, job_name):

    docker_name = test_bed.split('-')[0]
    if test_bed.split('-')[1] == 'DEBUG':
        docker_name = docker_name + '-DEBUG'

    job_start(docker_name, job_name)

    return 'redirect:/'


@get('/signout')
def signout(request):
    referer = request.headers.get('Referer')
    r = web.HTTPFound(referer or '/')
    r.set_cookie(COOKIE_NAME, '-deleted-', max_age=0, httponly=True)
    logging.info('user signed out.')
    return r


@get('/manage/')
def manage():
    return 'redirect:/manage/comments'


@get('/manage/comments')
def manage_comments(*, page='1'):
    return {
        '__template__': 'manage_comments.html',
        'page_index': get_page_index(page)
    }


@get('/manage/blogs')
def manage_blogs(*, page='1'):
    return {
        '__template__': 'manage_blogs.html',
        'page_index': get_page_index(page)
    }


@get('/manage/blogs/create')
def manage_create_blog():
    return {
        '__template__': 'manage_blog_edit.html',
        'id': '',
        'action': '/api/blogs'
    }


@get('/manage/blogs/edit')
def manage_edit_blog(*, id):
    return {
        '__template__': 'manage_blog_edit.html',
        'id': id,
        'action': '/api/blogs/%s' % id
    }


@get('/manage/users')
def manage_users(*, page='1'):
    return {
        '__template__': 'manage_users.html',
        'page_index': get_page_index(page)
    }


@get('/api/comments')
def api_comments(*, page='1'):
    page_index = get_page_index(page)
    num = yield from Comment.findNumber('count(id)')
    p = Page(num, page_index)
    if num == 0:
        return dict(page=p, comments=())
    comments = yield from Comment.findAll(orderBy='created_at desc', limit=(p.offset, p.limit))
    return dict(page=p, comments=comments)


@post('/api/blogs/{id}/comments')
def api_create_comment(id, request, *, content):
    user = request.__user__
    if user is None:
        raise APIPermissionError('Please signin first.')
    if not content or not content.strip():
        raise APIValueError('content')
    blog = yield from Blog.find(id)
    if blog is None:
        raise APIResourceNotFoundError('Blog')
    comment = Comment(blog_id=blog.id, user_id=user.id, user_name=user.name, user_image=user.image, content=content.strip())
    yield from comment.save()
    blog.comments_count += 1
    yield from blog.update()
    return comment


@post('/api/comments/{id}/delete')
def api_delete_comments(id, request):
    check_admin(request)
    c = yield from Comment.find(id)
    if c is None:
        raise APIResourceNotFoundError('Comment')
    yield from c.remove()
    return dict(id=id)


@get('/api/users')
def api_get_users(*, page='1'):
    page_index = get_page_index(page)
    num = yield from User.findNumber('count(id)')
    p = Page(num, page_index)
    if num == 0:
        return dict(page=p, users=())
    users = yield from User.findAll(orderBy='created_at desc', limit=(p.offset, p.limit))
    for u in users:
        u.passwd = '******'
    return dict(page=p, users=users)


_RE_EMAIL = re.compile(r'^[a-z0-9\.\-\_]+\@[a-z0-9\-\_]+(\.[a-z0-9\-\_]+){1,4}$')
_RE_SHA1 = re.compile(r'^[0-9a-f]{40}$')


@post('/api/users')
def api_register_user(*, email, name, passwd):
    if not name or not name.strip():
        raise APIValueError('name')
    if not email or not _RE_EMAIL.match(email):
        raise APIValueError('email')
    if not passwd or not _RE_SHA1.match(passwd):
        raise APIValueError('passwd')
    users = yield from User.findAll('email=?', [email])
    if len(users) > 0:
        raise APIError('register:failed', 'email', 'Email is already in use.')
    uid = next_id()
    sha1_passwd = '%s:%s' % (uid, passwd)
    user = User(id=uid, name=name.strip(), email=email, passwd=hashlib.sha1(sha1_passwd.encode('utf-8')).hexdigest(), image='http://www.gravatar.com/avatar/%s?d=mm&s=120' % hashlib.md5(email.encode('utf-8')).hexdigest())
    yield from user.save()
    # make session cookie:
    r = web.Response()
    r.set_cookie(COOKIE_NAME, user2cookie(user, 86400), max_age=86400, httponly=True)
    user.passwd = '******'
    r.content_type = 'application/json'
    r.body = json.dumps(user, ensure_ascii=False).encode('utf-8')
    return r


@get('/api/blogs')
def api_blogs(*, page='1'):
    page_index = get_page_index(page)
    num = yield from Blog.findNumber('count(id)')
    p = Page(num, page_index)
    if num == 0:
        return dict(page=p, blogs=())
    blogs = yield from Blog.findAll(orderBy='created_at desc', limit=(p.offset, p.limit))
    return dict(page=p, blogs=blogs)


@get('/api/blogs/{id}')
def api_get_blog(*, id):
    blog = yield from Blog.find(id)
    print(id)
    return blog


@post('/api/blogs')
def api_create_blog(request, *, name, summary, content):
    # print('the request is: %s' % request)
    check_actived(request)
    # print('Save blogs to the database......')
    if not name or not name.strip():
        raise APIValueError('name', 'name cannot be empty.')
    if not summary or not summary.strip():
        raise APIValueError('summary', 'summary cannot be empty.')
    if not content or not content.strip():
        raise APIValueError('content', 'content cannot be empty.')
    blog = Blog(user_id=request.__user__.id, user_name=request.__user__.name, user_image=request.__user__.image, name=name.strip(), summary=summary.strip(), content=content.strip())
    r = yield from blog.save()
    print(r)
    return blog


@post('/api/blogs/{id}')
def api_update_blog(id, request, *, name, summary, content):
    check_admin(request)
    blog = yield from Blog.find(id)
    if not name or not name.strip():
        raise APIValueError('name', 'name cannot be empty.')
    if not summary or not summary.strip():
        raise APIValueError('summary', 'summary cannot be empty.')
    if not content or not content.strip():
        raise APIValueError('content', 'content cannot be empty.')
    blog.name = name.strip()
    blog.summary = summary.strip()
    blog.content = content.strip()
    yield from blog.update()
    return blog


@post('/api/blogs/{id}/delete')
def api_delete_blog(request, *, id):
    check_admin(request)
    blog = yield from Blog.find(id)
    yield from blog.remove()
    return dict(id=id)


@get('/new_blogs')
def create_new_blogs(request):
    logging.info(request.__user__.id)
    return {
        '__template__': 'new_blogs.html',
        'userid': request.__user__.id,
        'id': '',
        'action': '/api/blogs'
    }
