#!/usr/bin/env python3
# -*- coding: utf-8 -*-

__author__ = 'qiaolifeng'

from apscheduler.schedulers.blocking import BlockingScheduler
import time

sched = BlockingScheduler()


@sched.scheduled_job('cron', hour='0-23')
def scheduler_run():
    print(time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(time.time())))


sched.start()
