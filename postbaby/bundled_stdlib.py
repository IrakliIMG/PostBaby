"""Bundled standard library modules for PostBaby.

This module ensures that Python standard library modules permitted by
Script Contract 2.0 (such as uuid, base64, hashlib, hmac, secrets, json,
time, datetime, re, urllib, etc.) are discovered and bundled by PyInstaller
into the frozen Windows executable, and are pre-loaded in sys.modules.
"""

from __future__ import annotations

# Pre-import common standard library modules used in API testing
import base64
import binascii
import calendar
import cmath
import collections
import copy
import csv
import dataclasses
import datetime
import decimal
import difflib
import enum
import fractions
import functools
import glob
import gzip
import hashlib
import hmac
import html
import http
import http.client
import ipaddress
import itertools
import json
import math
import mimetypes
import numbers
import operator
import os
import pathlib
import pprint
import random
import re
import secrets
import string
import struct
import tempfile
import textwrap
import time
import timeit
import typing
import unicodedata
import urllib
import urllib.error
import urllib.parse
import urllib.request
import uuid
import xml
import xml.etree.ElementTree
import zlib
import zoneinfo

__all__ = [
    "base64", "binascii", "calendar", "cmath", "collections", "copy", "csv",
    "dataclasses", "datetime", "decimal", "difflib", "enum", "fractions",
    "functools", "glob", "gzip", "hashlib", "hmac", "html", "http",
    "ipaddress", "itertools", "json", "math", "mimetypes", "numbers",
    "operator", "os", "pathlib", "pprint", "random", "re", "secrets",
    "string", "struct", "tempfile", "textwrap", "time", "timeit", "typing",
    "unicodedata", "urllib", "uuid", "xml", "zlib", "zoneinfo",
]
