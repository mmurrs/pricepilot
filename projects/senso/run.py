import subprocess, json, os, sys

def ingest_report(title: str, markdown: str) -> dict:
    payload = json.dumps({"title": title, "text": markdown})
    result = subprocess.run(
        ["npx", "senso", "--quiet", "kb", "create-raw", "--data", payload, "--output", "json"],
        env={**os.environ, "SENSO_API_KEY": os.environ["SENSO_API_KEY"]},
        capture_output=True, text=True, shell=True
    )
    stdout = result.stdout.strip()
    stderr = result.stderr.strip()

    if result.returncode != 0:
        raise RuntimeError(stderr or f"senso exited with code {result.returncode}")

    # find the JSON object in output (skips any stray header lines)
    start = stdout.find("{")
    if start == -1:
        raise RuntimeError(f"No JSON in response:\n{stdout}\n{stderr}")
    return json.loads(stdout[start:])

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python run.py <document.json>")
        print("  JSON format: { \"title\": \"My Report\", \"text\": \"# Markdown...\" }")
        sys.exit(1)

    with open(sys.argv[1]) as f:
        doc = json.load(f)

    try:
        data = ingest_report(doc["title"], doc["text"])
        print(json.dumps(data, indent=2))
    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
