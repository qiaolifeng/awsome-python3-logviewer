#!/usr/bin/env python3
# -*- coding: utf-8 -*-

__author__ = 'qiaolifeng'

import os
import sys

sys.stdout = os.fdopen(sys.stdout.fileno(), 'w', 0)
