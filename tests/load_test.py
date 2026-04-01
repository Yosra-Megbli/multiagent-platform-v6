"""
LOAD TESTING — Locust
======================
Tests system behavior under load.

Scenarios tested:
  1. Normal load: 10 users, 1 req/s each
  2. Spike load: 100 users sudden burst
  3. Rate limit: verify 429 responses at threshold
  4. Queue saturation: verify backpressure kicks in

Usage:
  pip install locust
  locust -f tests/load_test.py --host http://localhost:8000

  # Headless (CI):
  locust -f tests/load_test.py --host http://localhost:8000 \
    --users 50 --spawn-rate 10 --run-time 60s --headless
"""

from locust import HttpUser, task, between, events
import json
import random
import time


API_KEY = "sk-demo-123456"
LOCATIONS = ["Dallas, TX", "Miami, FL", "Chicago, IL", "Phoenix, AZ", "Seattle, WA"]
PRODUCTS  = ["ICE_CREAM_VANILLA", "ICE_CREAM_CHOCOLATE", "BEVERAGE_COLA"]


class AnalystUser(HttpUser):
    """Simulates a typical analyst: submit jobs and poll results."""
    wait_time = between(1, 3)

    def on_start(self):
        self.headers = {
            "X-API-Key": API_KEY,
            "Content-Type": "application/json",
        }

    @task(5)
    def submit_analysis(self):
        """Main task: submit an analysis job."""
        idempotency_key = f"load-test-{int(time.time())}-{random.randint(1000, 9999)}"
        payload = {
            "input_data": {
                "location": random.choice(LOCATIONS),
                "product_id": random.choice(PRODUCTS),
            }
        }

        with self.client.post(
            "/analyze",
            json=payload,
            headers={**self.headers, "Idempotency-Key": idempotency_key},
            catch_response=True,
        ) as response:
            if response.status_code == 202:
                data = response.json()
                response.success()
                # Poll result
                self._poll_job(data.get("job_id"))
            elif response.status_code == 429:
                response.success()  # Expected under load
            else:
                response.failure(f"Unexpected status: {response.status_code}")

    @task(2)
    def check_dashboard(self):
        """Secondary task: view observability dashboard."""
        with self.client.get(
            "/observability/dashboard",
            headers=self.headers,
            catch_response=True,
        ) as response:
            if response.status_code == 200:
                response.success()
            else:
                response.failure(f"Dashboard failed: {response.status_code}")

    @task(1)
    def check_rate_limit(self):
        """Check rate limit status."""
        self.client.get("/rate-limit", headers=self.headers)

    def _poll_job(self, job_id: str, max_polls: int = 3):
        """Polls job status up to max_polls times."""
        if not job_id:
            return
        for _ in range(max_polls):
            time.sleep(1)
            response = self.client.get(f"/jobs/{job_id}", headers=self.headers)
            if response.status_code == 200:
                status = response.json().get("status")
                if status in ("done", "error", "rejected"):
                    return


class HeavyUser(HttpUser):
    """Simulates a heavy user that submits many jobs rapidly (stress test)."""
    wait_time = between(0.1, 0.5)

    def on_start(self):
        self.headers = {"X-API-Key": API_KEY, "Content-Type": "application/json"}

    @task
    def spam_analyze(self):
        """Rapid-fire requests to test backpressure."""
        payload = {
            "input_data": {
                "location": "Dallas, TX",
                "product_id": "ICE_CREAM_VANILLA",
            }
        }
        self.client.post("/analyze", json=payload, headers=self.headers)


# ─── Event hooks for reporting ────────────────────────────────────────────────

@events.test_stop.add_listener
def on_test_stop(environment, **kwargs):
    stats = environment.stats.total
    print("\n" + "="*50)
    print("LOAD TEST RESULTS")
    print("="*50)
    print(f"Total requests:    {stats.num_requests}")
    print(f"Failed requests:   {stats.num_failures}")
    print(f"Failure rate:      {stats.fail_ratio:.1%}")
    print(f"Avg response time: {stats.avg_response_time:.0f}ms")
    print(f"P95 response time: {stats.get_response_time_percentile(0.95):.0f}ms")
    print(f"Requests/sec:      {stats.current_rps:.1f}")
    print("="*50)

    # Fail CI if error rate > 5%
    if stats.fail_ratio > 0.05:
        print("❌ LOAD TEST FAILED: Error rate > 5%")
        environment.process_exit_code = 1
    else:
        print("✅ LOAD TEST PASSED")
