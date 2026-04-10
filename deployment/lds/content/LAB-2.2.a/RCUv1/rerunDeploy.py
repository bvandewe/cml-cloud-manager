#!/usr/bin/env python3

import requests
import time

# --- Configuration ---
GITLAB_URL = "http://192.168.10.13"
PROJECT_ID = "3"
PRIVATE_TOKEN = "token-123123-123412345"
TARGET_STAGE_NAME = "deploy"
# ---------------------

def get_latest_pipeline_jobs(project_id, private_token):
    # First, get the latest pipeline ID
    url_latest = f"{GITLAB_URL}/api/v4/projects/{project_id}/pipelines/latest"
    headers = {"PRIVATE-TOKEN": private_token}
    try:
        response = requests.get(url_latest, headers=headers)
        response.raise_for_status()
        pipeline_id = response.json().get("id")
    except requests.exceptions.RequestException as e:
        print(f"Error finding latest pipeline ID: {e}")
        return None

    # get all jobs for that pipeline ID
    url_jobs = f"{GITLAB_URL}/api/v4/projects/{project_id}/pipelines/{pipeline_id}/jobs"
    response = requests.get(url_jobs, headers=headers)
    response.raise_for_status()
    # The API returns all jobs, including retried ones. filter later.
    return response.json()

def retry_stage_jobs(project_id, private_token, stage_name):
    jobs = get_latest_pipeline_jobs(project_id, private_token)
    if not jobs:
        return

    jobs_to_retry = [
        job for job in jobs 
        if job["stage"] == stage_name  # and job["status"] not in ("running", "pending", "created", "skipped")
    ]

    if not jobs_to_retry:
        print(f"No completed jobs found in stage '{stage_name}' to retry.")
        return

    print(f"Found {len(jobs_to_retry)} jobs to retry in stage '{stage_name}'.")

    for job in jobs_to_retry:
        job_id = job["id"]
        job_name = job["name"]
        retry_url = f"{GITLAB_URL}/api/v4/projects/{project_id}/jobs/{job_id}/retry"
        
        # POST request to retry the job
        response = requests.post(retry_url, headers={"PRIVATE-TOKEN": private_token})
        
        if response.status_code == 201:
            print(f"Triggered retry for job: '{job_name}' (ID: {job_id})")
        else:
            print(f"Failed to retry job '{job_name}'. Status code: {response.status_code}")

retry_stage_jobs(PROJECT_ID, PRIVATE_TOKEN, TARGET_STAGE_NAME)
