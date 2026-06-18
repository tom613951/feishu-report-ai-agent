# Feishu Daily Report AI Agent Workflow

A production-grade Python-based AI Agent workflow that pulls sales records from **Feishu (Lark) Bitable**, uses an LLM to generate structured daily summaries, runs rigorous programmatic validations to eliminate hallucinations and math errors, and pushes high-end formatted message cards back to a **Feishu Group Webhook**.

This project contains specific stability guardrails to handle API rate limits, empty inputs, network outages, and LLM hallucinations using a **Reflection (Self-Correction) Loop** and programmatic fallbacks.

---

## Architecture Flow

```
+------------------+
|  Feishu Bitable  |
+--------+---------+
         | (Fetch raw records)
         v
+------------------+
|  Feishu Client   | <--- [Network Retries (Tenacity): exponential backoff for 429/5xx]
+--------+---------+
         | (Verify schema / Check empty)
         v
+------------------+
|  Agent Workflow  | <--- [If Empty: push empty-state card & stop]
+--------+---------+
         |
         | (Create context prompt & inject raw data)
         v
+------------------+
|    LLM Call      | <--- [Generates structured JSON Report]
+--------+---------+
         |
         v
+------------------+          YES
| Guardrail Check  +--------------------------------------------+
+--------+---------+                                            |
         |                                                      |
         | NO (Math mismatch, missing fields, hallucinated data)|
         v                                                      v
+-----------------------+                               +---------------+
|   Reflection Loop     |                               | Push Webhook  |
|                       |                               | (Interactive) |
| - Compiles feedback   |                               +---------------+
| - Re-prompts LLM      |
| - Limit: Max Attempts |
+--------+--------------+
         |
         | (Failed consistently after Max Attempts)
         v
+-------------------------+
|  Programmatic Fallback  | (Strict Python-based aggregation to guarantee data accuracy)
+-------------------------+
```

---

## Directory Structure

```
.
├── src/
│   ├── config.py           # Environment variable loader & default configurations
│   ├── models.py           # Pydantic schemas for raw data & LLM structured report
│   ├── feishu_client.py    # Lark API wrapper & simulator mode
│   ├── agent_workflow.py   # Core workflow logic (reflection loop, guardrails, fallbacks)
│   └── utils.py            # Logger and tenacity retry decorator config
├── run_tests.py            # Automation test runner executing 5 boundary cases
├── requirements.txt        # Third-party dependencies
└── README.md               # User manual and project documentation
```

---

## Getting Started

### 1. Requirements
Ensure you have Python 3.8+ installed. Install the dependencies:
```bash
pip install -r requirements.txt
```

### 2. Configuration (.env)
Create a `.env` file in the root directory:
```env
# Feishu API credentials (leave empty to run in simulation mode)
FEISHU_APP_ID=
FEISHU_APP_SECRET=
FEISHU_BITABLE_APP_TOKEN=
FEISHU_BITABLE_TABLE_ID=
FEISHU_WEBHOOK_URL=

# LLM API configuration (leave empty to run mock LLM simulation)
LLM_API_KEY=
LLM_BASE_URL=https://api.openai.com/v1
LLM_MODEL=gpt-4o-mini

# Tuning settings
MAX_RETRIES=3
MAX_REFLECTION_ATTEMPTS=3
```

---

## Running the Stability Scenarios

We have created an automated test suite representing the 5 critical production boundary cases. Run the test suite:

```bash
python run_tests.py
```

### Scenarios Covered:
1. **Happy Path**: Successful data ingestion, correct LLM structured generation, schema verification, and webhook push.
2. **Boundary Case - Empty Data**: When Bitable is empty, the agent bypasses LLM compilation and gracefully sends a pre-formatted empty-state warning card.
3. **Boundary Case - Hallucination & Self-Correction**: Simulates an LLM returning incorrect totals or hallucinating a salesperson not in the raw Bitable. The validation engine flags the errors, prompts the LLM with corrective feedback, and verifies the corrected report on attempt 2.
4. **Boundary Case - Network Errors**: Simulates a 503 Service Unavailable error from Feishu API. Tenacity intercepts the error, runs exponential backoff retries, and fetches data successfully after network recovery.
5. **Consistent LLM Failure Fallback**: Simulates a permanently hallucinating LLM. The workflow hits the maximum reflection attempts, gracefully triggers a python programmatic fallback calculation, and delivers a mathematically perfect report marked with system warnings to prevent pipeline blockage.
