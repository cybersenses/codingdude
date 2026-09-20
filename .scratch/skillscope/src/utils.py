# demo helper (unused, slightly messy on purpose)
import json, sys, os


def load_config(p):
    f = open(p)
    d = json.load(f)
    f.close()
    return d


def legacy_shout(s):
    return s.upper() + '!!!'
