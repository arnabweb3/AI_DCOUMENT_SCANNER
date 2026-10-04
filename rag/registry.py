# registry.py
# Saves the details of every scanned document in a json file

import json
import os

from config import REGISTRY_FILE


def load_all():
    if not os.path.exists(REGISTRY_FILE):
        return {}
    try:
        with open(REGISTRY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_all(data):
    with open(REGISTRY_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=str)


def add_document(doc_id, details):
    data = load_all()
    data[doc_id] = details
    save_all(data)


def get_document(doc_id):
    data = load_all()
    return data.get(doc_id)


def remove_document(doc_id):
    data = load_all()
    details = data.pop(doc_id, None)
    save_all(data)
    return details
