from app.product.persistence import models


def test_product_schema_has_no_legacy_tenant_authority():
    assert models.SCHEMA == "geo_product"
    assert "tenant_id" not in {column.name for table in models.metadata.tables.values() for column in table.columns}


def test_observation_chain_has_formal_owner_and_not_foundation_evidence_name():
    assert "geo_product.observations" in models.metadata.tables
    assert "geo_product.observation_extractions" in models.metadata.tables
    assert "geo_product.brand_mentions" in models.metadata.tables
    observation_columns = {column.name for column in models.observations.columns}
    assert {"deployment_id", "enterprise_id", "subject_namespace", "subject_type", "subject_id", "content_hash"} <= observation_columns
    assert "evidence_id" not in observation_columns
