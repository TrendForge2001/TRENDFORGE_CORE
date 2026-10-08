from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_active_render_manifest_stays_free_without_paid_disk():
    text = (ROOT / "render.yaml").read_text(encoding="utf-8")
    assert "plan: free" in text
    assert "mountPath: /var/data" not in text


def test_opt_in_persistent_template_uses_paid_disk_and_sqlite_path():
    text = (
        ROOT / "deploy" / "render-persistent-disk.yaml"
    ).read_text(encoding="utf-8")
    assert "plan: 0.5c-512mb" in text
    assert "DATABASE_PATH" in text
    assert "/var/data/trendforge.db" in text
    assert "mountPath: /var/data" in text
    assert "sizeGB: 1" in text
    assert "TRENDFORGE_ADMIN_API_KEY" in text
    assert "FUNDAMENTALS_BOOTSTRAP_SHA256" in text
