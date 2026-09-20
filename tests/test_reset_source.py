"""Reset behavior uses an isolated database, never a repository-local GEO DB."""
from __future__ import annotations

import sys
from datetime import date, datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
API = ROOT / "apps" / "api"
sys.path.insert(0, str(API))


def test_reset_all_keeps_non_geo_sources(monkeypatch, tmp_path):
    """Reset removes AI-answer records but retains other-source observations."""
    monkeypatch.setenv("GEO_DB_PATH", str(tmp_path / "geo-reset-test.db"))

    # Product tests import the application before this legacy-compatibility
    # test is collected.  Reload only this old SQLite stack so its test DB is
    # still isolated rather than inheriting the selected GEO snapshot.
    for module_name in ("app.services.store", "app.models.geo_models", "app.core.config"):
        sys.modules.pop(module_name, None)
    import app.core
    if hasattr(app.core, "config"):
        delattr(app.core, "config")

    # Imports occur after the temporary path is supplied so SQLAlchemy cannot
    # resolve a divergent repository path or the selected production snapshot.
    from app.models.geo_models import BrandMention, GeoEvidence, GeoExtraction, GeoInsightReports
    from app.services.store import SessionLocal, init_db, reset_all

    init_db()
    db = SessionLocal()
    try:
        geo = GeoEvidence(
            id="evt_geo_test", source_type="ai_answer", subject_company="云启智能",
            raw_text="geo 原文", context_json="{}", parent_ref="p_geo", observed_at=datetime.utcnow(),
        )
        web = GeoEvidence(
            id="evt_web_test", source_type="website", subject_company="云启智能",
            raw_text="官网原文", context_json="{}", parent_ref="p_web", observed_at=datetime.utcnow(),
        )
        db.add_all([geo, web])
        db.flush()
        db.add_all([
            GeoExtraction(id="ext_geo", evidence_id=geo.id, source_type="ai_answer", subject_company="云启智能"),
            GeoExtraction(id="ext_web", evidence_id=web.id, source_type="website", subject_company="云启智能"),
            BrandMention(id="men_geo", evidence_id=geo.id, analysis_id="a1", brand_name="云启", mention_type="reason", factor="技术", evidence_quote="引文"),
            BrandMention(id="men_web", evidence_id=web.id, analysis_id="a2", brand_name="云启", mention_type="reason", factor="技术", evidence_quote="引文"),
            GeoInsightReports(id="rpt_1", company_name="云启智能", period_start=date(2026, 7, 1), period_end=date(2026, 7, 31), report_json="{}"),
        ])
        db.commit()

        reset_all()

        assert db.query(GeoEvidence).filter(GeoEvidence.source_type == "ai_answer").count() == 0
        assert db.query(GeoEvidence).filter(GeoEvidence.source_type == "website").count() == 1
        assert db.query(GeoExtraction).filter(GeoExtraction.source_type == "ai_answer").count() == 0
        assert db.query(GeoExtraction).filter(GeoExtraction.source_type == "website").count() == 1
        assert db.query(BrandMention).filter(BrandMention.evidence_id == web.id).count() == 1
        assert db.query(GeoInsightReports).count() == 0
    finally:
        db.close()
