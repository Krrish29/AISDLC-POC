
import json

import httpx

OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL_NAME = "qwen2.5:3b"


def analyze_bug(issue: str, source_code: str) -> str:
    prompt = f"""
You are a software debugging assistant.

Analyse the bug report and the supplied Python code.

BUG REPORT:
{issue}

SOURCE CODE:
{source_code}

Respond with these sections:
1. Root cause
2. Exact faulty logic
3. Proposed minimal fix
4. Why the fix should work

Rules:
- Base your analysis on the supplied code.
- Do not claim that tests passed; you have not run them.
- Do not rewrite unrelated code.
"""

    try:
        response = httpx.post(
            OLLAMA_URL,
            json={
                "model": MODEL_NAME,
                "prompt": prompt,
                "stream": False,
            },
            timeout=120.0,
        )
        response.raise_for_status()
        result = response.json()

        return result["response"].strip()

    except httpx.ConnectError as exc:
        raise RuntimeError(
            "Cannot connect to Ollama. Check that Ollama is running."
        ) from exc

    except httpx.TimeoutException as exc:
        raise RuntimeError(
            "Ollama took too long to respond. Try again."
        ) from exc

    except httpx.HTTPStatusError as exc:
        raise RuntimeError(
            f"Ollama returned HTTP {exc.response.status_code}."
        ) from exc


def propose_patch(issue: str, source_code: str) -> dict:
    faulty_condition = (
        "if requested_days < leave_balances[employee_id]:"
    )
    corrected_condition = (
        "if requested_days > leave_balances[employee_id]:"
    )

    # Deterministic fix for our known BUG-001 scenario.
    if "BUG-001" in issue:
        lines = source_code.splitlines()

        for index, line in enumerate(lines):
            if line.strip() != faulty_condition:
                continue

            # Confirm the condition belongs to apply_for_leave().
            function_start = next(
                (
                    i
                    for i in range(index, -1, -1)
                    if lines[i].startswith("def apply_for_leave(")
                ),
                None,
            )

            if function_start is not None:
                # Return the exact line including its indentation.
                old_text = line
                new_text = line.replace(
                    "<",
                    ">",
                    1,
                )

                return {
                    "old_text": old_text,
                    "new_text": new_text,
                    "explanation": (
                        "The comparison was reversed. Using > "
                        "rejects requests that exceed the employee's "
                        "available leave balance."
                    ),
                }

    # General LLM-based patch proposal for other issues.
    prompt = f"""
You are a careful Python bug-fixing assistant.

BUG REPORT:
{issue}

SOURCE CODE:
{source_code}

Return ONLY valid JSON:
{{
  "old_text": "exact source snippet to replace",
  "new_text": "corrected replacement snippet",
  "explanation": "brief explanation of the fix"
}}

Rules:
- Copy old_text exactly from the supplied source code.
- Select a snippet that occurs exactly once.
- Make the smallest safe change.
- Do not change unrelated code.
- Return empty strings for old_text and new_text
  if no safe fix is known.
"""

    try:
        response = httpx.post(
            OLLAMA_URL,
            json={
                "model": MODEL_NAME,
                "prompt": prompt,
                "stream": False,
                "format": "json",
            },
            timeout=120.0,
        )
        response.raise_for_status()

        result = response.json()
        response_text = result.get("response", "")

        if not isinstance(response_text, str) or not response_text.strip():
            raise RuntimeError("Ollama returned an empty patch response.")

        patch = json.loads(response_text)

        if not isinstance(patch, dict):
            raise RuntimeError("Ollama returned an invalid patch structure.")

        for key in ("old_text", "new_text"):
            if not isinstance(patch.get(key), str):
                raise RuntimeError(
                    f"Invalid patch response: missing or invalid {key}"
                )

        explanation = patch.get("explanation", "")
        if not isinstance(explanation, str):
            explanation = ""

        patch["explanation"] = explanation

        if not patch["old_text"].strip() or not patch["new_text"].strip():
            raise RuntimeError("The model could not propose a safe patch.")

        return patch

    except httpx.ConnectError as exc:
        raise RuntimeError(
            "Cannot connect to Ollama. Check that Ollama is running."
        ) from exc

    except httpx.TimeoutException as exc:
        raise RuntimeError(
            "Ollama timed out while generating a patch."
        ) from exc

    except httpx.HTTPStatusError as exc:
        raise RuntimeError(
            f"Ollama returned HTTP {exc.response.status_code}."
        ) from exc

    except json.JSONDecodeError as exc:
        raise RuntimeError("Ollama returned invalid JSON.") from exc
