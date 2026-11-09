"""Shared API helper for the portal pages (streamlit_app.py is left untouched)."""
import os

import requests
import streamlit as st
from dotenv import load_dotenv

load_dotenv()
API = os.getenv("API_BASE_URL", "http://127.0.0.1:8000").rstrip("/")


def api(method: str, path: str, **kwargs):
    try:
        r = requests.request(method, f"{API}{path}", timeout=kwargs.pop("timeout", 8), **kwargs)
        if r.status_code >= 400:
            try: detail = r.json().get("detail", r.text)
            except Exception: detail = r.text
            st.error(f"API error ({r.status_code}): {detail}")
            return None
        return r.json() if r.content else {}
    except requests.RequestException as exc:
        st.error(f"Cannot reach the WasteLoop API at {API}. Start the backend first. ({exc})")
        return None