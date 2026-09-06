import json
import os
import subprocess

from sqlalchemy import text

from pacificeo.db import SessionLocal


def deliver_once() -> bool:
    with SessionLocal.begin() as session:
        item = session.execute(text("""
            select n.id::text,n.channel,n.recipient,p.recipe,p.accuracy,p.asset_href
            from notifications n join products p on p.id=n.product_id and p.tenant_id=n.tenant_id
            where n.status='pending' and p.status='published'
            order by n.created_at for update of n skip locked limit 1
        """)).mappings().one_or_none()
        if not item:
            return False
        command = os.environ.get(f"PACIFICEO_{item['channel'].upper()}_COMMAND")
        if not command:
            session.execute(text("update notifications set status='failed',error='provider command not configured' where id=:id"), {"id":item["id"]})
            return True
        message = {"recipient":item["recipient"],"subject":f"PacificEO {item['recipe']} update", "summary":f"A reviewed {item['recipe']} product is available.","accuracy":item["accuracy"],"asset_href":item["asset_href"]}
        try:
            result = subprocess.run([command], input=json.dumps(message), text=True, capture_output=True, check=True, timeout=60)
            session.execute(text("update notifications set status='sent',provider_message_id=:provider,sent_at=now() where id=:id"), {"id":item["id"],"provider":result.stdout.strip()[:500] or None})
        except Exception as exc:
            session.execute(text("update notifications set status='failed',error=:error where id=:id"), {"id":item["id"],"error":str(exc)[:2000]})
        return True


if __name__ == "__main__":
    while deliver_once():
        pass
