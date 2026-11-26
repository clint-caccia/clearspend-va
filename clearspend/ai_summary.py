"""Optional plain-English briefing from Azure OpenAI.

Only the finished findings report (aggregated numbers, no transactions and no
payee names beyond the top organizations) is sent to the model. The prompt tells
it to use only numbers that appear in the report, and the output is saved next
to the report so it can be checked against it.

Set these to turn it on:
    AZURE_OPENAI_ENDPOINT     https://<your-resource>.openai.azure.com
    AZURE_OPENAI_API_KEY      key from the Azure portal
    AZURE_OPENAI_DEPLOYMENT   the name you gave your model deployment
"""

import json
import os
import urllib.request

API_VERSION = "2024-10-21"

PROMPT = """You are helping a budget analyst brief a manager on Virginia state agency spending.
Using ONLY the report below, write a short briefing in plain English:
1. Three to five bullet points on what changed and why it matters.
2. Two or three questions the analyst should look into next.
Rules: use only numbers that appear in the report, say "the data doesn't show" instead of
guessing at causes, and keep it under 250 words.

REPORT:
"""


def configured() -> bool:
    return all(os.environ.get(k) for k in ("AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_API_KEY", "AZURE_OPENAI_DEPLOYMENT"))


def summarize(report_markdown: str) -> str:
    endpoint = os.environ["AZURE_OPENAI_ENDPOINT"].rstrip("/")
    deployment = os.environ["AZURE_OPENAI_DEPLOYMENT"]
    url = f"{endpoint}/openai/deployments/{deployment}/chat/completions?api-version={API_VERSION}"
    body = {
        "messages": [{"role": "user", "content": PROMPT + report_markdown}],
        "temperature": 0.2,
        "max_tokens": 600,
    }
    request = urllib.request.Request(
        url, data=json.dumps(body).encode(), method="POST",
        headers={"Content-Type": "application/json", "api-key": os.environ["AZURE_OPENAI_API_KEY"]})
    with urllib.request.urlopen(request, timeout=60) as response:
        data = json.load(response)
    return data["choices"][0]["message"]["content"].strip()
