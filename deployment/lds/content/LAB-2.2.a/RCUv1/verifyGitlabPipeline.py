#!/usr/bin/env python3

import requests
import json
import time

# --- Configuration ---
GITLAB_URL = "http://192.168.10.13"
PROJECT_ID = "3"
PRIVATE_TOKEN = "token-123123-123412345"
BRANCH_REF = "main"
# ---------------------

def get_latest_pipeline_status(project_id, private_token, ref=None):
    url = f"{GITLAB_URL}/api/v4/projects/{project_id}/pipelines/latest"
    headers = {"PRIVATE-TOKEN": private_token}
    params = {}
    if ref:
        params["ref"] = ref

    try:
        response = requests.get(url, headers=headers, params=params)
        response.raise_for_status() # Raise an exception for bad status codes (4xx or 5xx)
        pipeline_data = response.json()
        return pipeline_data.get("status")

    except requests.exceptions.RequestException as e:
        print(f"Error fetching pipeline status: {e}")
        return None

status = get_latest_pipeline_status(PROJECT_ID, PRIVATE_TOKEN, BRANCH_REF)

if status:
    print(f"The latest pipeline status is: {status}")
    if status == "failed":
        print("The pipeline has failed.")
    elif status == "success":
        print("The pipeline was successful.")
    else:
        print(f"The pipeline is currently in state: {status}.")
else:
    print("Could not retrieve pipeline status.")
