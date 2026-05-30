"""Integration tests: HS Classifier + Rules Engine.

Tests that the classification rules engine correctly integrates with
HS code classification and the ADK workflow node.
"""

import pytest
from datetime import date, timedelta
from unittest.mock import MagicMock, AsyncMock, patch

from app.core.classification.rule_models import (
    ClassificationRule,
    RuleAction,
    RuleCondition,
)
from app.core.classification.rules_engine import RulesEngine


# ── Fixtures ────────────────────────────────────────────────────────────

@pytest.fixture
def mock_db():
    return MagicMock()


@pytest.fixture
def engine(mock_db):
    eng = RulesEngine(db_session=mock_db)
    eng.invalidate_cache()
    return eng


def make_rule(
    rule_id: str = "test_rule",
    category_mask: str = "*",
    priority: int = 0,
    conditions=None,
    action_type: str = "boost",
    target_code: str = "",
    reason: str = "test",
    **kwargs,
) -> ClassificationRule:
    if conditions is None:
        conditions = [RuleCondition(attribute="material_outer", operator="==", value="пластик")]
    return ClassificationRule(
        rule_id=rule_id,
        category_mask=category_mask,
        priority=priority,
        conditions=conditions,
        action=RuleAction(type=action_type, target_code=target_code, reason=reason, **kwargs),
        source="Test",
        effective_date=date.today(),
    )


def make_candidate(hs_code: str = "9503001000", confidence: float = 0.7) -> dict:
    return {
        "hs_code": hs_code,
        "product_name_ru": "Test Product",
        "confidence_score": confidence,
        "duty_rate_percent": 10.0,
        "reasoning": "",
    }


# ══════════════════════════════════════════════════════════════════════════
# Classification with Rules
# ══════════════════════════════════════════════════════════════════════════

class TestClassificationWithRulesApplied:
    """Test that rules refine classification results."""

    def test_boost_increases_confidence(self, engine):
        rule = make_rule(
            "material_boost",
            conditions=[RuleCondition(attribute="material_outer", operator="==", value="пластик")],
            action_type="boost",
            target_code="9503",
            confidence_boost=0.2,
        )
        candidates = [make_candidate("9503001000", 0.6)]
        result = engine.apply_rules(
            candidates=candidates,
            attributes={"material_outer": "пластик"},
            rules=[rule],
        )
        assert result.candidates[0]["confidence_score"] == 0.8

    def test_reclassify_changes_code(self, engine):
        rule = make_rule(
            "electronics_reclassify",
            conditions=[RuleCondition(attribute="has_electronics", operator="==", value=True)],
            action_type="reclassify",
            target_code="8504000000",
            reason="Electronics go to 85 chapter",
        )
        candidates = [make_candidate("9503001000", 0.7)]
        result = engine.apply_rules(
            candidates=candidates,
            attributes={"has_electronics": True},
            rules=[rule],
        )
        assert result.candidates[0]["hs_code"] == "8504000000"

    def test_exclude_removes_candidates(self, engine):
        rule = make_rule(
            "exclude_metals",
            conditions=[RuleCondition(attribute="material_outer", operator="==", value="металл")],
            action_type="exclude",
            target_code="9503",
            reason="Metal products go to different chapter",
        )
        candidates = [
            make_candidate("9503001000", 0.8),
            make_candidate("7326000000", 0.6),
        ]
        result = engine.apply_rules(
            candidates=candidates,
            attributes={"material_outer": "металл"},
            rules=[rule],
        )
        assert len(result.candidates) == 1
        assert result.candidates[0]["hs_code"] == "7326000000"

    def test_multiple_rules_chain(self, engine):
        """Multiple rules should chain: boost then reclassify."""
        rule1 = make_rule(
            "boost_plastic",
            priority=100,
            conditions=[RuleCondition(attribute="material_outer", operator="==", value="пластик")],
            action_type="boost",
            target_code="9503",
            confidence_boost=0.1,
        )
        rule2 = make_rule(
            "reclassify_large",
            priority=50,
            conditions=[RuleCondition(attribute="size_cm", operator=">=", value=100)],
            action_type="reclassify",
            target_code="9503009000",
            reason="Large items have different subheading",
        )
        candidates = [make_candidate("9503001000", 0.7)]
        result = engine.apply_rules(
            candidates=candidates,
            attributes={"material_outer": "пластик", "size_cm": 150},
            rules=[rule1, rule2],
        )
        # Rule1 boosts confidence, Rule2 reclassifies
        assert result.candidates[0]["hs_code"] == "9503009000"
        assert result.candidates[0]["confidence_score"] >= 0.7  # Was boosted first

    def test_rules_sorted_by_priority(self, engine):
        low = make_rule("low", priority=0)
        high = make_rule("high", priority=100)
        result = engine.apply_rules(
            candidates=[make_candidate()],
            attributes={"material_outer": "пластик"},
            rules=[low, high],
        )
        # The applied_rules should reflect priority ordering
        assert len(result.applied_rules) == 2
        assert result.applied_rules[0].rule_id == "high"

    def test_applied_rules_recorded(self, engine):
        rule = make_rule(
            "recorded_rule",
            conditions=[RuleCondition(attribute="material_outer", operator="==", value="пластик")],
            action_type="boost",
            confidence_boost=0.15,
        )
        result = engine.apply_rules(
            candidates=[make_candidate()],
            attributes={"material_outer": "пластик"},
            rules=[rule],
        )
        assert len(result.applied_rules) == 1
        assert result.applied_rules[0].rule_id == "recorded_rule"
        assert result.applied_rules[0].action_type == "boost"


class TestClassificationWithoutMatchingRules:
    """Test that classification works fine without matching rules."""

    def test_no_matching_rules_returns_original(self, engine):
        rule = make_rule(
            "no_match",
            conditions=[RuleCondition(attribute="material_outer", operator="==", value="металл")],
        )
        candidates = [make_candidate("9503001000", 0.8)]
        result = engine.apply_rules(
            candidates=candidates,
            attributes={"material_outer": "пластик"},
            rules=[rule],
        )
        assert result.candidates[0]["hs_code"] == "9503001000"
        assert result.candidates[0]["confidence_score"] == 0.8

    def test_empty_rules_list(self, engine):
        candidates = [make_candidate()]
        result = engine.apply_rules(
            candidates=candidates,
            attributes={"material_outer": "пластик"},
            rules=[],
        )
        assert len(result.candidates) == 1
        assert len(result.applied_rules) == 0


class TestClarifyingQuestionsWorkflow:
    """Test the clarifying questions loop."""

    def test_missing_attribute_generates_question(self, engine):
        rule = make_rule(
            "need_fur_info",
            conditions=[RuleCondition(attribute="fur_coverage_percent", operator=">", value=50)],
            action_type="boost",
            target_code="4303",
        )
        candidates = [make_candidate("4303000000", 0.6)]
        result = engine.apply_rules(
            candidates=candidates,
            attributes={"material_outer": "мех"},
            rules=[rule],
        )
        assert len(result.clarifying_questions) == 1
        q = result.clarifying_questions[0]
        assert q.attribute == "fur_coverage_percent"
        assert len(q.question) > 0

    def test_questions_not_generated_when_attr_present(self, engine):
        rule = make_rule(
            "has_attr",
            conditions=[RuleCondition(attribute="fur_coverage_percent", operator=">", value=50)],
            action_type="boost",
            target_code="4303",
        )
        candidates = [make_candidate("4303000000", 0.6)]
        result = engine.apply_rules(
            candidates=candidates,
            attributes={"fur_coverage_percent": 80},
            rules=[rule],
        )
        assert len(result.clarifying_questions) == 0
        assert len(result.applied_rules) == 1
