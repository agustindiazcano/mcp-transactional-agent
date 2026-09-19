import random
import uuid

from locust import HttpUser, between, task


class ClaimsUser(HttpUser):
    # Simulate a realistic think time between requests for a single user (e.g. 1 to 3 seconds)
    wait_time = between(1.0, 3.0)

    @task
    def submit_claim(self):
        # Generate a unique request_id to avoid idempotency blocking during the load test
        request_id = f"load-test-{uuid.uuid4()}"
        
        payload = {
            "request_id": request_id,
            "user_id": f"user_{random.randint(1, 10000)}",
            "claim_text": "My flight was delayed and I want a refund of $500. It was terrible."
        }
        
        # We expect a 202 Accepted because the API is asynchronous
        with self.client.post("/api/v1/claims", json=payload, catch_response=True) as response:
            if response.status_code == 202:
                response.success()
            else:
                response.failure(f"Expected HTTP 202, got {response.status_code}")
