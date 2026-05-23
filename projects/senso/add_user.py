import subprocess, json, os, sys

# Role ID from the existing org owner — use this for new members
DEFAULT_ROLE_ID = "b02ef8a7-0384-44c9-b823-0e75acfc46a4"

def add_user(user_id: str, role_id: str = DEFAULT_ROLE_ID) -> dict:
    payload = json.dumps({"user_id": user_id, "role_id": role_id})
    result = subprocess.run(
        ["npx", "senso", "--quiet", "users", "add", "--data", payload, "--output", "json"],
        env={**os.environ, "SENSO_API_KEY": os.environ["SENSO_API_KEY"]},
        capture_output=True, text=True, shell=True
    )
    stdout = result.stdout.strip()
    stderr = result.stderr.strip()

    if result.returncode != 0:
        raise RuntimeError(stderr or f"senso exited with code {result.returncode}")

    start = stdout.find("{")
    if start == -1:
        raise RuntimeError(f"No JSON in response:\n{stdout}\n{stderr}")
    return json.loads(stdout[start:])

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python add_user.py <user_id> [role_id]")
        print("  user_id: the Senso platform user UUID (not email)")
        print("  role_id: optional, defaults to org member role")
        sys.exit(1)

    user_id = sys.argv[1]

    if "@" in user_id:
        print("Error: Senso requires a user UUID, not an email address.", file=sys.stderr)
        print("The person must sign up at senso.ai first, then share their user_id with you.", file=sys.stderr)
        sys.exit(1)

    role_id = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_ROLE_ID

    try:
        data = add_user(user_id, role_id)
        print(json.dumps(data, indent=2))
    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
