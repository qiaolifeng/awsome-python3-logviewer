#!/usr/bin/env python3
# -*- coding: utf-8 -*-

__author__ = 'qiaolifeng'

' common modules '

from subprocess import check_output, CalledProcessError
from pymongo import MongoClient
from influxdb import InfluxDBClient
from ssh2.session import Session

import os
import logging
import configparser
import docker
import re
import socket

SCRIPT_PATH = os.path.dirname(os.path.realpath(__file__)) + '/../'
CONFIG_FILE = SCRIPT_PATH + "conf/script_config.conf"
SOCKET_TIMEOUT = 5
PAGE_SIZE = 10
PHONE_SCRIPT_PATH = '/root/phone_stress_test_scripts/utilities'
DOCKER_DAEMON_IP = '10.124.113.122'
DOCKER_DAEMON_HOST_USR = 'root'
DOCKER_DAEMON_HOST_PWD = 'CiscoSky'


def gethostname(ip):

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect((ip, 22))

    session = Session()
    session.handshake(sock)
    session.userauth_password(DOCKER_DAEMON_HOST_USR, DOCKER_DAEMON_HOST_PWD)

    channel = session.open_session()
    channel.execute(r'hostname')

    size, data = channel.read()
    while size > 0:
        hostname = data.decode('utf-8').split('\n')[0]
        size, data = channel.read()
    channel.close()

    return hostname


HOSTNAME = gethostname(DOCKER_DAEMON_IP)
BASIC_IMAGE = 'synergy_lite/pystress'


def log(sql, args=()):
    logging.info('SQL: %s' % sql)


def get_config(config=CONFIG_FILE):
    cf = configparser.ConfigParser()
    cf.read(config)
    return cf


def get_all_jobs():
    cf = get_config()
    return filter(
        lambda x: x not in [
            'default',
            'report',
            'influx_db',
            'mongo_db'],
        cf.sections())


def get_run_containers(*active_container):

    """
    # connect to the docker via dockapi
    :param active_container:
    :return:
    """
    """
    # connect to the docker where this app.py had been deployed.
    client = docker.APIClient(base_url='unix:///var/run/docker.sock')
    for component, version in client.version().items():
        print(component, version)
    print(client.containers())
    """
    try:
        output = []
        client_url = 'tcp://' + DOCKER_DAEMON_IP + ':2375'
        working_client = docker.APIClient(base_url=client_url, timeout=10)
        for component, version in working_client.version().items():
            logging.info(component, version)
        container_list = working_client.containers(all=True)
        for container in container_list:
            if re.search(BASIC_IMAGE, container['Image']):
                output.append(container)
        """
        hostname = check_output(r"hostname", shell=True).strip()
        hostname = hostname.decode('utf-8').split('\n')
        if len(hostname) > 0:
            hostname = hostname[0]
        else:
            hostname = ""
        containers = check_output(r"docker ps -a --format \"{{.ID}}:{{.Names}}:{{.Labels}}\"", shell=True).strip()
        if containers != b'':
            containers = containers.decode('utf-8').split('\n')
            i = 0
            output = []
            while i < len(containers):
                container_name = containers[i].split(":")[1]
                if active_container == ():
                    if i == 0:
                        actived = True
                    else:
                        actived = False
                else:
                    print(active_container[0])
                    print(container_name)
                    if container_name == active_container:
                        actived = True
                    else:
                        actived = False
                print(actived)
                container_info = '{{"index":{index}, ' \
                                 '"container": "{container_name}-{host_name}", ' \
                                 '"actived":{actived}}}'.format(index=i,
                                                                container_name=container_name,
                                                                host_name=hostname,
                                                                actived=actived)
                container_dict = ast.literal_eval(container_info)
                output.append(container_dict)
                i += 1
        """
        return output
    except CalledProcessError:
        return []


RUNNING_TEST_BED = get_run_containers()


def connect_mongodb():
    cf = get_config()
    config_name = 'mongo_db'
    if not cf.has_section(config_name):
        return None

    db_server = cf.get(config_name, "server")
    db_name = cf.get(config_name, "database")

    client = MongoClient(db_server)
    if not client:
        logging.error("Cannot connect to mongodb {}".format(db_server))
        return None

    return client[db_name]


def influxdb_update_job_status(
        test_name, job_status, measurement="job_status"):
    cf = get_config()
    cf_model = cf.get(
        'default',
        'model') if cf.has_option(
        'default',
        'model') else None
    json_body = [
        {
            "measurement": measurement,
            "tags": {
                "job_name": test_name,
                "model": cf_model
            },
            "fields": {
                "jobstatus": job_status,
            }
        }
    ]
    try:
        client = connect_influxdb()
        client.write_points(json_body)
    except Exception as e:
        logging.error('influxdb_update_memory err: %s', e)


def connect_influxdb():
    cf = get_config()
    config_name = 'influx_db'
    if not cf.has_section(config_name):
        return None

    db_server = cf.get(config_name, "server")
    db_name = cf.get(config_name, "database")
    client = InfluxDBClient(db_server, 8086, '', '', db_name)
    return client
