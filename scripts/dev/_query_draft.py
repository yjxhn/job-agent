import sqlite3
import sys

sys.stdout.reconfigure(encoding="utf-8")

conn = sqlite3.connect("data/agent.db")
conn.row_factory = sqlite3.Row
row = conn.execute(
    "SELECT resume_md, hr_message, feedback FROM material_drafts WHERE job_id='b2d994a5a5c90a2c'"
).fetchone()
print("=== resume_md ===")
print(row["resume_md"])
print("\n=== feedback ===")
print(row["feedback"])
conn.close()
