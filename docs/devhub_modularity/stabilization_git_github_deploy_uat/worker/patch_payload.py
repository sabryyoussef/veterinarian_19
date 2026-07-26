from pathlib import Path

p = Path("/host/srv/devhub/uat/stabilization/worker_stages.py")
t = p.read_text()
old = '''    payload = {
        "stage": "push_review",
        "workspace_id": ws.id,
        "state": ws.state,
        "push_remote_name": ws.push_remote_name,
        "push_ahead": ws.push_ahead,
        "push_behind": ws.push_behind,
        "current_head": ws.current_head,
    }'''
new = '''    payload = {
        "stage": "push_review",
        "workspace_id": ws.id,
        "state": ws.state,
        "push_remote_id": ws.push_remote_id.id if ws.push_remote_id else None,
        "push_remote_branch": ws.push_remote_branch,
        "push_remote_head": ws.push_remote_head,
        "push_ahead_count": ws.push_ahead_count,
        "current_head": ws.current_head,
    }'''
# tolerate partially mangled sed
if old not in t:
    import re
    t2, n = re.subn(
        r'    payload = \{\n        "stage": "push_review",.*?    \}',
        new,
        t,
        count=1,
        flags=re.S,
    )
    if not n:
        raise SystemExit("could not locate push_review payload")
    t = t2
else:
    t = t.replace(old, new)
p.write_text(t)
print("patched ok")
