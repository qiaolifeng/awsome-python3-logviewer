#!/usr/bin/env python3
# -*- coding: utf-8 -*-

__author__ = 'qiaolifeng'

from socket import timeout
from subprocess import check_output, CalledProcessError

import socket
import io
import docker

from common import PHONE_SCRIPT_PATH, SOCKET_TIMEOUT

buffering = io.DEFAULT_BUFFER_SIZE
socket.setdefaulttimeout(SOCKET_TIMEOUT)


def job_start(docker_name, job_name):
    try:

        client = docker.from_env()
        container = client.containers.get(docker_name)

        cmd = '{path}/startjob.py {job_name}'.format(
            path=PHONE_SCRIPT_PATH, job_name=job_name)
        res = container.exec_run(cmd, socket=True)
        raw = res.output
        buffer = io.BufferedReader(raw, buffering)
        text = io.TextIOWrapper(buffer, encoding='utf-8', newline='\n')

        print(next(text))
        try:
            print(next(text))
            print('already running')
        except timeout:
            print('timeout')
    except CalledProcessError:
        return []
    return text
